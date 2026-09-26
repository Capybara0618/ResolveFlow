"""AS02.2: the vocabulary a run is described in, independent of which loop drove it.

This module exists because the migration separates two things that used to live in one file: **what a run is**
(`RunFacts`, `RunResult`, the reason codes, the `ToolExecutor` protocol) and **the loop that runs it**. That
separation is what let the driver be replaced without every importer changing, and it is what makes "there is one
production loop" a structural statement rather than a promise: `runner.py` no longer contains a `while`.

The reason codes live here rather than beside the loop because they are the *interface* to everything that reads a
run's outcome — a callback writer, a worker, a test — and an interface that moved with the implementation would
have to be re-imported from wherever the implementation happened to be.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from resolveflow.contracts.core_models import ToolObservation

__all__ = [
    "HARNESS_SYSTEM_PROMPT",
    "REASON_ACTION_REFUSED",
    "REASON_COMPLETED",
    "REASON_TOOL_CALLS_EXHAUSTED",
    "REASON_TOOL_FAILED",
    "RunFacts",
    "RunResult",
    "ToolExecutor",
]

#: The run reached a decision. `docs/agent-spec.md:9`: COMPLETED means the plan callback was accepted by Case —
#: it does **not** mean a refund happened. The loops report "the investigation reached a decision", which is what
#: they can know.
REASON_COMPLETED: Final = "COMPLETED"

#: The model's action was refused by the ABI (`docs/agent-spec.md:22`).
REASON_ACTION_REFUSED: Final = "ACTION_REFUSED"

#: The tool layer itself failed: not "the source was unreadable" (that is an observation) but "the call could not
#: be completed at all". Kept distinct because the two need different responses — one is evidence to hand back to
#: the model, the other is an environment problem that will not improve by asking again.
REASON_TOOL_FAILED: Final = "TOOL_FAILED"

#: The executor ran out of the calls it was willing to make. Its own bound, separate from the run's budget: the
#: run budget is what the spec fixes, this is what the executor can physically serve.
REASON_TOOL_CALLS_EXHAUSTED: Final = "TOOL_CALLS_EXHAUSTED"

#: The system prompt. Deliberately short and free of business routing: a prompt that said "if the parcel is late,
#: read the shipment" would be the fixed route `docs/agent-harness.md:9` rules out, written in prose instead of
#: code. It moved here from `runner.py` so the loop and the vocabulary are not the same file.
HARNESS_SYSTEM_PROMPT: Final = (
    "You are investigating one after-sales case for one order line. Choose the next action from the ABI you "
    "are given. Read only what you need; a read is evidence only if you can cite its source, version and hash. "
    "Do not name a line, case, run, merchant or customer: the run already fixed those. When the evidence "
    "supports a decision, PROPOSE it and cite what you saw."
)


class ToolExecutor(Protocol):
    """Somewhere to make one tool call. Narrow on purpose: three methods, one of which closes it.

    The real implementation drives the five whitelisted tools over MCP stdio (`harness/mcp_client.py`), which is
    why the interface is *call by name with arguments* rather than a Python method per tool: an executor with a
    ``get_order_context()`` method would make the MCP path one option among several rather than the only way a
    tool is reached.

    ``note_trace_page`` belongs to the protocol even though a loop never calls it: `docs/agent-spec.md:29`'s
    two-page budget is the **run's**, and the executor is the object that lives for the run (a tool server is
    started per call and cannot remember), so the executor owns the counter and charges it when the server answers
    with a page.
    """

    def call_tool(self, *, run_id: str, tool_name: str, arguments: dict[str, Any]) -> ToolObservation: ...

    def note_trace_page(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RunFacts:
    """What the run is about, as the dispatch fixed it (`docs/core-contracts.md:60`).

    These never come from the model. ``line_id`` in particular is the subject of the whole investigation
    (`docs/core-scope.md:9` — one order line), and it is handed to the tools rather than accepted from an action,
    so "which line" cannot become a model decision.
    """

    run_id: str
    case_id: str
    input_revision: int
    line_id: str
    description: str
    merchant_id: str | None = None
    customer_id: str | None = None
    #: The window the run may work inside (`docs/agent-spec.md:42`), already resolved to
    #: ``min(deadline, start + 120s)`` by whoever started it. ``None`` means no worker has fixed one yet.
    active_deadline_at: str | None = None
    policy_manifest: dict[str, Any] = field(default_factory=dict)
    fence: int | None = None
    lease_owner: str | None = None

    def deadline(self) -> dt.datetime | None:
        """The window as an instant, tolerating the wire's ``Z``."""
        if not self.active_deadline_at:
            return None
        return dt.datetime.fromisoformat(self.active_deadline_at.replace("Z", "+00:00"))


@dataclass(frozen=True, slots=True)
class RunResult:
    """How one investigation ended, and everything a reader needs to check that claim.

    ``completed`` and ``reason_code`` are separate members because "the run finished" and "the run finished *with a
    decision*" are different facts, and one status would have to be wrong about one of them. A run stopped by its
    budget is not a failed investigation — nothing was refused — and it is not a completed one either.
    """

    completed: bool
    reason_code: str
    decision: Any
    observations: tuple[ToolObservation, ...]
    spend: Any
    #: One entry per action taken, in order: what was asked for and whether it produced anything new. The
    #: trajectory's skeleton (`docs/agent-spec.md:52` — explicit actions and short reasons, never hidden
    #: reasoning).
    trajectory: tuple[dict[str, Any], ...] = ()
    #: Everything the model was told, so a reader can check that the stop was visible to it.
    notices: tuple[str, ...] = ()
    #: Which mode answered each decision, in order. Mock and live results must stay distinguishable
    #: (`docs/core-scope.md`完成标准), and a record that lost this could not say what it is evidence of.
    modes: tuple[str, ...] = ()
