"""The proposal verifier: citations must name bytes *this run actually read* (C08.1c).

``docs/agent-harness.md:13`` gives ``ProposalVerifier`` four checks — Schema、可见引用、hash/版本、缺证检查 — and one
boundary that the tests state as an assertion rather than a comment: **Python通过不等于Java批准**. Passing here
means the citations are internally consistent with what the run saw; it is not an authorization, and Java re-reads
the sources itself (``docs/core-contracts.md:74``).

Everything the verifier checks is derived from the run's own observations, so there is no second record that could
drift from what the model was shown: an evidence citation has to match an observation the run made, and a policy
citation has to match a rule a ``SEARCH_POLICY`` observation actually returned.
"""

from __future__ import annotations

import pytest

from resolveflow.contracts.core_models import CoreToolError, ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.harness.actions import ActionRefusedError, validate_decision
from resolveflow.harness.local_reads import POLICY_SEARCH_TOOL_NAME
from resolveflow.harness.verifier import (
    CITATION_HASH_MISMATCH,
    CITATION_NOT_VISIBLE,
    CROSS_SCOPE_CITATION,
    MISSING_EVIDENCE_ON_REFUND,
    PROPOSAL_SCHEMA_REFUSED,
    ProposalVerifier,
    VerificationResult,
)

RUN = "11111111-1111-4111-8111-111111111111"
CASE = "22222222-2222-4222-8222-222222222222"
BUNDLE = "policy-logistics-2026.09"
VERSION = "2026.09.1"
RULE_HASH = "d" * 64
OBSERVATION_HASH = "a" * 64

EVIDENCE = {
    "observation_id": "obs-get_shipment_trace",
    "source_ref": "order:get_shipment_trace",
    "source_version": "3",
    "content_hash": OBSERVATION_HASH,
}
POLICY = {
    "bundle_id": BUNDLE,
    "version": VERSION,
    "rule_id": "rule-lost-refund",
    "chunk_id": "chunk-1",
    "content_hash": RULE_HASH,
}

RULE = {
    "bundle_id": BUNDLE,
    "version": VERSION,
    "rule_id": "rule-lost-refund",
    "chunk_id": "chunk-1",
    "content_hash": RULE_HASH,
    "title": "物流确认丢失可退款",
    "text": "承运商判定丢失时允许全额退款",
    "score": 0.87,
    "source_ref": f"policy:{BUNDLE}",
}


def observation() -> ToolObservation:
    return ToolObservation(
        observation_id="obs-get_shipment_trace",
        tool_name="get_shipment_trace",
        source_type=EvidenceSourceType.ORDER_LINE,
        source_ref="order:get_shipment_trace",
        source_version="3",
        content_hash=OBSERVATION_HASH,
        observed_at="2026-09-26T10:00:00Z",
        result={"conclusion": "LOST"},
    )


def search(*rules: dict[str, object]) -> ToolObservation:
    return ToolObservation(
        observation_id="policy-search-abc",
        tool_name=POLICY_SEARCH_TOOL_NAME,
        source_type=EvidenceSourceType.POLICY_RULE,
        source_ref=f"policy:{BUNDLE}",
        source_version=f"{BUNDLE}@bbbbbbbbbbbbbbbb",
        content_hash="c" * 64,
        observed_at="2026-09-26T10:00:01Z",
        result={"query": "丢失 退款", "hit_count": len(rules), "hits": list(rules)},
    )


def verifier(*observations: ToolObservation, pinned: frozenset[str] = frozenset({BUNDLE})) -> ProposalVerifier:
    return ProposalVerifier(observations=list(observations) or [observation(), search(RULE)], pinned_bundle_ids=pinned)


def refund(**overrides: object) -> VerificationResult:
    arguments: dict[str, object] = {
        "recommended_action": "REFUND",
        "evidence_refs": [dict(EVIDENCE)],
        "policy_refs": [dict(POLICY)],
        "missing_evidence": [],
    }
    arguments.update(overrides)
    return verifier().verify_citations(**arguments)  # type: ignore[arg-type]


def proposal(**overrides: object) -> dict[str, object]:
    members: dict[str, object] = {
        "schema_version": 2,
        "proposal_id": "33333333-3333-4333-8333-333333333333",
        "run_id": RUN,
        "case_id": CASE,
        "input_revision": 1,
        "case_type": "LOGISTICS",
        "recommended_action": "REFUND",
        "summary": "承运商判定丢失",
        "reason_codes": ["LOST_CONFIRMED"],
        "evidence_refs": [dict(EVIDENCE)],
        "policy_refs": [dict(POLICY)],
    }
    members.update(overrides)
    return members


def test_a_citation_the_run_actually_read_passes() -> None:
    """The happy path, stated so the refusals below are known to be about one thing each."""
    result = refund()

    assert result.ok is True
    assert result.refusals == ()


def test_passing_is_not_java_s_approval() -> None:
    """``docs/agent-harness.md:13``: Python通过不等于Java批准 — carried in the result, not just in prose."""
    result = refund()

    assert result.ok is True
    assert "Java" in result.note
    assert "approval" in result.note or "批准" in result.note


def test_an_observation_the_run_never_made_is_refused() -> None:
    """A citation to an observation id the run never produced is the fabricated-reference case."""
    result = refund(evidence_refs=[{**EVIDENCE, "observation_id": "obs-invented"}])

    assert result.reason_codes == (CITATION_NOT_VISIBLE,)


def test_a_hash_the_run_did_not_see_is_refused() -> None:
    """The id is real but the bytes are not: citing a hash nobody observed is a tampered reference."""
    result = refund(evidence_refs=[{**EVIDENCE, "content_hash": "f" * 64}])

    assert result.reason_codes == (CITATION_HASH_MISMATCH,)


def test_a_version_the_run_did_not_see_is_refused() -> None:
    """Same for the version: only the hash would not catch a stale or future version."""
    result = refund(evidence_refs=[{**EVIDENCE, "source_version": "9"}])

    assert result.reason_codes == (CITATION_HASH_MISMATCH,)


def test_a_policy_rule_the_run_never_saw_is_refused() -> None:
    """``docs/policy-rag.md:25``: Python检查是实际返回过的引用."""
    result = refund(policy_refs=[{**POLICY, "rule_id": "rule-invented"}])

    assert result.reason_codes == (CITATION_NOT_VISIBLE,)


def test_a_policy_rule_from_a_bundle_the_run_is_not_pinned_to_is_cross_scope() -> None:
    """``docs/core-scope.md``: no cross-subject reads; a citation may not leave the pinned bundle set.

    The rule is otherwise well formed and would pass a visibility check on its own, which is why the scope check
    has to be its own refusal rather than folded into "not visible".
    """
    other = {**POLICY, "bundle_id": "policy-other-merchant-2026.09"}

    result = refund(policy_refs=[other])

    assert result.reason_codes == (CROSS_SCOPE_CITATION,)


def test_a_refund_without_citations_is_refused() -> None:
    """The frozen schema's own rule, reported with a code that says which rule it was."""
    result = refund(evidence_refs=[], policy_refs=[])

    assert REFUND_SCHEMA_OR_CITATION in result.reason_codes


def test_a_refund_that_asks_for_more_evidence_is_refused() -> None:
    """``missing_evidence`` and a refund are contradictory: ask, or propose, not both."""
    result = refund(missing_evidence=["承运商签收证明"])

    assert MISSING_EVIDENCE_ON_REFUND in result.reason_codes


def test_a_whole_proposal_is_checked_against_the_frozen_schema() -> None:
    """``docs/agent-harness.md:13``'s first check: the wire shape, validated against the frozen v2 schema."""
    result = verifier().verify_proposal(proposal())

    assert result.ok is True

    # A source_ref that is a URL, a bad schema_version and a REFUND without policy refs are all schema refusals.
    for broken in (
        proposal(evidence_refs=[{**EVIDENCE, "source_ref": "https://example.invalid/evidence"}]),
        proposal(schema_version=1),
        proposal(policy_refs=[]),
    ):
        refused = verifier().verify_proposal(broken)
        assert refused.ok is False, broken
        assert PROPOSAL_SCHEMA_REFUSED in refused.reason_codes, broken


def test_the_verifier_does_not_invent_what_the_run_did_not_observe() -> None:
    """A run that never searched policy cannot pass a refund: there is no visible rule to cite."""
    lonely = ProposalVerifier(observations=[observation()], pinned_bundle_ids=frozenset({BUNDLE}))

    result = lonely.verify_citations(
        recommended_action="REFUND",
        evidence_refs=[dict(EVIDENCE)],
        policy_refs=[dict(POLICY)],
        missing_evidence=[],
    )

    assert result.reason_codes == (CITATION_NOT_VISIBLE,)


def test_a_propose_may_cite_and_a_read_may_not() -> None:
    """The ABI half: citations belong to a PROPOSE, and ``extra="forbid"`` used to make them impossible.

    Before C08.1c a PROPOSE could not carry a citation at all, so a refund proposal had nothing to verify —
    the verifier would have been unreachable. A read carrying a citation is still refused: that is a proposal
    smuggled through a read.
    """
    accepted = validate_decision(
        {
            "kind": "PROPOSE",
            "case_type": "LOGISTICS",
            "recommended_action": "REFUND",
            "reason_codes": ["LOST_CONFIRMED"],
            "summary": "承运商判定丢失",
            "evidence_refs": [dict(EVIDENCE)],
            "policy_refs": [dict(POLICY)],
        }
    )

    assert len(accepted.evidence_refs) == 1
    assert accepted.policy_refs[0].rule_id == "rule-lost-refund"

    with pytest.raises(ActionRefusedError):
        validate_decision(
            {
                "kind": "READ_TOOL",
                "tool_name": "get_order_context",
                "arguments": {},
                "evidence_refs": [dict(EVIDENCE)],
            }
        )


def test_a_citation_that_is_not_a_reference_at_all_is_refused_by_the_abi() -> None:
    """The reference shape is the contract's: a URL or a short hash is not a citation."""
    with pytest.raises(ActionRefusedError):
        validate_decision(
            {
                "kind": "PROPOSE",
                "case_type": "LOGISTICS",
                "recommended_action": "REFUND",
                "reason_codes": ["LOST_CONFIRMED"],
                "summary": "s",
                "evidence_refs": [{**EVIDENCE, "content_hash": "abc"}],
            }
        )


def test_an_escalation_does_not_invent_citations() -> None:
    """``docs/agent-spec.md:20``: ESCALATE 记录原因，不补造引用."""
    with pytest.raises(ActionRefusedError):
        validate_decision(
            {
                "kind": "ESCALATE",
                "reason_codes": ["NEEDS_HUMAN"],
                "summary": "转人工",
                "policy_refs": [dict(POLICY)],
            }
        )


# ``REFUND_CITATION_REQUIRED`` and the schema refusal both mean "a refund must cite"; which one fires depends on
# whether the schema or the citation check sees it first, and the tests accept either by name.
REFUND_SCHEMA_OR_CITATION = "REFUND_CITATION_REQUIRED"


def test_an_unknown_evidence_source_is_not_accepted_silently() -> None:
    """An error observation has no version and no hash (``docs/engineering.md:104``), so it cannot be cited."""
    failed = ToolObservation(
        observation_id="obs-get_refund_status",
        tool_name="get_refund_status",
        source_type=EvidenceSourceType.ORDER_LINE,
        source_ref="order:get_refund_status",
        observed_at="2026-09-26T10:00:02Z",
        result=None,
        error=CoreToolError(code="NOT_FOUND", message="no record", retryable=False),
    )
    lonely = ProposalVerifier(observations=[failed, search(RULE)], pinned_bundle_ids=frozenset({BUNDLE}))

    result = lonely.verify_citations(
        recommended_action="REFUND",
        evidence_refs=[
            {**EVIDENCE, "observation_id": "obs-get_refund_status", "source_ref": "order:get_refund_status"}
        ],
        policy_refs=[dict(POLICY)],
        missing_evidence=[],
    )

    assert result.reason_codes == (CITATION_NOT_VISIBLE,)