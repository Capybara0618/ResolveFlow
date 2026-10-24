"""Batch children keep independent fenced journal entries, including partial interruption."""

import pytest

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import SupportFailure
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import request
from tests.unit.test_support_fact_batch import script
from tests.unit.test_support_orchestrated_engine import Sources


def runtime_for(db, sources):
    models = [TokenizedScript(mode="live", script=script(), use_context_step=True)]
    runtime = SupportRuntime(db, DeploymentConfig(mode="live", provider="deepseek", model_id="deepseek-flash"),
                             architecture="orchestrated-v1", model_factory=lambda: models[0],
                             sources_factory=lambda *_: sources)
    return runtime, models


def expire(db, req):
    with db.connection() as c:
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))


def test_pair_persists_each_child_and_full_recovery_reuses_all_calls(agent_db):
    req, sources = request(), Sources()
    runtime, models = runtime_for(agent_db, sources)
    result = runtime.run(req, "test-bound")
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert result["spend"]["model_calls"] == 4 and result["spend"]["tool_attempts"] == 2
    with agent_db.connection() as c:
        rows = c.execute("SELECT position,request_json,status FROM support_agent_call "
                         "WHERE run_id=%s AND kind='tool' ORDER BY position", (req.run_id,)).fetchall()
    assert [(r["position"], r["request_json"]["name"], r["status"]) for r in rows] == [
        (1, "get_support_guide", "COMPLETE"), (2, "get_order_context", "COMPLETE"),
        (3, "get_shipment_trace", "COMPLETE"), (4, "search_policy", "COMPLETE")]
    expire(agent_db, req)
    previous = list(sources.calls)
    models[0] = TokenizedScript(mode="live", script=script(), use_context_step=True)
    assert runtime.run(req, "test-recovered") == result
    assert models[0].calls == 0 and sources.calls == previous


def test_interruption_before_second_child_start_reuses_first_child_only(agent_db, monkeypatch):
    original = SupportAgent.execute
    interrupted = False

    def interrupt(self, name, arguments):
        nonlocal interrupted
        if name == "get_shipment_trace" and not interrupted:
            interrupted = True
            raise SupportFailure("TEST_STOP_BEFORE_SECOND_CHILD")
        return original(self, name, arguments)

    monkeypatch.setattr(SupportAgent, "execute", interrupt)
    req, sources = request(), Sources()
    runtime, models = runtime_for(agent_db, sources)
    first = runtime.run(req, "test-bound")
    assert first["reason"] == "TEST_STOP_BEFORE_SECOND_CHILD"
    assert first["spend"]["model_calls"] == 2 and first["spend"]["tool_attempts"] == 1
    assert [n for n, _ in sources.calls] == ["get_support_guide", "get_order_context"]
    expire(agent_db, req)
    models[0] = TokenizedScript(mode="live", script=script(), use_context_step=True)
    result = runtime.run(req, "test-recovered")
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert models[0].calls == 2  # Only policy choice and final composition were not persisted.
    assert result["spend"]["model_calls"] == 4 and result["spend"]["tool_attempts"] == 2
    assert [n for n, _ in sources.calls] == ["get_support_guide", "get_order_context",
                                          "get_shipment_trace", "search_policy"]


def test_started_child_without_result_is_explicit_interruption_not_silent_resend(agent_db):
    class Interrupted(Sources):
        def read(self, name, arguments):
            if name == "get_shipment_trace":
                self.calls.append((name, arguments))
                raise RuntimeError("synthetic interrupted tool")
            return super().read(name, arguments)

    req, sources = request(), Interrupted()
    runtime, models = runtime_for(agent_db, sources)
    first = runtime.run(req, "test-bound")
    assert first["status"] == "FAILED"
    expire(agent_db, req)
    previous = list(sources.calls)
    models[0] = TokenizedScript(mode="live", script=script(), use_context_step=True)
    result = runtime.run(req, "test-recovered")
    assert result["reason"] == "INTERRUPTED_TOOL_RESULT"
    assert models[0].calls == 0 and sources.calls == previous


def test_fence_change_after_first_child_blocks_second_child(agent_db, monkeypatch):
    original = SupportAgent.execute

    def change_fence(self, name, arguments):
        result = original(self, name, arguments)
        if name == "get_order_context":
            with agent_db.connection() as c:
                c.execute("UPDATE support_agent_run SET fence=fence+1 WHERE run_id=%s", (self.request.run_id,))
        return result

    monkeypatch.setattr(SupportAgent, "execute", change_fence)
    req, sources = request(), Sources()
    runtime, models = runtime_for(agent_db, sources)
    with pytest.raises(SupportFailure, match="STALE_FENCE"):
        runtime.run(req, "test-bound")
    assert models[0].calls == 2
    assert [name for name, _ in sources.calls] == ["get_support_guide", "get_order_context"]
