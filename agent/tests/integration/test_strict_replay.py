import socket
from pathlib import Path

import pytest

from resolveflow.harness.model import MockModelClient
from resolveflow.replay.export import export_run
from resolveflow.replay.isolation import block_network
from resolveflow.replay.pack import PackInvalid, ReplayMiss
from resolveflow.replay.strict import strict_replay
from resolveflow.runtime.db import Database
from resolveflow.runtime.factory import DeploymentConfig, build_investigation
from resolveflow.runtime.runs import RunStore
from resolveflow.runtime.worker import RunWorker
from tests.integration.test_run_worker import CASE_DISPATCHER, RUN_ID, a_run
from tests.unit.test_harness_loop import StubTools, propose


def test_same_sdk_replays_complete_record_and_missing_call_fails(agent_db: Database, tmp_path: Path) -> None:
    RunStore(agent_db).queue(a_run(description="SYNTHETIC_REPLAY: one proposal"), caller=CASE_DISPATCHER)
    investigate = build_investigation(
        database=agent_db, config=DeploymentConfig(mode="mock"),
        model=MockModelClient(script=[propose("MANUAL_REVIEW", summary="synthetic")]), tools=StubTools(),
    )
    assert RunWorker(agent_db, investigate, recoverable=True).run_once().callback_kind == "PROPOSAL"
    pack = tmp_path / "pack"
    export_run(agent_db, RUN_ID, pack)
    report = strict_replay(pack)
    assert report["status"] == "MATCH"
    assert report["model_calls"] == 1
    from resolveflow.replay.pack import read_pack, write_pack

    document = read_pack(pack)
    document["model_calls"] = []
    write_pack(tmp_path / "missing", document)
    with pytest.raises(ReplayMiss):
        strict_replay(tmp_path / "missing")
    document = read_pack(pack)
    document["manifest"]["state_schema_version"] = 999
    write_pack(tmp_path / "changed", document)
    with pytest.raises(PackInvalid):
        strict_replay(tmp_path / "changed")


def test_replay_python_guard_refuses_real_socket_connect() -> None:
    with block_network() as attempts, pytest.raises(OSError, match="forbids network"):
        socket.create_connection(("127.0.0.1", 1), timeout=0.1)
    assert attempts
