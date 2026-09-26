from pathlib import Path

import pytest

from resolveflow.harness.model import MockModelClient
from resolveflow.replay.export import export_run
from resolveflow.replay.pack import UnsupportedRecord, read_pack
from resolveflow.runtime.db import Database
from resolveflow.runtime.factory import DeploymentConfig, build_investigation
from resolveflow.runtime.runs import RunStore
from resolveflow.runtime.worker import RunWorker
from tests.integration.test_run_worker import CASE_DISPATCHER, RUN_ID, a_run
from tests.unit.test_harness_loop import StubTools, propose


def test_export_is_complete_read_only_and_refuses_non_synthetic(agent_db: Database, tmp_path: Path) -> None:
    RunStore(agent_db).queue(a_run(description="SYNTHETIC_REPLAY: manual review"), caller=CASE_DISPATCHER)
    investigate = build_investigation(
        database=agent_db, config=DeploymentConfig(mode="mock"),
        model=MockModelClient(script=[propose("MANUAL_REVIEW", summary="synthetic")]), tools=StubTools(),
    )
    assert RunWorker(agent_db, investigate, recoverable=True).run_once().callback_kind == "PROPOSAL"
    pack = tmp_path / "pack"
    export_run(agent_db, RUN_ID, pack)
    document = read_pack(pack)
    assert document["source_run_id"] == RUN_ID
    assert document["model_calls"][0]["response"]["decision"]["kind"] == "PROPOSE"
    assert document["expected"]["callback_kind"] == "PROPOSAL"
    with pytest.raises(FileExistsError):
        export_run(agent_db, RUN_ID, pack)
    with agent_db.connection() as connection:
        connection.execute("UPDATE agent_run SET request_description='real customer text'")
    with pytest.raises(UnsupportedRecord):
        export_run(agent_db, RUN_ID, tmp_path / "refused")
