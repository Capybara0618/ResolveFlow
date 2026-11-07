"""Wrong accepted goals must not coerce a correct artifact into the wrong business request."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from resolveflow.support.engine import SupportAgent
from resolveflow.support.orchestration import Orchestration, Response
from resolveflow.support.progress import ProgressReporter
from tests.recorded_sources import ProjectedSupportInput as SupportInput
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.recorded_sources import SavedSources
from tests.support_request_checks import approve_requests, checked_script
from tests.unit.test_support_agent import request
from tests.unit.test_support_orchestration import plan, source_refs


def review(task_id="trace", previous="PREPARE_REFUND", goal="MERCHANT_REVIEW", quote=None):
    return {"kind": "REVIEW_GOAL", "task_id": task_id, "previous_goal": previous, "goal": goal,
            "operation_request": request().context["current_request"] if quote is None else quote,
            "reason": "客户要人工核查摘要，不是退款原因；核对本轮原话后更正。"}


def conflict(flow, meaning, refs=None):
    value = {"kind": "RESPOND", "parts": [{"task_id": meaning.focus[0].id, "text": "待本人核对。"}],
             "handoff_reason": {"customer_quotes": [flow.request.context["current_request"]]}}
    with pytest.raises(ValueError, match="GOAL_CONFLICT"):
        flow.compose(Response.model_validate(value), meaning, refs or source_refs(), [], {})


def test_saved_wrong_refund_goal_keeps_handoff_purpose_with_new_quote_draft_contract():
    raw = json.loads((Path(__file__).resolve().parents[3]
        / "agent/tests/fixtures/regressions/customer-agent-close-v1/runtime-results.json").read_text(encoding="utf-8"))
    row = next(r for r in raw["rows"] if (r["id"], r["turn"]) == ("M02", 2))
    req = SupportInput.model_validate({**row["input"], "deadline_at": request().deadline_at})
    decisions = deepcopy([m["decision"] for m in row["models"][:3]])
    # Saved plan/tool/body stay intact; adapt only the old free reason to the new quote-only ABI.
    decisions[-1]["handoff_reason"] = {"customer_quotes": ["新发现耳机外壳有损坏"]}
    corrected = review("t2", quote="能帮我整理一段给商家的摘要吗？先不要发出去。")
    batches = []
    reporter = ProgressReporter("http://synthetic.invalid", "run", "test", transport=httpx.MockTransport(
        lambda req: (batches.append(json.loads(req.content)) or httpx.Response(200))))

    class Script(TokenizedScript):
        def decide(self, **kwargs):
            reply = super().decide(**kwargs)
            reporter.content(json.dumps(reply.decision, ensure_ascii=False))
            return reply

    model = Script(mode="live", script=checked_script([*deepcopy(decisions), corrected, deepcopy(decisions[-1])]))
    agent = SupportAgent(req, model, SavedSources(row["calls"]), architecture="orchestrated-v1", progress=reporter)
    try:
        result = agent.run()
    finally:
        reporter.close()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert "新发现耳机外壳有损坏" in result["answer"]["handoff_summary"]
    assert "已读系统记录" not in result["answer"]["handoff_summary"]
    assert result["answer"]["customer_memory"]["origin"] == "GROUNDED_CUSTOMER_CLAIMS"
    assert "refund_summary" not in result["answer"] and "正式退款：" not in result["answer"]["text"]
    assert result["answer"]["buyer_view"]["parts"][0]["action"] == "MERCHANT_REVIEW"
    assert result["answer"]["text"] == result["answer"]["buyer_view"]["parts"][0]["text"]
    assert agent.repairs == 0 and len(agent.orchestration.goal_reviews) == 1
    assert "REVIEW_GOAL" not in model.conversations[1][0].get_content_blocks()[0].text
    assert "REVIEW_GOAL" in model.conversations[4][0].get_content_blocks()[0].text
    assert agent.tasks.tasks[0].intent == "HANDOFF"
    assert model.packets[4]["orchestration"]["goal_review"]["candidate_goals"] == ["MERCHANT_REVIEW"]
    assert model.packets[1]["orchestration"]["phase"] == model.packets[5]["orchestration"]["phase"] == "CHECK_REQUEST"
    assert model.calls == 7 and result["spend"]["model_calls"] == 7
    events = [e for batch in batches for e in batch["events"]]
    assert [e["attempt_id"] for e in events if e["kind"] == "answer.started"] == ["model-4", "model-7"]
    assert [e["attempt_id"] for e in events if e["kind"] == "answer.reset"] == ["model-5", "model-6", "model-7"]
    assert all(e["attempt_id"] in {"model-4", "model-7"}
               for e in events if e["kind"] == "answer.delta")


def test_review_keeps_evidence_and_lifecycle_and_rejects_stale_or_other_task_requests():
    req = request()
    p = plan(req)
    flow = Orchestration(req)
    flow.accept(p)
    approve_requests(flow, p.meaning())
    meaning = p.meaning()
    conflict(flow, meaning)
    before = deepcopy(meaning)
    for changed in [review(task_id="other"), review(previous="EXPLAIN"), review(quote="历史助手说要退款")]:
        with pytest.raises(ValueError):
            flow.review_goal(changed, meaning, {})
        assert meaning == before and flow.goals == {"trace": "PREPARE_REFUND"}
    with pytest.raises(ValueError):
        flow.review_goal(review(), meaning, {"trace": "PAUSED"})
    updated = flow.review_goal(review(), meaning, {})
    assert updated.focus[0].id == "trace" and updated.focus[0].intent == "HANDOFF"
    assert set(updated.focus[0].needs) >= set(meaning.focus[0].needs)
    assert updated.dialogue_events == meaning.dialogue_events and meaning == before


def test_review_cannot_run_without_conflict_and_does_not_loop():
    p = plan(request())
    flow = Orchestration(request())
    flow.accept(p)
    approve_requests(flow, p.meaning())
    with pytest.raises(ValueError):
        flow.review_goal(review(), p.meaning(), {})
    conflict(flow, p.meaning())
    updated = flow.review_goal(review(), p.meaning(), {})
    with pytest.raises(ValueError):
        flow.review_goal(review(previous="MERCHANT_REVIEW", goal="PREPARE_REFUND"), updated, {})


def test_review_can_confirm_original_refund_goal_if_candidate_artifact_was_wrong():
    p = plan(request())
    flow = Orchestration(request())
    flow.accept(p)
    approve_requests(flow, p.meaning())
    conflict(flow, p.meaning())
    updated = flow.review_goal(review(goal="PREPARE_REFUND"), p.meaning(), {})
    assert flow.goals == {"trace": "PREPARE_REFUND"} and updated.focus[0].intent == "APPLICATION"


def test_goal_review_is_investigation_not_user_visible_composition():
    p = plan(request())
    flow = Orchestration(request())
    flow.accept(p)
    approve_requests(flow, p.meaning())
    conflict(flow, p.meaning())
    state = flow.snapshot(p.meaning(), source_refs(), [], {})
    assert state["phase"] == "INVESTIGATE" and state["goal_review"]["task_ids"] == ["trace"]


def test_second_artifact_conflict_stops_without_another_review():
    from resolveflow.support.protocol import SupportFailure

    p = plan(request())
    flow = Orchestration(request())
    flow.accept(p)
    approve_requests(flow, p.meaning())
    conflict(flow, p.meaning())
    updated = flow.review_goal(review(goal="PREPARE_REFUND"), p.meaning(), {})
    with pytest.raises(SupportFailure, match="GOAL_REVIEW_EXHAUSTED"):
        flow.compose(Response.model_validate({"kind": "RESPOND", "parts": [
            {"task_id": "trace", "text": "待确认"}],
            "handoff_reason": {"customer_quotes": [request().context["current_request"]]}}),
            updated, source_refs(), [], {})


def test_review_to_refund_reopens_evidence_readiness_instead_of_skipping_order():
    req = request()
    p = plan(req, intent="HANDOFF", goal="MERCHANT_REVIEW")
    flow = Orchestration(req)
    flow.accept(p)
    approve_requests(flow, p.meaning())
    refs = {"O1": source_refs()["O1"]}
    with pytest.raises(ValueError, match="GOAL_CONFLICT"):
        flow.compose(Response.model_validate({"kind": "RESPOND", "parts": [
            {"task_id": "trace", "text": "待确认"}],
            "refund_reason": {"customer_quotes": [req.context["current_request"]]}}),
            p.meaning(), refs, [], {})
    updated = flow.review_goal(review(previous="MERCHANT_REVIEW", goal="PREPARE_REFUND"), p.meaning(), {})
    assert flow.snapshot(updated, refs, [], {})["tasks"][0]["missing"] == ["ORDER"]


def test_mock_script_loader_accepts_review_protocol_without_new_live_model(monkeypatch, tmp_path):
    from resolveflow.runtime.factory import DeploymentConfig
    from resolveflow.support.service import SupportRuntime

    script = [review()]
    path = tmp_path / "script.json"
    path.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("RESOLVEFLOW_SUPPORT_MOCK_SCRIPT", str(path))
    runtime = SupportRuntime(None, DeploymentConfig(mode="mock"), architecture="orchestrated-v1")
    assert runtime._model().script == script
