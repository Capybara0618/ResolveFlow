"""AS02.2: the loop-independent control rules, shared by the old runner and the SDK-driven one.

`docs/agentscope-migration.md:62` requires the old tests' semantics to be *kept* while the driver changes: 旧自主性/
权限/预算/翻页/无进展测试语义全部保留并跑在新循环. The dangerous way to satisfy that is to re-implement the rules
next to the new loop, because then two copies exist and only one of them is being tested.

So whatever a loop must do **regardless of which loop it is** lives here, and both drivers import it:

* the stop reasons, so a run that ends for "no progress" says so identically in either loop;
* the **no-progress rule's** decision — whether a repeated action without new evidence is fed back or stops the
  run — including the action digest that decides "repeated". ``docs/agent-spec.md:44`` is explicit about the
  shape (两次反馈NO_PROGRESS，第三次停止) and about the exception (不同版本/下一页不误判), and neither loop gets to
  have its own opinion about it.

What is deliberately *not* here: the budget arithmetic (`budget.py` — unchanged from C06.4) and the action ABI
(`actions.py` — unchanged). Those were already loop-independent, and moving them would be churn.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Final

from resolveflow.harness.actions import ModelDecision

__all__ = [
    "MAX_NO_PROGRESS_ROUNDS",
    "REASON_ACTION_REFUSED",
    "REASON_COMPLETED",
    "REASON_NO_PROGRESS",
    "REASON_POLICY_INDEX_UNAVAILABLE",
    "REASON_TOOL_FAILED",
    "NoProgressTracker",
    "action_digest",
]

#: The run reached a decision. `docs/agent-spec.md:9`: COMPLETED means the callback reached Case, not that a
#: refund happened — in these loops it means "the investigation reached a decision", which is what they can know.
REASON_COMPLETED: Final = "COMPLETED"

#: The model's action was refused by the ABI (`docs/agent-spec.md:22`).
REASON_ACTION_REFUSED: Final = "ACTION_REFUSED"

#: The tool layer itself failed: not "the source was unreadable" (that is an observation) but "the call could
#: not be completed at all".
REASON_TOOL_FAILED: Final = "TOOL_FAILED"

#: The policy a run is pinned to has no READY index, so `SEARCH_POLICY` could not be answered (C07.1).
#:
#: Its own code rather than `TOOL_FAILED`, because `docs/policy-rag.md:23` gives it its own handling: the run
#: **may retry until its deadline or escalate**, and it may *not* search another version. A caller reading
#: `TOOL_FAILED` would treat this as an environment problem that will not improve by asking again; the fact is
#: that it is a readiness state that changes on its own, and it is also the difference between "we could not
#: read policy" and "there is no policy index yet".
REASON_POLICY_INDEX_UNAVAILABLE: Final = "POLICY_INDEX_NOT_READY"

#: `docs/agent-spec.md:44`: 连续重复同动作且无新证据，两次反馈NO_PROGRESS，第三次停止.
REASON_NO_PROGRESS: Final = "NO_PROGRESS"
MAX_NO_PROGRESS_ROUNDS: Final = 2


def action_digest(decision: ModelDecision) -> str:
    """A stable digest of what an action *asked for*, for the no-progress rule.

    Keyed on the action's content rather than on its kind, because ``docs/agent-spec.md:44`` says 不同版本/下一页不
    误判: a different page of the same trace is a different action, and a digest that ignored the arguments would
    stop a run that is legitimately paging. This is the same digest C06.4 shipped — moved, not rewritten, so the
    old loop's behaviour cannot drift from the new loop's.
    """
    canonical = json.dumps(
        {
            "kind": decision.kind,
            "tool_name": decision.tool_name,
            "arguments": decision.arguments,
            "cursor": decision.cursor,
            "query": decision.query,
            "observation_id": decision.observation_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class NoProgressTracker:
    """Decides whether a repeated action is fed back to the model or stops the run.

    The rule has two halves on opposite sides of the action, which is why this is a small object rather than a
    predicate: whether the *third* identical action may run at all is decided before it runs, while whether a
    repeat produced new evidence is only knowable after. C06.4 got the order wrong first (it executed the third
    attempt and then stopped, spending an attempt on the thing it was refusing), so the order is stated here once
    and both loops use it.
    """

    #: How many no-progress rounds have been *fed back* so far.
    rounds: int = 0
    last_digest: str | None = None
    #: Set when the previous action's evidence was new; the loop reports it rather than inferring it.
    latest_was_new: bool = False
    #: Set when the action about to run repeated the previous one, so the evidence that follows decides whether it
    #: was "no progress" or a legitimate re-read.
    pending_repeat: bool = False

    def note_action(self, decision: ModelDecision) -> bool:
        """Record the action about to run and return whether it is a repeat of the previous one.

        Deliberately does **not** count a round. Whether a repeat was "no progress" depends on the evidence it
        produced, which is not known until after it ran — and a version of this that counted here incremented the
        streak for a repeat that returned *new* evidence, so a run paging or re-reading after a change was stopped
        as if it had made no progress. The counted decision is made in :meth:`note_evidence`.
        """
        digest = action_digest(decision)
        repeated = digest == self.last_digest
        self.last_digest = digest
        self.latest_was_new = False
        self.pending_repeat = repeated
        return repeated

    @property
    def feedback_rounds_remaining(self) -> int:
        return max(0, MAX_NO_PROGRESS_ROUNDS - self.rounds)

    def should_stop_before_running(self) -> bool:
        """True when this repeat is the third one, so it must be **refused before it runs**.

        Two repeat-without-evidence rounds are fed back (`docs/agent-spec.md:44`: 两次反馈NO_PROGRESS，第三次停止),
        and the third repeat is refused rather than executed — executing it first would spend an attempt on the
        action being refused.
        """
        return self.rounds >= MAX_NO_PROGRESS_ROUNDS

    def note_evidence(self, fresh: bool) -> None:
        """Record whether the action that just ran produced evidence the run had not seen.

        **This is where a no-progress round is counted**, because this is the first moment it is knowable:
        new evidence clears the streak, while a repeat that produced nothing new adds to it.
        """
        if fresh:
            self.latest_was_new = True
            self.rounds = 0
        elif self.pending_repeat:
            self.rounds += 1
        self.pending_repeat = False
