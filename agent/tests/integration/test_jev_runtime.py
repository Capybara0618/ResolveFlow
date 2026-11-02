import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from resolveflow.harness.budget import BudgetGuard, RunBudget
from resolveflow.harness.model import MockModelClient
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.jev import JevClient, JevConfig
from resolveflow.support.protocol import SupportFailure
from resolveflow.support.service import SupportRuntime
from resolveflow.support.store import SupportStore
from tests.unit.test_jev import response
from tests.unit.test_support_agent import Reads, answer, read, request


def runtime(db, transport, *, enabled=True):
    config = JevConfig(enabled=enabled, api_key="test-secret")
    return SupportRuntime(db, DeploymentConfig(mode="mock"),
                          model_factory=lambda: MockModelClient(script=[read(), answer(citations=["O1"])]),
                          sources_factory=lambda *_: Reads(), jev_config=config,
                          jev_client=JevClient(config, transport=httpx.MockTransport(transport)))


def test_actual_runtime_records_jev_and_recovery_never_calls_provider_twice(agent_db):
    calls = []

    def send(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, json=response())

    run, req = runtime(agent_db, send), request()
    result = run.run(req, "bound-token")
    assert result["status"] == "SUCCEEDED" and result["spend"]["model_calls"] == 3
    assert len(calls) == 1 and calls[0]["state"]["observations"][0]["source_id"] == "O1"
    assert calls[0]["state"]["answer"] == result["answer"]["text"]
    with agent_db.connection() as c:
        saved = c.execute("SELECT * FROM support_agent_call WHERE run_id=%s AND kind='jev'", (req.run_id,)).fetchone()
        assert saved["response_json"]["verdict"] == "contradicted"
        assert saved["status"] == "COMPLETE"
        assert "test-secret" not in json.dumps(saved, default=str)
        manifest = c.execute("SELECT manifest_json FROM support_agent_run WHERE run_id=%s", (req.run_id,)).fetchone()
        assert manifest["manifest_json"]["jev"]["model"] == "jev-1.14.0"
    assert run.run(req, "new-token") == result and len(calls) == 1
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET result_json=NULL,status='RUNNING',"
                  "lease_until=now()-interval '1 second'")
    assert run.run(req, "new-token") == result and len(calls) == 1


@pytest.mark.parametrize("outcome", ["TIMEOUT", 402, 429, "INVALID"])
def test_provider_failure_is_recorded_and_original_answer_survives(agent_db, outcome):
    calls = []

    def send(req):
        calls.append(req)
        if outcome == "TIMEOUT":
            raise httpx.ReadTimeout("test-secret", request=req)
        return httpx.Response(200, json={}) if outcome == "INVALID" else httpx.Response(outcome)

    run, req = runtime(agent_db, send), request()
    result = run.run(req, "bound-token")
    assert result["status"] == "SUCCEEDED" and result["answer"]["text"] == answer()["text"]
    with agent_db.connection() as c:
        saved = c.execute("SELECT response_json FROM support_agent_call WHERE kind='jev'").fetchone()["response_json"]
    assert saved["status"] == "ERROR" and "verdict" not in saved
    assert saved["usage_estimated"] is True and len(calls) == 1
    assert run.run(req, "bound-token") == result and len(calls) == 1


def test_disabled_never_calls_or_adds_audit_rows(agent_db):
    run = runtime(agent_db, lambda _: pytest.fail("disabled Jev called"), enabled=False)
    assert run.run(request(), "bound-token")["spend"]["model_calls"] == 2
    with agent_db.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM support_agent_call WHERE kind='jev'").fetchone()["n"] == 0


def test_started_unknown_audit_is_not_repaid_on_recovery_and_changed_manifest_refused(agent_db):
    calls = []
    run = runtime(agent_db, lambda req: calls.append(req) or httpx.Response(200, json=response()))
    req = request()
    result = run.run(req, "bound-token")
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET result_json=NULL,status='RUNNING',"
                  "lease_until=now()-interval '1 second'")
        c.execute("UPDATE support_agent_call SET status='STARTED',response_json=NULL WHERE kind='jev'")
    recovered = run.run(req, "bound-token")
    assert recovered["answer"] == result["answer"] and recovered["spend"] == result["spend"]
    assert len(calls) == 1
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET result_json=NULL,status='RUNNING',"
                  "lease_until=now()-interval '1 second'")
    run.jev_config = replace(run.jev_config, enabled=False)
    with pytest.raises(SupportFailure, match="MANIFEST_MISMATCH"):
        run.run(req, "bound-token")


def test_audit_cannot_write_under_a_stale_fence(agent_db):
    def send(req):
        with agent_db.connection() as c:
            c.execute("UPDATE support_agent_run SET fence=fence+1")
        return httpx.Response(200, json=response())

    with pytest.raises(SupportFailure, match="STALE_FENCE"):
        runtime(agent_db, send).run(request(), "bound-token")
    with agent_db.connection() as c:
        row = c.execute("SELECT result_json FROM support_agent_run").fetchone()
        assert row["result_json"] is None


def test_nearly_expired_deadline_skips_audit_without_network(agent_db, monkeypatch):
    # The main loop can finish; only the optional audit has too little time left.
    from resolveflow.support import jev_audit

    req = request()
    monkeypatch.setattr(jev_audit, "remaining_seconds", lambda _: .01)
    run = runtime(agent_db, lambda _: pytest.fail("deadline audit called"))
    result = run.run(req, "bound-token")
    assert result["status"] == "SUCCEEDED" and result["spend"]["model_calls"] == 2
    with agent_db.connection() as c:
        saved = c.execute("SELECT response_json FROM support_agent_call WHERE kind='jev'").fetchone()["response_json"]
        assert saved["status"] == "SKIPPED" and saved["reason"] == "DEADLINE"


@pytest.mark.parametrize("budget,observations,reason", [
    (RunBudget(model_calls=0), [], "BUDGET_MODEL_CALLS"),
    (RunBudget(), [{"data": {"text": "完整条款" * 3000}}], "BUDGET_STEP_TOKENS"),
])
def test_exhausted_budget_or_large_evidence_is_explicitly_skipped(agent_db, budget, observations, reason):
    from resolveflow.support.jev_audit import audit_answer

    req = request()
    journal, _ = SupportStore(agent_db).claim(req, {"test": "budget"})
    config = JevConfig(enabled=True, api_key="test-secret")
    agent = SimpleNamespace(request=req, observations=observations, journal=journal,
                            guard=BudgetGuard(budget, active_deadline=req.deadline_at))
    result = {"status": "SUCCEEDED", "answer": {"text": "请核查。"}}
    client = JevClient(config, transport=httpx.MockTransport(lambda _: pytest.fail("budget bypassed")))
    audit_answer(agent, result, config, client)
    with agent_db.connection() as c:
        saved = c.execute("SELECT response_json FROM support_agent_call WHERE kind='jev'").fetchone()["response_json"]
    assert saved["status"] == "SKIPPED" and saved["reason"] == reason
    assert result["spend"]["model_calls"] == 0


def test_internal_http_dispatch_keeps_wire_contract_and_saves_check(agent_db, tmp_path):
    from fastapi.testclient import TestClient

    from resolveflow.api.app import create_app
    from resolveflow.api.identity import mint_service_token
    from tests.integration.test_support_staged_api import SECRET

    req = request()
    run = runtime(agent_db, lambda _: httpx.Response(200, json=response()))
    app = create_app(provider_db=tmp_path / "provider.db", delivery_loop=False, worker_loop=False,
                     migrate=False, jwt_secret=SECRET, support_runtime=run)
    token = mint_service_token("case-service", SECRET, scope="support:run",
                               merchant_id=req.merchant_id, customer_id=req.customer_id)
    with TestClient(app) as api:
        reply = api.post("/internal/v1/support-runs",
                         json={**req.model_dump(mode="json"), "tool_token": "bound-test"},
                         headers={"Authorization": "Bearer " + token})
    assert reply.status_code == 200
    assert reply.json()["status"] == "SUCCEEDED" and reply.json()["spend"]["model_calls"] == 3
    assert "jev" not in reply.json()["answer"]
    with agent_db.connection() as c:
        saved = c.execute("SELECT response_json FROM support_agent_call WHERE kind='jev'").fetchone()["response_json"]
    assert saved["verdict"] == "contradicted"


def test_complete_application_guide_fits_the_existing_budget(agent_db):
    from tests.unit.test_support_agent import GuideReads

    config = JevConfig(enabled=True, api_key="test-secret")
    run = SupportRuntime(agent_db, DeploymentConfig(mode="mock"), jev_config=config,
                         model_factory=lambda: MockModelClient(script=[read("get_support_guide"),
                             answer(text="你可以请商家协助核查。", citations=["O1"])]),
                         sources_factory=lambda *_: GuideReads(),
                         jev_client=JevClient(config, transport=httpx.MockTransport(
                             lambda _: httpx.Response(200, json=response()))))
    assert run.run(request(), "bound-test")["status"] == "SUCCEEDED"
    with agent_db.connection() as c:
        saved = c.execute("SELECT request_json,response_json FROM support_agent_call WHERE kind='jev'").fetchone()
    assert saved["response_json"]["status"] == "COMPLETE"
    assert saved["request_json"]["body"]["state"]["observations"][0]["data"]["authority"] == "APPLICATION_GUIDE"
