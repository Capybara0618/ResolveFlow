"""A saved refused question must not reset its repair or become a customer callback."""

from dataclasses import replace

import pytest
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.runtime.durable import DurableRun

from tests.integration.test_recovery_budget_store import _store
from tests.integration.test_run_store import RUN_ID
from tests.integration.test_sdk_durable_recovery import Crash
from tests.unit.test_harness_loop import FACTS, StubTools, observation, propose, read
from tests.unit.test_investigation_termination import ask


@pytest.mark.parametrize("window", ["before_model_saved", "after_model_saved", "after_tool_saved"])
def test_identity_question_repair_is_reconstructed_with_existing_spend(agent_db, window):
    _store(agent_db)
    facts = replace(FACTS, run_id=RUN_ID, fence=1, lease_owner="test-worker")
    script = [ask("order_id"), read("get_order_context"), propose("MANUAL_REVIEW")]
    tools = StubTools(observation())

    def crash(stage):
        if stage == window:
            raise Crash()

    with pytest.raises((Crash, BaseExceptionGroup)):
        AgentScopeRunner(model=MockModelClient(script=script), tools=tools, facts=facts,
                         durability=DurableRun(agent_db, facts, fault=crash)).run()
    resumed_tools = StubTools() if window == "after_tool_saved" else StubTools(observation())
    result = AgentScopeRunner(model=MockModelClient(script=script), tools=resumed_tools, facts=facts,
                             durability=DurableRun(agent_db, facts)).run()
    assert result.completed and result.decision.kind == "PROPOSE"
    assert result.spend.model_calls == (4 if window == "before_model_saved" else 3)
    assert len(tools.calls) + len(resumed_tools.calls) == 1
    assert sum("QUESTION_ALREADY_BOUND" in notice for notice in result.notices) == 1
