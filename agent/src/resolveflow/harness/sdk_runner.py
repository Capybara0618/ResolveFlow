"""AS02.2: the run assembled over AgentScope's own loop, with the domain's guards in front of it.

`docs/agentscope-migration.md:34` gives the shape of the target and one prohibition: there must be **one**
production loop, and it is AgentScope's, while the domain Harness keeps the hard constraints. So this module does
not implement a second loop — it wires the SDK's `Agent` to the project's already-tested guards and translates the
outcome back into the `RunResult` the rest of the project speaks.

**Where each rule lives, now that the loop is not ours.** This mapping is what makes "the old semantics were
kept" checkable rather than a claim. Each row names the rule, the object that enforces it, and why it belongs
there rather than somewhere else:

- **the model decides the next action** — the SDK's reasoning-acting loop. It *is* the loop
  (`docs/agent-harness.md:9`).
- **every model request is reserved against the run budget, before it goes out** — `_BudgetHook` on
  `on_model_call`. The SDK's own "wrap up" nudge is not a refusal (`agent-migration.md:51`), and this hook also
  sees retries and repairs, which a per-turn count would miss.
- **an action outside the ABI never reaches a tool** — `ActionGateMiddleware` on `on_check_permission`. AS01.1
  measured that the SDK consults this **before** executing, so "illegal ⇒ zero executions" is structural.
- **no progress is fed back twice and refused the third time** — `ActionGateMiddleware` plus
  `control.NoProgressTracker`. The rule spans the action, and the third attempt must be refused **before** it
  runs (`docs/agent-spec.md:44`).
- **a tool that cannot observe returns an error observation** — `McpToolBridge`. `docs/agent-harness.md:51`
  wants the error handed back, so it must be an observation and not an exception.
- **which bound ended the run** — this module's `_outcome`. A stop has to say *which* budget ran out, in either
  loop.

**Why the SDK `Agent` is built per run.** A runner carries one run's budget, observations and no-progress state,
and `docs/core-scope.md`'s "同run恢复不静默重置预算" is the mirror image: state belonging to a run must not be
reachable from another.

**What this module does not do.** It is not the recovery engine: nothing here persists a snapshot or checks a
fence (`docs/agentscope-migration.md:63`, C09 owns that). The AS01.2 probe fixed the *shape* the storage needs;
this is not that storage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import anyio
from agentscope.agent import Agent, ReActConfig
from agentscope.message import Msg, TextBlock
from agentscope.middleware import MiddlewareBase
from agentscope.tool import ToolBase, Toolkit

from resolveflow.harness.actions import WHITELIST, ActionRefusedError, ModelDecision, validate_decision
from resolveflow.harness.budget import BudgetExhaustedError, BudgetGuard, RunBudget, RunSpend
from resolveflow.harness.control import (
    REASON_ACTION_REFUSED,
    REASON_COMPLETED,
    REASON_NO_PROGRESS,
    REASON_TOOL_FAILED,
    NoProgressTracker,
)
from resolveflow.harness.model import ModelReply, ModelUsage
from resolveflow.harness.sdk_adapter import AgentScopeModelAdapter, messenger_message
from resolveflow.harness.vocabulary import HARNESS_SYSTEM_PROMPT, RunFacts, RunResult, ToolExecutor

__all__ = ["AgentScopeRunner", "ActionGateMiddleware", "McpToolBridge"]

#: The decisions that end a run. Kept beside the ABI rather than derived from it, because "which kinds are
#: terminal" is a fact about the run and not about the schema; `validate_decision` enforces the rest.
_TERMINAL_KINDS = frozenset({"PROPOSE", "ASK_CUSTOMER", "ESCALATE"})




class ActionGateMiddleware(MiddlewareBase):
    """Refuses an action the ABI forbids, **before** the SDK executes anything for it.

    Two rules live here because both must happen on the SDK's side of the boundary:

    * **the ABI guard** — unknown kinds, write tools, identity fields, arbitrary URLs (`docs/agent-spec.md:22`);
    * **the no-progress rule** — the third identical action without new evidence is refused *before it runs*, and
      the first two are fed back (`docs/agent-spec.md:44`).

    Refusals are recorded rather than merely returned, so a test can assert *which* rule fired and that the tool
    body never ran. The weaker assertion — "a deny decision came back" — would pass for a gate that denied and
    executed anyway, which is the failure worth excluding.
    """

    def __init__(self) -> None:
        self.progress = NoProgressTracker()
        #: Every refusal, in order, with the reason code the outcome will report.
        self.refusals: list[dict[str, Any]] = []
        #: Set when the run must stop rather than continue, with the reason code to report.
        self.stop_reason: str | None = None
        #: The last decision the gate accepted, as the ABI's own mapping.
        self.accepted: dict[str, Any] | None = None
        #: The last *terminal* decision, which is the run's proposal.
        self.terminal: ModelDecision | None = None
        #: Notices fed back to the model (the two no-progress rounds).
        self.notices: list[str] = []

    def check(self, payload: dict[str, Any]) -> ModelDecision | None:
        """Validate one decision: return it, or set the stop reason and return ``None``.

        A plain method rather than a hook so the rules are testable without an event loop; the SDK-facing part is
        :meth:`on_check_permission`, which is thin. That split is what lets the *same* rules run on the SDK loop
        without every rule test needing a model.
        """
        try:
            decision = validate_decision(payload)
        except ActionRefusedError as refusal:
            self.refusals.append({"reason": refusal.reason_code, "detail": str(refusal)})
            self.stop_reason = refusal.reason_code or REASON_ACTION_REFUSED
            return None

        if decision.kind in _TERMINAL_KINDS:
            # Terminal: it ends the run and is not executed, so it does not touch the no-progress tracker.
            self.terminal = decision
            self.accepted = payload
            return decision

        repeated = self.progress.note_action(decision)
        if repeated and self.progress.should_stop_before_running():
            self.refusals.append(
                {
                    "reason": REASON_NO_PROGRESS,
                    "detail": "the same action repeated three times with no new evidence",
                }
            )
            self.stop_reason = REASON_NO_PROGRESS
            return None
        # A repeat is **not** counted here: whether it was "no progress" depends on the evidence it produces, which
        # arrives after the tool runs. `note_evidence` below is what counts a round, and it is also what stops the
        # third repeat — see `control.NoProgressTracker` for why the order matters.
        self.accepted = payload
        return decision

    def note_stop(self, reason_code: str) -> None:
        """Record why the run must stop, without overwriting a reason already recorded.

        First refusal wins: if the ABI refused an action *and* a later attempt hit a budget, the earlier fact is
        the one that explains the run, and overwriting it would report the symptom instead of the cause.
        """
        if self.stop_reason is None:
            self.stop_reason = reason_code

    def note_evidence(self, fresh: bool) -> None:
        """Tell the gate whether the last action produced evidence the run had not already seen.

        This is what decides a no-progress round, and it also produces the notice the model is owed: the first two
        no-evidence repeats are **fed back** (`docs/agent-spec.md:44`), so the model has to be told, in the
        conversation, that its attempt added nothing.
        """
        was_repeat = self.progress.pending_repeat
        self.progress.note_evidence(fresh)
        if was_repeat and not fresh:
            self.notices.append(
                "NO_PROGRESS: that action produced nothing you had not already seen. Read something else or "
                "decide with what you have."
            )

    async def on_check_permission(self, agent: Any, input_kwargs: dict[str, Any], next_handler: Any) -> Any:
        """The SDK's pre-execution hook: allow the accepted action, deny anything else.

        The model's decision is re-validated here rather than trusted from the adapter, and the call is allowed
        only when the SDK is about to execute exactly the tool the accepted decision named. That is what makes the
        gate a boundary instead of a formality: a tool call the model emitted that the gate never accepted — or one
        whose arguments differ from the validated ones — is denied.
        """
        from agentscope.permission import PermissionBehavior, PermissionDecision

        tool = input_kwargs.get("tool")
        name = getattr(tool, "name", None)
        if self.stop_reason is not None:
            # A stop has already been recorded (a budget bound ran out, or a tool layer failed). Denying here is
            # what makes the SDK **stop asking**: recording the reason alone left the loop reasoning-acting until
            # the next bound fired, so a run out of tool attempts reported the model-call bound instead
            # (`docs/agent-harness.md:45` requires the stop to name the bound that actually ran out).
            return PermissionDecision(
                behavior=PermissionBehavior.DENY, message=f"the run has stopped: {self.stop_reason}"
            )
        accepted = self.accepted
        allowed_name = None
        if isinstance(accepted, dict) and accepted.get("kind") == "READ_TOOL":
            allowed_name = accepted.get("tool_name")

        if name is None or name != allowed_name:
            self.refusals.append(
                {
                    "reason": REASON_ACTION_REFUSED,
                    "detail": f"{name!r} is not the tool the accepted decision named ({allowed_name!r})",
                }
            )
            self.stop_reason = self.stop_reason or REASON_ACTION_REFUSED
            return PermissionDecision(
                behavior=PermissionBehavior.DENY, message=f"{name!r} was not the accepted action"
            )
        return await next_handler()


class McpToolBridge(ToolBase):
    """One whitelisted tool, executed through the project's own `ToolExecutor`.

    The bridge is what keeps the MCP boundary where it already is: the SDK calls `call`, and `call` reaches the
    real tool server through `harness/mcp_client.py` — the official stdio path with its own tests — rather than
    through AgentScope's MCP client, which AS01.1 measured broken under mcp 2.x. The user decided this
    (2026-09-25); `reports/agentscope-migration/compatibility.md` §3 records the four findings behind it.

    A tool that cannot observe returns a `ToolChunk` carrying the error observation, never a raised exception:
    `docs/agent-harness.md:51` requires the error to go back to the model, and an exception would end the reply.
    """

    def __init__(
        self,
        name: str,
        executor: ToolExecutor,
        facts: RunFacts,
        gate: ActionGateMiddleware,
        adapter: AgentScopeModelAdapter,
        client: Any,
        guard: Any,
    ) -> None:
        self.name = name
        self.description = f"Read-only investigation tool {name}."
        self.input_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "cursor": {"type": "string"},
                "limit": {"type": "integer"},
                "kind": {"type": "string"},
            },
            "required": [],
        }
        self.is_concurrency_safe = False
        self.is_read_only = True
        # **Not** an external tool, and getting this wrong is how the first version failed: with
        # `is_external_tool = True` the SDK does not execute the call at all — it parks the reply waiting for an
        # `ExternalExecutionResultEvent` from outside, and the run ends with a message about waiting for
        # permission. That shape is for work a *person* must do; our five reads are ordinary tool calls the loop
        # should make, reaching the tool server over MCP stdio.
        self.is_external_tool = False
        self.is_state_injected = False
        self.is_mcp = False
        self.mcp_name: str | None = None
        self.dangerous_files: list[str] = []
        self.dangerous_directories: list[str] = []
        self._executor = executor
        self._facts = facts
        self._gate = gate
        self._adapter = adapter
        self._client = client
        #: The run's budget guard, so **every** tool attempt is reserved before it happens. Without this the
        #: SDK loop enforced the model-call and token bounds but not the 16-attempt bound: a test with
        #: `tool_attempts=3` observed four executions, which is a bound `docs/agent-spec.md:40` states and the
        #: C06.4 loop enforced. The gap was found by running the old assertions on the new loop.
        self._guard: Any = guard
        #: Every call this bridge made, so a test can assert what actually ran.
        self.calls: list[dict[str, Any]] = []

    def check_permissions(self, tool_input: dict[str, Any], context: Any) -> Any:
        """Passthrough: the gate is the middleware, and two gates would make a refusal ambiguous."""
        from agentscope.permission import PermissionBehavior, PermissionDecision

        return PermissionDecision(behavior=PermissionBehavior.PASSTHROUGH, message="the action gate decides")

    async def call(self, **kwargs: Any) -> Any:
        from agentscope.tool import ToolChunk
        from agentscope.tool._response import ToolResultState  # type: ignore[attr-defined]

        self.calls.append({"name": self.name, "arguments": dict(kwargs)})
        # Reserved **before** the call (docs/agent-spec.md:40: 所有attempt计预算). A refusal is recorded as the
        # run's stop reason and the chunk comes back as an error, which is what makes the *tool-attempt* bound the
        # one reported: the first version returned an error chunk **without** recording the stop, so the SDK fed
        # "no attempts left" back to the model, which asked again until the model-call bound fired — a run that ran
        # out of tool attempts then named the wrong bound (`docs/agent-harness.md:45`).
        #
        # The refusal is not raised, and that is deliberate: raising it propagates out of `Toolkit.call_tool`,
        # whose exception handler reads `mcp.shared.exceptions.McpError` — an mcp **1.x** name that mcp 2.2.0
        # renamed, so the handler itself raises `AttributeError` and the budget reason is lost. That is finding #4
        # in `reports/agentscope-migration/compatibility.md` §3, met live rather than in a probe.
        try:
            self._guard.guard.reserve_tool_attempt()
        except BudgetExhaustedError as exhausted:
            self._gate.note_stop(exhausted.reason_code)
            self._adapter.trajectory.append(
                {"action": self.name, "outcome": "REFUSED", "detail": exhausted.reason_code}
            )
            return ToolChunk(
                content=[TextBlock(type="text", text=f"{exhausted.reason_code}: {exhausted}")],
                state=ToolResultState.ERROR,
            )
        try:
            # `to_thread` because the project's executor is synchronous by construction (it bridges a private
            # event loop for MCP stdio); calling it inline would block the SDK's loop.
            observation = await anyio.to_thread.run_sync(
                lambda: self._executor.call_tool(
                    run_id=self._facts.run_id, tool_name=self.name, arguments=dict(kwargs)
                )
            )
        except Exception as failure:  # noqa: BLE001 - the executor's failure is the run's fact to record
            self._gate.note_stop(REASON_TOOL_FAILED)
            self._adapter.trajectory.append(
                {"action": self.name, "outcome": "FAILED", "detail": str(failure)[:300]}
            )
            return ToolChunk(
                content=[TextBlock(type="text", text=f"TOOL_FAILED: {failure}")],
                state=ToolResultState.ERROR,
            )

        fresh = self._adapter.record_observation(observation)
        self._client.note_observation(observation)
        self._gate.note_evidence(fresh)
        self._adapter.trajectory.append(
            {
                "action": self.name,
                "outcome": "OBSERVED" if observation.error is None else f"ERROR:{observation.error.code}",
                "new_evidence": fresh,
                "observation_id": observation.observation_id,
            }
        )
        return ToolChunk(
            content=[TextBlock(type="text", text=json.dumps(observation.model_dump(mode="json"), default=str))],
            state=ToolResultState.SUCCESS,
        )


@dataclass(slots=True)
class AgentScopeRunner:
    """The run, assembled over AgentScope's loop.

    The constructor shape deliberately matches the C06.4 `HarnessRunner`, so the tests that assert run semantics
    can run against either driver without rewriting what they claim — which is the only way "the old semantics
    were kept" becomes checkable.
    """

    model: Any
    tools: ToolExecutor
    facts: RunFacts
    budget: RunBudget = field(default_factory=RunBudget)
    system: str = HARNESS_SYSTEM_PROMPT
    max_iters: int | None = None

    def run(self) -> RunResult:
        """Drive one reply to completion and report the outcome.

        The loop is the SDK's; what this does is build it, seed the conversation with the run's facts, and
        translate what happened back into the vocabulary the project records. Nothing here decides an action.
        """
        return anyio.run(self._drive)

    async def _drive(self) -> RunResult:
        gate = ActionGateMiddleware()
        guard = _BudgetHook(self)
        client = _GateAwareClient(self, gate)
        model = AgentScopeModelAdapter(client, system=self.system)
        # The adapter settles real output usage through this, so the cumulative output meter reflects what the
        # provider produced rather than the ceiling reserved before each call.
        model.note_output = guard.note_output_tokens  # type: ignore[attr-defined]
        toolkit = Toolkit()
        for name in sorted(WHITELIST):
            await toolkit.add_tool(McpToolBridge(name, self.tools, self.facts, gate, model, client, guard))

        agent = Agent(
            name="resolveflow-agent",
            system_prompt=self.system,
            model=model,
            toolkit=toolkit,
            middlewares=[guard, gate],
            react_config=ReActConfig(max_iters=self.max_iters or self.budget.model_calls),
        )

        try:
            await agent.reply(messenger_message(_starting_packet(self)))
        except BudgetExhaustedError as exhausted:
            return _outcome(exhausted.reason_code, gate, model, guard, completed=False)
        except _ScriptExhausted:
            return _outcome(REASON_COMPLETED, gate, model, guard, completed=True)

        # A recorded stop ends the run. Without the loop's own check the model would be asked again after a budget
        # refusal, and the run would stop on whichever bound happened to fire next.
        if gate.stop_reason is not None:
            return _outcome(gate.stop_reason, gate, model, guard, completed=False)
        return _outcome(REASON_COMPLETED, gate, model, guard, completed=True)


class _ScriptExhausted(Exception):
    """The scripted model has nothing left to say. For a mock that is the end of the run, not a crash."""


class _BudgetHook(MiddlewareBase):
    """`on_model_call`: reserve every request against the run's budget before it goes out."""

    def __init__(self, runner: AgentScopeRunner) -> None:
        self._runner = runner
        self.guard = BudgetGuard(runner.budget, active_deadline=runner.facts.deadline())

    async def on_model_call(self, agent: Any, input_kwargs: dict[str, Any], next_handler: Any) -> Any:
        """Reserve one request, then let it through.

        **``count_tokens`` must not be called from here.** The first version did, to size the reservation from the
        real input, and the SDK's ``ChatModelBase.__call__`` calls ``count_tokens`` *before* ``_call_api`` — so the
        hook ran again for the same request and every request was reserved **twice**. The symptom was a run hitting
        ``BUDGET_OUTPUT_TOKENS`` at half the requests it should have been allowed: a budget that reports the wrong
        bound and spends twice what it says.

        The input size is measured from the messages and tools this hook was handed, which are the objects the
        provider would receive. It is an estimate (characters over four) and a *conservative* one, which is the
        direction `docs/agent-harness.md:37` requires: an estimate that was too small would let a request past a
        cap that should have refused it.
        """
        estimated = _estimate_input_tokens(input_kwargs)
        # **The step cap is a ceiling, not a meter.** The first version reserved `step_output_tokens` through
        # `reserve_model_call`, which charges the *cumulative* output allowance — so the spec's 4000-token
        # allowance was consumed after four requests and every budget test stopped on `BUDGET_OUTPUT_TOKENS`
        # instead of the bound it named. The two are different things: the per-step cap bounds one request, while
        # the cumulative cap meters what the provider actually produced. So one model call is reserved here, the
        # input estimate is charged, and the **real** output usage is added after the answer arrives
        # (`note_output_tokens`), which is also how `docs/agent-spec.md:44` describes it — 成功按usage结算.
        self.guard.reserve_model_call_without_output(input_tokens=estimated)
        return await next_handler()

    def note_output_tokens(self, tokens: int) -> None:
        """Settle a request's **actual** output against the cumulative meter."""
        self.guard.spend.output_tokens += max(0, tokens)


class _GateAwareClient:
    """The harness's `ModelClient`, with every decision passing through the gate first.

    The gate has to see each decision **before** the adapter renders it into blocks, because the rendering is what
    the SDK executes: a decision refused after rendering would already be a tool call. So the client is wrapped,
    not the adapter.
    """

    def __init__(self, runner: AgentScopeRunner, gate: ActionGateMiddleware) -> None:
        self._runner = runner
        self._gate = gate
        #: Every observation this run has made, in order, so the packet can be built from what is *known*
        #: rather than from how the conversation happened to go (`docs/agent-harness.md:22`).
        self.observations: list[Any] = []
        #: How many turns have been asked for, for the packet's `step`.
        self.turns = 0

    def note_observation(self, observation: Any) -> None:
        """Record one tool observation; the bridge calls this as it produces them."""
        self.observations.append(observation)

    def decide(self, *, system: str, messages: list[Msg]) -> Any:
        if self._gate.stop_reason is not None:
            # The run has already stopped, so the model is **not asked again**. Without this the SDK kept
            # reasoning-acting after a budget refusal and the run ended on whichever bound fired next, naming the
            # wrong one (`docs/agent-harness.md:45`). Returning a terminal decision ends the reply without a
            # provider call — and without inventing a decision, since the stop reason is already recorded.
            return ModelReply(
                decision={
                    "kind": "ESCALATE",
                    "reason_codes": ["STOPPED"],
                    "summary": f"the run stopped: {self._gate.stop_reason}",
                    "reasoning": "the harness stopped this run",
                },
                usage=ModelUsage(),
                mode="harness",
                model_alias=None,
            )
        self.turns += 1
        reply = self._runner.model.decide(
            system=system, messages=_with_current_packet(messages, self._runner, self.observations, self.turns)
        )
        decision = self._gate.check(reply.decision)
        if decision is None:
            # Refused: the run stops, and the adapter is given a terminal text so the SDK ends the reply rather
            # than executing anything. The refusal is already recorded on the gate.
            return ModelReply(
                decision={"kind": "ESCALATE", "reason_codes": ["REFUSED"], "summary": "the action was refused"},
                usage=reply.usage,
                mode=reply.mode,
                model_alias=reply.model_alias,
            )
        return reply


def _starting_packet(runner: AgentScopeRunner) -> dict[str, Any]:
    """The run's facts, in the packet shape the harness has used since C06.4."""
    return {
        "run": {
            "run_id": runner.facts.run_id,
            "case_id": runner.facts.case_id,
            "input_revision": runner.facts.input_revision,
            "line_id": runner.facts.line_id,
            "description": runner.facts.description,
        },
        "step": 1,
        "budget": {
            "tool_attempts_made": 0,
            "tool_attempts_allowed": runner.budget.tool_attempts,
            "local_reads_made": 0,
            "local_reads_allowed": runner.budget.local_reads,
            "no_progress_rounds": 0,
        },
        "observations": [],
    }


def _estimate_input_tokens(input_kwargs: dict[str, Any]) -> int:
    """A conservative estimate of one request's input, from the serialised messages and tool schemas.

    Four characters per token is roughly right for English and pessimistic for JSON keys, and pessimism is the
    direction that matters. Both parts are counted because `docs/agent-harness.md:37` requires the count to cover
    the final system prompt, the messages **and** the tool schemas — the schemas are the part that grows as tools
    are added, so counting only the messages would undercount exactly what changes.
    """
    import json

    messages = input_kwargs.get("messages") or []
    tools = input_kwargs.get("tools")
    rendered = json.dumps(
        [
            {"role": getattr(message, "role", None), "content": [str(block) for block in message.get_content_blocks()]}
            for message in messages
        ],
        ensure_ascii=False,
        default=str,
    )
    if tools:
        rendered += json.dumps(tools, ensure_ascii=False, default=str)
    return max(1, len(rendered) // 4)


def _with_current_packet(
    messages: list[Msg], runner: AgentScopeRunner, observations: list[Any], turn: int
) -> list[Msg]:
    """The conversation with its harness packet replaced by one built from what is known now.

    Rebuilt rather than appended: appending would make the prompt depend on the transcript''s history, so two paths
    that observed the same things would send different inputs and a saved input hash would describe neither. The
    packet goes **first**, where the opening one was, and the SDK''s own turns stay after it untouched.

    This is the C06.4 rule that a run''s input is a function of the evidence. Without it the second turn''s input
    carried no observations at all — ``test_the_observation_reaches_the_next_model_call`` failed on the first SDK
    version — which is exactly the kind of semantic loss that running the old assertions on the new loop exists to
    catch.
    """
    rebuilt = messenger_message(_packet_of(runner, observations, turn))
    rest = [
        message
        for message in messages
        # Drop the opening packet: the rebuilt one replaces it, and leaving both would show the model two
        # contradictory views of the run.
        if not (message.name == "harness" and message.role == "user")
    ]
    return [rebuilt, *rest]


def _packet_of(runner: AgentScopeRunner, observations: list[Any], turn: int) -> dict[str, Any]:
    """The packet for one turn: the run''s facts, the budget position, and every observation so far."""
    packet = _starting_packet(runner)
    packet["step"] = turn
    packet["budget"] = {
        "tool_attempts_made": len(observations),
        "tool_attempts_allowed": runner.budget.tool_attempts,
        "local_reads_made": 0,
        "local_reads_allowed": runner.budget.local_reads,
        "no_progress_rounds": 0,
    }
    packet["observations"] = [observation.model_dump(mode="json") for observation in observations]
    return packet


def _outcome(
    reason_code: str,
    gate: ActionGateMiddleware,
    model: AgentScopeModelAdapter,
    guard: _BudgetHook,
    *,
    completed: bool,
) -> RunResult:
    """Translate what the SDK run did into the project's `RunResult`."""
    # The tool attempts are the observations the bridges produced: every bridge call records exactly one, including
    # a failed read (which is an attempt that happened, docs/agent-spec.md:40).
    spend = RunSpend(
        model_calls=guard.guard.spend.model_calls,
        tool_attempts=len(model.observations),
        local_reads=guard.guard.spend.local_reads,
        input_tokens=guard.guard.spend.input_tokens,
        output_tokens=guard.guard.spend.output_tokens,
        no_progress_rounds=gate.progress.rounds,
    )
    return RunResult(
        completed=completed,
        reason_code=reason_code,
        decision=gate.terminal,
        observations=tuple(model.observations),
        spend=spend,
        trajectory=tuple(model.trajectory),
        notices=tuple(gate.notices),
        modes=tuple(model.modes),
    )
