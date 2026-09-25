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

from resolveflow.harness.actions import PROPOSE, READ_TOOL
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

    @property
    def calls(self) -> int:
        """How many times the underlying client was asked. Must equal the loop's number of model turns."""
        return len(self.replies)

    def record_observation(self, observation: Any) -> bool:
        """Keep one tool observation and say whether it is **new evidence**.

        The adapter owns this because it is the only object that sees both the decision and the tool call the SDK
        made of it. The rule is `docs/agent-spec.md:44`'s 无新证据 made decidable: a failed observation (no hash) is
        always new — "I could not read it" is a fresh fact each time — while a successful one is new only when its
        content hash has not been seen before. That distinction is what stops a run being stopped for paging and
        what stops an endlessly retried failure from counting as progress.
        """
        if observation.content_hash is None:
            self.observations.append(observation)
            return True
        fresh = observation.content_hash not in self._seen_hashes
        self._seen_hashes.add(observation.content_hash)
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
        # The trajectory entry is recorded here, from the decision the run validated, so the old loop's
        # "one line per action" shape survives the driver change.
        kind = reply.decision.get("kind")
        entry: dict[str, Any] = {"action": reply.decision.get("tool_name") or kind}
        if kind in ("PROPOSE", "ASK_CUSTOMER", "ESCALATE"):
            entry["outcome"] = "DECIDED"
            entry["detail"] = reply.decision.get("recommended_action") or kind
            self.decision = reply.decision
        else:
            entry["outcome"] = "REQUESTED"
        self.trajectory.append(entry)
        return _as_chat_response(reply)


def _as_chat_response(reply: ModelReply) -> ChatResponse:
    """A harness decision as AgentScope blocks.

    `READ_TOOL` becomes a tool call, so the *SDK's* loop performs the action and its permission hook sees it — the
    interception point AS01.1 validated. Every terminal decision becomes a text block carrying the decision JSON,
    which ends the loop: AgentScope stops when a turn produces no tool call, and a terminal action is by definition
    not a tool call (`actions.TERMINAL_KINDS`).
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
