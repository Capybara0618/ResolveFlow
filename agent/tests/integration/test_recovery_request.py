import pytest

from resolveflow.harness.budget import RunBudget
from resolveflow.harness.context import hash_document
from resolveflow.runtime.db import Database
from resolveflow.runtime.recovery_store import RecoveryConflictError
from tests.integration.test_recovery_budget_store import _store
from tests.integration.test_run_store import RUN_ID


def test_request_body_and_snapshot_are_frozen_with_reservation(agent_db: Database) -> None:
    store = _store(agent_db)
    store.initialize(RUN_ID, fence=1, owner="test-worker", manifest_id="m", budget=RunBudget())
    body = {"messages": [{"role": "user", "content": "synthetic"}], "max_tokens": 1024}
    store.reserve(RUN_ID, fence=1, owner="test-worker", call_id="0", request_hash=hash_document(body),
                  kind="ORDINARY", input_tokens=20, request_body=body, replay_spend={}, sdk_state={"context": []})
    with agent_db.connection() as connection:
        row = connection.execute("SELECT request_body,replay_spend,sdk_state FROM agent_model_call").fetchone()
        assert row["request_body"] == body and row["replay_spend"] == {} and row["sdk_state"] == {"context": []}


def test_request_hash_or_ceiling_mismatch_rolls_back(agent_db: Database) -> None:
    store = _store(agent_db)
    store.initialize(RUN_ID, fence=1, owner="test-worker", manifest_id="m", budget=RunBudget())
    body = {"messages": [], "max_tokens": 9999}
    with pytest.raises(RecoveryConflictError):
        store.reserve(RUN_ID, fence=1, owner="test-worker", call_id="0", request_hash=hash_document(body),
                      kind="ORDINARY", input_tokens=20, request_body=body)
    with agent_db.connection() as connection:
        assert connection.execute("SELECT count(*) AS n FROM agent_model_call").fetchone()["n"] == 0
