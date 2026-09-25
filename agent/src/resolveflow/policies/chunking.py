"""Chunks and the hashes that make a citation checkable by the service that owns it (C07.1).

**The unit is the rule, and it is not split further.** ``docs/policy-rag.md:15`` requires that a rule's
conditions and exceptions stay together — "禁止把例外切掉". A chunker that split on length would happily cut
``例外：本规则不适用于…`` off the rule it qualifies, and the retrieval would then rank the rule highly and hand
the model a citation to a rule saying something the text no longer says. The fixtures at
``fixtures/policies/bundles/`` carry exactly such an exception (``R-LOST-EXC-001``), so a chunker that split
rules would be caught by a test rather than by a refund.

**Why the hash is computed here at all, when Java derives it too.** ``docs/core-contracts.md:56`` fixes the
construction: ``bundle_id``/``chunk_id``/``title``/``text`` under canonical JSON, the same construction the
bundle's own manifest hash uses. This module recomputes it so the index can store what a citation will carry
and so a drift between the two implementations is a red test (``tests/unit/test_policy_hashes.py``) instead of
a citation that Java rejects for a reason nobody can see. It is **not** the authority: the value Java serves
through ``GET /internal/v1/policies/{bundle_id}`` is copied verbatim by the ingestion script, and the two are
compared rather than one being trusted (see :mod:`resolveflow.policies.ingest`).

**Why ``chunk_id`` counts from one.** Storage counts rules from zero and citations count from one
(``c-01``), because the contract's example writes it that way and Java's ``PolicyRule.chunkIdFor`` is the
only place the conversion happens. Reimplementing it with a different base would make every citation from
this index name a chunk Java has never heard of.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from resolveflow.contracts.canonical import content_hash

__all__ = [
    "MAX_RULE_TEXT_LENGTH",
    "Chunk",
    "ChunkingError",
    "chunk_id_for",
    "chunk_of",
    "chunks_of_bundle",
]

#: ``contracts/core/openapi-case.yaml``'s ``PolicyRule.text``: ``maxLength: 4000``. A rule longer than this
#: could not be served by the route this index reads from, so it cannot be ingested either — refusing it here
#: names the rule instead of letting it fail as a contract violation in an unrelated place.
MAX_RULE_TEXT_LENGTH: Final = 4000


class ChunkingError(ValueError):
    """A bundle whose rules cannot be turned into citable chunks."""


@dataclass(frozen=True, slots=True)
class Chunk:
    """One citable policy rule, with everything a citation and a ranked result both need.

    ``embedded_text`` is stored beside ``text`` rather than derived from it at read time: the two being the
    same string is a property of *this* chunker, and a future one that embedded a shortened form would have
    to say so explicitly, because the retrieval would then be ranking something other than what it cites.
    """

    bundle_id: str
    chunk_id: str
    rule_id: str
    position: int
    title: str
    text: str
    content_hash: str

    @property
    def embedded_text(self) -> str:
        """What the dense and lexical paths index. Equal to :attr:`text` by construction."""
        return self.text

    @property
    def citation(self) -> dict[str, str]:
        """The reference members a proposal carries (``docs/policy-rag.md:25``)."""
        return {
            "chunk_id": self.chunk_id,
            "rule_id": self.rule_id,
            "content_hash": self.content_hash,
        }


def chunk_id_for(stored_position: int) -> str:
    """``c-01``, ``c-02``… for a rule at zero-based ``stored_position``, as Java writes it."""
    if stored_position < 0:
        raise ChunkingError("a rule's position is zero-based and cannot be negative")
    return f"c-{stored_position + 1:02d}"


def chunk_of(bundle_id: str, position: int, rule_id: str, title: str, text: str) -> Chunk:
    """One chunk, with the hash Java derives for the same four members.

    The bundle id is part of the hash, so the same wording in two versions of a policy is two different
    citations — which is the point of citing a version at all (``docs/policy-rag.md:25``).
    """
    if not bundle_id or not rule_id or not title or not text:
        raise ChunkingError("a chunk needs a bundle, a rule id, a title and a body")
    if len(text) > MAX_RULE_TEXT_LENGTH:
        raise ChunkingError(
            f"rule {rule_id} of {bundle_id} carries {len(text)} characters of text, over the contract's "
            f"{MAX_RULE_TEXT_LENGTH}; the route this index reads from could not serve it"
        )
    chunk_id = chunk_id_for(position)
    payload: dict[str, Any] = {"bundle_id": bundle_id, "chunk_id": chunk_id, "title": title, "text": text}
    return Chunk(
        bundle_id=bundle_id,
        chunk_id=chunk_id,
        rule_id=rule_id,
        position=position,
        title=title,
        text=text,
        content_hash=content_hash(payload),
    )


def chunks_of_bundle(bundle_id: str, rules: list[dict[str, Any]]) -> tuple[Chunk, ...]:
    """Every rule of one served bundle, in the order Java served them.

    The order is Java's (``policy_rule.position``, which is the source file's), because it is what fixes the
    chunk ids: re-sorting here — by rule id, say — would renumber the chunks and invalidate every citation
    the service would otherwise accept.
    """
    if not rules:
        raise ChunkingError(f"bundle {bundle_id} has no rules; a bundle with no rules decides nothing")
    seen: set[str] = set()
    chunks: list[Chunk] = []
    for position, rule in enumerate(rules):
        try:
            rule_id = rule["rule_id"]
            title = rule["title"]
            text = rule["text"]
        except KeyError as missing:
            raise ChunkingError(f"bundle {bundle_id} rule {position} has no {missing.args[0]}") from missing
        if rule_id in seen:
            raise ChunkingError(f"bundle {bundle_id} names rule {rule_id} twice")
        seen.add(rule_id)
        chunks.append(chunk_of(bundle_id, position, rule_id, title, text))
    return tuple(chunks)
