from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from resolveflow.harness.budget import BudgetExhaustedError, RunBudget
from resolveflow.harness.model import ModelReply, ModelUsage
from resolveflow.runtime.db import Database
from resolveflow.runtime.recovery_store import RecoveryBudgetStore, RecoveryConflictError, StaleFenceError

from tests.integration.test_recovery_budget_store import _store
from tests.integration.test_run_store import RUN_ID


def _reserved(database: Database) -> RecoveryBudgetStore:
    store = _store(database)
    store.initialize(RUN_ID, fence=1, owner="test-worker", manifest_id="manifest-1", budget=RunBudget())
    store.reserve(RUN_ID, fence=1, owner="test-worker", call_id="step-0", request_hash="a" * 64,
                  kind="ORDINARY", input_tokens=20)
    return store


def _spend(database: Database) -> dict:
    with database.connection() as connection:
        return connection.execute("SELECT budget_spent FROM agent_run WHERE run_id=%s", (RUN_ID,)).fetchone()[
            "budget_spent"
        ]


def test_unlimited_cumulative_usage_survives_store_reconstruction(agent_db: Database) -> None:
    store = _store(agent_db)
    store.initialize(RUN_ID, fence=1, owner="test-worker", manifest_id="usage-only", budget=RunBudget())
    for index in range(8):
        store = RecoveryBudgetStore(agent_db)
        store.initialize(RUN_ID, fence=1, owner="test-worker", manifest_id="usage-only", budget=RunBudget())
        reservation = store.reserve(RUN_ID, fence=1, owner="test-worker", call_id=f"step-{index}",
                                    request_hash=f"{index:064x}", kind="ORDINARY", input_tokens=7000)
        assert reservation.output_ceiling == 1024
        result = store.save_result(RUN_ID, fence=1, owner="test-worker", call_id=f"step-{index}",
                                   reply=ModelReply(decision={"kind": "ESCALATE"}, usage=ModelUsage(7000, 800)))
        assert result.stop_reason is None
    assert _spend(agent_db)["input_tokens"] == 56000 and _spend(agent_db)["output_tokens"] == 6400
    with agent_db.connection() as connection:
        frozen = connection.execute("SELECT budget FROM agent_run_model_budget WHERE run_id=%s", (RUN_ID,)).fetchone()
    assert frozen["budget"]["input_tokens"] is None and frozen["budget"]["output_tokens"] is None


def test_saved_response_reused_without_checkpoint_or_second_settlement(agent_db: Database) -> None:
    store = _reserved(agent_db)
    assert store.recorded_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0") is None
    reply = ModelReply(decision={"kind": "ESCALATE", "reason_codes": ["CONFLICT"]},
                       usage=ModelUsage(input_tokens=15, output_tokens=8), mode="live", model_alias="test-model")
    saved = store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0", reply=reply)
    assert saved.new_result and saved.stop_reason is None
    assert _spend(agent_db)["model_calls"] == 1
    assert _spend(agent_db)["input_tokens"] == 15 and _spend(agent_db)["output_tokens"] == 8
    # No checkpoint writer ran: a new process/store can recover the exact reply directly from the call ledger.
    rebuilt = RecoveryBudgetStore(agent_db)
    recovered = rebuilt.recorded_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0")
    assert recovered.reply == reply and not recovered.new_result
    repeated = rebuilt.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0", reply=reply)
    assert not repeated.new_result and _spend(agent_db)["output_tokens"] == 8
    with pytest.raises(RecoveryConflictError):
        rebuilt.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0",
                            reply=ModelReply(decision={"kind": "PROPOSE"}))


def test_concurrent_duplicate_results_settle_only_once(agent_db: Database) -> None:
    store = _reserved(agent_db)
    reply = ModelReply(decision={"kind": "ESCALATE"}, usage=ModelUsage(10, 5))

    def save(_: int) -> bool:
        return store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0", reply=reply).new_result

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert sum(executor.map(save, range(4))) == 1
    assert _spend(agent_db)["output_tokens"] == 5


def test_estimated_usage_never_releases_reservation(agent_db: Database) -> None:
    store = _reserved(agent_db)
    store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0",
                      reply=ModelReply(decision={"kind": "ESCALATE"}, usage=ModelUsage(1, 1, estimated=True)))
    assert _spend(agent_db)["input_tokens"] == 20
    assert _spend(agent_db)["output_tokens"] == 1024


def test_excess_usage_is_committed_and_blocks_further_calls(agent_db: Database) -> None:
    store = _reserved(agent_db)
    result = store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0",
                               reply=ModelReply(decision={"kind": "ESCALATE"}, usage=ModelUsage(20, 1025)))
    assert result.stop_reason == "BUDGET_OUTPUT_TOKENS"
    assert _spend(agent_db)["output_tokens"] == 1025
    recovered = store.recorded_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0")
    assert recovered.stop_reason == result.stop_reason
    with pytest.raises(BudgetExhaustedError):
        store.reserve(RUN_ID, fence=1, owner="test-worker", call_id="step-1", request_hash="b" * 64,
                      kind="ORDINARY", input_tokens=1)


def test_late_worker_cannot_save_result_or_change_spend(agent_db: Database) -> None:
    store = _reserved(agent_db)
    before = _spend(agent_db)
    with agent_db.connection() as connection:
        connection.execute("UPDATE agent_run SET fence=2,lease_owner='new-worker' WHERE run_id=%s", (RUN_ID,))
    with pytest.raises(StaleFenceError):
        store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0",
                          reply=ModelReply(decision={"kind": "ESCALATE"}, usage=ModelUsage(10, 5)))
    assert _spend(agent_db) == before
    assert store.recorded_result(RUN_ID, fence=2, owner="new-worker", call_id="step-0") is None


@pytest.mark.parametrize("usage", [ModelUsage(-1, 1), ModelUsage(1, -1), ModelUsage(True, 1)])
def test_invalid_usage_cannot_change_unknown_reservation(agent_db: Database, usage: ModelUsage) -> None:
    store = _reserved(agent_db)
    before = _spend(agent_db)
    with pytest.raises(ValueError, match="usage"):
        store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0",
                          reply=ModelReply(decision={"kind": "ESCALATE"}, usage=usage))
    assert _spend(agent_db) == before
    assert store.recorded_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0") is None


def test_input_overage_is_saved_and_stops_after_store_reconstruction(agent_db: Database) -> None:
    store = _reserved(agent_db)
    result = store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0",
                               reply=ModelReply(decision={"kind": "ESCALATE"}, usage=ModelUsage(8193, 1)))
    assert result.stop_reason == "BUDGET_INPUT_TOKENS"
    assert _spend(agent_db)["input_tokens"] == 8193
    rebuilt = RecoveryBudgetStore(agent_db)
    with pytest.raises(BudgetExhaustedError):
        rebuilt.reserve(RUN_ID, fence=1, owner="test-worker", call_id="step-1", request_hash="b" * 64,
                        kind="RECOVERY_TURN", input_tokens=1)


def test_run_stop_reason_is_visible_when_reusing_an_earlier_safe_response(agent_db: Database) -> None:
    store = _reserved(agent_db)
    safe = ModelReply(decision={"kind": "ESCALATE"}, usage=ModelUsage(10, 1))
    store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0", reply=safe)
    store.reserve(RUN_ID, fence=1, owner="test-worker", call_id="step-1", request_hash="b" * 64,
                  kind="ORDINARY", input_tokens=1)
    store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-1",
                      reply=ModelReply(decision={"kind": "ESCALATE"}, usage=ModelUsage(1, 1025)))
    recovered = store.recorded_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0")
    assert recovered.reply == safe and recovered.stop_reason == "BUDGET_OUTPUT_TOKENS"
    repeated = store.save_result(RUN_ID, fence=1, owner="test-worker", call_id="step-0", reply=safe)
    assert repeated.stop_reason == "BUDGET_OUTPUT_TOKENS"
