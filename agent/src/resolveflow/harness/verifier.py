"""The proposal verifier: a citation must name bytes this run actually read (``docs/agent-harness.md:13``).

``docs/agent-harness.md:13`` gives this component four checks — Schema、可见引用、hash/版本、缺证检查 — and one
boundary that is built into the return value rather than left to a comment: **Python通过不等于Java批准**. Passing
here says the citations are consistent with the run's own record. It is not an authorization:
``docs/core-contracts.md:74`` has Java re-read the authoritative sources by a fixed ``source_ref`` mapping, and a
hash that checks out says nothing about whether the *facts* are true (``docs/reliability-security.md:34``).

The record the verifier checks against is the run's **observations** — the same objects the context builder renders
P2/P3 from. There is deliberately no parallel citation ledger:

* an evidence citation must match an observation the run made, on ``observation_id``, ``source_ref``,
  ``source_version`` **and** ``content_hash``. The id alone would let a model cite an id it saw paired with bytes it
  invented; the hash alone would let it cite the right bytes under the wrong subject;
* a policy citation must match a rule a ``SEARCH_POLICY`` observation actually returned
  (``docs/policy-rag.md:25``: Python检查是实际返回过的引用). The hits are read out of the observation's own
  ``result``, so "what the model was shown" and "what may be cited" cannot drift;
* the bundle must be one the run is **pinned** to. That is the cross-scope check (``docs/core-scope.md``): a rule
  from another merchant's bundle is well formed and would pass visibility on its own, so it needs its own refusal.

An observation carrying an error has no ``source_version`` and no ``content_hash`` — ``docs/engineering.md:104``
keeps them "一起有或一起无" precisely so a failed read cannot look citable — and this module refuses to treat such a
record as visible evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from resolveflow.contracts._schemaio import CORE_SCHEMA_FILES, validator_bundle
from resolveflow.contracts.core_models import CoreToolError, ToolObservation
from resolveflow.harness.actions import POLICY_SEARCH_TOOL_NAME

__all__ = [
    "CITATION_HASH_MISMATCH",
    "CITATION_NOT_VISIBLE",
    "CROSS_SCOPE_CITATION",
    "MISSING_EVIDENCE_ON_REFUND",
    "PROPOSAL_SCHEMA_REFUSED",
    "REFUND_CITATION_REQUIRED",
    "REJECT_CITATION_REQUIRED",
    "REJECT_FACTS_REQUIRED",
    "CitationRefusal",
    "ProposalVerifier",
    "VerificationResult",
]

#: The citation names an observation or rule the run never saw.
CITATION_NOT_VISIBLE: Final = "CITATION_NOT_VISIBLE"

#: The citation names something the run saw, but pins bytes or a version it did not see.
CITATION_HASH_MISMATCH: Final = "CITATION_HASH_MISMATCH"

#: The citation reaches outside the policy set this run is pinned to.
CROSS_SCOPE_CITATION: Final = "CROSS_SCOPE_CITATION"

#: An actionable proposal with nothing to check it against.
REFUND_CITATION_REQUIRED: Final = "REFUND_CITATION_REQUIRED"

REJECT_CITATION_REQUIRED: Final = "REJECT_CITATION_REQUIRED"
REJECT_FACTS_REQUIRED: Final = "REJECT_FACTS_REQUIRED"

#: A refund that also says it is missing evidence is asking and proposing at once.
MISSING_EVIDENCE_ON_REFUND: Final = "MISSING_EVIDENCE_ON_REFUND"

#: The composed proposal does not satisfy the frozen v2 schema.
PROPOSAL_SCHEMA_REFUSED: Final = "PROPOSAL_SCHEMA_REFUSED"

#: The frozen wire schema for a proposal (``contracts/core/agent-proposal.schema.json``).
PROPOSAL_SCHEMA_ID: Final = "urn:resolveflow:core:agent-proposal:v2"

#: Refund-specific requirements; rejection has its own evidence floor below.
_ACTIONABLE: Final = "REFUND"

#: Stated on every result, because a caller that only reads ``ok`` would otherwise mistake this for approval.
NOT_APPROVAL: Final = (
    "Python-side citation check only: this is not Java's approval, and Java re-reads the sources itself "
    "(docs/agent-harness.md:13, docs/core-contracts.md:74)"
)


@dataclass(frozen=True, slots=True)
class CitationRefusal:
    """One reason a proposal's citations were refused, with a code the outcome can report."""

    reason_code: str
    detail: str


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """The outcome of one verification, carrying its own boundary.

    ``note`` is not decoration: ``docs/agent-harness.md:13`` requires Python's pass **not** to be read as Java's
    approval, and a result object is the only place that statement travels with the answer.
    """

    refusals: tuple[CitationRefusal, ...] = ()
    note: str = NOT_APPROVAL

    @property
    def ok(self) -> bool:
        return not self.refusals

    @property
    def reason_codes(self) -> tuple[str, ...]:
        """The distinct codes, in the order they were found."""
        return tuple(dict.fromkeys(refusal.reason_code for refusal in self.refusals))

    def detail(self) -> str:
        return "; ".join(f"{refusal.reason_code}: {refusal.detail}" for refusal in self.refusals)


@dataclass(slots=True)
class ProposalVerifier:
    """Checks a proposal's citations against the run's own observations.

    ``observations`` is the run's record, in order. ``pinned_bundle_ids`` is the policy set the dispatch pinned
    (``runtime.runs`` refuses a dispatch without one), which is what makes the cross-scope check possible at all.
    """

    observations: Sequence[ToolObservation]
    pinned_bundle_ids: frozenset[str]

    def verify_citations(
        self,
        *,
        recommended_action: str,
        evidence_refs: Sequence[Mapping[str, Any]],
        policy_refs: Sequence[Mapping[str, Any]],
        missing_evidence: Sequence[str] = (),
    ) -> VerificationResult:
        """Check the citations of one proposed action, without needing the composed wire proposal.

        Separate from :meth:`verify_proposal` because the action gate sees the model's decision, which has no
        ``proposal_id``/``case_type`` yet — those are the runtime's to add when the callback is composed. The
        citation rules are the same either way, so they live in one place.
        """
        refusals: list[CitationRefusal] = []

        if recommended_action == _ACTIONABLE:
            if not evidence_refs:
                refusals.append(
                    CitationRefusal(
                        REFUND_CITATION_REQUIRED,
                        "a refund proposal must cite at least one observation this run made",
                    )
                )
            if not policy_refs:
                refusals.append(
                    CitationRefusal(
                        REFUND_CITATION_REQUIRED,
                        "a refund proposal must cite at least one policy rule this run retrieved",
                    )
                )
            if missing_evidence:
                refusals.append(
                    CitationRefusal(
                        MISSING_EVIDENCE_ON_REFUND,
                        "a refund cannot also report missing evidence: ask for it, or propose, not both",
                    )
                )

        refusals.extend(self._check_evidence(evidence_refs))
        refusals.extend(self._check_policy(policy_refs))
        if recommended_action == "REJECT":
            if not evidence_refs or not policy_refs:
                refusals.append(CitationRefusal(
                    REJECT_CITATION_REQUIRED,
                    "拒绝须引用真实事实及检索过的政策；空材料、无候选或读取失败不足以拒绝，可继续调查或转人工",
                ))
            cited = {str(ref.get("observation_id", "")) for ref in evidence_refs}
            successful = [item for item in self.observations if item.observation_id in cited and _is_citable(item)]
            order = any(item.tool_name == "get_order_context" and isinstance(item.result, Mapping)
                        and item.result.get("status") and item.result.get("line_paid_amount") is not None
                        for item in successful)
            shipment = any(item.tool_name == "get_shipment_trace" and isinstance(item.result, Mapping)
                           and item.result.get("status") not in (None, "", "UNKNOWN")
                           and item.result.get("carrier_conclusion") not in (None, "", "UNKNOWN")
                           for item in successful)
            if not order or not shipment or missing_evidence:
                refusals.append(CitationRefusal(
                    REJECT_FACTS_REQUIRED,
                    "拒绝前须读取并引用订单付款和物流事实；NOT_FOUND不代表未发货，未知条件需补查或转人工",
                ))
        return VerificationResult(refusals=tuple(refusals))

    def verify_proposal(self, proposal: Mapping[str, Any]) -> VerificationResult:
        """Check the composed wire proposal: the frozen schema first, then its citations.

        The schema is the **frozen** one rather than a Python re-statement of it, because that document is what
        Java enforces (``contracts/core/agent-proposal.schema.json``): a proposal that only satisfies a laxer local
        shape would be accepted here and refused there, which is the disagreement this check exists to prevent.
        """
        bundle = validator_bundle(PROPOSAL_SCHEMA_ID, CORE_SCHEMA_FILES)
        errors = sorted(bundle.validator.iter_errors(dict(proposal)), key=lambda error: list(error.path))
        if errors:
            return VerificationResult(
                refusals=tuple(
                    CitationRefusal(
                        PROPOSAL_SCHEMA_REFUSED,
                        f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}",
                    )
                    for error in errors
                )
            )

        refusals = list(
            self.verify_citations(
                recommended_action=str(proposal.get("recommended_action", "")),
                evidence_refs=_sequence_of(proposal.get("evidence_refs")),
                policy_refs=_sequence_of(proposal.get("policy_refs")),
                missing_evidence=[str(item) for item in _sequence_of(proposal.get("missing_evidence"))],
            ).refusals
        )
        return VerificationResult(refusals=tuple(refusals))

    def _check_evidence(self, refs: Sequence[Mapping[str, Any]]) -> list[CitationRefusal]:
        visible = {observation.observation_id: observation for observation in self.observations}
        refusals: list[CitationRefusal] = []
        for ref in refs:
            observation_id = str(ref.get("observation_id", ""))
            seen = visible.get(observation_id)
            if seen is None or not _is_citable(seen):
                refusals.append(
                    CitationRefusal(
                        CITATION_NOT_VISIBLE,
                        f"{observation_id!r} is not an observation this run made with readable content",
                    )
                )
                continue
            mismatched = _compare(
                ref,
                {
                    "source_ref": seen.source_ref,
                    "source_version": seen.source_version,
                    "content_hash": seen.content_hash,
                },
            )
            if mismatched:
                refusals.append(
                    CitationRefusal(
                        CITATION_HASH_MISMATCH,
                        f"{observation_id!r} was seen with a different {mismatched}",
                    )
                )
        return refusals

    def _check_policy(self, refs: Sequence[Mapping[str, Any]]) -> list[CitationRefusal]:
        visible = self._visible_rules()
        refusals: list[CitationRefusal] = []
        for ref in refs:
            identity = (str(ref.get("bundle_id", "")), str(ref.get("rule_id", "")), str(ref.get("chunk_id", "")))
            if identity[0] not in self.pinned_bundle_ids:
                refusals.append(
                    CitationRefusal(
                        CROSS_SCOPE_CITATION,
                        f"{identity[0]!r} is outside the policy set this run is pinned to",
                    )
                )
                continue
            seen = visible.get(identity)
            if seen is None:
                refusals.append(
                    CitationRefusal(
                        CITATION_NOT_VISIBLE,
                        f"rule {identity[1]!r} in {identity[0]!r} was not returned by any policy search this run made",
                    )
                )
                continue
            mismatched = _compare(ref, {"version": seen.get("version"), "content_hash": seen.get("content_hash")})
            if mismatched:
                refusals.append(
                    CitationRefusal(
                        CITATION_HASH_MISMATCH,
                        f"rule {identity[1]!r} was retrieved with a different {mismatched}",
                    )
                )
        return refusals

    def _visible_rules(self) -> dict[tuple[str, str, str], Mapping[str, Any]]:
        """Every rule this run was actually shown, keyed by the identity a citation names.

        Read out of the ``SEARCH_POLICY`` observations' own ``result`` rather than from the index: the index today
        may hold a newer generation, and a citation must be checkable against what the model saw
        (``docs/policy-rag.md:25``).
        """
        rules: dict[tuple[str, str, str], Mapping[str, Any]] = {}
        for observation in self.observations:
            if observation.tool_name != POLICY_SEARCH_TOOL_NAME:
                continue
            result = observation.result
            hits = result.get("hits") if isinstance(result, Mapping) else None
            if not isinstance(hits, list):
                continue
            for hit in hits:
                if not isinstance(hit, Mapping):
                    continue
                rules[(str(hit.get("bundle_id", "")), str(hit.get("rule_id", "")), str(hit.get("chunk_id", "")))] = hit
        return rules


def _is_citable(observation: ToolObservation) -> bool:
    """Whether an observation can be cited at all.

    A failed read carries ``error`` and no version/hash (``docs/engineering.md:104``), so it has nothing to cite;
    requiring both is what keeps "the tool answered nothing" from becoming a citation.
    """
    error = observation.error
    if isinstance(error, CoreToolError) or error is not None:
        return False
    return bool(observation.source_version) and bool(observation.content_hash)


def _sequence_of(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _compare(ref: Mapping[str, Any], seen: Mapping[str, Any]) -> str | None:
    """The first member whose cited value differs from what the run saw, if any."""
    for member, actual in seen.items():
        if str(ref.get(member, "")) != str(actual):
            return member
    return None
