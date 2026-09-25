"""The model boundary: what a decision call looks like, and a scripted stand-in (C06.4①).

``docs/agent-harness.md:14`` pairs ``RunStore/ModelClient`` as one responsibility: 调用/上下文记录、checkpoint/fence、
mock/live, and the acceptance criterion for the pair is 复用已落库结果，UNKNOWN成本可见. This slice delivers the
``ModelClient`` side only — a narrow protocol, a scripted implementation, and the accounting that makes
"mock/live记录分开" (``docs/agent-spec.md`` acceptance) expressible rather than implied. The persisted
checkpoint half is C09.

**Why the interface is a packet and a reply rather than a prompt string.** ``docs/agent-harness.md:22`` requires
the *exact provider input* to be saved, without credentials, and hashed. A ``decide(prompt: str)`` signature
makes the harness responsible for rendering, so two harness steps could render two different prompts and the
saved hash would describe neither. Here the harness hands over a structured packet, the client renders it, and
the reply says which provider answered — so the record can state the packet, the rendering, and the provider
separately, which is what makes a mock result distinguishable from a live one after the fact.

**Why the scripted client refuses to invent.** :class:`MockModelClient` raises when its script runs out instead
of returning a default. A mock that always answered something would turn "the harness looped one time too
many" into a passing test, because the extra call would get a plausible answer and the run would end normally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

if TYPE_CHECKING:
    # Imported for typing only: the client protocol speaks AgentScope messages, and importing the SDK at module
    # scope would make `harness.model` unimportable without it — including from tools that never touch a model.
    from agentscope.message import Msg as Message

__all__ = [
    "MODEL_MODE_LIVE",
    "MODEL_MODE_MOCK",
    "ModelClient",
    "ModelReply",
    "ModelUsage",
    "MockModelClient",
]

#: How a decision was produced. ``docs/core-scope.md`` requires mock and live results to stay distinguishable,
#: so every reply carries it and a record built from the reply cannot lose the distinction by omission.
MODEL_MODE_MOCK: Final = "mock"
MODEL_MODE_LIVE: Final = "live"


@dataclass(frozen=True, slots=True)
class ModelUsage:
    """Token accounting for one call.

    ``estimated`` exists because ``docs/agent-spec.md:44`` allows a run to continue without exact provider
    counts but requires it to be marked: 缺provider准确计数时标ESTIMATED. A usage that claims precision it does
    not have is how a budget stops being a budget.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    estimated: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class ModelReply:
    """One answer from a model client: the decision, what it cost, and who produced it.

    ``decision`` stays a plain mapping until :func:`~resolveflow.harness.actions.validate_decision` has seen it,
    deliberately. Parsing it here would put the ABI's policy inside the model client, and a client that
    pre-validated would make the run's own refusal path unreachable — the refusals would happen at a layer whose
    job is transport.
    """

    decision: dict[str, Any]
    usage: ModelUsage = field(default_factory=ModelUsage)
    mode: str = MODEL_MODE_MOCK
    #: The provider's own name for what answered (a model alias). ``docs/agent-harness.md:35`` requires a
    #: drifting alias to be recorded as a limitation rather than assumed reproducible.
    model_alias: str | None = None


@runtime_checkable
class ModelClient(Protocol):
    """A decision call. One method, so a live client and a script are interchangeable by construction.

    ``messages`` are provider-agnostic turns (``role``/``content``); the client renders them for whatever
    provider it speaks to. The first message is always the harness's JSON packet, which is what
    ``docs/agent-harness.md:22`` saves as the exact input.

    ``context`` is the second input, and it is separate from ``messages`` because the two answer different
    questions (C08.1): ``messages`` is *what to send to a provider* — prose, bounded, hashed — while ``context`` is
    the run's own structured view (observations, budget, step) which a **scripted** client reads to decide what to
    do next. A script needs the cursor a previous page answered with, and it is not in the rendered prose; a
    provider must not receive a second copy of the same facts in a different shape. ``None`` means the caller has
    no structured view to offer.

    ``sent_context`` is the rendered context packet itself, when the caller assembled one. It is passed for the
    same reason ``context`` is: the two are genuinely different objects, and a caller that conflated them would
    either send a provider the run's internal bookkeeping or leave a script without the cursor it needs.
    """

    def decide(
        self,
        *,
        system: str,
        messages: list[Message],
        context: dict[str, Any] | None = None,
        sent_context: Any = None,
    ) -> ModelReply: ...


@dataclass(slots=True)
class MockModelClient:
    """A model whose decisions are written down in advance.

    ``packets`` keeps every packet it was handed, parsed back out of the *last* message, so a test can assert
    what the *next* action was based on — the mechanism ``docs/agent-harness.md:9`` asks to be proven. Keeping
    the packets is the whole point of the mock: without them a test can only assert the run's ending, which a
    harness that ignored its observations would also produce.

    **A script entry may be a callable**, and that exists for one honest reason: continuing a page needs the
    cursor the previous page answered with, and a cursor is opaque and issued per call
    (``docs/agent-spec.md:29``, ``tools/catalog.py``). A fixed script would have to invent one, and an invented
    cursor is refused — which is the rule working, not a test limitation. A callable is handed the packet the
    model is being given, so the script can continue the run's real cursor without the mock knowing what a cursor
    is. It is still a script: nothing is decided by a model.
    """

    script: list[Any] = field(default_factory=list)
    usage: ModelUsage = field(default_factory=ModelUsage)
    mode: str = MODEL_MODE_MOCK
    model_alias: str | None = "mock-scripted"
    #: Every packet handed to :meth:`decide`, in order, parsed from the last message.
    packets: list[dict[str, Any]] = field(default_factory=list)
    #: Every **structured context** handed to :meth:`decide`, in order (C08.1). Separate from ``packets`` because
    #: the two are different inputs: ``packets`` is what a test parses out of the rendered messages, while this is
    #: the run's own view (observations, budget, step) that a *script* reads to choose its next action. A test that
    #: wants to know what the model was *shown* reads ``conversations``; one that wants the view a script decided
    #: from reads this.
    contexts: list[dict[str, Any] | None] = field(default_factory=list)
    #: The **rendered context packet** handed to :meth:`decide`, in order — the prose request the model received
    #: when the context builder is on, and ``None`` when it is not. This is what "the model's input is a P0–P4
    #: packet" is asserted against.
    sent_contexts: list[Any] = field(default_factory=list)
    #: Every message list handed to :meth:`decide`, in order, for a test that needs the raw turns. AgentScope
    #: messages, because the SDK owns the conversation once the loop is its own (AS02).
    conversations: list[list[Message]] = field(default_factory=list)
    #: How many decisions were asked for. Equal to ``len(packets)``; kept separate so a test can state which
    #: one it means.
    calls: int = 0
    #: Whether the last decision repeats once the script is spent. ``False`` by default so a test that
    #: mis-scripts its model gets a loud failure rather than an endlessly patient loop.
    repeat_last: bool = False

    @classmethod
    def always(cls, *decisions: Any) -> MockModelClient:
        """A client that answers with ``decisions`` in order and then **repeats the last one forever**.

        Repeating is what makes the budget tests meaningful: the run has to be ended by a bound of the harness,
        so the model must not be the thing that stops it. A script that ran out would end the run with a
        script-exhausted error, which would prove nothing about the budget.
        """
        if not decisions:
            raise ValueError("a scripted model needs at least one decision")
        return cls(script=list(decisions), repeat_last=True)

    def decide(
        self,
        *,
        system: str,
        messages: list[Message],
        context: dict[str, Any] | None = None,
        sent_context: Any = None,
    ) -> ModelReply:
        self.calls += 1
        self.conversations.append(messages)
        self.contexts.append(context)
        self.sent_contexts.append(sent_context)
        # The system prompt is recorded **with** the conversation rather than beside it: the packet a test reads
        # back is then the whole input the client was given, and a script that wanted to answer differently for a
        # different system prompt can see it. AS02's adapter passes the loop's own prompt through, so this is the
        # same string the SDK sent.
        #
        # The packet a **script** is handed is the structured view when the caller offered one, and otherwise the
        # mapping parsed out of the messages. That order is deliberate: a continuation script needs the cursor a
        # previous page answered with, and the rendered prose does not carry it.
        packet = context if context is not None else _packet_of(messages)
        if system:
            packet = {"system": system, **packet}
        self.packets.append(packet)
        if not self.script:
            raise AssertionError("the scripted model was asked to decide but its script is empty")
        if self.calls <= len(self.script):
            entry = self.script[self.calls - 1]
        elif self.repeat_last:
            entry = self.script[-1]
        else:
            raise AssertionError(
                f"the scripted model holds {len(self.script)} decisions but was asked for {self.calls}; "
                "a mock that invented one would let a harness bug look like a passing run"
            )
        # A callable entry is a script step that may read the packet — see the class docstring for why that is
        # not the same as letting a model decide.
        decision = entry(packet) if callable(entry) else entry
        if not isinstance(decision, dict):
            raise AssertionError(f"a scripted entry produced {type(decision).__name__}, not a decision mapping")
        return ModelReply(decision=dict(decision), usage=self.usage, mode=self.mode, model_alias=self.model_alias)


def _packet_of(messages: list[Message]) -> dict[str, Any]:
    """The harness's packet, read back out of the last message **for this turn**.

    The last one, not the first: the harness rebuilds the packet every turn and appends it, so ``messages[0]`` is
    only ever the *first* turn's packet — reading index zero made every recorded packet a copy of the opening one,
    which a test asserting "the observation reached the second call" caught immediately.

    The packet travels as one JSON text block because that is literally the text a provider receives, so this is a
    decode rather than a second channel. Messages may carry other blocks (AgentScope injects hints and tool
    results), which is why the *text* blocks are searched rather than assuming the packet is the only content.
    """
    import json

    from agentscope.message import TextBlock

    # An empty conversation is recorded as an empty packet rather than raising: the adapter's job is to forward
    # whatever the SDK built, and a caller driving the SDK directly has no harness packet to send. Raising here
    # would make the adapter unusable outside the harness loop, which AS02.2 does not want.
    if not messages:
        return {}
    # Only **user** turns are searched. AgentScope appends its own assistant turns, and it injects runtime-state
    # hints as extra assistant/system messages (`HintBlock`); scanning every message found one of those first and
    # reported "no message carries the packet" for a conversation that plainly did.
    for message in reversed(messages):
        if message.role != "user":
            continue
        for block in message.get_content_blocks():
            if not isinstance(block, TextBlock):
                continue
            try:
                packet = json.loads(block.text)
            except ValueError:
                continue
            if isinstance(packet, dict) and "run" in packet:
                return packet
    return {}