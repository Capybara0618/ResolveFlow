"""Alternating-loop progress is reconstructed from fenced persisted results."""

from dataclasses import replace

import pytest
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.runtime.durable import DurableRun

from tests.integration.test_recovery_budget_store import _store
from tests.integration.test_run_store import RUN_ID
from tests.integration.test_sdk_durable_recovery import Crash
from tests.unit.test_harness_loop import FACTS, StubTools, observation, read


def test_alternating_no_progress_survives_crash_without_repeating_saved_tools(agent_db):
    _store(agent_db)
    facts = replace(FACTS, run_id=RUN_ID, fence=1, lease_owner="test-worker")
    a = observation("get_order_context")
    b = observation("get_refund_status").model_copy(update={"content_hash": "b" * 64})
    script = [read(name) for name in ["get_order_context", "get_refund_status", "get_order_context",
                                    "get_refund_status", "get_order_context"]]
    saved = 0

    def crash(stage):
        nonlocal saved
        if stage == "after_tool_saved":
            saved += 1
            if saved == 4:
                raise Crash()

    original = MockModelClient(script=script)
    tools = StubTools(a, b, a, b)
    with pytest.raises((Crash, BaseExceptionGroup)):
        AgentScopeRunner(model=original, tools=tools, facts=facts,
            durability=DurableRun(agent_db, facts, fault=crash)).run()
    resumed = MockModelClient(script=script)
    resumed_tools = StubTools()
    result = AgentScopeRunner(model=resumed, tools=resumed_tools, facts=facts,
        durability=DurableRun(agent_db, facts)).run()
    assert result.reason_code == "NO_PROGRESS" and result.spend.no_progress_rounds == 2
    assert original.calls + resumed.calls == result.spend.model_calls == 5
    assert len(tools.calls) == 4 and not resumed_tools.calls
    assert sum(n.startswith("NO_PROGRESS") for n in result.notices) == 2
