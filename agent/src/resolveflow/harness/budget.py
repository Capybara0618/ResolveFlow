"""Run termination bounds and usage accounting; see ``docs/model-usage-policy.md``.

New runs have no cumulative token spending limit. Iteration/read counts, deadline and request size remain
bounded. Calls and usage are still counted before transmission and settled after known responses arrive.
Explicit numeric cumulative limits are retained for frozen legacy runs and compatibility tests; recovery
never silently replaces their manifest, counters or budget with new defaults.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Final

__all__ = [
    "DEFAULT_STEP_INPUT_TOKENS",
    "DEFAULT_STEP_OUTPUT_TOKENS",
    "DEFAULT_TIMEOUT_SECONDS",
    "REASON_BUDGET_INPUT_TOKENS",
    "REASON_BUDGET_LOCAL_READS",
    "REASON_BUDGET_MODEL_CALLS",
    "REASON_BUDGET_OUTPUT_TOKENS",
    "REASON_BUDGET_STEP_TOKENS",
    "REASON_BUDGET_TOOL_ATTEMPTS",
    "REASON_DEADLINE",
    "REASON_NO_PROGRESS",
    "BudgetExhaustedError",
    "BudgetGuard",
    "RunBudget",
    "RunSpend",
]

#: Per-request sizing and timeout are independent of cumulative expense accounting.
DEFAULT_STEP_INPUT_TOKENS: Final = 8192
DEFAULT_STEP_OUTPUT_TOKENS: Final = 1024
DEFAULT_TIMEOUT_SECONDS: Final = 30.0

#: Stable reason codes. ``docs/agent-harness.md:45`` requires a stable code and visible evidence for every stop,
#: and the code has to say *which* bound ran out: "the run hit its budget" is not actionable, "the tool-attempt
#: budget ran out while reading the shipment" is.
REASON_BUDGET_MODEL_CALLS: Final = "BUDGET_MODEL_CALLS"
REASON_BUDGET_TOOL_ATTEMPTS: Final = "BUDGET_TOOL_ATTEMPTS"
REASON_BUDGET_LOCAL_READS: Final = "BUDGET_LOCAL_READS"
REASON_BUDGET_INPUT_TOKENS: Final = "BUDGET_INPUT_TOKENS"
REASON_BUDGET_OUTPUT_TOKENS: Final = "BUDGET_OUTPUT_TOKENS"
REASON_BUDGET_STEP_TOKENS: Final = "BUDGET_STEP_TOKENS"
REASON_DEADLINE: Final = "DEADLINE_REACHED"
REASON_NO_PROGRESS: Final = "NO_PROGRESS"

#: ``docs/agent-spec.md:44``: 连续重复同动作且无新证据，两次反馈NO_PROGRESS，第三次停止.
MAX_NO_PROGRESS_ROUNDS: Final = 2


class BudgetExhaustedError(Exception):
    """A bound of the run's budget, reached. Carries the code the outcome reports."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class RunBudget:
    """The caps one run is given. Frozen: a budget that can be edited mid-run is not a bound.

    Defaults are the spec's numbers, and they are the *only* place they appear, so a caller that wants a
    smaller cap for a test says which one rather than re-stating the others.
    """

    model_calls: int = 12
    tool_attempts: int = 16
    local_reads: int = 8
    # None means accounting only. Numeric values retain explicitly frozen legacy run budgets.
    input_tokens: int | None = None
    output_tokens: int | None = None
    step_input_tokens: int = DEFAULT_STEP_INPUT_TOKENS
    step_output_tokens: int = DEFAULT_STEP_OUTPUT_TOKENS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        for member in (
            "model_calls",
            "tool_attempts",
            "local_reads",
            "step_input_tokens",
            "step_output_tokens",
        ):
            value = getattr(self, member)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{member} must be a non-negative integer")
        for member in ("input_tokens", "output_tokens"):
            value = getattr(self, member)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{member} must be None or a non-negative integer")
        if not isinstance(self.timeout_seconds, (int, float)) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(slots=True)
class RunSpend:
    """What the run has actually spent so far. Counters, so "at most 12" is decidable."""

    model_calls: int = 0
    tool_attempts: int = 0
    local_reads: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    #: How many times a repeat was fed back to the model without new evidence (docs/agent-spec.md:44).
    no_progress_rounds: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, int]:
        """The spend as a plain mapping, for a record or a report."""
        return {
            "model_calls": self.model_calls,
            "tool_attempts": self.tool_attempts,
            "local_reads": self.local_reads,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "no_progress_rounds": self.no_progress_rounds,
        }


@dataclass(slots=True)
class BudgetGuard:
    """The one place that decides whether an attempt may happen, and then counts it.

    Every ``reserve_*`` method either raises :class:`BudgetExhaustedError` **without changing anything** or
    counts the attempt and returns. There is deliberately no separate "record" step that a caller could forget:
    an attempt that was allowed is an attempt that was spent.
    """

    budget: RunBudget
    spend: RunSpend = field(default_factory=RunSpend)
    #: The run's activity window (``docs/agent-spec.md:42``). ``None`` means no window was fixed for this run,
    #: which is the honest state of a run whose worker has not started it yet — not a licence to run forever.
    active_deadline: dt.datetime | None = None
    _pending_output: int | None = field(default=None, init=False)

    def reserve_model_call(self, *, input_tokens: int, output_tokens: int) -> None:
        """Reserve one model call, checking every cap it is subject to before counting it.

        This low-level method charges a reservation. The SDK path uses ``reserve_model_request``
        and ``settle_model_output`` to refund the unused portion only after known usage arrives.

        The order matters for the message rather than the outcome: the *per-step* cap is reported first because
        it is a fact about this request, while the cumulative caps are facts about the run. A caller told
        "step too large" can shrink the request; one told "run out of input tokens" cannot.
        """
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts cannot be negative")
        self.check_deadline()
        # ``docs/agent-harness.md:37``: 单步不能超过累计. The check lives here rather than in ``__post_init__``
        # because a *declared* per-step cap larger than the cumulative one is harmless — the cumulative check
        # below refuses first, so no request can ever exceed it. A test that shrinks one cap to isolate a rule
        # should not have to restate the other, and forbidding the combination would have made that impossible.
        if self.budget.input_tokens is not None and input_tokens > self.budget.input_tokens:
            raise BudgetExhaustedError(
                REASON_BUDGET_STEP_TOKENS,
                f"this step asks for {input_tokens} input tokens, over the whole run's "
                f"{self.budget.input_tokens} (docs/agent-harness.md:37)",
            )
        if self.budget.output_tokens is not None and output_tokens > self.budget.output_tokens:
            raise BudgetExhaustedError(
                REASON_BUDGET_STEP_TOKENS,
                f"this step asks for {output_tokens} output tokens, over the whole run's "
                f"{self.budget.output_tokens} (docs/agent-harness.md:37)",
            )
        if input_tokens > self.budget.step_input_tokens:
            raise BudgetExhaustedError(
                REASON_BUDGET_STEP_TOKENS,
                f"this step asks for {input_tokens} input tokens, over the {self.budget.step_input_tokens} cap "
                "for one step (docs/agent-harness.md:37)",
            )
        if output_tokens > self.budget.step_output_tokens:
            raise BudgetExhaustedError(
                REASON_BUDGET_STEP_TOKENS,
                f"this step asks for {output_tokens} output tokens, over the {self.budget.step_output_tokens} cap "
                "for one step (docs/agent-harness.md:37)",
            )
        if self.spend.model_calls + 1 > self.budget.model_calls:
            raise BudgetExhaustedError(
                REASON_BUDGET_MODEL_CALLS,
                f"the run has made {self.spend.model_calls} of its {self.budget.model_calls} model calls "
                "(docs/agent-spec.md:40)",
            )
        if self.budget.input_tokens is not None and self.spend.input_tokens + input_tokens > self.budget.input_tokens:
            raise BudgetExhaustedError(
                REASON_BUDGET_INPUT_TOKENS,
                f"the run has used {self.spend.input_tokens} of its {self.budget.input_tokens} input tokens and "
                f"this step asks for {input_tokens} more",
            )
        if self.budget.output_tokens is not None and (
            self.spend.output_tokens + output_tokens > self.budget.output_tokens
        ):
            raise BudgetExhaustedError(
                REASON_BUDGET_OUTPUT_TOKENS,
                f"the run has used {self.spend.output_tokens} of its {self.budget.output_tokens} output tokens and "
                f"this step asks for {output_tokens} more",
            )
        self.spend.model_calls += 1
        self.spend.input_tokens += input_tokens
        self.spend.output_tokens += output_tokens

    def reserve_model_request(self, *, input_tokens: int) -> int:
        """Reserve and return the ceiling the client must enforce on this request.

        A prior unsettled request keeps its full charge (UNKNOWN). This in-memory guard is
        sequential; stable call IDs, durable reservations and fencing remain C09 work.
        """
        ceiling = self.budget.step_output_tokens
        if self.budget.output_tokens is not None:
            ceiling = min(ceiling, self.budget.output_tokens - self.spend.output_tokens)
        if ceiling <= 0:
            raise BudgetExhaustedError(REASON_BUDGET_OUTPUT_TOKENS, "no output allowance remains")
        self.reserve_model_call(input_tokens=input_tokens, output_tokens=ceiling)
        self._pending_output = ceiling
        return ceiling

    def settle_model_output(self, tokens: int | None, *, estimated: bool = False) -> None:
        """Settle once, before accepting any action; unknown usage cannot refund a reservation."""
        reserved = self._pending_output
        if reserved is None:
            raise RuntimeError("model output has no pending reservation")
        if tokens is not None and tokens < 0:
            raise ValueError("output usage cannot be negative")
        charged = reserved if tokens is None else max(reserved, tokens) if estimated else tokens
        self.spend.output_tokens += charged - reserved
        self._pending_output = None
        if charged > reserved:
            raise BudgetExhaustedError(
                REASON_BUDGET_OUTPUT_TOKENS,
                f"provider exceeded reserved output: {charged} > {reserved}; charged and stopped",
            )

    def reserve_tool_attempt(self) -> None:
        """Reserve one external tool/search attempt. Every attempt counts, refusals and retries included."""
        self.check_deadline()
        if self.spend.tool_attempts + 1 > self.budget.tool_attempts:
            raise BudgetExhaustedError(
                REASON_BUDGET_TOOL_ATTEMPTS,
                f"the run has made {self.spend.tool_attempts} of its {self.budget.tool_attempts} tool attempts "
                "(docs/agent-spec.md:40)",
            )
        self.spend.tool_attempts += 1

    def reserve_local_read(self) -> None:
        """Reserve one local read: policy search and READ_OBSERVATION, which are not MCP calls."""
        self.check_deadline()
        if self.spend.local_reads + 1 > self.budget.local_reads:
            raise BudgetExhaustedError(
                REASON_BUDGET_LOCAL_READS,
                f"the run has made {self.spend.local_reads} of its {self.budget.local_reads} local reads "
                "(docs/agent-spec.md:40)",
            )
        self.spend.local_reads += 1

    def note_no_progress(self) -> bool:
        """Record a repeat that produced no new evidence; return whether another turn may be taken.

        ``docs/agent-spec.md:44``: 连续重复同动作且无新证据，两次反馈NO_PROGRESS，第三次停止. So the first two repeats
        are *fed back* — the model is told and gets another turn — and the **third is refused before it runs**.
        The refusal-before-running is the part that is easy to get wrong and expensive to get wrong: a harness
        that executed the third attempt and then stopped would have spent a call on the action it was supposed
        to refuse, and ``docs/agent-spec.md:40``'s "所有attempt计预算" would count it.

        So this returns ``True`` while feedback is still owed and ``False`` when the run must stop, and the
        caller uses the answer directly instead of re-deriving the count and getting the boundary wrong.
        """
        self.spend.no_progress_rounds += 1
        return self.spend.no_progress_rounds <= MAX_NO_PROGRESS_ROUNDS

    def feedback_rounds_remaining(self) -> int:
        """How many more no-progress repeats this run may be *told about* before one stops it."""
        return max(0, MAX_NO_PROGRESS_ROUNDS - self.spend.no_progress_rounds)

    def note_progress(self) -> None:
        """New evidence arrived: the repeat streak is over.

        Reset rather than decayed. A run that reads a shipment, re-reads it, learns something, and re-reads it
        again has not repeated three times *without new evidence*, and counting the earlier repeat would stop a
        run that is making progress.
        """
        self.spend.no_progress_rounds = 0

    def check_deadline(self, *, now: dt.datetime | None = None) -> None:
        """Stop a run whose activity window has closed (``docs/agent-spec.md:42``).

        A window is only checked when one was fixed. ``None`` is not "no deadline": it is "this process has not
        been told the window", and inventing one here would make the run's real deadline unenforceable later.
        """
        if self.active_deadline is None:
            return
        moment = now or dt.datetime.now(dt.UTC)
        if moment >= self.active_deadline:
            raise BudgetExhaustedError(
                REASON_DEADLINE,
                f"the run's activity window closed at {self.active_deadline.isoformat()}",
            )
