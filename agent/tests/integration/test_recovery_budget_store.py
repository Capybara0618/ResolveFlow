from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import pytest

from resolveflow.harness.budget import BudgetExhaustedError, RunBudget
from resolveflow.runtime.db import Database
from resolveflow.runtime.recovery_budget import RecoveryCallBudgetExhausted
from resolveflow.runtime.recovery_store import RecoveryBudgetStore, RecoveryConflictError, StaleFenceError
from resolveflow.runtime.runs import RunStore
from tests.integration.test_run_store import CASE_DISPATCHER, RUN_ID, a_request


def _store(database: Database) -> RecoveryBudgetStore:
    RunStore(database).queue(a_request(), caller=CASE_DISPATCHER)
    with database.connection() as connection:
        connection.execute(
            "UPDATE agent_run SET status='RUNNING', fence=1, lease_owner='test-worker', "
            "lease_until=now()+interval '1 hour', active_deadline_at=now()+interval '120 seconds' "
            "WHERE run_id=%s", (RUN_ID,),
        )
    return RecoveryBudgetStore(database)


def test_reservation_is_committed_rebuilt_and_not_duplicated(agent_db: Database) -> None:
    store = _store(agent_db)
    store.initialize(RUN_ID, fence=1, owner="test-worker", manifest_id="manifest-1", budget=RunBudget())
    reserved = store.reserve(RUN_ID, fence=1, owner="test-worker", call_id="step-0", request_hash="a" * 64,
                             kind="ORDINARY", input_tokens=20)
    assert reserved.new_reservation and reserved.output_ceiling == 1024
    rebuilt = RecoveryBudgetStore(agent_db)
    rebuilt.initialize(RUN_ID, fence=1, owner="test-worker", manifest_id="manifest-1", budget=RunBudget())
    reused = rebuilt.reserve(RUN_ID, fence=1, owner="test-worker", call_id="step-0", request_hash="a" * 64,
                            kind="ORDINARY", input_tokens=20)
    assert not reused.new_reservation and reused.state == "UNKNOWN"
    with agent_db.connection() as connection:
        row = connection.execute("SELECT budget_spent FROM agent_run WHERE run_id=%s", (RUN_ID,)).fetchone()
        assert row is not None and row["budget_spent"]["model_calls"] == 1
        assert row["budget_spent"]["output_tokens"] == 1024
        assert connection.execute("SELECT count(*) AS n FROM agent_model_call").fetchone()["n"] == 1
    with pytest.raises(RecoveryConflictError):
        rebuilt.reserve(RUN_ID, fence=1, owner="test-worker", call_id="step-0", request_hash="b" * 64,
                        kind="ORDINARY", input_tokens=20)
    with pytest.raises(RecoveryConflictError):
        rebuilt.initialize(RUN_ID, fence=1, owner="test-worker", manifest_id="other", budget=RunBudget())


def test_old_fence_cancel_and_expiry_leave_no_call(agent_db: Database) -> None:
    store = _store(agent_db)
    store.initialize(RUN_ID, fence=1, owner="test-worker", manifest_id="manifest-1", budget=RunBudget())
    arguments = dict(fence=0, owner="test-worker", call_id="step-0", request_hash="a" * 64,
                     kind="ORDINARY", input_tokens=20)
    with pytest.raises(StaleFenceError):
        store.reserve(RUN_ID, **arguments)
    arguments["fence"] = 1
    with agent_db.connection() as connection:
        connection.execute("UPDATE agent_run SET lease_until=now()+interval '1 hour', "
                           "active_deadline_at=now()-interval '1 second' WHERE run_id=%s", (RUN_ID,))
    with pytest.raises(StaleFenceError):
        store.reserve(RUN_ID, **arguments)
    with agent_db.connection() as connection:
        connection.execute("UPDATE agent_run SET cancelled_at=now(), active_deadline_at=now()+interval '120 seconds' "
                           "WHERE run_id=%s", (RUN_ID,))
    with pytest.raises(StaleFenceError):
        store.reserve(RUN_ID, **arguments)
    with agent_db.connection() as connection:
        connection.execute("UPDATE agent_run SET cancelled_at=NULL, lease_until=now()-interval '1 second' "
                           "WHERE run_id=%s", (RUN_ID,))
    with pytest.raises(StaleFenceError):
        store.reserve(RUN_ID, **arguments)
    with agent_db.connection() as connection:
        assert connection.execute("SELECT count(*) AS n FROM agent_model_call").fetchone()["n"] == 0


def test_unknown_output_stays_reserved_and_token_refusal_rolls_back_partition(agent_db: Database) -> None:
    store = _store(agent_db)
    store.initialize(RUN_ID, fence=1, owner="test-worker", manifest_id="manifest-1", budget=RunBudget())
    for index, ceiling in enumerate((1024, 1024, 1024, 928)):
        result = store.reserve(RUN_ID, fence=1, owner="test-worker", call_id=f"step-{index}",
                               request_hash=f"{index:064x}", kind="ORDINARY", input_tokens=1)
        assert result.output_ceiling == ceiling
    with pytest.raises(BudgetExhaustedError):
        store.reserve(RUN_ID, fence=1, owner="test-worker", call_id="step-4", request_hash="f" * 64,
                      kind="ORDINARY", input_tokens=1)
    with agent_db.connection() as connection:
        spend = connection.execute("SELECT budget_spent FROM agent_run WHERE run_id=%s", (RUN_ID,)).fetchone()
        partition = connection.execute("SELECT call_partition FROM agent_run_model_budget WHERE run_id=%s",
                                       (RUN_ID,)).fetchone()
        assert spend["budget_spent"]["output_tokens"] == 4000
        assert spend["budget_spent"]["model_calls"] == 4
        assert partition["call_partition"]["ordinary_calls"] == 4
        assert connection.execute("SELECT count(*) AS n FROM agent_model_call").fetchone()["n"] == 4


def test_concurrent_ordinary_reservations_cannot_spend_recovery_partition(agent_db: Database) -> None:
    store = _store(agent_db)
    # A small per-call output ceiling isolates the call-count bound from the cumulative token bound.
    store.initialize(RUN_ID, fence=1, owner="test-worker", manifest_id="manifest-1",
                     budget=RunBudget(step_output_tokens=1))

    def attempt(index: int) -> bool:
        try:
            store.reserve(RUN_ID, fence=1, owner="test-worker", call_id=f"step-{index}",
                          request_hash=f"{index:064x}", kind="ORDINARY", input_tokens=1)
            return True
        except RecoveryCallBudgetExhausted:
            return False

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(attempt, range(12)))
    assert sum(results) == 10
    for index in range(2):
        store.reserve(RUN_ID, fence=1, owner="test-worker", call_id=f"recovery-{index}",
                      request_hash=f"{index+20:064x}", kind="RECOVERY_TURN", input_tokens=1)
    with pytest.raises(RecoveryCallBudgetExhausted):
        store.reserve(RUN_ID, fence=1, owner="test-worker", call_id="extra", request_hash="f" * 64,
                      kind="RECOVERY_TURN", input_tokens=1)
    with agent_db.connection() as connection:
        row = connection.execute("SELECT budget_spent, active_deadline_at FROM agent_run WHERE run_id=%s",
                                 (RUN_ID,)).fetchone()
        assert row["budget_spent"]["model_calls"] == 12
        assert row["active_deadline_at"] < dt.datetime.now(dt.UTC) + dt.timedelta(seconds=121)
