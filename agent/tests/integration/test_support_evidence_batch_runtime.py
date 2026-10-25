"""Optional policy child preserves per-call persistence, budgets and fencing."""

import pytest

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import SupportFailure
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.integration.test_support_fact_batch_runtime import expire
from tests.unit.test_support_agent import request
from tests.unit.test_support_evidence_batch import fast_script
from tests.unit.test_support_orchestrated_engine import Sources
from tests.unit.test_support_orchestration import plan


def runtime_for(db, sources):
    models = [TokenizedScript(mode="live", script=fast_script(), use_context_step=True)]
    runtime = SupportRuntime(db, DeploymentConfig(mode="live", provider="deepseek", model_id="deepseek-flash"),
                             architecture="orchestrated-v1", model_factory=lambda: models[0],
                             sources_factory=lambda *_: sources)
    return runtime, models


def test_all_three_children_persist_and_complete_recovery_has_no_new_sends(agent_db):
    req, sources = request(), Sources()
    runtime, models = runtime_for(agent_db, sources)
    result = runtime.run(req, "test-bound")
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert result["spend"]["model_calls"] == 3 and result["spend"]["tool_attempts"] == 2
    assert result["spend"]["local_reads"] == 2
    with agent_db.connection() as c:
        rows = c.execute("SELECT position,request_json,status FROM support_agent_call "
                         "WHERE run_id=%s AND kind='tool' ORDER BY position", (req.run_id,)).fetchall()
    assert [r["request_json"]["name"] for r in rows] == ["get_support_guide", "get_order_context",
                                                       "get_shipment_trace", "search_policy"]
    assert all(r["status"] == "COMPLETE" for r in rows)
    expire(agent_db, req)
    previous = list(sources.calls)
    models[0] = TokenizedScript(mode="live", script=fast_script(), use_context_step=True)
    assert runtime.run(req, "test-recovered") == result
    assert models[0].calls == 0 and sources.calls == previous


def test_partial_group_reuses_both_facts_before_policy_start(agent_db, monkeypatch):
    original = SupportAgent.execute
    stopped = False

    def stop_before_policy(self, name, arguments):
        nonlocal stopped
        if name == "search_policy" and not stopped:
            stopped = True
            raise SupportFailure("TEST_BEFORE_POLICY_START")
        return original(self, name, arguments)

    monkeypatch.setattr(SupportAgent, "execute", stop_before_policy)
    req, sources = request(), Sources()
    runtime, models = runtime_for(agent_db, sources)
    first = runtime.run(req, "test-bound")
    assert first["reason"] == "TEST_BEFORE_POLICY_START"
    assert first["spend"]["model_calls"] == 2 and first["spend"]["tool_attempts"] == 2
    assert first["spend"]["local_reads"] == 1
    expire(agent_db, req)
    models[0] = TokenizedScript(mode="live", script=fast_script(), use_context_step=True)
    result = runtime.run(req, "test-recovered")
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert models[0].calls == 1 and result["spend"]["model_calls"] == 3
    assert result["spend"]["tool_attempts"] == 2 and result["spend"]["local_reads"] == 2
    assert [n for n, _ in sources.calls] == ["get_support_guide", "get_order_context",
                                          "get_shipment_trace", "search_policy"]


def test_stale_fence_after_facts_blocks_policy_child(agent_db, monkeypatch):
    original = SupportAgent.execute

    def change_fence(self, name, arguments):
        value = original(self, name, arguments)
        if name == "get_shipment_trace":
            with agent_db.connection() as c:
                c.execute("UPDATE support_agent_run SET fence=fence+1 WHERE run_id=%s", (self.request.run_id,))
        return value

    monkeypatch.setattr(SupportAgent, "execute", change_fence)
    req, sources = request(), Sources()
    runtime, _ = runtime_for(agent_db, sources)
    with pytest.raises(SupportFailure, match="STALE_FENCE"):
        runtime.run(req, "test-bound")
    assert [n for n, _ in sources.calls] == ["get_support_guide", "get_order_context", "get_shipment_trace"]


def test_single_fact_policy_group_persists_and_recovers_without_new_calls(agent_db):
    req, sources = request(), Sources()
    opening = plan(req, intent="LOGISTICS", goal="EXPLAIN", needs=["SHIPMENT", "POLICY"]).model_dump()
    selected = {"kind": "READ_FACTS", "tools": ["get_shipment_trace"], "policy_query": "签收争议处理条件"}
    answer = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "需按条款核验争议。",
                                            "citations": ["P1"]}]}
    script = [opening, selected, answer]
    models = [TokenizedScript(mode="live", script=script, use_context_step=True)]
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode="mock"), architecture="orchestrated-v1",
        model_factory=lambda: models[0], sources_factory=lambda *_: sources)
    result = runtime.run(req, "test-bound")
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert result["spend"]["tool_attempts"] == 1 and result["spend"]["local_reads"] == 2
    with agent_db.connection() as c:
        rows = c.execute("SELECT request_json FROM support_agent_call WHERE run_id=%s AND kind='tool' "
                         "ORDER BY position", (req.run_id,)).fetchall()
    assert [r["request_json"]["name"] for r in rows] == ["get_support_guide", "get_shipment_trace", "search_policy"]
    expire(agent_db, req)
    before = list(sources.calls)
    models[0] = TokenizedScript(mode="live", script=script, use_context_step=True)
    assert runtime.run(req, "test-recovered") == result
    assert models[0].calls == 0 and sources.calls == before
