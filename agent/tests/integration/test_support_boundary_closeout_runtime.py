"""The new quote references and multi-target correction recover under the actual PG journal."""

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_boundary_closeout import seeded_memory
from tests.unit.test_support_orchestrated_engine import Sources
from tests.unit.test_support_orchestration import plan


def test_multi_claim_correction_and_reference_summary_recover_without_new_calls(agent_db):
    req, mem = seeded_memory()
    original_ids = [e["id"] for e in mem.entries[:2]]
    opening = plan(req, intent="HANDOFF", goal="MERCHANT_REVIEW").model_dump()
    opening["customer_claims"] = [{"topic": "RECEIPT", "reference": "CURRENT",
        "quote": req.context["current_request"], "change": "REPLACE", "targets": original_ids}]
    final = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "请核对核查说明，尚未发送。"}],
             "handoff_reason": {"customer_refs": ["CURRENT"]}}
    script = [opening, final]
    models, sources = [TokenizedScript(mode="live", script=script)], Sources()
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode="mock"), architecture="orchestrated-v1",
                             model_factory=lambda: models[0], sources_factory=lambda *_: sources)
    result = runtime.run(req, "test-bound")
    assert result["status"] == "SUCCEEDED" and models[0].calls == 2
    assert [e["status"] for e in result["answer"]["customer_memory"]["entries"]] == [
        "SUPERSEDED", "SUPERSEDED", "ACTIVE", "ACTIVE", "ACTIVE"]
    assert "包裹已找到" in result["answer"]["handoff_summary"]
    assert "本人尚未收到" not in result["answer"]["handoff_summary"]
    with agent_db.connection() as c:
        calls = c.execute("SELECT request_json FROM support_agent_call WHERE run_id=%s AND kind='model' "
                          "ORDER BY position", (req.run_id,)).fetchall()
        assert "summary_candidates" in str(calls[-1])
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    models[0] = TokenizedScript(mode="live", script=script)
    before = list(sources.calls)
    assert runtime.run(req, "replacement-test-bound") == result
    assert models[0].calls == 0 and sources.calls == before
