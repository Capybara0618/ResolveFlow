"""C09 call-count partition for a durable run; persistence and token charging are separate steps.

The spike proved a recovery turn can be charged, but its 12+2 allowance violates the
production maximum of twelve calls. This value object is intentionally immutable:
the C09 store must write the returned state under the run's fence before any network
request. Reconstructing it from a row never resets either counter.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Final

MAX_MODEL_CALLS: Final = 12
DEFAULT_RECOVERY_RESERVE: Final = 2
RECOVERY_TURN: Final = "RECOVERY_TURN"
ORDINARY: Final = "ORDINARY"


class RecoveryCallBudgetExhausted(RuntimeError):
    """A model call cannot fit inside the run's frozen call-count partition."""


@dataclass(frozen=True, slots=True)
class RecoveryCallBudget:
    total_limit: int = MAX_MODEL_CALLS
    recovery_reserve: int = DEFAULT_RECOVERY_RESERVE
    ordinary_calls: int = 0
    recovery_calls: int = 0

    def __post_init__(self) -> None:
        values = (self.total_limit, self.recovery_reserve, self.ordinary_calls, self.recovery_calls)
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("invalid recovery call budget: non-negative integer counts required")
        if self.total_limit > MAX_MODEL_CALLS:
            raise ValueError("invalid recovery call budget: total exceeds the twelve-call specification")
        if self.recovery_reserve > self.total_limit:
            raise ValueError("invalid recovery reserve: larger than total")
        if self.ordinary_calls > self.total_limit - self.recovery_reserve:
            raise ValueError("invalid recovery call budget: ordinary partition exceeded")
        if self.recovery_calls > self.recovery_reserve or self.total_spent > self.total_limit:
            raise ValueError("invalid recovery call budget: recovery or total partition exceeded")

    @property
    def total_spent(self) -> int:
        return self.ordinary_calls + self.recovery_calls

    def reserve(self, kind: str) -> RecoveryCallBudget:
        if kind == ORDINARY:
            if self.ordinary_calls >= self.total_limit - self.recovery_reserve:
                raise RecoveryCallBudgetExhausted("ordinary model-call allowance exhausted")
            return replace(self, ordinary_calls=self.ordinary_calls + 1)
        if kind == RECOVERY_TURN:
            if self.recovery_calls >= self.recovery_reserve:
                raise RecoveryCallBudgetExhausted("recovery model-call allowance exhausted")
            return replace(self, recovery_calls=self.recovery_calls + 1)
        raise ValueError(f"unknown model-call kind: {kind!r}")

    def as_dict(self) -> dict[str, int]:
        return {
            "total_limit": self.total_limit,
            "recovery_reserve": self.recovery_reserve,
            "ordinary_calls": self.ordinary_calls,
            "recovery_calls": self.recovery_calls,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecoveryCallBudget:
        if set(data) != {"total_limit", "recovery_reserve", "ordinary_calls", "recovery_calls"}:
            raise ValueError("invalid recovery call budget: exact persisted fields required")
        return cls(**data)
