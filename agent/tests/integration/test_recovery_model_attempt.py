from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from psycopg.types.json import Jsonb

from resolveflow.harness.budget import BudgetExhaustedError, RunBudget, RunSpend
from resolveflow.harness.model import ModelReply, ModelUsage
from resolveflow.runtime.db import Database
from resolveflow.runtime.recovery_budget import RecoveryCallBudget, RecoveryCallBudgetExhausted
from resolveflow.runtime.recovery_store import RecoveryBudgetStore, RecoveryConflictError, StaleFenceError
from tests.integration.test_recovery_budget_store import _store
from tests.integration.test_recovery_model_result import _reserved, _spend
from tests.integration.test_run_store import RUN_ID


def test_unknown_retry_has_distinct_attempt_and_preserves_first_unknown_charge(agent_db: Database) -> None:
    store = _reserved(agent_db)
    retried = store.reserve_retry(RUN_ID, fence=1, owner="test-worker", call_id="step-0",
                                  request_hash="a" * 64, expected_attempt=0)
    assert retried.new_reservation and retried.attempt_no == 1 and retried.output_ceiling == 1024
    assert _spend(agent_db)["model_calls"] == 2
    assert _spend(agent_db)["output_tokens"] == 2048
    repeated = RecoveryBudgetStore(agent_db).reserve_retry(
        RUN_ID, fence=1, owner="test-worker", call_id="step-0", request_hash="a" * 64, expected_attempt=0,
    )
    assert not repeated.new_reservation and repeated.attempt_no == 1
    reply = ModelReply(decision={"kind": "ESCALATE"}, usage=ModelUsage(10, 5))
    store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0", attempt_no=1, reply=reply)
    assert _spend(agent_db)["input_tokens"] == 30
    assert _spend(agent_db)["output_tokens"] == 1029
    with agent_db.connection() as connection:
        rows = connection.execute("SELECT attempt_no,state FROM agent_model_attempt ORDER BY attempt_no").fetchall()
        assert [(row["attempt_no"], row["state"]) for row in rows] == [(0, "UNKNOWN"), (1, "SAVED")]
    with pytest.raises(RecoveryConflictError):
        store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0", attempt_no=0, reply=reply)


def test_only_one_retry_and_no_changed_request_or_saved_call_retry(agent_db: Database) -> None:
    store = _reserved(agent_db)
    with pytest.raises(RecoveryConflictError):
        store.reserve_retry(RUN_ID, fence=1, owner="test-worker", call_id="step-0",
                            request_hash="b" * 64, expected_attempt=0)
    store.reserve_retry(RUN_ID, fence=1, owner="test-worker", call_id="step-0",
                        request_hash="a" * 64, expected_attempt=0)
    with pytest.raises(RecoveryConflictError, match="retry"):
        store.reserve_retry(RUN_ID, fence=1, owner="test-worker", call_id="step-0",
                            request_hash="a" * 64, expected_attempt=1)
    store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0", attempt_no=1,
                      reply=ModelReply(decision={"kind": "ESCALATE"}, usage=ModelUsage(10, 5)))
    with pytest.raises(RecoveryConflictError, match="saved"):
        store.reserve_retry(RUN_ID, fence=1, owner="test-worker", call_id="step-0",
                            request_hash="a" * 64, expected_attempt=0)
    assert _spend(agent_db)["model_calls"] == 2


def test_concurrent_retry_requests_create_only_one_charge(agent_db: Database) -> None:
    store = _reserved(agent_db)

    def retry(_: int) -> bool:
        return store.reserve_retry(RUN_ID, fence=1, owner="test-worker", call_id="step-0",
                                   request_hash="a" * 64, expected_attempt=0).new_reservation

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert sum(executor.map(retry, range(4))) == 1
    assert _spend(agent_db)["model_calls"] == 2


@pytest.mark.parametrize("budget", [RunBudget(model_calls=3), RunBudget(output_tokens=1500)])
def test_retry_cannot_bypass_partition_or_shrink_frozen_request_ceiling(agent_db: Database, budget: RunBudget) -> None:
    store = _store(agent_db)
    store.initialize(RUN_ID, fence=1, owner="test-worker", manifest_id="manifest-1", budget=budget)
    store.reserve(RUN_ID, fence=1, owner="test-worker", call_id="step-0", request_hash="a" * 64,
                  kind="ORDINARY", input_tokens=20)
    before = _spend(agent_db)
    with pytest.raises((RecoveryCallBudgetExhausted, BudgetExhaustedError)):
        store.reserve_retry(RUN_ID, fence=1, owner="test-worker", call_id="step-0",
                            request_hash="a" * 64, expected_attempt=0)
    assert _spend(agent_db) == before
    with agent_db.connection() as connection:
        assert connection.execute("SELECT count(*) AS n FROM agent_model_attempt").fetchone()["n"] == 1


def test_new_fence_can_reserve_retry_but_old_worker_cannot_save(agent_db: Database) -> None:
    store = _reserved(agent_db)
    with agent_db.connection() as connection:
        connection.execute("UPDATE agent_run SET fence=2,lease_owner='new-worker' WHERE run_id=%s", (RUN_ID,))
    with pytest.raises(StaleFenceError):
        store.reserve_retry(RUN_ID, fence=1, owner="test-worker", call_id="step-0",
                            request_hash="a" * 64, expected_attempt=0)
    result = store.reserve_retry(RUN_ID, fence=2, owner="new-worker", call_id="step-0",
                                 request_hash="a" * 64, expected_attempt=0)
    assert result.attempt_no == 1
    with pytest.raises(StaleFenceError):
        store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0", attempt_no=0,
                          reply=ModelReply(decision={"kind": "ESCALATE"}))


def test_legacy_migration_keeps_unknown_charge_and_does_not_invent_fence(agent_db: Database) -> None:
    store = _store(agent_db)
    store.initialize(RUN_ID, fence=1, owner="test-worker", manifest_id="manifest-1", budget=RunBudget())
    # Construct a pre-007 charged call in this test's isolated schema, with no attempt/fence history.
    with agent_db.connection() as connection, connection.transaction():
        connection.execute(
            "INSERT INTO agent_model_call(run_id,call_id,kind,request_hash,reserved_input,reserved_output,"
            "state,created_at) VALUES (%s,'legacy','ORDINARY',%s,20,1024,'UNKNOWN',now())",
            (RUN_ID, "a" * 64),
        )
        connection.execute("UPDATE agent_run SET budget_spent=%s WHERE run_id=%s",
                           (Jsonb(RunSpend(model_calls=1, input_tokens=20, output_tokens=1024).as_dict()), RUN_ID))
        connection.execute("UPDATE agent_run_model_budget SET call_partition=%s WHERE run_id=%s",
                           (Jsonb(RecoveryCallBudget(ordinary_calls=1).as_dict()), RUN_ID))
    before = _spend(agent_db)
    agent_db.migrations()
    agent_db.migrations()
    assert _spend(agent_db) == before
    with agent_db.connection() as connection:
        row = connection.execute("SELECT reserved_fence FROM agent_model_attempt WHERE call_id='legacy'").fetchone()
        assert row["reserved_fence"] is None
    with pytest.raises(RecoveryConflictError, match="fence"):
        store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="legacy",
                          reply=ModelReply(decision={"kind": "ESCALATE"}))
    store.reserve_retry(RUN_ID, fence=1, owner="test-worker", call_id="legacy",
                        request_hash="a" * 64, expected_attempt=0)
    store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="legacy", attempt_no=1,
                      reply=ModelReply(decision={"kind": "ESCALATE"}, usage=ModelUsage(10, 5)))
    agent_db.migrations()
    with agent_db.connection() as connection:
        rows = connection.execute("SELECT attempt_no,state FROM agent_model_attempt ORDER BY attempt_no").fetchall()
        assert [(row["attempt_no"], row["state"]) for row in rows] == [(0, "UNKNOWN"), (1, "SAVED")]
    assert _spend(agent_db)["model_calls"] == 2
