import json

import httpx
import pytest

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.jev import JevClient, JevConfig
from resolveflow.support.jev_intent import OPTIONS, IntentPolicy
from resolveflow.support.protocol import SupportFailure
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import request
from tests.unit.test_support_orchestrated_engine import Sources
from tests.unit.test_support_orchestration import plan


def purpose_response(choice="MERCHANT_REVIEW", confidence=.99):
    return {"model": "jev-1.14.0", "usage": {"input_tokens": 600, "output_tokens": 60},
            "answers": {"purpose_0": {"type": "choice", "choice": choice, "confidence": confidence,
                "probabilities": {key: float(key == choice) for key in OPTIONS}}}}


def configured(db, send, *, fallback=False, enabled=True):
    req = request()
    req.context["current_request"] = "请帮我准备商家核查摘要：耳机按键没反应。"
    opening = plan(req, intent="HANDOFF", goal="MERCHANT_REVIEW", needs=["GUIDE"]).model_dump()
    final = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "按键情况还需要商家核实。",
                                            "citations": ["O1"]}],
             "handoff_reason": {"customer_quotes": ["耳机按键没反应"]}}
    check = {"kind": "CHECK_REQUEST", "assessments": [{"task_id": "trace", "purpose": "MERCHANT_REVIEW",
              "quote": req.context["current_request"], "reason": "测试脚本明确准备核查，不代表模型质量。"}]}
    models = []

    def make_model():
        model = TokenizedScript(mode="live", script=[opening, *([check] if fallback or not enabled else []), final])
        models.append(model)
        return model

    config = JevConfig(api_key="test-secret")
    runtime = SupportRuntime(db, DeploymentConfig(mode="mock"), architecture="orchestrated-v1",
        model_factory=make_model, sources_factory=lambda *_: Sources(), jev_config=config,
        intent_policy=IntentPolicy(enabled=enabled),
        intent_client=JevClient(config, transport=httpx.MockTransport(send)))
    return runtime, req, models


def test_confident_choice_replaces_only_the_existing_request_check_and_replays(agent_db):
    calls = []
    run, req, models = configured(agent_db, lambda r: calls.append(r) or httpx.Response(200, json=purpose_response()))
    result = run.run(req, "bound-test")
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert models[0].calls == 2 and result["spend"]["model_calls"] == 3
    assert result["answer"]["handoff_summary"] == "耳机按键没反应"
    with agent_db.connection() as c:
        saved = c.execute("SELECT request_json,response_json FROM support_agent_call "
                          "WHERE kind='jev' AND position>1").fetchone()
        assert saved["response_json"]["status"] == "ACCEPTED"
        assert "test-secret" not in json.dumps(saved, default=str)
        assert c.execute("SELECT count(*) AS n FROM support_agent_call WHERE kind='model'").fetchone()["n"] == 2
    assert run.run(req, "new-token") == result and len(calls) == 1
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET result_json=NULL,status='RUNNING',"
                  "lease_until=now()-interval '1 second'")
    assert run.run(req, "new-token") == result and len(calls) == 1 and models[-1].calls == 0


@pytest.mark.parametrize("kind", ["low", "unclear", "timeout", "http", "invalid"])
def test_failure_or_uncertainty_uses_original_model_without_repeating_jev(agent_db, kind):
    calls = []

    def send(req):
        calls.append(req)
        if kind == "timeout":
            raise httpx.ReadTimeout("test-secret", request=req)
        value = purpose_response("UNCLEAR" if kind == "unclear" else "MERCHANT_REVIEW", .4 if kind == "low" else .99)
        return httpx.Response(402 if kind == "http" else 200, json={} if kind == "invalid" else value)

    run, req, models = configured(agent_db, send, fallback=True)
    result = run.run(req, "bound-test")
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert models[0].calls == 3 and result["spend"]["model_calls"] == 4 and len(calls) == 1
    with agent_db.connection() as c:
        saved = c.execute("SELECT response_json FROM support_agent_call "
                          "WHERE kind='jev' AND position>1").fetchone()["response_json"]
        assert saved["status"] == "FALLBACK" and "decision" not in saved
    assert run.run(req, "bound-test") == result and len(calls) == 1


def test_disabled_leaves_the_original_model_path_untouched(agent_db):
    run, req, models = configured(agent_db, lambda _: pytest.fail("disabled choice called"), enabled=False)
    result = run.run(req, "bound-test")
    assert result["status"] == "SUCCEEDED" and models[0].calls == 3
    with agent_db.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM support_agent_call "
                         "WHERE kind='jev' AND position>1").fetchone()["n"] == 0


def test_old_fence_cannot_publish_a_choice_or_a_draft(agent_db):
    def send(req):
        with agent_db.connection() as c:
            c.execute("UPDATE support_agent_run SET fence=fence+1")
        return httpx.Response(200, json=purpose_response())

    run, req, models = configured(agent_db, send)
    with pytest.raises(SupportFailure, match="STALE_FENCE"):
        run.run(req, "bound-test")
    assert models[0].calls == 1


def test_unknown_choice_never_resends_and_recovery_reuses_original_model_fallback(agent_db):
    calls = []
    run, req, models = configured(agent_db, lambda r: calls.append(r) or
                                 httpx.Response(200, json=purpose_response(confidence=.4)), fallback=True)
    result = run.run(req, "bound-test")
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET result_json=NULL,status='RUNNING',"
                  "lease_until=now()-interval '1 second'")
        c.execute("UPDATE support_agent_call SET status='STARTED',response_json=NULL WHERE kind='jev' AND position>1")
    assert run.run(req, "bound-test") == result and len(calls) == 1 and models[-1].calls == 0


def test_changed_intent_policy_cannot_be_adopted_by_an_unfinished_run(agent_db):
    run, req, _ = configured(agent_db, lambda _: httpx.Response(200, json=purpose_response()))
    run.run(req, "bound-test")
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET result_json=NULL,status='RUNNING',"
                  "lease_until=now()-interval '1 second'")
    run.intent_policy = IntentPolicy(enabled=False)
    with pytest.raises(SupportFailure, match="MANIFEST_MISMATCH"):
        run.run(req, "bound-test")


@pytest.mark.parametrize("field,amount,reason", [("output_tokens", 2048, "BUDGET_OUTPUT_TOKENS"),
                                                ("input_tokens", 100000, "BUDGET_STEP_TOKENS")])
def test_provider_overrun_is_charged_saved_and_stops_before_draft(agent_db, field, amount, reason):
    def send(_):
        value = purpose_response()
        value["usage"][field] = amount
        return httpx.Response(200, json=value)

    run, req, models = configured(agent_db, send)
    result = run.run(req, "bound-test")
    assert result["status"] == "FAILED" and result["reason"] == reason
    assert models[0].calls == 1 and result["answer"] is None
    with agent_db.connection() as c:
        saved = c.execute("SELECT response_json FROM support_agent_call "
                          "WHERE kind='jev' AND position>1").fetchone()["response_json"]
    assert saved["status"] == "STOPPED" and saved["usage"][field] == amount
