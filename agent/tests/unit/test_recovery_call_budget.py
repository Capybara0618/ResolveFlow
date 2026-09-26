from __future__ import annotations

import pytest

from resolveflow.runtime.recovery_budget import RecoveryCallBudget, RecoveryCallBudgetExhausted


def test_ordinary_calls_stop_at_ten_and_recovery_uses_same_twelve_total() -> None:
    budget = RecoveryCallBudget()
    for _ in range(10):
        budget = budget.reserve("ORDINARY")
    with pytest.raises(RecoveryCallBudgetExhausted, match="ordinary"):
        budget.reserve("ORDINARY")
    budget = budget.reserve("RECOVERY_TURN").reserve("RECOVERY_TURN")
    assert budget.total_spent == 12
    with pytest.raises(RecoveryCallBudgetExhausted, match="recovery"):
        budget.reserve("RECOVERY_TURN")


def test_rebuilt_budget_keeps_spend_and_rejects_malformed_counts() -> None:
    first = RecoveryCallBudget().reserve("ORDINARY").reserve("RECOVERY_TURN")
    resumed = RecoveryCallBudget.from_dict(first.as_dict())
    assert resumed == first
    assert resumed.total_spent == 2
    with pytest.raises(ValueError, match="invalid"):
        RecoveryCallBudget.from_dict({"ordinary_calls": 11, "recovery_calls": 2})
    with pytest.raises(ValueError, match="invalid"):
        RecoveryCallBudget.from_dict({"ordinary_calls": True, "recovery_calls": 0})


def test_no_hidden_kind_or_extra_recovery_turn() -> None:
    with pytest.raises(ValueError, match="kind"):
        RecoveryCallBudget().reserve("SUMMARY")
    with pytest.raises(ValueError, match="recovery reserve"):
        RecoveryCallBudget(total_limit=12, recovery_reserve=13)
