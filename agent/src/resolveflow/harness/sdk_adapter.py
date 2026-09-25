"""AS02.1: the thin SDK boundary — our `ModelClient` presented as an AgentScope `ChatModelBase`.

`docs/agentscope-migration.md:43` asks for exactly this and warns about the mistake it prevents: *"`ModelClient`可以
增加SDK适配…不得外层先调模型决定动作，再让SDK调模型重新决定一次"*. So there is one model call per step and this
adapter is a **translation**, not a second decision layer: it turns the harness's packet into AgentScope messages,
and the model's answer back into AgentScope blocks. Nothing here decides anything.

**Why the two vocabularies are kept apart rather than unified.** The harness's rule set (`actions.py`) is about
what the *domain* permits, and AgentScope's tool-call blocks are about what the *loop* can invoke. Collapsing them
would either teach the SDK about refund policy or move the ABI into a third-party shape — and the second is how a
framework silently becomes the authority on permissions. So this file translates and nothing more.

**The recorded-response shape.** `ModelClient.decide` returns a decision mapping (the ABI's own form) plus usage
and mode. The adapter renders that mapping as blocks: a `PROPOSE`/`ASK_CUSTOMER`/`ESCALATE` decision becomes a text
block carrying the decision as JSON, and a `READ_TOOL` decision becomes a tool-call block whose `input` is the
arguments. That keeping-the-mapping-intact choice is deliberate: the harness still validates the decision with
`validate_decision`, so a translated-away field would be a check that no longer happens.
"""

from __future__ import annotations

import json
from typing import Any, Literal, cast

from agentscope.message import Msg, TextBlock, ToolCallBlock
from agentscope.model import ChatModelBase, ChatResponse
from agentscope.state import AgentState

from resolveflow.harness.actions import (
    OBSERVATION_READ_TOOL_NAME,
    POLICY_SEARCH_TOOL_NAME,
    PROPOSE,
    READ_OBSERVATION,
    READ_TOOL,
    SEARCH_POLICY,
)
from resolveflow.harness.model import ModelClient, ModelReply, ModelUsage

__all__ = ["AgentScopeModelAdapter", "MessageRole", "messenger_message"]

#: The SDK's role vocabulary, spelled once so a caller cannot pass a role the SDK would refuse. A plain `str`
#: needed a `type: ignore` at the construction site, which is worse than naming the three values.
MessageRole = Literal["user", "assistant", "system"]

#: The decisions that end a run. Kept in step with `actions.TERMINAL_KINDS` by reading that set rather than
#: restating it: a second list is how the two drift and a terminal action starts being sent back as a tool call.
_TERMINAL_KINDS = frozenset({"PROPOSE", "ASK_CUSTOMER", "ESCALATE"})


def messenger_message(
    packet: dict[str, Any], *, name: str = "harness", role: MessageRole = "user"
) -> Msg:
    """The harness's packet as an AgentScope user message.

    The packet goes over as **one JSON text block**, unchanged. Two reasons: the bytes AgentScope sends are then
    literally what the harness recorded as the exact provider input (`docs/agent-harness.md:22`), and a future
    contributor cannot quietly re-shape the packet into prose on the way through.
    """
    return Msg(
        name=name,
        role=role,
        content=[TextBlock(type="text", text=json.dumps(packet, ensure_ascii=False, sort_keys=True))],
    )


class AgentScopeModelAdapter(ChatModelBase):
    """Presents a harness :class:`ModelClient` as an AgentScope chat model.

    One `decide` per `_call_api`, and the count is the point: the harness's budget guard and this adapter both
    count the same calls because there is only one call. If the adapter ever called the client twice (a repair, a
    retry, a "let me re-read that"), the run's ledger and AgentScope's loop would disagree about how many model
    calls happened, and `docs/agent-spec.md:40`'s cap would be enforced against the smaller number.
    """

    def __init__(self, client: ModelClient, *, system: str, model_alias: str = "harness-adapter") -> None:
        from pydantic import BaseModel

        class _NoParameters(BaseModel):
            """AgentScope wants a parameter model; the harness's client owns its own settings."""

        super().__init__(
            # A cast rather than a fake credential: the SDK types this as `CredentialBase` and this adapter has
            # none — it delegates authentication to the harness client it wraps. Inventing an object here would be
            # a credential a later edit could start using.
            credential=cast(Any, None),
            model=model_alias,
            parameters=_NoParameters(),
            stream=False,
            # Zero: `docs/agent-spec.md:40` allows exactly one layer to retry, and that layer is the harness's
            # budget guard. Letting the SDK retry underneath it would turn one reservation into several provider
            # requests — the same finding AS01.1 recorded.
            max_retries=0,
        )
        from agentscope.formatter import DeepSeekChatFormatter

        self.formatter = DeepSeekChatFormatter()
        self._client = client
        self._system = system
        #: Every decision the client produced, in order, so a test can assert one call per step and inspect what
        #: the client was actually asked.
        self.replies: list[ModelReply] = []
        #: The last terminal decision, which is the run's proposal/question/escalation. Recorded here rather than
        #: re-parsed from the conversation, so the runner reports the decision object it validated.
        self.decision: Any = None
        #: The trajectory and the observations the tools produced, in order. The adapter owns them because it is
        #: the only object that sees both the decision and the tool call the SDK made of it.
        self.trajectory: list[dict[str, Any]] = []
        self.observations: list[Any] = []
        self.notices: list[str] = []
        self.modes: list[str] = []
        #: Content hashes already observed, so "new evidence" is decidable (docs/agent-spec.md:44).
        self._seen_hashes: set[str] = set()
        #: Failures already seen, keyed by error code and source. A failure has no content hash, so this is what
        #: makes "the same read failed again" distinguishable from "the read failed differently" (see
        #: `record_observation`).
        self._seen_failures: set[str] = set()

    @property
    def calls(self) -> int:
        """How many times the underlying client was asked. Must equal the loop's number of model turns."""
        return len(self.replies)

    def record_observation(self, observation: Any) -> bool:
        """Keep one tool observation and say whether it is **new evidence**.

        `docs/agent-spec.md:44`'s 无新证据 made decidable. A **failed** observation has no content hash, so hash
        equality cannot decide it — and the first version therefore called every failure new, which meant an
        identical failure repeated forever was treated as progress and the run ended on its model-call budget
        instead of on the no-progress rule. That is the exact failure mode the rule exists for, and it was caught
        by ``test_a_repeated_failing_read_is_not_progress`` once that test ran against this loop.

        So a failure is identified by its **error code and the reference it was reading**: the first time a read
        fails it is new information the model must see, while the same failure from the same source again is not
        new information however many times it is retried. A *different* failure stays new, because "this line is
        not yours" and "the shop is down" are different facts about the world.
        """
        if observation.content_hash is not None:
            fresh = observation.content_hash not in self._seen_hashes
            self._seen_hashes.add(observation.content_hash)
            self.observations.append(observation)
            return fresh
        error = observation.error
        failure_key = f"{getattr(error, 'code', 'UNKNOWN')}@{observation.source_ref}"
        fresh = failure_key not in self._seen_failures
        self._seen_failures.add(failure_key)
        self.observations.append(observation)
        return fresh

    async def _call_api(
        self,
        model_name: str,
        messages: list[Msg],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Ask the harness's client once, and render its answer as AgentScope blocks."""
        # The SDK's messages go through **untouched**: the client protocol speaks AgentScope messages (see
        # `model.py`), so there is no translation here to get wrong and no second rendering of the conversation.
        reply = self._client.decide(system=self._system, messages=list(messages))
        self.replies.append(reply)
        self.modes.append(reply.mode)
        # Settle what the provider actually produced, if the caller wants the cumulative output meter to move.
        # Optional because the adapter must work without a budget (the strict replay has none).
        settle = getattr(self, "note_output", None)
        if callable(settle):
            settle(reply.usage.output_tokens)
        # **One trajectory entry per action**, and for a read the entry belongs to the bridge that executed it,
        # not here. Recording it in both places produced two lines per read (`REQUESTED` then `OBSERVED`), which a
        # test comparing the trajectory against the recorded actions caught immediately. A terminal decision is
        # recorded here because nothing else sees it: it is not executed, so no tool has it.
        kind = reply.decision.get("kind")
        if kind in ("PROPOSE", "ASK_CUSTOMER", "ESCALATE"):
            self.trajectory.append(
                {
                    "action": kind,
                    "outcome": "DECIDED",
                    "detail": reply.decision.get("recommended_action") or kind,
                }
            )
            self.decision = reply.decision
        return _as_chat_response(reply)


def _as_chat_response(reply: ModelReply) -> ChatResponse:
    """A harness decision as AgentScope blocks.

    `READ_TOOL` becomes a tool call, so the *SDK's* loop performs the action and its permission hook sees it — the
    interception point AS01.1 validated. Every terminal decision becomes a text block carrying the decision JSON,
    which ends the loop: AgentScope stops when a turn produces no tool call, and a terminal action is by definition
    not a tool call (`actions.TERMINAL_KINDS`).

    **`SEARCH_POLICY` also becomes a tool call, under a name that is not one of the five** (C07.1). It is a
    local capability (`docs/agent-spec.md:34`), so it does not exist in the MCP tool server — but it has to
    reach the SDK the same way a tool does, because that is what makes the SDK's loop execute it and what puts
    it in front of `ActionGateMiddleware`. Two things follow, and both matter: the input carries the model's
    `query`/`top_k` and **no identity**, and the name is a constant rather than anything the model sent, so a
    decision cannot choose which mechanism reads policy.
    """
    decision = reply.decision
    kind = decision.get("kind")
    if kind == READ_TOOL:
        return ChatResponse(
            content=[
                ToolCallBlock(
                    type="tool_call",
                    id=str(decision.get("tool_call_id") or f"call-{id(reply)}"),
                    name=str(decision.get("tool_name")),
                    input=json.dumps(decision.get("arguments") or {}, ensure_ascii=False),
                )
            ],
            is_last=True,
        )
    if kind == SEARCH_POLICY:
        # Only the model's own two members travel. Re-sending the whole decision would put `reasoning` and
        # whatever else the model emitted into the tool's input, where nothing validates it.
        arguments: dict[str, object] = {"query": decision.get("query")}
        top_k = (decision.get("arguments") or {}).get("top_k")
        if top_k is not None:
            arguments["top_k"] = top_k
        return ChatResponse(
            content=[
                ToolCallBlock(
                    type="tool_call",
                    id=str(decision.get("tool_call_id") or f"call-{id(reply)}"),
                    name=POLICY_SEARCH_TOOL_NAME,
                    input=json.dumps(arguments, ensure_ascii=False),
                )
            ],
            is_last=True,
        )
    if kind == READ_OBSERVATION:
        # The same shape as the policy search, and for the same reason: a local read the SDK's loop performs so the
        # permission gate sees it. `observation_id` is the model's choice (it comes from the P4 index), and
        # `offset`/`limit` are its window — the store, not the model, decides whether that window exists.
        window: dict[str, object] = {"observation_id": decision.get("observation_id")}
        for member in ("offset", "limit"):
            value = (decision.get("arguments") or {}).get(member)
            if value is not None:
                window[member] = value
        return ChatResponse(
            content=[
                ToolCallBlock(
                    type="tool_call",
                    id=str(decision.get("tool_call_id") or f"call-{id(reply)}"),
                    name=OBSERVATION_READ_TOOL_NAME,
                    input=json.dumps(window, ensure_ascii=False),
                )
            ],
            is_last=True,
        )
    if kind == PROPOSE or kind in _TERMINAL_KINDS:
        # The whole decision, as JSON: the harness validates it again after the loop, and a translation that kept
        # only the prose would drop the fields that validation is about.
        return ChatResponse(
            content=[TextBlock(type="text", text=json.dumps(decision, ensure_ascii=False, sort_keys=True))],
            is_last=True,
        )
    # An unknown kind is still rendered rather than dropped: the harness's `validate_decision` is the thing that
    # refuses it, and it can only do that if the decision arrives intact.
    return ChatResponse(
        content=[TextBlock(type="text", text=json.dumps(decision, ensure_ascii=False, sort_keys=True))],
        is_last=True,
    )


def usage_of(reply: ModelReply) -> ModelUsage:
    """The reply's usage, for a caller that wants it without reaching into the adapter's state."""
    return reply.usage


def fresh_state() -> AgentState:
    """A new `AgentState`, so callers do not have to import AgentScope for the common case."""
    return AgentState()
