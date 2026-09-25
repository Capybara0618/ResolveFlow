"""The HarnessRunner: one investigation, driven by the model's next action (C06.4①).

``docs/agent-harness.md:9`` is the property this module exists for: **Observation 后动作来自模型，不是case_type固定
路线**. So this is a loop, not a workflow: it asks the model what to do, executes that, hands the result back,
and asks again — and the only things that end it are a terminal decision from the model or a bound of the
harness.

What the harness owns, and what it deliberately does not:

- **It owns permissions, budget and termination** (``docs/core-scope.md``: Harness控制权限/预算/终止). Every action
  passes :func:`~resolveflow.harness.actions.validate_decision` before anything is executed, every attempt is
  reserved against :class:`~resolveflow.harness.budget.BudgetGuard` before it happens, and every stop carries a
  stable reason code with the evidence that produced it (``docs/agent-harness.md:45``).
- **It does not choose the investigation.** There is no ``case_type`` branch anywhere in this file. The run's
  facts (which line, which case) come from the dispatch and are handed to the tools; what to *read* comes from
  the model.

**Why the packet is rebuilt from the recorded observations every turn.** The alternative — appending to a
growing transcript and letting that be the input — makes the model's input a function of how the run got there
rather than of what is known, so two paths that observed the same things would send different prompts and a
saved input hash would describe neither. Rebuilding from the observations makes the packet a function of the
evidence, which is what ``docs/agent-harness.md:22`` wants to save and hash. The turns are still sent (a
provider needs the conversation); they are just not the source of truth.

**Why a repeated action is fed back before it stops the run.** ``docs/agent-spec.md:44``: 连续重复同动作且无新证据，
两次反馈NO_PROGRESS，第三次停止. The first two repeats are therefore *not* failures — the model is told, in the
packet, that its attempt produced nothing it had not already seen, and gets another turn. The third stops. A
harness that stopped on the first repeat would refuse a legitimate retry; one that never stopped would end at
the budget, and the reason code would then name the wrong bound.

**What this slice does not do**, stated here so a reader does not infer it from the module's size: there is no
checkpoint or fence (C09), no context snapshot persistence (C07), no proposal validation against citations
(C07/C08), and no callback to Case (C08). The action's outcome is returned to the caller; nothing is written
anywhere yet.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from agentscope.message import Msg

from resolveflow.contracts.core_models import ToolObservation
from resolveflow.harness.actions import (
    ASK_CUSTOMER,
    ESCALATE,
    PROPOSE,
    READ_OBSERVATION,
    READ_TOOL,
    SEARCH_POLICY,
    ActionRefusedError,
    ModelDecision,
    validate_decision,
)
from resolveflow.harness.budget import (
    REASON_BUDGET_MODEL_CALLS,
    REASON_NO_PROGRESS,
    BudgetExhaustedError,
    BudgetGuard,
    RunBudget,
    RunSpend,
)
from resolveflow.harness.model import ModelClient, ModelReply
from resolveflow.harness.sdk_adapter import messenger_message as MessengerMessage

__all__ = [
    "REASON_ACTION_REFUSED",
    "REASON_COMPLETED",
    "REASON_TOOL_CALLS_EXHAUSTED",
    "REASON_TOOL_FAILED",
    "SYSTEM_PROMPT",
    "HarnessRunner",
    "RunFacts",
    "RunResult",
    "ToolExecutor",
]

#: The run reached a decision. ``docs/agent-spec.md:9``: COMPLETED means the plan callback was accepted by
#: Case — it does **not** mean a refund happened. Nothing in this slice sends a callback yet (that is C08), so
#: the code says "the investigation reached a decision", which is exactly what this slice can know.
REASON_COMPLETED: Final = "COMPLETED"

#: The model's action was refused by the ABI (``docs/agent-spec.md:22``).
REASON_ACTION_REFUSED: Final = "ACTION_REFUSED"

#: The tool layer itself failed: not "the source was unreadable" (that is an observation) but "the call could
#: not be completed at all". Kept distinct because the two need different responses — one is evidence to hand
#: back to the model, the other is an environment problem that will not improve by asking again.
REASON_TOOL_FAILED: Final = "TOOL_FAILED"

#: The executor ran out of the calls it was willing to make. Its own bound, separate from the run's budget: the
#: run budget is what the spec fixes, this is what the executor can physically serve.
REASON_TOOL_CALLS_EXHAUSTED: Final = "TOOL_CALLS_EXHAUSTED"

#: The system prompt. Deliberately short and free of business routing: a prompt that said "if the parcel is
#: late, read the shipment" would be the fixed route ``docs/agent-harness.md:9`` rules out, written in prose
#: instead of in code.
SYSTEM_PROMPT: Final = (
    "You are investigating one after-sales case for one order line. Choose the next action from the ABI you "
    "are given. Read only what you need; a read is evidence only if you can cite its source, version and hash. "
    "Do not name a line, case, run, merchant or customer: the run already fixed those. When the evidence "
    "supports a decision, PROPOSE it and cite what you saw."
)


class ToolExecutor(Protocol):
    """Somewhere to make one tool call. Narrow on purpose: three methods, one of which closes it.

    The real implementation drives the five whitelisted tools over MCP stdio (C06.4②), which is why the
    interface is *call by name with arguments* rather than a Python method per tool: an executor with a
    ``get_order_context()`` method would make the MCP path one option among several rather than the only way a
    tool is reached, and the claim being made is that the tools are reached the way a deployment reaches them.

    ``note_trace_page`` is here rather than being inferred by the executor, and it is the one method the runner
    never has to call. ``docs/agent-spec.md:29``'s two-page budget belongs to the **run**, and the executor is the
    object that lives for the run (a tool server process is started per call and cannot remember), so the
    executor owns the counter and charges it when the server answers with a page. The method is on the protocol
    because it is part of what "an executor" means for a paged tool — a second implementation that forgot it
    would make the cap mean "two pages per call", which is not a cap.
    """

    def call_tool(self, *, run_id: str, tool_name: str, arguments: dict[str, Any]) -> ToolObservation: ...

    def note_trace_page(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RunFacts:
    """What the run is about, as the dispatch fixed it (``docs/core-contracts.md:60``).

    These never come from the model. ``line_id`` in particular is the subject of the whole investigation
    (``docs/core-scope.md:9`` — one order line), and it is handed to the tools rather than accepted from an
    action, so "which line" cannot become a model decision.
    """

    run_id: str
    case_id: str
    input_revision: int
    line_id: str
    description: str
    merchant_id: str | None = None
    customer_id: str | None = None
    #: The window the run may work inside (``docs/agent-spec.md:42``), already resolved to
    #: ``min(deadline, start + 120s)`` by whoever started it. ``None`` means no worker has fixed one yet.
    active_deadline_at: str | None = None
    policy_manifest: dict[str, Any] = field(default_factory=dict)

    def deadline(self) -> dt.datetime | None:
        """The window as an instant, tolerating the wire's ``Z``."""
        if not self.active_deadline_at:
            return None
        return dt.datetime.fromisoformat(self.active_deadline_at.replace("Z", "+00:00"))


@dataclass(frozen=True, slots=True)
class RunResult:
    """How one investigation ended, and everything a reader needs to check that claim.

    ``completed`` and ``reason_code`` are separate members because "the run finished" and "the run finished
    *with a decision*" are different facts, and one status would have to be wrong about one of them. A run
    stopped by its budget is not a failed investigation — nothing was refused — and it is not a completed one
    either.
    """

    completed: bool
    reason_code: str
    decision: ModelDecision | None
    observations: tuple[ToolObservation, ...]
    spend: RunSpend
    #: One entry per action taken, in order: what was asked for and whether it produced anything new. The
    #: trajectory's skeleton (``docs/agent-spec.md:52`` — explicit actions and short reasons, never hidden
    #: reasoning).
    trajectory: tuple[dict[str, Any], ...] = ()
    #: Everything the model was told, so a reader can check that the stop was visible to it.
    notices: tuple[str, ...] = ()
    #: Which mode answered each decision, in order. Mock and live results must stay distinguishable
    #: (``docs/core-scope.md``完成标准), and a record that lost this could not say what it is evidence of.
    modes: tuple[str, ...] = ()


class HarnessRunner:
    """One run's decision loop. Constructed per run, never reused across runs.

    A runner that could be reused would carry one run's observations and budget into the next, which is the
    mirror image of ``docs/core-scope.md``'s "同run恢复不静默重置预算": a budget belongs to a run, so a runner
    belongs to one too.
    """

    #: Set when a terminal decision arrives. A class-level default rather than an ``__init__`` assignment so a
    #: reader can see it is per-run state, and so :meth:`_finish` can read it for a run that never decided.
    _last_decision: ModelDecision | None = None
    #: Whether the last executed action produced evidence the run had not already seen.
    _latest_was_new: bool = False

    def __init__(
        self,
        *,
        model: ModelClient,
        tools: ToolExecutor,
        facts: RunFacts,
        budget: RunBudget | None = None,
        system: str = SYSTEM_PROMPT,
        max_steps: int | None = None,
    ) -> None:
        self._model = model
        self._tools = tools
        self._facts = facts
        self._system = system
        self._budget = budget or RunBudget()
        self._guard = BudgetGuard(self._budget, active_deadline=facts.deadline())
        #: The transcript handed to the provider, turn by turn. Not the source of truth for what the model
        #: sees — the packet is rebuilt from the observations every turn — but a provider needs it.
        self._turns: list[Msg] = []
        self._observations: list[ToolObservation] = []
        #: Content hashes already observed. ``docs/agent-spec.md:44``'s 无新证据 is decided against this: the
        #: same hash twice means the second read added nothing, whatever the model hoped would change.
        self._seen_hashes: set[str] = set()
        self._trajectory: list[dict[str, Any]] = []
        self._notices: list[str] = []
        self._modes: list[str] = []
        self._last_action_digest: str | None = None
        self._last_decision = None
        self._latest_was_new = False
        self._max_steps = max_steps if max_steps is not None else self._budget.model_calls

    @property
    def guard(self) -> BudgetGuard:
        """The budget, exposed so a caller can read the spend of a run that is still going."""
        return self._guard

    def run(self) -> RunResult:
        """Drive the loop until the model decides or a bound of the harness stops it."""
        while True:
            stop = self._step()
            if stop is not None:
                return self._finish(stop)
            if len(self._trajectory) >= self._max_steps * 4:
                # A backstop for the one case the budget cannot cover: an action that is never reserved (a
                # refused repeat or an unbuilt search) repeated forever. The model-call budget still bounds
                # this in practice, since every turn costs one; this is the belt to that pair of braces, and
                # it reports the budget code because that is what would have run out next.
                return self._finish(
                    (False, REASON_BUDGET_MODEL_CALLS, "the loop took no reserveable action at all")
                )

    # ------------------------------------------------------------------ one turn

    def _step(self) -> tuple[bool, str, str] | None:
        """One ask-execute-observe turn. Returns the stop reason, or ``None`` to keep going."""
        packet = self._packet()
        # AgentScope messages: the client protocol speaks them (see `model.py`), and once AS02.2 replaces this loop
        # with the SDK's own the conversation is the SDK's, so building a second dict shape here would be
        # vocabulary that has to be thrown away.
        turn = MessengerMessage(packet)
        self._turns.append(turn)

        # The reservation happens before the call (docs/agent-harness.md:22). The requested input size is
        # measured from the packet rather than guessed: an estimate that was too *small* would let a step past
        # a cap that should have refused it, and the per-step cap is a statement about the request that is
        # about to be sent. Output is reserved as zero here and added from the reply, because the answer's
        # length is not knowable beforehand — the direction that cannot make a run spend less than it reserved.
        try:
            self._guard.reserve_model_call(input_tokens=_token_estimate(packet), output_tokens=0)
        except BudgetExhaustedError as exhausted:
            self._turns.pop()
            return (False, exhausted.reason_code, str(exhausted))

        reply = self._model.decide(system=self._system, messages=list(self._turns))
        self._record_output(reply)
        self._modes.append(reply.mode)
        self._turns.append(MessengerMessage(reply.decision, name="assistant", role="assistant"))

        try:
            decision = validate_decision(reply.decision)
        except ActionRefusedError as refusal:
            self._trajectory.append(
                {"action": reply.decision.get("kind"), "outcome": "REFUSED", "detail": str(refusal)}
            )
            return (False, refusal.reason_code or REASON_ACTION_REFUSED, str(refusal))

        if decision.kind in (PROPOSE, ASK_CUSTOMER, ESCALATE):
            self._trajectory.append(
                {
                    "action": decision.kind,
                    "outcome": "DECIDED",
                    "detail": decision.recommended_action or decision.kind,
                }
            )
            self._last_decision = decision
            return (True, REASON_COMPLETED, f"the model decided: {decision.kind}")

        return self._act(decision)

    def _act(self, decision: ModelDecision) -> tuple[bool, str, str] | None:
        """Execute a non-terminal action, and apply the no-progress rule around it.

        The rule has two halves and they are on opposite sides of the action, which is why they read oddly:

        - **whether the third identical action may run at all is decided before it runs.** ``docs/agent-spec.md:44``
          stops the run at the third repeat; executing it first would spend an attempt on the thing being refused,
          and ``docs/agent-spec.md:40``'s 所有attempt计预算 would count it.
        - **whether a repeat produced new evidence is only knowable after it runs**, which is why the first two
          repeats are *fed back* rather than refused: they already happened, and the useful response is to tell
          the model what came back (``note_no_progress`` says so).
        """
        digest = _action_digest(decision)
        repeated = digest == self._last_action_digest
        self._last_action_digest = digest
        self._latest_was_new = False

        if repeated and self._guard.feedback_rounds_remaining() == 0:
            self._trajectory.append(
                {
                    "action": decision.kind,
                    "outcome": "NO_PROGRESS",
                    "detail": "refused before running: the same action already repeated twice",
                }
            )
            return (
                False,
                REASON_NO_PROGRESS,
                "the same action was repeated three times with no new evidence (docs/agent-spec.md:44)",
            )

        if decision.kind == READ_TOOL:
            stop = self._read_tool(decision)
            if stop is not None:
                return stop
        elif decision.kind == SEARCH_POLICY:
            # The policy index is C07. Refusing loudly is the honest state: a harness that pretended to search
            # and returned nothing would make "the policy does not apply" indistinguishable from "the search is
            # not built", and the difference is the whole reason the run cites policy at all.
            self._trajectory.append(
                {"action": SEARCH_POLICY, "outcome": "UNIMPLEMENTED", "detail": "the policy index is C07"}
            )
            self._notices.append("SEARCH_POLICY is not built yet (C07); read a tool or decide without it")
            self._latest_was_new = True  # a notice is new information: the model has not been told this before
            return None
        elif decision.kind == READ_OBSERVATION:
            stop = self._read_observation(decision)
            if stop is not None:
                return stop

        if repeated and not self._latest_was_new:
            if not self._guard.note_no_progress():  # pragma: no cover - the refusal above runs first
                raise AssertionError("the no-progress refusal should have happened before the action")
            self._notices.append(
                "NO_PROGRESS: that action produced nothing you had not already seen. Read something else or "
                "decide with what you have."
            )
            return None
        self._guard.note_progress()
        return None

    def _read_tool(self, decision: ModelDecision) -> tuple[bool, str, str] | None:
        """One MCP tool call, bounded before it happens and recorded whatever it answers."""
        name = decision.tool_name or ""
        repeated = _action_digest(decision) == self._last_action_digest
        try:
            self._guard.reserve_tool_attempt()
        except BudgetExhaustedError as exhausted:
            return (False, exhausted.reason_code, str(exhausted))

        try:
            observation = self._tools.call_tool(
                run_id=self._facts.run_id, tool_name=name, arguments=dict(decision.arguments)
            )
        except Exception as failure:  # noqa: BLE001 - the executor's failure is the run's fact to record
            # A tool *layer* that raised has not observed anything, so this is not evidence: the run stops with
            # a code that says the environment failed rather than inventing an observation. An unreadable
            # *source* is a different thing entirely and arrives as an observation with an ``error`` member.
            self._trajectory.append({"action": name, "outcome": "FAILED", "detail": str(failure)[:300]})
            return (False, REASON_TOOL_FAILED, f"{name} could not be called: {failure}")

        fresh = self._admit(observation)
        # What counts as progress is *new evidence*, not "something came back". A failed read is new information
        # the first time — the model has to see that its read failed — but an identical read that fails again
        # has told the run nothing it did not already have, and treating it as progress is how a model retrying
        # an unreachable source runs until its model-call budget while every attempt looks productive. So the
        # streak is decided on the action's identity: a *repeat* is judged by whether the evidence changed.
        if not repeated:
            self._latest_was_new = True
        else:
            self._latest_was_new = observation.error is None and fresh
        self._trajectory.append(
            {
                "action": name,
                "outcome": "OBSERVED" if observation.error is None else f"ERROR:{observation.error.code}",
                "new_evidence": fresh,
                "observation_id": observation.observation_id,
            }
        )
        return None

    def _read_observation(self, decision: ModelDecision) -> tuple[bool, str, str] | None:
        """A local read of an excerpt this run already holds (``docs/agent-spec.md:17``).

        Bounded by the *local read* budget rather than the tool budget, because it is not an external call: it
        costs nothing at a provider and is what ``docs/agent-harness.md:41`` means by 按需读回.
        """
        try:
            self._guard.reserve_local_read()
        except BudgetExhaustedError as exhausted:
            return (False, exhausted.reason_code, str(exhausted))
        wanted = decision.observation_id
        # A local read that happened at all is not "a repeat with no new evidence": the no-progress rule guards
        # against repeating an *external* read that keeps answering the same thing, and a run must not be stopped
        # for reading back what it already holds. It is bounded instead by the local-read budget, which is what
        # that budget is for.
        self._latest_was_new = True
        if not any(item.observation_id == wanted for item in self._observations):
            # A reference to something this run does not hold is refused rather than answered empty: an empty
            # answer reads as "the source has nothing", which is a claim about the world
            # (docs/agent-spec.md:36 — NOT_FOUND 不是否定事实).
            self._trajectory.append({"action": READ_OBSERVATION, "outcome": "NOT_HELD", "detail": str(wanted)})
            self._notices.append(
                f"this run holds no observation {wanted!r}; you may only read back what you already saw"
            )
            return None
        self._trajectory.append({"action": READ_OBSERVATION, "outcome": "READ", "detail": str(wanted)})
        return None

    # ------------------------------------------------------------------ what the model is told

    def _packet(self) -> dict[str, Any]:
        """The exact input for one decision call (``docs/agent-harness.md:22``).

        Rebuilt from the recorded facts and observations every turn, so the packet is a function of what is
        known rather than of how the run got there (see the module docstring). The limits are stated *in* the
        packet because a model that does not know it has read fourteen of sixteen things cannot decide to stop
        reading — a run stopped by a budget it was never told about is a surprise, not a bound.
        """
        packet: dict[str, Any] = {
            "run": {
                "run_id": self._facts.run_id,
                "case_id": self._facts.case_id,
                "input_revision": self._facts.input_revision,
                "line_id": self._facts.line_id,
                "description": self._facts.description,
            },
            "step": len(self._trajectory) + 1,
            "budget": {
                "tool_attempts_made": self._guard.spend.tool_attempts,
                "tool_attempts_allowed": self._guard.budget.tool_attempts,
                "local_reads_made": self._guard.spend.local_reads,
                "local_reads_allowed": self._guard.budget.local_reads,
                "no_progress_rounds": self._guard.spend.no_progress_rounds,
            },
            "observations": [_observation_payload(item) for item in self._observations],
        }
        if self._notices:
            packet["notices"] = list(self._notices)
        if self._facts.active_deadline_at:
            packet["run"]["active_deadline_at"] = self._facts.active_deadline_at
        return packet

    def _admit(self, observation: ToolObservation) -> bool:
        """Keep an observation, and say whether it is new evidence.

        A failed observation (no hash) is always new: "I could not read it" is a fresh fact each time it
        happens, and the model has to see that its retry failed too. A successful one is new only when its
        content hash is new, which is ``docs/agent-spec.md:44``'s 无新证据 made decidable.
        """
        if observation.content_hash is None:
            self._observations.append(observation)
            return True
        fresh = observation.content_hash not in self._seen_hashes
        self._seen_hashes.add(observation.content_hash)
        self._observations.append(observation)
        return fresh

    def _record_output(self, reply: ModelReply) -> None:
        """Add the reply's real output tokens to the spend, on top of whatever was reserved.

        The reservation counted input only, because the answer's length is not knowable beforehand. Recording
        the actual usage afterwards can therefore only *add*, which is the direction that keeps 预占 meaningful
        (``docs/agent-spec.md:44``).
        """
        self._guard.spend.output_tokens += reply.usage.output_tokens

    # ------------------------------------------------------------------ ending

    def _finish(self, stop: tuple[bool, str, str]) -> RunResult:
        completed, reason_code, detail = stop
        self._notices.append(detail)
        return RunResult(
            completed=completed,
            reason_code=reason_code,
            decision=self._last_decision,
            observations=tuple(self._observations),
            spend=self._guard.spend,
            trajectory=tuple(self._trajectory),
            notices=tuple(self._notices),
            modes=tuple(self._modes),
        )


def _observation_payload(observation: ToolObservation) -> dict[str, Any]:
    """One observation as the model sees it.

    ``model_dump(mode="json")`` rather than a hand-built dict: the members are the wire contract's
    (``ObservationRecord``), and a second spelling here is how the packet would start disagreeing with what the
    run records. The raw body is not re-truncated — the 8 KiB gate lives in the tool
    (``docs/agent-spec.md:36``), and a second gate here would make the packet the place that decides what
    evidence is.
    """
    return dict(observation.model_dump(mode="json"))


def _token_estimate(packet: dict[str, Any]) -> int:
    """A conservative estimate of the packet's input tokens, from its serialised size.

    Four characters per token is roughly right for English and pessimistic for JSON keys, and pessimism is the
    direction that matters: ``docs/agent-harness.md:37`` requires unknown token usage to be estimated
    conservatively, and an estimate that was too small would let a request through that the step cap exists to
    refuse. This is the *reservation*; a provider's own count is what settles the accounting.
    """
    return max(1, len(json.dumps(packet, ensure_ascii=False)) // 4)


def _action_digest(decision: ModelDecision) -> str:
    """A stable digest of what the action *asked for*, for the no-progress rule.

    Keyed on the action's content rather than on its kind, because ``docs/agent-spec.md:44`` says 不同版本/下一页不
    误判: a different page of the same trace is a different action, and a digest that ignored the arguments would
    stop a run that is legitimately paging.
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
