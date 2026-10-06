"""A saved finding refusal reconstructs the same one-repair limit under the original fence."""

from dataclasses import replace

import pytest
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.runtime.durable import DurableRun

from tests.integration.test_recovery_budget_store import _store
from tests.integration.test_run_store import RUN_ID
from tests.integration.test_sdk_durable_recovery import Crash
from tests.unit.test_harness_loop import FACTS, StubTools, observation, propose, read


@pytest.mark.parametrize("repair", [True, False])
def test_saved_finding_error_preserves_feedback_and_repair_count_after_crash(agent_db, repair):
    _store(agent_db)
    facts = replace(FACTS, run_id=RUN_ID, fence=1, lease_owner="test-worker")
    bad = propose("MANUAL_REVIEW", evidence_refs=["O1"], review_findings=[
        {"kind": "CONFLICT", "text": "synthetic conflict", "observation_ids": ["O1"]}])
    good = propose("MANUAL_REVIEW", evidence_refs=["O1"], review_findings=[
        {"kind": "FACT", "text": "synthetic source claim", "observation_ids": ["O1"]}])
    script = [read("get_order_context"), bad, good if repair else bad]
    original_tools = StubTools(observation())

    def fault(stage):
        if stage == "after_model_saved":
            with agent_db.connection() as connection:
                row = connection.execute("SELECT count(*) AS n FROM agent_model_call WHERE state='SAVED'").fetchone()
            if row["n"] == 2:
                raise Crash()

    with pytest.raises((Crash, BaseExceptionGroup)):
        AgentScopeRunner(model=MockModelClient(script=script), tools=original_tools, facts=facts,
                         durability=DurableRun(agent_db, facts, fault=fault)).run()
    resumed_tools = StubTools()
    resumed_model = MockModelClient(script=script)
    result = AgentScopeRunner(model=resumed_model, tools=resumed_tools, facts=facts,
                              durability=DurableRun(agent_db, facts)).run()
    assert result.completed is repair
    assert result.spend.model_calls == 3
    assert len(original_tools.calls) == 1 and not resumed_tools.calls
    assert resumed_model.calls == 1
    assert sum("FINDING_SOURCE_INVALID" in notice for notice in result.notices) == 1
    if repair:
        assert result.decision.review_findings[0].kind == "FACT"
    else:
        assert result.reason_code == "FINDING_SOURCE_INVALID" and result.decision is None
        assert result.trajectory[-1]["origin"] == "HARNESS"
