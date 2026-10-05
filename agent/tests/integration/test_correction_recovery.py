"""Fenced persisted failures must reconstruct the correction state, not reset it."""

from dataclasses import replace

import pytest
from resolveflow.harness.live_model import _decision_of
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.runtime.durable import DurableRun

from tests.integration.test_recovery_budget_store import _store
from tests.integration.test_run_store import RUN_ID
from tests.integration.test_sdk_durable_recovery import Crash
from tests.unit.test_harness_loop import FACTS, StubTools, observation, propose, read


@pytest.mark.parametrize("window", ["before_model_saved", "after_model_saved", "after_tool_saved"])
def test_invalid_json_repair_survives_crash(agent_db, window):
    _store(agent_db)
    facts = replace(FACTS, run_id=RUN_ID, fence=1, lease_owner="test-worker")
    script = [_decision_of("SYNTHETIC non JSON"), read("get_order_context"), propose("MANUAL_REVIEW")]
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
    assert result.completed and result.spend.model_calls == (4 if window == "before_model_saved" else 3)
    assert len(tools.calls) + len(resumed_tools.calls) == 1
    assert sum("MODEL_JSON_INVALID" in n for n in result.notices) == 1


@pytest.mark.parametrize("repair_exhausted", [False, True])
def test_saved_tool_failure_is_reused_and_retry_state_is_reconstructed(agent_db, repair_exhausted):
    _store(agent_db)
    facts = replace(FACTS, run_id=RUN_ID, fence=1, lease_owner="test-worker")
    script = [read("get_order_context"), read("get_order_context"),
              read("get_order_context") if repair_exhausted else propose("MANUAL_REVIEW")]
    tools = StubTools(TimeoutError("SYNTHETIC temporary failure"))

    def crash(stage):
        if stage == "after_tool_saved":
            raise Crash()

    with pytest.raises((Crash, BaseExceptionGroup)):
        AgentScopeRunner(model=MockModelClient(script=script), tools=tools, facts=facts,
                         durability=DurableRun(agent_db, facts, fault=crash)).run()
    resumed_tools = StubTools(TimeoutError() if repair_exhausted else observation())
    result = AgentScopeRunner(model=MockModelClient(script=script), tools=resumed_tools, facts=facts,
                             durability=DurableRun(agent_db, facts)).run()
    assert result.completed is not repair_exhausted
    if repair_exhausted:
        assert result.reason_code == "TOOL_RETRIES_EXHAUSTED"
    assert len(tools.calls) + len(resumed_tools.calls) == 2
    assert result.spend.tool_attempts == 2
    assert sum("TOOL_TRANSIENT" in n for n in result.notices) == (2 if repair_exhausted else 1)


def test_saved_invalid_json_does_not_grant_second_repair(agent_db):
    _store(agent_db)
    facts = replace(FACTS, run_id=RUN_ID, fence=1, lease_owner="test-worker")
    invalid = _decision_of("not JSON")

    def crash(stage):
        if stage == "after_model_saved":
            raise Crash()

    with pytest.raises((Crash, BaseExceptionGroup)):
        AgentScopeRunner(model=MockModelClient(script=[invalid, invalid]), tools=StubTools(), facts=facts,
                         durability=DurableRun(agent_db, facts, fault=crash)).run()
    result = AgentScopeRunner(model=MockModelClient(script=[invalid, invalid]), tools=StubTools(), facts=facts,
                             durability=DurableRun(agent_db, facts)).run()
    assert not result.completed and result.reason_code == "MODEL_JSON_INVALID"
    assert result.spend.model_calls == 2


def test_saved_semantic_refusal_reconstructs_its_one_repair(agent_db):
    _store(agent_db)
    facts = replace(FACTS, run_id=RUN_ID, fence=1, lease_owner="test-worker")
    source = observation("get_shipment_trace", carrier_conclusion="LOST", status="LOST")
    refs = [{k: getattr(source, k) for k in ("observation_id", "source_ref", "source_version", "content_hash")}]
    script = [read("get_shipment_trace"),
              propose("MANUAL_REVIEW", summary="承运商已确认正常签收。", evidence_refs=refs),
              propose("MANUAL_REVIEW", summary="承运商确认丢失，建议人工检查。", evidence_refs=refs)]
    tools, saved = StubTools(source), 0

    def crash(stage):
        nonlocal saved
        if stage == "after_model_saved":
            saved += 1
            if saved == 2:
                raise Crash()

    original = MockModelClient(script=script)
    with pytest.raises((Crash, BaseExceptionGroup)):
        AgentScopeRunner(model=original, tools=tools, facts=facts,
                         durability=DurableRun(agent_db, facts, fault=crash)).run()
    resumed = MockModelClient(script=script)
    resumed_tools = StubTools()
    result = AgentScopeRunner(model=resumed, tools=resumed_tools, facts=facts,
                             durability=DurableRun(agent_db, facts)).run()
    assert result.completed and result.spend.model_calls == original.calls + resumed.calls == 3
    assert len(tools.calls) == 1 and not resumed_tools.calls
    assert sum("FACT_CLAIM_UNSUPPORTED" in n for n in result.notices) == 1
