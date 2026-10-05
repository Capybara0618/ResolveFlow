"""Raw alias decisions recover and replay into exactly the same canonical callback."""

import os
from dataclasses import replace
from pathlib import Path

import pytest
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.replay.export import export_run
from resolveflow.replay.pack import read_pack
from resolveflow.replay.strict import strict_replay
from resolveflow.runtime.durable import DurableRun
from resolveflow.runtime.factory import DeploymentConfig, build_investigation
from resolveflow.runtime.runs import RunStore
from resolveflow.runtime.worker import RunWorker

from tests.integration.test_run_store import CASE_DISPATCHER, RUN_ID, a_request
from tests.integration.test_sdk_durable_recovery import Crash
from tests.unit.test_harness_loop import FACTS, StubTools, observation, propose, read


def script():
    return [read("get_order_context"),
            {"kind": "READ_OBSERVATION", "observation_id": "O1", "arguments": {"limit": 30}},
            {**propose("MANUAL_REVIEW"), "evidence_refs": ["O1"]}]


@pytest.mark.parametrize("window", ["before_model_saved", "after_model_saved", "after_tool_saved"])
def test_short_refs_reconstruct_without_rebinding_or_duplicate_tool_calls(agent_db, window):
    RunStore(agent_db).queue(a_request(), caller=CASE_DISPATCHER)
    with agent_db.connection() as connection:
        connection.execute("UPDATE agent_run SET status='RUNNING', fence=1, lease_owner='test-worker', "
                           "lease_until=now()+interval '1 hour', active_deadline_at=now()+interval '120 seconds' "
                           "WHERE run_id=%s", (RUN_ID,))
    facts = replace(FACTS, run_id=RUN_ID, fence=1, lease_owner="test-worker")
    saved_models = 0

    def crash(stage):
        nonlocal saved_models
        if stage == "after_model_saved":
            saved_models += 1
        # Model faults target the final alias proposal, after the two reads exist.
        target = 3 if stage == "after_model_saved" else 2
        if stage == window and (stage == "after_tool_saved" or saved_models == target):
            raise Crash()

    first_tools = StubTools(observation())
    with pytest.raises((Crash, BaseExceptionGroup)):
        AgentScopeRunner(model=MockModelClient(script=script()), tools=first_tools, facts=facts,
                         durability=DurableRun(agent_db, facts, fault=crash)).run()
    resumed_tools = StubTools()
    result = AgentScopeRunner(model=MockModelClient(script=script()), tools=resumed_tools, facts=facts,
                             durability=DurableRun(agent_db, facts)).run()
    assert result.completed and result.decision.evidence_refs[0].observation_id == observation().observation_id
    assert len(first_tools.calls) + len(resumed_tools.calls) == 1
    assert result.spend.local_reads == 1
    assert result.spend.model_calls == (4 if window == "before_model_saved" else 3)
    with agent_db.connection() as connection:
        assert connection.execute("SELECT count(*) AS n FROM agent_tool_call").fetchone()["n"] == 2
        reply = connection.execute("SELECT response FROM agent_model_call WHERE call_id='model-2'").fetchone()
        assert reply["response"]["decision"]["evidence_refs"] == ["O1"]


def test_short_ref_readback_and_proposal_strict_replay(agent_db, tmp_path):
    RunStore(agent_db).queue(a_request(description="SYNTHETIC_REPLAY: short references"), caller=CASE_DISPATCHER)
    investigate = build_investigation(database=agent_db, config=DeploymentConfig(mode="mock"),
                                     tools=StubTools(observation()), model=MockModelClient(script=script()))
    outcome = RunWorker(agent_db, investigate, recoverable=True).run_once()
    assert outcome.callback_kind == "PROPOSAL"
    output_root = os.environ.get("RESOLVEFLOW_SHORT_REF_GOLDEN_DIR")
    directory = Path(output_root) / "short_references" if output_root else tmp_path / "short-references"
    export_run(agent_db, RUN_ID, directory)
    pack = read_pack(directory)
    assert pack["tool_calls"][1]["request_body"]["arguments"]["observation_id"] == observation().observation_id
    assert pack["model_calls"][2]["response"]["decision"]["evidence_refs"] == ["O1"]
    assert strict_replay(directory)["status"] == "MATCH"


def test_committed_short_reference_pack():
    directory = Path(__file__).resolve().parents[3] / "evals/replay/calibration-v9/short_references"
    assert strict_replay(directory)["status"] == "MATCH"
