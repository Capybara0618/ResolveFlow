"""``READ_OBSERVATION``: reading an observation's original text back, within this run (C07.2).

``docs/context-engineering.md:31`` states the whole contract in one line:
``READ_OBSERVATION(offset>=0,limit<=4000字符)仅访问当前run及明确允许继承的材料；不存在ref返回NOT_FOUND，不猜内容或跨case
查找。总本地读取<=8次``.

Five properties follow, and each is a decision rather than plumbing:

**The store holds what this run actually read.** It is populated from the observations the loop already made, so a
``source_ref`` in a packet is answerable from the run's own record. This is the layer C07.1 left missing: the facts
view held the *fields*, the packet held the excerpts, and nothing could hand back the text behind either. Without
it ``docs/context-engineering.md:21``'s "按需读回" is a promise with no implementation.

**Only this run, and only what it read.** A reference that exists but was not read by this run is ``NOT_FOUND``,
not "found by searching". Cross-case lookup is refused by construction — the store is per run and has no case
index — and ``docs/core-scope.md``'s "Agent 无跨主体读取权限" is thereby a property of the shape rather than a
check somebody has to remember.

**A missing reference is ``NOT_FOUND``, and nothing is guessed.** ``docs/agent-spec.md:36`` already makes
NOT_FOUND a read that happened rather than a negative fact; here it is also the answer when a model asks for an id
that does not exist. Inventing a nearby observation would make the model's citation point at text it never saw.

**Bounds are refused, not clamped.** An ``offset`` beyond the text, a negative offset, a limit over 4000 — each is
an error naming the bound. Clamping a request for characters 5000-9000 into 4000-5000 would hand back text under a
window the caller did not ask for, and a model that believed it had read the tail would reason from the wrong part.

**The local-read budget is spent here.** ``:31`` counts these against the same 8 the policy search uses, and
C07.1 wired that counter (``budget.reserve_local_read``). A read that is refused for budget is a *stop*, reported
with its own reason code, exactly like the policy search.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from resolveflow.contracts.core_models import ToolObservation

__all__ = [
    "MAX_READ_LIMIT",
    "ObservationNotFoundError",
    "ObservationReadRefusedError",
    "ObservationStore",
    "ObservationWindow",
    "read_observation",
]

#: ``docs/context-engineering.md:31``: limit<=4000 characters. Characters, not tokens: it is the unit the
#: specification states and the unit a reader reasons about when deciding whether they have seen the tail.
MAX_READ_LIMIT: Final = 4000

#: The code an unreadable reference answers with. Same spelling as the wire's own NOT_FOUND, because a model
#: already knows that word and ``docs/agent-spec.md:36`` gives it exactly this meaning for a tool read.
NOT_FOUND: Final = "NOT_FOUND"


class ObservationNotFoundError(LookupError):
    """The reference does not name anything this run read.

    Raised for an unknown id **and** for one this run did not read, with the same code: from the caller's side
    those are the same fact — "there is no such observation for you" — and distinguishing them would tell a model
    which observations exist in other runs, which is the disclosure the per-run store exists to prevent.
    """

    code = NOT_FOUND

    def __init__(self, message: str, *, observation_id: str) -> None:
        super().__init__(message)
        self.observation_id = observation_id


class ObservationReadRefusedError(ValueError):
    """The window or the limit is outside what ``docs/context-engineering.md:31`` allows.

    A refusal rather than a clamp: a clamped read would return text under a window the caller did not ask for, and
    a model that believed it had read the tail would reason from the wrong characters.
    """

    def __init__(self, message: str, *, code: str = "INVALID_WINDOW") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ObservationWindow:
    """One page of an observation's text, with everything a reader needs to ask for the next one.

    ``total_length`` and ``next_offset`` are in the result because a model paging through a long trace otherwise
    has to guess when it is done — and a guess is how "I read the whole thing" becomes a claim the record cannot
    support.
    """

    observation_id: str
    source_ref: str
    text: str
    offset: int
    limit: int
    total_length: int
    citation: dict[str, str] = field(default_factory=dict)

    @property
    def next_offset(self) -> int | None:
        end = self.offset + len(self.text)
        return end if end < self.total_length else None

    def as_result(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "source_ref": self.source_ref,
            "offset": self.offset,
            "limit": self.limit,
            "total_length": self.total_length,
            "returned": len(self.text),
            "next_offset": self.next_offset,
            "text": self.text,
            "citation": self.citation,
        }


@dataclass(slots=True)
class ObservationStore:
    """The text this run has read, keyed by observation id. **Per run**, deliberately.

    There is no case index and no cross-run lookup, so ``docs/context-engineering.md:31``'s 仅访问当前run is a
    property of the object rather than a rule a caller has to apply. The store is filled by the loop as
    observations arrive; a store handed another run's observations would be the bug the shape prevents.
    """

    run_id: str
    #: id → the observation as it was read. The whole observation, not just the text, because the window has to
    #: report the ``source_ref`` a citation will quote.
    _by_id: dict[str, ToolObservation] = field(default_factory=dict)

    def remember(self, observation: ToolObservation) -> None:
        """Keep one observation. Re-remembering the same id **replaces** it with the same object's content.

        Not "first wins" here, unlike the context builder's dedup: this store is the run's record of what it read,
        and if the same id arrives twice with different content then the loop has a bug worth seeing — the caller
        that filled it decides. What matters is that a read can only ever return what was stored, never anything
        composed at read time.
        """
        self._by_id[observation.observation_id] = observation

    def __contains__(self, observation_id: object) -> bool:
        return observation_id in self._by_id

    def ids(self) -> list[str]:
        """The ids this run can read, in insertion order — what the model may ask for."""
        return list(self._by_id)

    def read(self, observation_id: str, *, offset: int = 0, limit: int = MAX_READ_LIMIT) -> ObservationWindow:
        """One window of one observation's text, or a refusal naming the bound.

        The text returned is the observation's own rendering (``_readable_text``), which is the same string the
        packet's P3 excerpt is cut from — so what the model reads back is the evidence the packet pointed at, and
        not a second rendering that could differ from it.
        """
        if offset < 0:
            raise ObservationReadRefusedError(f"offset must be >= 0, got {offset}")
        if limit < 1 or limit > MAX_READ_LIMIT:
            raise ObservationReadRefusedError(
                f"limit must be 1..{MAX_READ_LIMIT} characters, got {limit} (docs/context-engineering.md:31)"
            )
        observation = self._by_id.get(observation_id)
        if observation is None:
            raise ObservationNotFoundError(
                f"{observation_id!r} is not an observation this run read; there is nothing to read back and "
                "nothing is guessed from a similar id or another case",
                observation_id=observation_id,
            )
        text = _readable_text(observation)
        if offset > len(text):
            raise ObservationReadRefusedError(
                f"offset {offset} is past the end of {observation_id} ({len(text)} characters)"
            )
        window = text[offset : offset + limit]
        return ObservationWindow(
            observation_id=observation_id,
            source_ref=observation.source_ref,
            text=window,
            offset=offset,
            limit=limit,
            total_length=len(text),
            citation={"observation_id": observation.observation_id, "source_ref": observation.source_ref,
                      **({"source_version": observation.source_version, "content_hash": observation.content_hash}
                         if observation.error is None and observation.source_version and observation.content_hash else {})},
        )


def _readable_text(observation: ToolObservation) -> str:
    """The text of one observation, from the **one** function that produces it.

    Delegates to :func:`resolveflow.harness.context.observation_text` rather than re-rendering. The packet's P3
    excerpt is cut from that same string, so a model comparing a read-back window with the excerpt it was shown is
    looking at one rendering of one read; two implementations that agreed by convention would eventually not.
    """
    from resolveflow.harness.context import observation_text

    return observation_text(observation)


def read_observation(
    store: ObservationStore,
    *,
    observation_id: str,
    offset: int = 0,
    limit: int = MAX_READ_LIMIT,
) -> ObservationWindow:
    """``READ_OBSERVATION`` as a function, so the rule is testable without the loop.

    The budget is **not** spent here: the store answers questions about text, while which budget a read charges is
    the loop's business (``PolicySearchBridge`` does the same split). Keeping them apart is what lets this be
    tested for its own properties and the loop tested for the counter.
    """
    return store.read(observation_id, offset=offset, limit=limit)
