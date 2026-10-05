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
from typing import Any, Final, cast

import anyio
from agentscope.agent import Agent, ReActConfig
from agentscope.message import Msg, TextBlock
from agentscope.middleware import MiddlewareBase
from agentscope.tool import ToolBase, Toolkit

from resolveflow.contracts.core_models import CoreToolError
from resolveflow.contracts.enums import CaseType
from resolveflow.harness.actions import (
    ASK_CUSTOMER,
    ESCALATE,
    OBSERVATION_READ_TOOL_NAME,
    POLICY_SEARCH_TOOL_NAME,
    PROPOSE,
    READ_OBSERVATION,
    READ_TOOL,
    RECOMMENDED_ACTIONS,
    SEARCH_POLICY,
    WHITELIST,
    ActionRefusedError,
    ModelDecision,
    validate_decision,
)
from resolveflow.harness.budget import BudgetExhaustedError, BudgetGuard, RunBudget, RunSpend
from resolveflow.harness.context import (
    CONFIRMED_ACTION_WINDOW,
    DEFAULT_INPUT_CAP,
    DEFAULT_OUTPUT_RESERVE,
    MAX_ACTION_ARGUMENT_CHARS,
    PROVIDER_WRAPPER_ALLOWANCE,
    ContextBuilder,
    OverflowRefusedError,
    canonical_json,
    estimate_tokens,
    extract_facts,
)
from resolveflow.harness.control import (
    REASON_ACTION_REFUSED,
    REASON_COMPLETED,
    REASON_NO_PROGRESS,
    REASON_TOOL_FAILED,
    NoProgressTracker,
)
from resolveflow.harness.correction import SECURITY_ERRORS, feedback, notice
from resolveflow.harness.facts import FactsView

# The two local-read executors live in their own module because they share every boundary decision: the budget
# pair, the stop reason, the trajectory entry and the error chunk. Two copies is where behaviour drifts.
from resolveflow.harness.local_reads import ObservationReadBridge, PolicySearchBridge
from resolveflow.harness.manifest import build_manifest, model_block_for
from resolveflow.harness.mcp_client import ToolCallFailedError
from resolveflow.harness.model import ModelReply, ModelUsage
from resolveflow.harness.observation_read import ObservationStore
from resolveflow.harness.references import expand_references
from resolveflow.harness.sdk_adapter import (
    AgentScopeModelAdapter,
    messenger_message,
    raw_text_message,
)
from resolveflow.harness.token_counting import counter_for
from resolveflow.harness.verifier import ProposalVerifier
from resolveflow.harness.vocabulary import HARNESS_SYSTEM_PROMPT, RunFacts, RunResult, ToolExecutor
from resolveflow.tools.catalog import ToolContext, _failed

__all__ = ["AgentScopeRunner", "ActionGateMiddleware", "McpToolBridge"]

#: The decisions that end a run. Kept beside the ABI rather than derived from it, because "which kinds are
#: terminal" is a fact about the run and not about the schema; `validate_decision` enforces the rest.
_TERMINAL_KINDS = frozenset({"PROPOSE", "ASK_CUSTOMER", "ESCALATE"})

#: How many times a run feeds a refused decision back for repair. One, because ``docs/agent-spec.md:52`` says the
#: model's Schema/citation output is repairable **once** — a second chance is a retry loop wearing a spec quote.
MAX_REPAIRS: Final = 1

#: The kinds the adapter renders as a **tool call**. A refused decision of one of these can be handed to the SDK
#: unchanged for its denial; a refused terminal decision cannot, and needs a probe (see `_repair_probe`).
_TOOL_CALL_KINDS = frozenset({READ_TOOL, SEARCH_POLICY, READ_OBSERVATION})


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
        #: How many refusals have already been fed back as a repair opportunity (C08.1c-2). Exactly
        #: :data:`MAX_REPAIRS` of them, because ``docs/agent-spec.md:52`` grants the model one chance to fix its own
        #: output and no more — an unbounded repair is a retry loop, which is what the model-call budget forbids.
        self.repairs_used = 0
        #: The reason to hand back when the SDK next asks to execute a refused action, or ``None``. Set only while a
        #: repair is available: it is what carries the refusal into the model's conversation, and it is consumed by
        #: :meth:`on_check_permission`.
        self.repair_message: str | None = None
        #: The proposal verifier (C08.1c), attached by the run once the observation record exists. ``None`` means
        #: citations are not checked — which is honest for a gate driven on its own in a unit test, and set for
        #: every real run.
        self.verifier: Any = None
        self.references: dict[str, dict[str, Any]] = {}
        self.read_ids: dict[str, str] = {}
        self.tool_failures: dict[str, int] = {}
        self.blocked_tools: set[str] = set()

    def check(self, payload: dict[str, Any]) -> ModelDecision | None:
        """Validate one decision: return it, or set the stop reason and return ``None``.

        A plain method rather than a hook so the rules are testable without an event loop; the SDK-facing part is
        :meth:`on_check_permission`, which is thin. That split is what lets the *same* rules run on the SDK loop
        without every rule test needing a model.
        """
        if payload.get("kind") == "__INVALID_MODEL_JSON__":
            self._refuse("MODEL_JSON_INVALID", "response is not a JSON decision object")
            return None
        try:
            payload = expand_references(payload, self.references, self.read_ids)
            decision = validate_decision(payload)
        except ActionRefusedError as refusal:
            self._refuse(refusal.reason_code or REASON_ACTION_REFUSED, str(refusal))
            return None

        if decision.kind in _TERMINAL_KINDS:
            # Terminal: it ends the run and is not executed, so it does not touch the no-progress tracker.
            if decision.kind == ASK_CUSTOMER and any(
                question.field.strip().lower() in {
                    "order_id", "line_id", "case_id", "run_id", "merchant_id", "customer_id",
                } for question in decision.questions
            ):
                self._refuse("QUESTION_ALREADY_BOUND",
                             "订单行/工单/用户/商家已绑定，勿向客户索要身份编号；系统事实可用只读工具获取")
                return None
            citation_refusal = self._verify_proposal(decision)
            if citation_refusal is not None:
                return None
            self.terminal = decision
            self.accepted = payload
            return decision

        if decision.kind == READ_TOOL and decision.tool_name in self.blocked_tools:
            code = ("TOOL_RETRIES_EXHAUSTED" if self.tool_failures.get(decision.tool_name, 0) >= 2
                    else "TOOL_NOT_RETRYABLE")
            self._refuse(code, "this bound read cannot be repeated; use another source or hand over", repairable=False)
            return None
        repeated = self.progress.note_action(decision)
        if repeated and self.progress.should_stop_before_running():
            # Not repairable: this is the loop's own bound, not a mistake in the model's output, and the two rounds
            # before it were already fed back (docs/agent-spec.md:44).
            self._refuse(
                REASON_NO_PROGRESS, "the same action repeated three times with no new evidence", repairable=False
            )
            return None
        # A repeat is **not** counted here: whether it was "no progress" depends on the evidence it produces, which
        # arrives after the tool runs. `note_evidence` below is what counts a round, and it is also what stops the
        # third repeat — see `control.NoProgressTracker` for why the order matters.
        self.accepted = payload
        return decision

    def _verify_proposal(self, decision: ModelDecision) -> Any:
        """Check a terminal proposal's citations, or record the refusal and return why.

        Only a PROPOSE is verified: an ASK_CUSTOMER asks and an ESCALATE hands over, and neither cites anything
        (``docs/agent-spec.md:20``). A refund proposal whose citations do not match what this run actually read stops
        the run instead of becoming its outcome (``docs/agent-harness.md:13``), because a proposal is submitted to
        Java and a citation nobody can check is worse than no proposal.

        The verifier is attached by the run once the observation record exists and, crucially, holds *that same
        list*: a verifier built with a copy would check citations against an empty run.
        """
        if decision.kind != "PROPOSE" or self.verifier is None:
            return None
        result = self.verifier.verify_citations(
            recommended_action=decision.recommended_action or "",
            evidence_refs=[ref.model_dump() for ref in decision.evidence_refs],
            policy_refs=[ref.model_dump() for ref in decision.policy_refs],
            missing_evidence=decision.missing_evidence,
        )
        if result.ok:
            result = self.verifier.verify_content(summary=decision.summary or "",
                        review_findings=[f.model_dump() for f in decision.review_findings],
                        evidence_refs=[ref.model_dump() for ref in decision.evidence_refs])
        if not result.ok:
            self._refuse(result.reason_codes[0], result.detail())
            return result
        return None

    def _refuse(self, reason_code: str, detail: str, *, repairable: bool = True) -> None:
        """Record a refusal, and give the model its one chance to repair it (``docs/agent-spec.md:52``).

        The refusal is recorded either way, so the run's record says what was wrong even when the model fixed it.
        What changes is whether the run **stops**: the first repairable refusal sets :attr:`repair_message` instead
        of :attr:`stop_reason`, and the caller turns that into a turn the SDK will deny — the denial carries this
        text back to the model. Only the *repairable* kinds qualify: a no-progress stop is the loop's own bound, not
        a mistake in the model's output, and ``docs/agent-spec.md:44`` already feeds back its two warnings.
        """
        repairable = repairable and reason_code not in SECURITY_ERRORS
        can_repair = repairable and self.repairs_used < MAX_REPAIRS
        record = feedback(reason_code, detail, repair=can_repair)
        self.refusals.append(record)
        if can_repair:
            self.repairs_used += 1
            message = notice(record)
            # Both channels, one text: the notice is what the *next* request carries in P1 even if the model never
            # reads the denial, and the message is what the SDK feeds back for the call it is about to refuse.
            self.notices.append(message)
            self.repair_message = message
            return
        self.stop_reason = self.stop_reason or reason_code

    def note_tool_result(self, observation: Any) -> None:
        tool = observation.tool_name
        error = observation.error
        if error is None:
            self.tool_failures.pop(tool, None)
            return
        if error.code in SECURITY_ERRORS:
            self._refuse(error.code, "tool read violated the bound permission/source", repairable=False)
            return
        if error.code == "INVALID_CURSOR":
            # The tool already executed and supplied a denial. Give its argument
            # error the same single model-repair allowance without a second probe.
            if self.repairs_used >= MAX_REPAIRS:
                self._refuse(error.code, "cursor correction allowance exhausted", repairable=False)
                return
            self.repairs_used += 1
            record = feedback(error.code, "use the issued cursor or omit it for the first page", repair=True)
            self.refusals.append(record)
            self.notices.append(notice(record))
            return
        if error.retryable:
            self.tool_failures[tool] = self.tool_failures.get(tool, 0) + 1
            if self.tool_failures[tool] >= 2:
                self.blocked_tools.add(tool)
        else:
            self.blocked_tools.add(tool)
        record = feedback(error.code, f"{tool}: failed read is not evidence")
        record["repair_remaining"] = MAX_REPAIRS - self.repairs_used
        if tool in self.blocked_tools:
            record["next_step"] = ('Do not repeat this tool or ask for bound order/line/customer IDs. '
                                   'Use another source or {"kind":"ESCALATE",'
                                   '"reason_codes":["NEEDS_HUMAN_VERIFICATION"]}.')
        self.notices.append(notice(record))

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
        if self.repair_message is not None:
            # The repair turn (C08.1c-2): the model was refused, and the SDK is now trying to execute the very
            # action that was refused — or, for a refused proposal, a probe the caller substituted for it. Denying
            # with the refusal's own text is what puts the reason in the model's conversation as a tool result
            # (`docs/agent-spec.md:52`: fix it once). Nothing executes, and this denial is *not* recorded as a
            # second refusal: the refusal already happened, and recording the echo would make one mistake look like
            # two and set the stop reason that the repair exists to avoid.
            message = self.repair_message
            self.repair_message = None
            return PermissionDecision(behavior=PermissionBehavior.DENY, message=message)
        accepted = self.accepted
        allowed_name = None
        if isinstance(accepted, dict) and accepted.get("kind") == "READ_TOOL":
            allowed_name = accepted.get("tool_name")
        elif isinstance(accepted, dict) and accepted.get("kind") == SEARCH_POLICY:
            # C07.1: `SEARCH_POLICY` is executed through the SDK's tool machinery — that is what makes the SDK's
            # loop perform the action and this gate see it — but it is **not** an MCP tool. The name is fixed
            # rather than taken from the decision: the model chooses the *query*, never which mechanism reads
            # policy (`docs/agent-spec.md:16`).
            allowed_name = POLICY_SEARCH_TOOL_NAME
        elif isinstance(accepted, dict) and accepted.get("kind") == READ_OBSERVATION:
            allowed_name = OBSERVATION_READ_TOOL_NAME

        if name is None or name != allowed_name:
            self.refusals.append(
                {
                    "reason": REASON_ACTION_REFUSED,
                    "detail": f"{name!r} is not the tool the accepted decision named ({allowed_name!r})",
                }
            )
            self.stop_reason = self.stop_reason or REASON_ACTION_REFUSED
            return PermissionDecision(behavior=PermissionBehavior.DENY, message=f"{name!r} was not the accepted action")
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
            if self._client.durability is not None:
                self._client.durability.before_tool(self.name, dict(kwargs), self._guard)
            self._guard.guard.reserve_tool_attempt()
        except BudgetExhaustedError as exhausted:
            self._gate.note_stop(exhausted.reason_code)
            # A refused attempt produced no evidence, and saying so is what keeps the no-progress rule working:
            # without it `pending_repeat` stays set, the third identical refusal is never counted, and the run burns
            # its model-call budget instead of stopping on the refusal (docs/agent-spec.md:44). The local-read
            # bridges were fixed for the same reason; this is the MCP path's copy of it.
            self._gate.note_evidence(False)
            self._adapter.trajectory.append(
                {"action": self.name, "outcome": "REFUSED", "detail": exhausted.reason_code}
            )
            return ToolChunk(
                content=[TextBlock(type="text", text=f"{exhausted.reason_code}: {exhausted}")],
                state=ToolResultState.ERROR,
            )
        except Exception as failure:  # noqa: BLE001 - preserve fenced refusal outside SDK's legacy MCP handler
            code = self._client.durability.capture_error(failure) if self._client.durability is not None else None
            if code is None:
                raise
            self._gate.note_stop(code)
            return ToolChunk(content=[TextBlock(type="text", text=code)], state=ToolResultState.ERROR)
        try:
            # `to_thread` because the project's executor is synchronous by construction (it bridges a private
            # event loop for MCP stdio); calling it inline would block the SDK's loop.
            def invoke() -> Any:
                def read() -> Any:
                    try:
                        return self._executor.call_tool(run_id=self._facts.run_id, tool_name=self.name,
                                                        arguments=dict(kwargs))
                    except (TimeoutError, ConnectionError, ToolCallFailedError) as failure:
                        # Convert only known boundary failures, before journal.save_tool.
                        # Fence/budget/programming errors still propagate and stop the run.
                        from resolveflow.contracts.enums import EvidenceSourceType
                        source = {"get_order_context": EvidenceSourceType.ORDER_LINE,
                                  "get_refund_status": EvidenceSourceType.PAYMENT_LEDGER,
                                  "get_shipment_trace": EvidenceSourceType.SHIPMENT_TRACK,
                                  "get_case_evidence": EvidenceSourceType.CUSTOMER_STATEMENT,
                                  "get_policy_manifest": EvidenceSourceType.POLICY_RULE}[self.name]
                        context = ToolContext(line_id=self._facts.line_id, run_id=self._facts.run_id,
                            case_id=self._facts.case_id,
                            tool_call_id=f"{self._facts.run_id}:tool-{len(self._client.observations)}")
                        retryable = (isinstance(failure, (TimeoutError, ConnectionError))
                                     or getattr(failure, "retryable", False))
                        code = getattr(failure, "code", "TOOL_TRANSIENT")
                        return _failed(self.name, source, f"harness:{self.name}",
                            CoreToolError(code=code, message="read boundary failed; no verified result",
                                          retryable=retryable), context)
                return self._client.durability.transmit(self._executor, read, self._guard) \
                    if self._client.durability is not None else read()

            observation = await anyio.to_thread.run_sync(
                lambda: self._client.durability.observe(self.name, dict(kwargs), invoke, self._guard, local=False)
                if self._client.durability is not None else invoke()
            )
        except Exception as failure:  # noqa: BLE001 - the executor's failure is the run's fact to record
            code = self._client.durability.capture_error(failure) if self._client.durability is not None else None
            self._gate.note_stop(code or REASON_TOOL_FAILED)
            self._gate.note_evidence(False)
            self._adapter.trajectory.append({"action": self.name, "outcome": "FAILED", "detail": str(failure)[:300]})
            return ToolChunk(
                content=[TextBlock(type="text", text=f"TOOL_FAILED: {failure}")],
                state=ToolResultState.ERROR,
            )

        fresh = self._adapter.record_observation(observation)
        self._client.note_observation(observation)
        self._gate.note_evidence(fresh)
        # C08.1: the run learns from **every** observation, not only from the local reads. Before this the facts
        # view and the store were reachable only from `PolicySearchBridge`, so the five MCP tools — which is where
        # the amount, the shipment conclusion and the refund state come from — contributed no facts at all, and a
        # run could not read its own tool evidence back. Both are the run's state, and the run is what records.
        self._client.note_evidence(observation)
        self._gate.note_tool_result(observation)
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

    The constructor shape deliberately matches the C06.4 ``HarnessRunner``, so the tests that assert run
    semantics can run against either driver without rewriting what they claim — which is the only way "the old
    semantics were kept" becomes checkable.
    """

    model: Any
    tools: ToolExecutor
    facts: RunFacts
    budget: RunBudget = field(default_factory=RunBudget)
    system: str = HARNESS_SYSTEM_PROMPT
    max_iters: int | None = None
    #: The run's policy index and the embedder the dense path ranks with (C07.1). Both optional so a run that
    #: never searches policy needs neither, and a run that searches without an index gets the index's own
    #: refusal rather than an ``AttributeError``.
    policy_index: Any = None
    policy_embedder: Any = None
    #: Where ``READ_OBSERVATION`` reads from (C07.2): the text this run has already observed. ``None`` means the
    #: tool is not offered, which is honest — there is nothing to read back.
    observation_store: Any = None
    #: The run's facts view (C08.1). ``None`` means this run builds its own on first use — the store and the view
    #: are the run's state, not a caller's, and a caller that wants to inspect them afterwards passes its own.
    facts_view: Any = None
    #: Whether the model's input is assembled by :class:`~resolveflow.harness.context.ContextBuilder` (P0–P4) or by
    #: the C06.4 evidence packet. **On by default (C08.1a)**: ``docs/context-engineering.md`` is the specification,
    #: so the specification is the path a run takes unless a caller explicitly asks for the older shape.
    #:
    #: The C06.4 blob is kept as an explicit compatibility path rather than deleted, because the two must be
    #: comparable while the migration finishes — but it is no longer what a worker gets by default, and the evidence
    #: it used to carry now travels through the bounded, hashed, counted packet.
    use_context_builder: bool = True
    #: What the provider can take, and what is held back for the answer. ``docs/context-engineering.md:27``'s
    #: minimum subtracts the reserve and the wrapper allowance from the capacity, so these two are the provider
    #: terms of that cap.
    context_provider_capacity: int = DEFAULT_INPUT_CAP
    context_output_reserve: int = DEFAULT_OUTPUT_RESERVE
    #: The client this run built, kept so a caller can report the packet it sent (C08.1). Not part of the run's
    #: semantics: it is the object the loop assembled, and a snapshot needs the packet rather than a way to
    #: recompute it.
    last_client: Any = None
    durability: Any = None
    #: The run's frozen Harness manifest (C08.1b), built on first use and then reused for every step. Memoised
    #: rather than rebuilt per packet because "frozen" is the property that matters: ``docs/agent-harness.md:35``
    #: forbids silently changing the manifest on resume, and a manifest recomputed each step could differ from the
    #: one a snapshot stored without anything noticing.
    frozen_manifest: dict[str, Any] | None = field(default=None, init=False, repr=False)

    def manifest(self) -> dict[str, Any]:
        """The run's frozen manifest (``docs/agent-harness.md:33``), built once."""
        if self.frozen_manifest is None:
            self.frozen_manifest = build_manifest(
                facts=self.facts,
                system_prompt=self.system,
                tool_schema=_tool_schema_document(self),
                budget=self.budget,
                model=model_block_for(self.model, context_window_tokens=self.context_provider_capacity),
                index_generation=self.index_generation(),
            )
        return self.frozen_manifest

    def index_generation(self) -> str:
        """The ``index_generation`` the manifest pins.

        The dispatch pins a policy *set* (``bundle_ids`` + ``manifest_hash``, C07.1); the rows that actually serve
        retrieval carry their own ``generation_id``. When this run has a policy index and the pinned bundle has a
        READY generation at that hash, that real id is what gets pinned — the index a read would have hit.

        When it does not (a run assembled by hand, or one that never searches policy), the fallback is a
        deterministic uuid5 of the pin itself. It is **not** a ``policy_index_generation`` row id and must not be
        looked up as one: it is a stable name for "this pin", so the manifest stays reproducible instead of
        borrowing an id the run never resolved.
        """
        import uuid

        pinned = self.facts.policy_manifest or {}
        bundles = sorted(bundle for bundle in (pinned.get("bundle_ids") or []) if isinstance(bundle, str))
        manifest_hash = pinned.get("manifest_hash")
        if self.policy_index is not None and bundles and isinstance(manifest_hash, str) and manifest_hash:
            generation = self.policy_index.generation_for(bundles[0], manifest_hash)
            if generation is not None:
                return str(generation.generation_id)
        pin_hash = manifest_hash if isinstance(manifest_hash, str) else ""
        identity = f"resolveflow:policy-pin:{','.join(bundles)}:{pin_hash}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))

    def run(self) -> RunResult:
        """Drive one reply to completion and report the outcome.

        The loop is the SDK's; what this does is build it, seed the conversation with the run's facts, and
        translate what happened back into the vocabulary the project records. Nothing here decides an action.
        """
        try:
            return anyio.run(self._drive)
        finally:
            close = getattr(self.durability, "close", None)
            if callable(close):
                close()

    async def _drive(self) -> RunResult:
        if self.durability is not None:
            self.durability.bind(self)
        gate = ActionGateMiddleware()
        # Two-phase construction, because the budget hook and the client each need the other: the hook reserves for
        # the request *the client assembles*, and the client needs the hook's counters for the packet's budget
        # section. The alternative — the hook reaching into the client's private field after the fact — is the same
        # cycle hidden one step later.
        guard = _BudgetHook(self, gate)
        client = _GateAwareClient(self, gate, guard)
        guard.attach_client(client)
        self.last_client = client
        model = AgentScopeModelAdapter(client, system=self.system)
        # C08.1: the run's own facts view and observation store. Created here when the caller did not supply them,
        # so the loop always has somewhere to record what it learned — a bridge with a store but no view would
        # observe without accumulating facts, which is the state C07.2 left behind.
        store = (
            self.observation_store if self.observation_store is not None else ObservationStore(run_id=self.facts.run_id)
        )
        if store.run_id != self.facts.run_id:
            raise ValueError("observation store belongs to another run")
        store.bind_materials(self.facts.review_context or {}, case_id=self.facts.case_id,
                             input_revision=self.facts.input_revision)
        view = self.facts_view if self.facts_view is not None else FactsView()
        client.bind_context(view=view, store=store, guard=guard, system=self.system)
        toolkit = Toolkit()
        for name in sorted(WHITELIST):
            await toolkit.add_tool(McpToolBridge(name, self.tools, self.facts, gate, model, client, guard))
        # C07.1: the sixth entry, and the only one that is not one of the five MCP tools. Registered only when
        # this run was given an index: a run with no policy index cannot search policy, and offering the tool
        # anyway would let the model ask a question the harness would then fail to answer with `TOOL_FAILED`
        # instead of the honest "not ready".
        if self.policy_index is not None:
            await toolkit.add_tool(
                PolicySearchBridge(
                    self.policy_index,
                    self.facts,
                    gate,
                    model,
                    client,
                    guard,
                    embedder=self.policy_embedder,
                )
            )
        # C07.2: the second local read. Registered whenever this run has a store — which, since ``_drive`` creates
        # one above, is every run: ``READ_OBSERVATION`` is a local ability of the harness, not something a caller
        # has to opt into. (An explicit ``observation_store=None`` no longer disables it, and that is deliberate:
        # the tool with an empty store answers an honest ``NOT_FOUND``, while a run that could not read its own
        # evidence back would be missing a documented capability.)
        await toolkit.add_tool(ObservationReadBridge(store, self.facts, gate, model, client, guard))

        agent = Agent(
            name="resolveflow-agent",
            system_prompt=self.system,
            model=model,
            toolkit=toolkit,
            middlewares=[guard, gate],
            react_config=ReActConfig(max_iters=self.max_iters or self.budget.model_calls),
        )

        try:
            await agent.reply(messenger_message(_starting_packet(self, guard)))
        except BudgetExhaustedError as exhausted:
            if self.durability is not None and self.durability.failure is not None:
                raise self.durability.failure from None
            return _outcome(exhausted.reason_code, gate, model, guard, completed=False)
        except OverflowRefusedError as overflow:
            # C08.1: the mandatory layers do not fit, so the run stops with the code the specification names rather
            # than dropping a constraint (`docs/context-engineering.md:27`). It is caught separately from
            # `BudgetExhaustedError` because it is a different fact: the run did not run out of anything, it was
            # asked to send more than a request may carry.
            gate.notices.append("CONTEXT_DIAGNOSTICS=" + canonical_json(overflow.diagnostics))
            gate.note_stop(overflow.reason_code)
            return _outcome(overflow.reason_code, gate, model, guard, completed=False)
        except _ScriptExhausted:
            return _outcome(REASON_COMPLETED, gate, model, guard, completed=True)

        if self.durability is not None and self.durability.failure is not None:
            raise self.durability.failure

        # A recorded stop ends the run. Without the loop's own check the model would be asked again after a budget
        # refusal, and the run would stop on whichever bound happened to fire next.
        if gate.stop_reason is not None:
            return _outcome(gate.stop_reason, gate, model, guard, completed=False)
        return _outcome(REASON_COMPLETED, gate, model, guard, completed=True)


class _ScriptExhausted(Exception):
    """The scripted model has nothing left to say. For a mock that is the end of the run, not a crash."""


class _BudgetHook(MiddlewareBase):
    """`on_model_call`: reserve every request against the run's budget before it goes out."""

    def __init__(self, runner: AgentScopeRunner, gate: ActionGateMiddleware) -> None:
        self._runner = runner
        #: The gate, so a run that has **already stopped** does not reserve another model call. Without this the
        #: hook kept reserving after a refusal, and because it runs *before* the adapter's `decide` — which is what
        #: consults `stop_reason` — the run ended on `BUDGET_MODEL_CALLS` instead of on the refusal that stopped it.
        #: Two tests expecting the refusal's own reason found it; a run that stopped must not be charged for
        #: stopping (`docs/agent-harness.md:45`).
        self._gate = gate
        #: The client, attached by `attach_client` — see `_drive` for why the two are built in two phases.
        self._client: Any = None
        self.guard = BudgetGuard(runner.budget, active_deadline=runner.facts.deadline())
        #: The same gate under a public name, for the same reason ``budget_guard`` is public: the module-level packet
        #: builder has to read what the harness has told the model, and a leading-underscore reach across a module
        #: boundary is how a second path to one field starts. Still one object.
        self.gate = gate
        #: The same guard, under a name the packet builder can reach without a leading-underscore access from a
        #: module-level function. One object, two names, no second counter.
        self.budget_guard = self.guard
        self.output_ceiling = 0

    def attach_client(self, client: Any) -> None:
        """Attach the client the hook builds the packet with. Called once, by `_drive`."""
        self._client = client

    async def on_model_call(self, agent: Any, input_kwargs: dict[str, Any], next_handler: Any) -> Any:
        """Reserve one request, then let it through.

        **``count_tokens`` must not be called from here.** The first version did, to size the reservation from the
        real input, and the SDK's ``ChatModelBase.__call__`` calls ``count_tokens`` *before* ``_call_api`` — so the
        hook ran again for the same request and every request was reserved **twice**. The symptom was a run hitting
        ``BUDGET_OUTPUT_TOKENS`` at half the requests it should have been allowed: a budget that reports the wrong
        bound and spends twice what it says.

        Assemble the actual ModelClient input first, then reserve. Token estimates use
        UTF-8 bytes plus framing, not characters/4. Live provider serialization is C08 work.
        """
        if self._gate is not None and self._gate.stop_reason is not None:
            # The run already stopped, so this request must not be reserved or sent. `BudgetExhaustedError` is how
            # the loop hears "no more calls", and the free-text message names the *real* reason so a reader is not
            # told the budget ran out when what happened was a refusal.
            raise BudgetExhaustedError(
                self._gate.stop_reason,
                f"the run has stopped: {self._gate.stop_reason}",
            )
        # C08.1: when the context builder is on, the packet is built **here**, before the reservation, so the
        # reserved input size and the request the model receives are the same object. The alternative — estimating
        # here and assembling later — would give the ledger and the provider two different numbers for one request,
        # which is what `docs/agent-harness.md:37` asks to avoid. An `OverflowRefusedError` from this call is left
        # to propagate: it is not a budget exhaustion, and it carries the reason code the outcome must report.
        if self._runner.durability is not None:
            self._runner.durability.before_model(agent, self)
        self._client.begin_turn()
        packet = self._client.prepare_packet(input_kwargs.get("messages") or [])
        if packet is not None:
            estimated = int(packet.input_tokens)
        else:
            self._client.legacy_messages = _with_current_packet(
                input_kwargs.get("messages") or [],
                self._runner,
                self,
                self._client.observations,
                self._client.turns,
            )
            estimated = _estimate_input_tokens(
                {"system": self._runner.system, "messages": self._client.legacy_messages}
            )
        # Reserve the ceiling before the call; refund only known unused output afterwards.
        self.output_ceiling = self.guard.reserve_model_request(input_tokens=estimated)
        return await next_handler()


class _GateAwareClient:
    """The harness's `ModelClient`, with every decision passing through the gate first.

    The gate has to see each decision **before** the adapter renders it into blocks, because the rendering is what
    the SDK executes: a decision refused after rendering would already be a tool call. So the client is wrapped,
    not the adapter.
    """

    def __init__(self, runner: AgentScopeRunner, gate: ActionGateMiddleware, guard: Any) -> None:
        self._runner = runner
        self.durability = runner.durability
        self._gate = gate
        #: The run's budget guard, so the packet the model is shown reports the *same* counters the refusals and
        #: the outcome do. Passed in rather than read off the gate: the gate does not own the budget, and giving
        #: it a reference so a packet builder could reach through it would be a second path to one fact.
        self._guard = guard
        #: Every observation this run has made, in order, so the packet can be built from what is *known*
        #: rather than from how the conversation happened to go (`docs/agent-harness.md:22`).
        self.observations: list[Any] = []
        # The gate verifies a proposal's citations (C08.1c), and it must verify them against **this** list — the
        # run's own record — not a copy taken now: the verifier is attached while the run is still learning, so a
        # snapshot would check every citation against an empty run and refuse them all.
        gate.verifier = ProposalVerifier(
            observations=self.observations,
            review_context=runner.facts.review_context,
            case_id=runner.facts.case_id,
            input_revision=runner.facts.input_revision,
            pinned_bundle_ids=frozenset(
                str(bundle) for bundle in (runner.facts.policy_manifest.get("bundle_ids") or [])
            ),
        )
        #: How many turns have been asked for, for the packet's `step`.
        self.turns = 0
        #: The run's structured state (C08.1), bound by `_drive`: the facts view the model is shown and the store
        #: it reads back from. `None` until bound, and never `None` during a real run.
        self._view: Any = None
        self._store: Any = None
        #: This turn's assembled packet and the token count it reported, so the **budget** and the request agree.
        #: The packet is built once per turn — by `prepare_packet`, which the budget hook calls *before* reserving —
        #: and the adapter then sends the same one. Building it twice would give the model one request and the
        #: ledger another, which is the pair this exists to keep together (`docs/agent-harness.md:37`).
        self._packet: Any = None
        self._packet_step: int | None = None
        #: The last packet that was sent, for the outcome to report.
        self.last_packet: Any = None
        self.legacy_messages: list[Msg] = []
        #: The actions the gate **confirmed**, newest last, as P1 history entries (C08.1a-3).
        #:
        #: Under C06.4 the model learned its own actions from the SDK transcript; the formal path sends only the
        #: packet, so this is where they reappear. Bounded by the builder's window rather than by trimming: P1 is a
        #: mandatory layer (`docs/context-engineering.md:18` keeps it, and only P3/P4 are trimmable), so what the run
        #: puts there has to be bounded *by construction* — an untrimmable layer that grows with the run is a run that
        #: ends in ``CONTEXT_REQUIRED_OVERFLOW`` instead of a decision.
        self.confirmed_actions: list[dict[str, str]] = []

    def bind_context(self, *, view: Any, store: Any, guard: Any, system: str) -> None:
        """Attach the run's facts view, observation store and budget guard, before the loop starts."""
        self._view = view
        self._store = store
        self._guard = guard
        self._system = system

    def note_observation(self, observation: Any) -> None:
        """Record one tool observation; the bridge calls this as it produces them."""
        self.observations.append(observation)

    def note_evidence(self, observation: Any) -> None:
        """Turn one observation into facts and make its text readable back (C08.1).

        This is the join C07.2 left open: ``extract_facts`` knows which fields a tool contributes, and
        ``ObservationStore.remember`` is what makes the P4 index's pointers followable. Both are idempotent for a
        repeated observation, so calling this on every observation — including re-reads — is safe and is the point:
        a re-read that returns something new supersedes, and one that returns the same thing adds nothing.
        """
        if self._view is not None:
            extract_facts(self._view, observation)
        if self._store is not None:
            self._store.remember(observation)

    def begin_turn(self) -> int:
        """Start a new model turn and return its number. Called by the budget hook, once per model call.

        The turn counter is moved **here** rather than inside ``prepare_packet``, and that distinction cost two
        debugging rounds: with the increment inside the rebuild branch, the first build latched ``turns=1`` and no
        later call could ever see a different step, so every packet in the run was the opening one and the model was
        never shown a fact it had learned. A turn boundary is what the hook knows and the builder does not.
        """
        self.turns += 1
        return self.turns

    def prepare_packet(self, messages: list[Msg]) -> Any:
        """Build (once per turn) the request :class:`ContextBuilder` says this run may send.

        Called by the budget hook before it reserves, and by the adapter when it renders — so the reserved input
        size and the sent request are the **same object**. Returns ``None`` when the run is not using the context
        builder, which is the C06.4 evidence packet's path.
        """
        if not self._runner.use_context_builder or self._view is None:
            return None
        # One build per turn: the hook runs first for a given turn, so the adapter reuses what it built rather
        # than building a second packet that could differ (the facts view may have changed between the two calls
        # only if an observation arrived, which happens on a later turn).
        if self._packet is None or self._packet_step != self.turns:
            self._packet = self._build_packet()
            self._packet_step = self.turns
            self.last_packet = self._packet
            self._gate.references = self._packet.references
            self._gate.read_ids = self._packet.read_ids
        return self._packet

    def _build_packet(self) -> Any:
        """Assemble this step's request with :class:`ContextBuilder`.

        The builder is constructed **per step** because the cap depends on what the run has already spent: the
        third term of ``docs/context-engineering.md:27``'s minimum is 累计剩余输入, which changes between steps.
        """
        builder = ContextBuilder(
            system_prompt=self._system,
            provider_capacity=self._runner.context_provider_capacity,
            output_reserve=self._runner.context_output_reserve,
            counter=counter_for(self._runner.model),
        )
        budget = self._runner.budget
        spent = self._guard.guard.spend
        return builder.build(
            run_id=self._runner.facts.run_id,
            case_id=self._runner.facts.case_id,
            step=self.turns,
            input_revision=self._runner.facts.input_revision,
            line_id=self._runner.facts.line_id,
            description=self._runner.facts.description,
            review_context=self._runner.facts.review_context,
            manifest_id=self._runner.manifest()["manifest_id"],
            view=self._view,
            observations=self.observations,
            tool_schema=_tool_schema_document(self._runner),
            cumulative_remaining=(None if budget.input_tokens is None
                                  else max(0, budget.input_tokens - spent.input_tokens)),
            history=self.confirmed_actions[-CONFIRMED_ACTION_WINDOW:],
            # What the harness has already told the model — a no-progress round, or a refusal it may repair. P1,
            # so it cannot be trimmed away; see `ContextBuilder.build` for why that matters here.
            notices=list(self._gate.notices),
        )

    def note_confirmed_action(self, decision: Any) -> None:
        """Record one action the gate confirmed, for the next packet's P1 (C08.1a-3).

        Called after ``ActionGateMiddleware.check`` accepts a decision, which is the moment an action becomes a fact
        about the run: an action that was refused is not recorded here, because it never happened.
        """
        self.confirmed_actions.append({"role": "assistant", "content": _confirmed_action_line(decision)})

    def decide(
        self,
        *,
        system: str,
        messages: list[Msg],
        context: dict[str, Any] | None = None,
        sent_context: Any = None,
        max_output_tokens: int | None = None,
    ) -> Any:
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
        if self._runner.use_context_builder and self._view is not None:
            packet = self.prepare_packet(messages)
            # Two inputs, deliberately different (C08.1):
            #  * the **model** is sent the assembled packet's own messages — prose, bounded, hashed — and *not* the
            #    SDK's conversation, because `docs/context-engineering.md:5` requires the final input to be the
            #    assembled one and an appended transcript would be a second, unbounded input nobody measured;
            #  * a **script** is handed the run's structured view, which is where the cursor of a previous page and
            #    the budget position live. Those are facts about the run rather than prose for a provider, and the
            #    C06.4 packet is their existing rendering.
            request = dict(
                system="",  # P0 already carries the system prompt and action schema.
                messages=_messages_of_packet(packet),
                context=_packet_of(self._runner, self._guard, self.observations, self.turns),
                sent_context=packet,
                max_output_tokens=self._guard.output_ceiling,
            )
        else:
            request = dict(
                system=system,
                messages=self.legacy_messages,
                max_output_tokens=self._guard.output_ceiling,
            )
        reply = (
            self._runner.durability.decide(self._runner.model, self._guard, request)
            if self._runner.durability is not None else self._runner.model.decide(**request)
        )
        self._guard.guard.settle_model_output(reply.usage.output_tokens, estimated=reply.usage.estimated)
        if self._runner.durability is not None:
            self._runner.durability.after_model(self._guard)
        decision = self._gate.check(reply.decision)
        if decision is None:
            if self._gate.repair_message is not None:
                # Refused, but repairable once (docs/agent-spec.md:52). The reply is *not* turned into a terminal
                # text: that would end the SDK's loop and spend the one repair on a turn nobody sees. Instead the
                # SDK is handed a call the permission hook denies, so the refusal travels back as a tool result and
                # the loop asks the model again — one counted model call, which is the whole cost of a repair.
                return ModelReply(
                    decision=_repair_probe(reply.decision),
                    usage=reply.usage,
                    mode=reply.mode,
                    model_alias=reply.model_alias,
                )
            # Refused for good: the run stops, and the adapter is given a terminal text so the SDK ends the reply
            # rather than executing anything. The refusal is already recorded on the gate.
            return ModelReply(
                decision={"kind": "ESCALATE", "reason_codes": ["REFUSED"], "summary": "the action was refused"},
                usage=reply.usage,
                mode=reply.mode,
                model_alias=reply.model_alias,
            )
        self.note_confirmed_action(decision)
        return ModelReply(decision=self._gate.accepted or reply.decision, usage=reply.usage,
                          mode=reply.mode, model_alias=reply.model_alias)


def _repair_probe(decision: dict[str, Any]) -> dict[str, Any]:
    """The decision to hand the SDK for a refused action, so the refusal reaches the model as a tool result.

    A refused ``READ_TOOL``/``SEARCH_POLICY``/``READ_OBSERVATION`` already renders as a tool call, so it is passed
    through: the SDK tries to execute exactly what the model asked for, and the permission hook denies it because no
    decision was accepted. (A tool that does not exist at all is caught one step earlier by the SDK's own
    "tool not available" path, which also feeds the error back and continues — both are verified in
    ``agentscope/agent/_agent.py``.)

    A refused **terminal** decision is different: ``ADAPTER`` renders it as a text block, and a turn with no tool
    call ends the SDK's loop — so handing it through would end the run and spend the repair on nothing. It is
    replaced by a read of a whitelisted tool instead, which the gate denies. The probe cannot execute: the five
    bridges accept an empty argument mapping (``required: []``), and execution only happens after the permission
    hook returns ALLOW, which it cannot while no decision has been accepted.
    """
    kind = str(decision.get("kind") or "")
    if kind in _TOOL_CALL_KINDS:
        return dict(decision)
    probe: dict[str, Any] = {"kind": READ_TOOL, "tool_name": sorted(WHITELIST)[0], "arguments": {}}
    return probe


def _confirmed_action_line(decision: Any) -> str:
    """One deterministic line naming an action the gate confirmed, for P1.

    Readable rather than a digest: :func:`~resolveflow.harness.control.action_digest` answers "was this the same
    request as last time", which the no-progress rule needs, while P1 answers "what has this run already done", which
    a reader — a model, or someone reading a stored packet — has to be able to see.

    The model's free text (``reasoning``, ``summary``) is deliberately **excluded**. P1 is untrimmable, so anything
    admitted there must be bounded by construction, and a model's own explanation is neither bounded nor evidence:
    ``docs/context-engineering.md:11`` refuses to let MODEL_INFERENCE become authority through repetition, and
    putting prose in a layer that can never be trimmed is exactly how that would happen by accident.
    """
    parts = [str(getattr(decision, "kind", "") or "")]
    for name in ("tool_name", "observation_id"):
        value = getattr(decision, name, None)
        if value:
            parts.append(str(value))
    arguments = getattr(decision, "arguments", None) or {}
    if isinstance(arguments, dict):
        for key in sorted(arguments):
            value = arguments[key]
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                # Bounded per value: an argument is model-supplied and could otherwise be arbitrarily long, which is
                # the second way an untrimmable layer grows without limit.
                parts.append(f"{key}={str(value)[:MAX_ACTION_ARGUMENT_CHARS]}")
    return " ".join(part for part in parts if part)


def _messages_of_packet(packet: Any) -> list[Msg]:
    """Send only the bounded packet; observations/history must enter through the builder.

    P0 retains its system role. SDK hints and raw tool transcripts are not appended after
    trimming; doing so would bypass both the packet hash and the input reservation.
    """
    return [
        raw_text_message(message["content"], name="harness", role=cast("Any", message["role"]))
        for message in packet.messages
    ]


def _tool_schema_document(runner: AgentScopeRunner) -> dict[str, Any]:
    """The action/tool schema the model is offered, as P0 requires (``docs/context-engineering.md:17``).

    Built from the runner's own configuration rather than from the SDK's tool objects: the SDK's schemas are one
    rendering, and what P0 must carry is *which actions and tools this run makes available*, which is a fact about
    the harness. The local reads appear only when the run can perform them, so the packet cannot advertise a tool
    the gate would refuse.
    """
    tools = {
        "get_order_context": "paid amount/payment/fulfillment",
        "get_shipment_trace": "carrier status/events",
        "get_refund_status": "refund state/amount",
        "get_case_evidence": "customer/reviewer materials",
        "get_policy_manifest": "pinned policy version/index",
    }
    assert tools.keys() == WHITELIST
    document: dict[str, Any] = {
        "tools": tools,
        "wire_format": "输出一个扁平JSON,kind在根部;禁type/action_fields包装;示例非路线/事实,引用用当前P2编号。",
        "reference_format": "run-short-v1",
        "tool_arguments": "{} by default; evidence:kind?; shipment:cursor?,limit?<=20",
        "syntax_examples_only": [
            {"kind": READ_TOOL, "tool_name": "get_order_context", "arguments": {}},
            {"kind": SEARCH_POLICY, "query": "terms", "arguments": {"top_k": 2}},
            {"kind": READ_OBSERVATION, "observation_id": "O1", "arguments": {"offset": 0, "limit": 1000}},
            {"kind": ASK_CUSTOMER, "questions": [
                {"question_id": "q1", "field": "package_photo", "prompt": "..."}],
             "reason_codes": ["NEEDS_EVIDENCE"]},
            {"kind": PROPOSE, "case_type": "LOGISTICS", "recommended_action": "REFUND",
             "reason_codes": ["POLICY_CONDITIONS_MET"], "summary": "...",
             "evidence_refs": ["O1"], "policy_refs": ["P1"]},
            {"kind": ESCALATE, "reason_codes": ["NEEDS_HUMAN_VERIFICATION"]},
        ],
        "bounds": "top_k:1..5;read:material:ID或O#,limit:1..4000字符;ASK<=3;PROPOSE可加missing_evidence。",
        "proposal": {
            "case_type": [member.value for member in CaseType],
            "recommended_action": sorted(RECOMMENDED_ACTIONS),
            "evidence_refs": "[O-number,...] from P2",
            "policy_refs": "[P-number,...] from P2",
            "review_findings": "max8 [{kind:FACT|INFERENCE|CONFLICT,text<=400,observation_ids:1..8 cited O-numbers}]; "
                               "CONFLICT>=2",
            "rule": "REFUND: both refs, no missing_evidence. REJECT: both refs/current facts. "
                    "Material windows cannot be cited.",
        },
    }
    if runner.policy_index is not None:
        document["local_reads"] = [POLICY_SEARCH_TOOL_NAME, OBSERVATION_READ_TOOL_NAME]
    else:
        document["local_reads"] = [OBSERVATION_READ_TOOL_NAME]
    return document


def _starting_packet(runner: AgentScopeRunner, guard: _BudgetHook) -> dict[str, Any]:
    """The run's facts, in the packet shape the harness has used since C06.4."""
    return {
        "run": {
            "run_id": runner.facts.run_id,
            "case_id": runner.facts.case_id,
            "input_revision": runner.facts.input_revision,
            "line_id": runner.facts.line_id,
            "description": runner.facts.description,
            **({"review_context": runner.facts.review_context} if runner.facts.review_context else {}),
        },
        "step": 1,
        "budget": _budget_position(runner, guard),
        "observations": [],
    }


def _estimate_input_tokens(input_kwargs: dict[str, Any]) -> int:
    """A conservative estimate of one request's input, from the serialised messages and tool schemas.

    UTF-8 bytes are a conservative allowance, not the provider tokenizer. Both parts are counted because
    `docs/agent-harness.md:37` requires the count to cover
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
    return estimate_tokens(str(input_kwargs.get("system") or "") + rendered) + PROVIDER_WRAPPER_ALLOWANCE


def _with_current_packet(
    messages: list[Msg],
    runner: AgentScopeRunner,
    guard: _BudgetHook,
    observations: list[Any],
    turn: int,
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
    rebuilt = messenger_message(_packet_of(runner, guard, observations, turn))
    rest = [
        message
        for message in messages
        # Drop the opening packet: the rebuilt one replaces it, and leaving both would show the model two
        # contradictory views of the run.
        if not (message.name == "harness" and message.role == "user")
    ]
    # SDK state mutates Msg objects in later turns. Freeze this request before counting
    # so its saved input cannot acquire later tool blocks or hints after the reservation.
    return [rebuilt, *(message.model_copy(deep=True) for message in rest)]


def _packet_of(runner: AgentScopeRunner, guard: _BudgetHook, observations: list[Any], turn: int) -> dict[str, Any]:
    """The packet for one turn: the run's facts, the budget position, and every observation so far.

    The two counters come from the **guard**, not from the observation list. They used to be derived — "tool
    attempts = len(observations)" and "local reads = 0" — which was correct only while no local read existed;
    once C07.1 added policy search, an observation could be either kind, so counting the list as attempts would
    have reported a search as an external tool call and reported zero local reads no matter how many happened.
    """
    packet = _starting_packet(runner, guard)
    packet["step"] = turn
    packet["budget"] = _budget_position(runner, guard)
    # What the harness has told the model so far. Part of the *packet* rather than an appended SDK message, so the
    # legacy path (which sends this packet as the request) delivers it and the structured view a script reads
    # reports the same thing the model was given.
    packet["notices"] = list(guard.gate.notices)
    packet["observations"] = [observation.model_dump(mode="json") for observation in observations]
    return packet


def _budget_position(runner: AgentScopeRunner, guard: _BudgetHook) -> dict[str, int]:
    """What the model is told about the run's remaining allowance (``docs/agent-harness.md:22``)."""
    spend = guard.guard.spend
    return {
        "tool_attempts_made": spend.tool_attempts,
        "tool_attempts_allowed": runner.budget.tool_attempts,
        "local_reads_made": spend.local_reads,
        "local_reads_allowed": runner.budget.local_reads,
        "no_progress_rounds": spend.no_progress_rounds,
    }


def _outcome(
    reason_code: str,
    gate: ActionGateMiddleware,
    model: AgentScopeModelAdapter,
    guard: _BudgetHook,
    *,
    completed: bool,
) -> RunResult:
    """Translate what the SDK run did into the project's `RunResult`.

    Every counter comes from the guard, because the guard is what *refused* — and a count a refusal was decided
    against has to be the count the outcome reports. ``tool_attempts`` used to be ``len(model.observations)``,
    which was the same number while every observation was an external read; C07.1's policy search is also an
    observation, so deriving it here would report a local index read as an external tool call and would disagree
    with the bound that actually stopped the run (``docs/agent-harness.md:45``).
    """
    spend = RunSpend(
        model_calls=guard.guard.spend.model_calls,
        tool_attempts=guard.guard.spend.tool_attempts,
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
