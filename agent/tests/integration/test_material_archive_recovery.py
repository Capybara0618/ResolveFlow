"""Material windows reconstruct from the same persisted revision without network or renewed budgets."""

from dataclasses import replace

import pytest
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.replay.export import export_run
from resolveflow.replay.strict import strict_replay
from resolveflow.runtime.db import Database
from resolveflow.runtime.durable import DurableRun
from resolveflow.runtime.factory import DeploymentConfig, build_investigation
from resolveflow.runtime.runs import RunStore
from resolveflow.runtime.worker import RunWorker

from tests.integration.test_run_store import CASE_DISPATCHER, RUN_ID, a_request
from tests.integration.test_sdk_durable_recovery import Crash
from tests.unit.test_context_batch2 import material
from tests.unit.test_harness_loop import FACTS, StubTools, propose


@pytest.mark.parametrize("window", ["before_model_saved", "after_model_saved", "after_tool_saved"])
def test_material_window_recovery(agent_db: Database, window: str) -> None:
    RunStore(agent_db).queue(a_request(review_context={"materials": [material()], "questions": []},
                                     evidence_refs=("m1",)), caller=CASE_DISPATCHER)
    with agent_db.connection() as connection:
        row = connection.execute(
            "UPDATE agent_run SET status='RUNNING', fence=1, lease_owner='test-worker', "
            "lease_until=now()+interval '1 hour', active_deadline_at=now()+interval '120 seconds' "
            "WHERE run_id=%s RETURNING review_context", (RUN_ID,),
        ).fetchone()
    assert row is not None
    facts = replace(FACTS, run_id=RUN_ID, fence=1, lease_owner="test-worker",
                    review_context=row["review_context"])
    script = [{"kind": "READ_OBSERVATION", "observation_id": "material:m1",
               "arguments": {"offset": 7000, "limit": 100}}, propose("MANUAL_REVIEW")]

    def crash(stage: str) -> None:
        if stage == window:
            raise Crash()

    first = AgentScopeRunner(model=MockModelClient(script=script), tools=StubTools(), facts=facts,
                             durability=DurableRun(agent_db, facts, fault=crash))
    with pytest.raises((Crash, BaseExceptionGroup)):
        first.run()
    with agent_db.connection() as connection:
        row = connection.execute("SELECT review_context FROM agent_run WHERE run_id=%s", (RUN_ID,)).fetchone()
    facts = replace(facts, review_context=row["review_context"])
    result = AgentScopeRunner(model=MockModelClient(script=script), tools=StubTools(), facts=facts,
                              durability=DurableRun(agent_db, facts)).run()
    assert result.completed and result.spend.local_reads == 1
    assert result.spend.model_calls == (3 if window == "before_model_saved" else 2)
    assert result.observations[0].result["text"] == facts.review_context["materials"][0]["content"][7000:7100]
    with agent_db.connection() as connection:
        assert connection.execute("SELECT count(*) AS n FROM agent_tool_call").fetchone()["n"] == 1


def test_material_window_strict_replay(agent_db: Database, tmp_path) -> None:
    RunStore(agent_db).queue(a_request(review_context={"materials": [material()], "questions": []},
                                     evidence_refs=("m1",), description="SYNTHETIC_REPLAY: material window"),
                             caller=CASE_DISPATCHER)
    investigate = build_investigation(
        database=agent_db, config=DeploymentConfig(mode="mock"), tools=StubTools(),
        model=MockModelClient(script=[
            {"kind": "READ_OBSERVATION", "observation_id": "material:m1",
             "arguments": {"offset": 7000, "limit": 100}}, propose("MANUAL_REVIEW")]),
    )
    outcome = RunWorker(agent_db, investigate, recoverable=True).run_once()
    assert outcome.callback_kind == "PROPOSAL"
    directory = tmp_path / "material-read"
    export_run(agent_db, RUN_ID, directory)
    assert strict_replay(directory)["status"] == "MATCH"
