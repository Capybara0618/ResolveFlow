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
from dataclasses import dataclass, field
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
UNSHIPPED_FACTS_REQUIRED: Final = "UNSHIPPED_FACTS_REQUIRED"
INVESTIGATION_FACTS_REQUIRED: Final = "INVESTIGATION_FACTS_REQUIRED"

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
    review_context: Mapping[str, Any] = field(default_factory=dict)
    case_id: str | None = None
    input_revision: int | None = None

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
        cited = {str(ref.get("observation_id", "")) for ref in evidence_refs}
        latest = {item.source_ref: item for item in self.observations
                  if item.tool_name in ("get_order_context", "get_shipment_trace", "get_refund_status",
                                        "get_case_evidence")}
        successful = [item for item in self.observations if item.observation_id in cited and _is_citable(item)
                      and latest.get(item.source_ref, item).observation_id == item.observation_id]
        orders = [item.result for item in successful
                  if item.tool_name == "get_order_context" and isinstance(item.result, Mapping)]
        unshipped = any(ref.get("rule_id") == "R-UNSHIPPED-001" for ref in policy_refs)
        if unshipped and recommended_action == "REFUND":
            explicit = any(_paid_order(body) and body.get("fulfillment_status") == "NOT_SHIPPED"
                           and _positive_int(body.get("fulfillment_version")) and body.get("fulfillment_version") == 1
                           and body.get("line_refund_state") == "FREE"
                           and _whole_line_available(body) for body in orders)
            # A newly read conflicting/failed trace or occupied refund slot cannot be hidden by citing only order.
            conflicting = any(
                (item.tool_name == "get_shipment_trace"
                 and (not _is_citable(item) or not isinstance(item.result, Mapping)
                      or item.result.get("status") != "NOT_SHIPPED"))
                or (item.tool_name == "get_refund_status"
                    and (not _is_citable(item) or not isinstance(item.result, Mapping)
                         or item.result.get("state") != "FREE"))
                for item in latest.values())
            if not explicit or conflicting:
                refusals.append(CitationRefusal(
                    UNSHIPPED_FACTS_REQUIRED,
                    "未发货退款须引用当前已付款、明确未发货版本及整行可退事实；缺失/未知/冲突或占用需补查或转人工",
                ))
        rules = {ref.get("rule_id") for ref in policy_refs}
        if recommended_action == "REFUND" and rules and rules <= {
            "R-MONEY-001", "R-SIGNED-001", "R-INTRANSIT-001",
        }:
            refusals.append(CitationRefusal(
                INVESTIGATION_FACTS_REQUIRED,
                "资金限制/普通在途/签收争议条款本身不建立退款资格；需检索并引用实际适用的退款条款或转人工",
            ))
        if recommended_action == "REFUND" and rules & {"R-LOST-001", "R-DMG-001"}:
            # A source-kind floor for the existing named policies, not a generated entitlement
            # verdict. Order fulfillment never establishes a carrier conclusion or human check.
            paid = any(_paid_order(body) and body.get("line_refund_state") == "FREE"
                       and _whole_line_available(body) for body in orders)
            bodies = [item.result for item in successful
                      if item.tool_name == "get_shipment_trace" and isinstance(item.result, Mapping)]
            lost = any(body.get("status") == "LOST" and body.get("carrier_conclusion") == "LOST"
                       and not any(event.get("code") in {"SIGNED", "DELIVERED"}
                                   for event in _sequence_of(body.get("events"))) for body in bodies)
            delivered = (any(body.get("fulfillment_status") == "DELIVERED" for body in orders)
                         or any(body.get("status") == "DELIVERED" for body in bodies))
            occupied = any(item.tool_name == "get_refund_status"
                           and (not _is_citable(item) or (item.result or {}).get("state") != "FREE")
                           for item in latest.values())
            conflicting_delivery = ("R-DMG-001" in rules and any(
                item.tool_name == "get_shipment_trace" and (
                    not _is_citable(item) or (item.result or {}).get("status") != "DELIVERED")
                for item in latest.values()))
            confirmed = self._confirmed_material(successful)
            if (not paid or not confirmed or occupied or conflicting_delivery or ("R-LOST-001" in rules and not lost)
                    or ("R-DMG-001" in rules and not delivered)):
                refusals.append(CitationRefusal(
                    INVESTIGATION_FACTS_REQUIRED,
                    "退款须引用当前已付可退订单及get_case_evidence外层核验；丢失另需承运LOST，质量需送达。"
                    "核验须关联本案客户材料并为CONFIRMED；缺口补查或转人工",
                ))
        if recommended_action == "REJECT":
            if not evidence_refs or not policy_refs:
                refusals.append(CitationRefusal(
                    REJECT_CITATION_REQUIRED,
                    "拒绝须引用真实事实及检索过的政策；空材料、无候选或读取失败不足以拒绝，可继续调查或转人工",
                ))
            order = any(body.get("order_status", body.get("status"))
                        and body.get("line_paid_amount") is not None for body in orders)
            shipment = any(item.tool_name == "get_shipment_trace" and isinstance(item.result, Mapping)
                           and item.result.get("status") not in (None, "", "UNKNOWN")
                           and item.result.get("carrier_conclusion") not in (None, "", "UNKNOWN")
                           for item in successful)
            # This narrow positive entitlement never establishes denial of the entire application.
            # Shipment only rules this clause out; another applicable clause or human review is needed.
            sufficient = not unshipped and order and shipment
            if not sufficient or missing_evidence:
                refusals.append(CitationRefusal(
                    REJECT_FACTS_REQUIRED,
                    "未发货条款不适用不能拒绝整个申请；拒绝须有其他适用政策及当前订单/已知物流，未知需补查或转人工",
                ))
        return VerificationResult(refusals=tuple(refusals))

    def _confirmed_material(self, cited: Sequence[ToolObservation]) -> bool:
        """Match the revision snapshot's latest check and target to registered material identities.

        A CONFIRMED word in a model finding, order or unrelated material is insufficient.
        Equal-revision contradictory checks fail closed; this is provenance, not text semantics.
        """
        materials = _sequence_of(self.review_context.get("materials"))
        targets = {m.get("evidence_id"): m for m in materials
                   if m.get("source_type") == "CUSTOMER_STATEMENT"}
        checks = [m for m in materials if m.get("source_type") == "REVIEWER_VERIFICATION"
                  and m.get("reviewed_evidence_id") in targets]
        for item in cited:
            body = item.result
            if (item.tool_name != "get_case_evidence" or not isinstance(body, Mapping)
                    or self.case_id is None or self.input_revision is None
                    or body.get("case_id") != self.case_id or body.get("input_revision") != self.input_revision):
                continue
            registered = {r.get("observation_id"): r for r in _sequence_of(body.get("evidence"))}
            for target_id, target in targets.items():
                related = [m for m in checks if m.get("reviewed_evidence_id") == target_id]
                if not related:
                    continue
                revision = max(m.get("input_revision", 0) for m in related)
                current = [m for m in related if m.get("input_revision") == revision]
                if (revision > self.input_revision
                        or any(m.get("verification_result") != "CONFIRMED" for m in current)):
                    continue
                required = [target, *current]
                if all(m.get("evidence_id") in registered
                       and all(m.get(k) == registered[m["evidence_id"]].get(k)
                               for k in ("source_ref", "source_version", "content_hash")) for m in required):
                    return True
        return False

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
            if (seen is None or not _is_citable(seen)
                    or (seen.tool_name == "read_observation" and (seen.result or {}).get("kind") == "MATERIAL")
                    or observation_id.startswith("material:")):
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


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _paid_order(body: Mapping[str, Any]) -> bool:
    return (body.get("order_status") == "PAID" and bool(body.get("paid_at")) and body.get("currency") == "CNY"
            and _positive_int(body.get("line_paid_amount")) and _positive_int(body.get("payment_version")))


def _whole_line_available(body: Mapping[str, Any]) -> bool:
    values = [body.get(key) for key in ("order_paid_amount", "refunded_amount", "reserved_refund_amount")]
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
        return False
    return values[0] - values[1] - values[2] >= body["line_paid_amount"]


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
