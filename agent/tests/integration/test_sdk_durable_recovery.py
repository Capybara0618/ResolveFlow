from dataclasses import replace

import pytest

from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.runtime.db import Database
from resolveflow.runtime.durable import DurableRun
from tests.integration.test_recovery_budget_store import _store
from tests.integration.test_run_store import RUN_ID
from tests.unit.test_harness_loop import FACTS, StubTools, observation, propose


class Crash(BaseException):
    pass


@pytest.mark.parametrize("window", ["before_model_saved", "after_model_saved", "after_tool_saved"])
@pytest.mark.parametrize("repeat", range(5))
def test_same_sdk_reconstruction_reuses_saved_calls(agent_db: Database, window: str, repeat: int) -> None:
    _store(agent_db)
    facts = replace(FACTS, run_id=RUN_ID, fence=1, lease_owner="test-worker")
    script = [{"kind": "READ_TOOL", "tool_name": "get_order_context", "arguments": {}},
              propose("MANUAL_REVIEW", summary="synthetic manual review")]
    tools = StubTools(observation())

    def crash(stage: str) -> None:
        if stage == window:
            raise Crash()

    first = AgentScopeRunner(model=MockModelClient(script=script), tools=tools, facts=facts,
                             durability=DurableRun(agent_db, facts, fault=crash))
    with pytest.raises((Crash, BaseExceptionGroup)):
        first.run()
    resumed_tools = StubTools() if window == "after_tool_saved" else StubTools(observation())
    resumed = AgentScopeRunner(model=MockModelClient(script=script), tools=resumed_tools, facts=facts,
                               durability=DurableRun(agent_db, facts))
    result = resumed.run()
    assert result.completed and result.decision.recommended_action == "MANUAL_REVIEW"
    assert len(tools.calls) + len(resumed_tools.calls) == 1
    assert result.spend.model_calls == (3 if window == "before_model_saved" else 2)


def test_reconstructed_mcp_keeps_trace_page_allowance(agent_db: Database) -> None:
    from resolveflow.harness.mcp_client import McpToolExecutor

    _store(agent_db)
    facts = replace(FACTS, run_id=RUN_ID, fence=1, lease_owner="test-worker")
    script = [{"kind": "READ_TOOL", "tool_name": "get_shipment_trace", "arguments": {}},
              propose("MANUAL_REVIEW", summary="synthetic")]
    def crash(stage):
        if stage == "after_tool_saved":
            raise Crash()
    first = AgentScopeRunner(model=MockModelClient(script=script),
                             tools=StubTools(observation().model_copy(update={"tool_name": "get_shipment_trace"})),
                             facts=facts, durability=DurableRun(agent_db, facts, fault=crash))
    with pytest.raises(Crash):
        first.run()
    tools = McpToolExecutor(line_id=facts.line_id, run_id=facts.run_id, case_id=facts.case_id)
    resumed = AgentScopeRunner(model=MockModelClient(script=script), tools=tools, facts=facts,
                               durability=DurableRun(agent_db, facts))
    assert resumed.run().completed
    assert tools.trace_pages == 1
    assert tools.calls == []
