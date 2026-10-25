"""Both evaluation arms journal the same output contracts and replay without new model calls."""

import pytest
from scripts.evaluation.support_fixed_current import FixedCurrentRuntime

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import read
from tests.unit.test_support_boundary_closeout import seeded_memory
from tests.unit.test_support_orchestrated_engine import Sources
from tests.unit.test_support_orchestration import plan


@pytest.mark.parametrize("runtime_type", [SupportRuntime, FixedCurrentRuntime])
def test_paired_arms_keep_correction_summary_and_fenced_recovery(agent_db, runtime_type):
    req, mem = seeded_memory()
    opening = plan(req, intent="HANDOFF", goal="MERCHANT_REVIEW").model_dump()
    opening["customer_claims"] = [{"topic": "RECEIPT", "reference": "CURRENT",
        "quote": req.context["current_request"], "change": "REPLACE", "targets": [e["id"] for e in mem.entries[:2]]}]
    final = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "请核对后确认，尚未发送。"}],
             "handoff_reason": {"customer_refs": ["CURRENT"]}}
    query = [read("search_policy", query="核查规则")] if runtime_type is FixedCurrentRuntime else []
    script = [opening, *query, final]
    models, sources = [TokenizedScript(script=script, mode="live")], Sources()
    runtime = runtime_type(agent_db, DeploymentConfig(mode="mock"), architecture="orchestrated-v1",
        model_factory=lambda: models[0], sources_factory=lambda *_: sources)
    result = runtime.run(req, "test-bound")
    assert result["status"] == "SUCCEEDED" and not result["answer"].get("refund_summary")
    assert result["answer"]["customer_memory"]["entries"][0]["status"] == "SUPERSEDED"
    assert "包裹已找到" in result["answer"]["handoff_summary"]
    with agent_db.connection() as c:
        manifest = c.execute("SELECT manifest_json FROM support_agent_run WHERE run_id=%s",
                             (req.run_id,)).fetchone()["manifest_json"]
        assert ("evaluation_controller" in manifest) == (runtime_type is FixedCurrentRuntime)
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    before = list(sources.calls)
    models[0] = TokenizedScript(script=script, mode="live")
    assert runtime.run(req, "new-test-bound") == result
    assert models[0].calls == 0 and sources.calls == before
