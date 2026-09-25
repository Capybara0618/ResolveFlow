"""The facts view: what the run knows, where each fact came from, and how trustworthy that source is (C07.2).

``docs/context-engineering.md:9`` fixes the record: 结构化facts视图保存值、来源、source_version/hash 与
FRESH/STALE/CONFLICT/UNVERIFIED. ``:11`` fixes the rule that makes the view worth having: 用户陈述与模型推断**不能
因摘要或重复出现而升级为权威**, and 不同来源冲突**同时保留**.

Three decisions shape this module, and each one is a failure it prevents.

**Authority is a property of the source, not of the fact.** ``SourceAuthority`` is derived from the
observation's ``source_type`` — the same mapping Java uses to decide who may submit which evidence kind
(``EvidenceSourceType.isMachineRead``) — and nothing in this module can raise it. There is deliberately no
"promote" and no "override": a customer statement that five tools repeat is still a customer statement, and the
way a model's guess becomes a fact is a *tool read*, not a summary.

**A newer read supersedes its own source, and the old record stays.** ``FactStatus.STALE`` marks the superseded
row rather than deleting it (``:11`` 新版本替换同源旧事实仍保留原记录). Deleting it would make "the run once
believed X and then learned Y" unanswerable, which is exactly the history a reviewer needs when the two disagree.

**Conflict is a status, not a resolution.** When an ``AUTHORITY`` value and a ``USER_CLAIM`` disagree about the
same key, both facts are kept and both are marked ``CONFLICT`` (``:11`` 不同来源冲突同时保留). This module does
not pick a winner, and that is the point: the choice belongs to the policy and to a human, and a context builder
that silently preferred the authority would hide the disagreement from the model that has to explain it.

**What a fact is allowed to be.** ``(key, value)`` pairs only — no prose. ``docs/context-engineering.md:19``
requires 精确字段及来源，禁止生成式重写, and a fact whose value is a sentence is a summary wearing a
structured name. The prose stays in the observation (``:9`` 原始…Observation持久保留) and is reachable by
``READ_OBSERVATION``; the facts view carries the fields a decision is checked against.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from resolveflow.contracts.canonical import canonical_bytes
from resolveflow.contracts.core_models import ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType

__all__ = [
    "AUTHORITY_SOURCES",
    "CLAIM_SOURCES",
    "MAX_VALUE_LENGTH",
    "Fact",
    "FactStatus",
    "FactsView",
    "SourceAuthority",
    "authority_of",
    "facts_hash",
]

#: Characters that may not appear in a fact key. A key is a field name the builder sorts and groups by, so it
#: has to be one token; anything else is either a typo or an attempt to smuggle a sentence into a field name.
_KEY_PATTERN: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{0,62}$")

#: How long a fact's value may be. Short by construction: a value this long is prose, and prose belongs in the
#: observation. The bound is generous enough for a reference or an ISO instant and short enough that nobody can
#: pass a policy paragraph off as a field.
MAX_VALUE_LENGTH: Final = 200


class SourceAuthority(StrEnum):
    """``docs/context-engineering.md:11``'s three sources, in the order they are trusted.

    The order is the enum's declaration order, but nothing in this codebase compares them by rank: knowing that
    an ``AUTHORITY`` outranks a ``USER_CLAIM`` is what lets a *reader* interpret a conflict, while a comparison
    in code is how "the authority always wins" quietly becomes a rule. The disagreement is surfaced instead.
    """

    AUTHORITY = "AUTHORITY"
    USER_CLAIM = "USER_CLAIM"
    MODEL_INFERENCE = "MODEL_INFERENCE"


class FactStatus(StrEnum):
    """``docs/context-engineering.md:9``'s four freshness states.

    ``CONFLICT`` is a peer of the other three rather than a flag beside them, because a fact in conflict is not
    "fresh with a note": the run cannot use it the way it uses a fresh one, and a model shown a fresh-looking
    fact with a separator flag would reasonably treat it as settled.
    """

    FRESH = "FRESH"
    STALE = "STALE"
    CONFLICT = "CONFLICT"
    UNVERIFIED = "UNVERIFIED"


#: The two sources that are a *person saying something*, not a system of record being read. Spelled once, here,
#: because it is the whole content of the authority mapping below — ``EvidenceSourceType``'s own split
#: (``isMachineRead`` on the Java side) is exactly this question, and a second list of names elsewhere is how the
#: two would drift until a customer statement outranked a payment ledger.
CLAIM_SOURCES: Final[frozenset[EvidenceSourceType]] = frozenset(
    {EvidenceSourceType.CUSTOMER_STATEMENT, EvidenceSourceType.REVIEWER_VERIFICATION}
)

#: Every source the platform reads. Derived rather than listed, so adding an ``EvidenceSourceType`` forces a
#: decision about which side of the authority question it falls on instead of defaulting into silence.
AUTHORITY_SOURCES: Final[frozenset[EvidenceSourceType]] = frozenset(
    source for source in EvidenceSourceType if source not in CLAIM_SOURCES
)


def authority_of(source_type: EvidenceSourceType) -> SourceAuthority:
    """The authority a source carries, and the only place that mapping is written down.

    ``CUSTOMER_STATEMENT`` and ``REVIEWER_VERIFICATION`` are ``USER_CLAIM`` even though one of them is a
    *merchant's* claim: the axis is not "who is important" but "did the platform read this from a system of
    record". A reviewer who checked something by hand is asserting it, and ``docs/domain-model.md:27`` makes that
    a recorded verification rather than an authority read — which is why a reviewer's conclusion cannot silently
    outrank the shipment record it contradicts; the two are kept side by side and the reviewer's is a claim.

    Everything else the five tools return is read from a system of record: the order line, the payment ledger,
    the carrier data, the case's own material, and the immutable policy bundle.
    """
    return SourceAuthority.USER_CLAIM if source_type in CLAIM_SOURCES else SourceAuthority.AUTHORITY


@dataclass(slots=True)
class Fact:
    """One structured value, with everything needed to judge it later.

    ``source_ref``/``source_version``/``content_hash`` travel with the value because a fact without them is an
    assertion: the whole reason the tools return those members (``docs/agent-spec.md:36``) is so a decision can
    point at the bytes it was made from. ``observation_id`` is how the prose behind this value is read back
    (``READ_OBSERVATION``), which is what keeps the value and the原文 in one record rather than two stories.

    **Mutable, and that is the model rather than a shortcut.** A fact's ``status`` and ``note`` are the two
    members that change as the run learns: a newer read of the same source marks its predecessor ``STALE``, and a
    disagreement marks both sides ``CONFLICT``. The first version of this record was frozen and the view replaced
    rows, which meant the object ``note()`` handed back was *not* the one the view went on to update — a caller
    holding the returned fact read ``FRESH`` forever, and a test comparing the returned object to the stored one
    caught it. Identity is what makes the returned handle mean anything, so the record is mutable and the
    mutations happen in place.

    ``value``/``authority``/``source_*`` are still treated as write-once: nothing in the view reassigns them, and
    a superseding read creates a new fact rather than editing the old one's content — which is what
    ``docs/context-engineering.md:11``'s 仍保留原记录 requires.
    """

    key: str
    value: str
    authority: SourceAuthority
    status: FactStatus
    source_ref: str
    source_version: str | None
    content_hash: str | None
    observation_id: str
    #: Monotonic within a view: the order facts were learned, which is what makes "the newer of two same-source
    #: reads" decidable without trusting a timestamp the tool supplied.
    sequence: int
    #: Why this fact is not FRESH. Empty for a fresh one; a reader (and the model) gets the reason rather than
    #: having to infer it from a status code.
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        """The wire/JSON shape, so a snapshot and a packet agree by construction."""
        return {
            "key": self.key,
            "value": self.value,
            "authority": str(self.authority),
            "status": str(self.status),
            "source_ref": self.source_ref,
            "source_version": self.source_version,
            "content_hash": self.content_hash,
            "observation_id": self.observation_id,
            "note": self.note,
        }

    @property
    def is_protected(self) -> bool:
        """Whether losing this fact would change what a decision can be checked against.

        Everything except a ``STALE`` row: a stale fact is history, and history is exactly what裁剪 may drop
        (``docs/context-engineering.md:27`` allows dropping 最旧非关键段). A ``CONFLICT`` is protected because it is
        live — it is one of two answers the run has not chosen between.
        """
        return self.status is not FactStatus.STALE


@dataclass(slots=True)
class FactsView:
    """Every fact the run has learned, keyed by field, with its history and its conflicts.

    Not frozen, because learning is the operation this object exists for. The mutating methods are the only
    writers, and each one is a named statement about what happened to the view ("this read superseded that
    source", "this disagrees with that authority") rather than a setter a caller could use to rewrite history.
    """

    #: Facts in the order they were learned. Kept as a list rather than a dict alone so the sequence survives and
    #: ``facts_hash`` is order-sensitive, which is what makes it a statement about this view.
    facts: list[Fact] = field(default_factory=list)
    _next_sequence: int = 0

    def note(
        self,
        *,
        key: str,
        value: str,
        observation: ToolObservation,
        status: FactStatus | None = None,
        note: str = "",
    ) -> Fact:
        """Record one field from one observation, superseding that source's previous value for the key.

        ``status`` defaults to ``UNVERIFIED`` when the observation carries no ``content_hash``: a read that
        could not be hashed cannot be cited, and a fact the run cannot cite is not one it should treat as fresh
        (``docs/agent-spec.md:52`` requires ref/来源/版本/hash to match). Passing ``FRESH`` for such a read is
        possible but has to be deliberate.
        """
        if not _KEY_PATTERN.match(key):
            raise ValueError(f"{key!r} is not a fact key: fields are single identifiers, not sentences")
        if len(value) > MAX_VALUE_LENGTH:
            raise ValueError(
                f"fact {key!r} carries {len(value)} characters; a value that long is prose, and prose belongs in "
                "the observation (docs/context-engineering.md:19 forbids rewriting prose into fields)"
            )
        resolved = status or (FactStatus.FRESH if observation.content_hash else FactStatus.UNVERIFIED)

        # Supersede the same source's earlier value before appending, so at most one fact per (key, source_ref) is
        # ever non-STALE. Done by marking, never by removing (docs/context-engineering.md:11).
        superseded: list[Fact] = []
        for existing in self.facts:
            if existing.key != key or existing.source_ref != observation.source_ref:
                continue
            if existing.status is FactStatus.STALE:
                continue
            if existing.value == value:
                # The same source saying the same thing again is not a new fact: re-reading a shipment must not
                # grow the view, or "重复出现" would look like accumulating evidence.
                return existing
            superseded.append(existing)
        for existing in superseded:
            existing.status = FactStatus.STALE
            existing.note = f"superseded by a newer read of the same source ({observation.source_ref})"

        fact = Fact(
            key=key,
            value=value,
            authority=authority_of(observation.source_type),
            status=resolved,
            source_ref=observation.source_ref,
            source_version=observation.source_version,
            content_hash=observation.content_hash,
            observation_id=observation.observation_id,
            sequence=self._next_sequence,
            note=note,
        )
        self._next_sequence += 1
        self.facts.append(fact)
        self._mark_conflicts(key)
        return fact

    def _mark_conflicts(self, key: str) -> None:
        """Flag every live fact for ``key`` as ``CONFLICT`` when the live values disagree.

        The rule is about **values**, not about authorities: two authorities disagreeing is as much a conflict as
        an authority and a claim disagreeing, and resolving the first by rank would be the same mistake as
        resolving the second. When the live values agree, the flag is cleared again — a conflict that has been
        resolved *by a read* is no longer a conflict, and leaving it set would make every re-read look contested.
        """
        live = [fact for fact in self.facts if fact.key == key and fact.status is not FactStatus.STALE]
        values = {fact.value for fact in live}
        if len(values) <= 1:
            for fact in live:
                if fact.status is FactStatus.CONFLICT:
                    fact.status = FactStatus.FRESH
                    fact.note = ""
            return
        for fact in live:
            if fact.status is FactStatus.CONFLICT:
                continue
            fact.status = FactStatus.CONFLICT
            fact.note = f"{len(values)} live sources disagree about {key}"

    # ------------------------------------------------------------------ reading

    def live(self, key: str | None = None) -> list[Fact]:
        """Every fact that is not history: what the run currently believes (including its conflicts)."""
        return [
            fact
            for fact in self.facts
            if fact.status is not FactStatus.STALE and (key is None or fact.key == key)
        ]

    def conflicts(self) -> list[Fact]:
        return [fact for fact in self.facts if fact.status is FactStatus.CONFLICT]

    def keys(self) -> list[str]:
        return sorted({fact.key for fact in self.live()})

    def by_authority(self, authority: SourceAuthority) -> list[Fact]:
        return [fact for fact in self.live() if fact.authority is authority]

    def as_list(self) -> list[dict[str, Any]]:
        return [fact.as_dict() for fact in self.facts]


def facts_hash(view: FactsView) -> str:
    """The hash of the **facts that must not be changed by裁剪** (``docs/context-engineering.md:35``).

    Covers value, authority, status and the source's version/hash for every non-stale fact, in sequence order.
    It therefore changes when a fact is learned, superseded, or becomes conflicted — and does **not** change
    when the builder drops a stale row or reorders the packet, which is the property the裁剪 demonstration
    checks: 裁剪前后必保留字段一致.

    It is not a claim that the facts are *correct*. ``docs/context-engineering.md:37`` says so explicitly — the
    hash proves the剪裁 did not alter what is preserved, and nothing about whether the preserved thing is true.
    """
    protected = [
        {
            "key": fact.key,
            "value": fact.value,
            "authority": str(fact.authority),
            "status": str(fact.status),
            "source_ref": fact.source_ref,
            "source_version": fact.source_version,
            "content_hash": fact.content_hash,
            "sequence": fact.sequence,
        }
        for fact in view.facts
        if fact.is_protected
    ]
    return hashlib.sha256(canonical_bytes(protected)).hexdigest()
