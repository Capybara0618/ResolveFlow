"""Actual PG cached recovery preserves facts/summary and emits no new provider work."""

import logging

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_orchestrated_engine import Sources, respond
from tests.unit.test_support_orchestration import plan


def test_timing_does_not_invalidate_saved_results_or_invent_provider_work(agent_db, caplog):
    caplog.set_level(logging.INFO, logger="resolveflow.support.engine")
    req = request()
    script = [plan(req).model_dump(), read("get_order_context"), respond()]
    models = [TokenizedScript(mode="live", script=script, use_context_step=True)]
    sources = Sources()
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode="mock"), architecture="orchestrated-v1",
                             model_factory=lambda: models[0], sources_factory=lambda *_: sources)
    original = runtime.run(req, "test-bound")
    assert original["status"] == "SUCCEEDED" and models[0].calls == 3
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    caplog.clear()
    # The script is part of the frozen mock manifest. Keep it identical during recovery.
    models[0] = TokenizedScript(mode="live", script=script, use_context_step=True)
    recovered = runtime.run(req, "test-bound")
    assert recovered == original and models[0].calls == 0
    assert [name for name, _ in sources.calls] == ["get_support_guide", "get_order_context"]
    logs = [r.message for r in caplog.records if "support_model_timing" in r.message]
    assert len(logs) == 3 and all("cached=True" in line and "provider_ms=0" in line for line in logs)
