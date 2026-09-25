"""The facts view: authority, freshness, supersession and conflicts (C07.2).

These are the properties ``docs/context-engineering.md:9-11`` states, and each test names the failure it
excludes. The two that matter most are the ones a plausible implementation gets wrong:

* a **customer statement repeated by a tool** must not become authoritative — authority comes from the source,
  and there is no operation in the view that raises it;
* a **conflict must survive as two facts** — a view that kept the winner would let the model decide a case
  without ever seeing that the world disagreed.
"""

from __future__ import annotations

import pytest

from resolveflow.contracts.core_models import CoreToolError, ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.harness.facts import (
    AUTHORITY_SOURCES,
    CLAIM_SOURCES,
    FactStatus,
    FactsView,
    SourceAuthority,
    authority_of,
    facts_hash,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def observation(
    *,
    tool: str = "get_order_context",
    source_type: EvidenceSourceType = EvidenceSourceType.ORDER_LINE,
    source_ref: str = "order:7001",
    source_version: str = "3",
    content_hash: str | None = HASH_A,
    observation_id: str = "obs-1",
    result: dict[str, object] | None = None,
) -> ToolObservation:
    """One successful observation, or an unciteable one when ``content_hash`` is ``None``.

    The unciteable case **omits** ``source_version``/``content_hash`` rather than passing nulls, because the core
    wire refuses an explicit null (缺失=省略). That refusal fired on the first version of this helper, which is the
    DTO's rule doing its job — the same rule that makes a failed observation unrepresentable as a citable one.
    """
    fields: dict[str, object] = {
        "observation_id": observation_id,
        "tool_name": tool,
        "source_type": source_type,
        "source_ref": source_ref,
        "observed_at": "2026-09-25T10:00:00Z",
        "result": result if result is not None else {"line_paid_amount": 2599},
    }
    if content_hash is not None:
        fields["content_hash"] = content_hash
        fields["source_version"] = source_version
    return ToolObservation(**fields)


def failed(*, source_ref: str = "order:7001", observation_id: str = "obs-1") -> ToolObservation:
    return ToolObservation(
        observation_id=observation_id,
        tool_name="get_order_context",
        source_type=EvidenceSourceType.ORDER_LINE,
        source_ref=source_ref,
        observed_at="2026-09-25T10:00:00Z",
        error=CoreToolError(code="UPSTREAM_UNAVAILABLE", message="commerce is down", retryable=True),
    )


# --------------------------------------------------------------------------- authority


def test_authority_comes_from_the_source_and_the_two_halves_are_named() -> None:
    """``docs/context-engineering.md:11``: 来源分AUTHORITY/USER_CLAIM/MODEL_INFERENCE.

    The split is derived from ``EvidenceSourceType``, so it cannot fall out of step with the enum Java decides
    evidence permissions from. The assertion that the two sets partition the enum is what makes adding a source
    a decision rather than a default.
    """
    assert CLAIM_SOURCES | AUTHORITY_SOURCES == set(EvidenceSourceType)
    assert not (CLAIM_SOURCES & AUTHORITY_SOURCES)
    assert authority_of(EvidenceSourceType.ORDER_LINE) is SourceAuthority.AUTHORITY
    assert authority_of(EvidenceSourceType.SHIPMENT) is SourceAuthority.AUTHORITY
    assert authority_of(EvidenceSourceType.POLICY_RULE) is SourceAuthority.AUTHORITY
    # A reviewer's own verification is a claim, not an authority read: docs/domain-model.md:27 makes it a recorded
    # conclusion, and it must not silently outrank the carrier record it contradicts.
    assert authority_of(EvidenceSourceType.REVIEWER_VERIFICATION) is SourceAuthority.USER_CLAIM
    assert authority_of(EvidenceSourceType.CUSTOMER_STATEMENT) is SourceAuthority.USER_CLAIM


def test_a_customer_statement_cannot_become_authoritative_by_being_repeated() -> None:
    """``:11`` 用户陈述与模型推断不能因摘要或重复出现而升级为权威.

    The same claim read four times stays a ``USER_CLAIM``. There is no ``promote`` in the view, so this test is
    really asserting that no such operation exists: a view that could raise authority would need a rule for when,
    and any such rule is a way for a claim to become a fact without a tool read.
    """
    view = FactsView()
    for index in range(4):
        view.note(
            key="customer_claim_conclusion",
            value="包裹丢了",
            observation=observation(
                tool="get_case_evidence",
                source_type=EvidenceSourceType.CUSTOMER_STATEMENT,
                source_ref="evidence:claim-1",
                source_version=str(index),
                content_hash=HASH_A,
                observation_id=f"obs-{index}",
            ),
        )

    claims = view.live("customer_claim_conclusion")
    assert claims, "the claim is kept"
    assert {fact.authority for fact in claims} == {SourceAuthority.USER_CLAIM}
    assert not view.by_authority(SourceAuthority.AUTHORITY)


# --------------------------------------------------------------------------- freshness


def test_a_read_without_a_content_hash_is_unverified_rather_than_fresh() -> None:
    """A read that cannot be cited is not one to treat as settled (``docs/agent-spec.md:52``)."""
    view = FactsView()
    fact = view.note(
        key="shipment_status",
        value="DELAYED",
        observation=observation(
            tool="get_shipment_trace",
            source_type=EvidenceSourceType.SHIPMENT,
            source_ref="shipment:7001",
            content_hash=None,
        ),
    )

    assert fact.status is FactStatus.UNVERIFIED
    assert fact.content_hash is None


def test_a_newer_read_of_the_same_source_supersedes_and_keeps_the_old_row() -> None:
    """``:11`` 新版本替换同源旧事实**仍保留原记录**.

    Deleting the old value would make "the run once believed X and then learned Y" unanswerable, and that history
    is what a reviewer needs when the two disagree.
    """
    view = FactsView()
    first = view.note(
        key="shipment_carrier_conclusion",
        value="DELAYED",
        observation=observation(
            tool="get_shipment_trace",
            source_type=EvidenceSourceType.SHIPMENT,
            source_ref="shipment:7001",
            source_version="1",
            content_hash=HASH_A,
        ),
    )
    second = view.note(
        key="shipment_carrier_conclusion",
        value="LOST",
        observation=observation(
            tool="get_shipment_trace",
            source_type=EvidenceSourceType.SHIPMENT,
            source_ref="shipment:7001",
            source_version="2",
            content_hash=HASH_B,
            observation_id="obs-2",
        ),
    )

    assert first.status is FactStatus.STALE, "the superseded row stays, marked"
    assert second.status is FactStatus.FRESH
    assert [fact.value for fact in view.facts] == ["DELAYED", "LOST"]
    assert [fact.value for fact in view.live("shipment_carrier_conclusion")] == ["LOST"]


def test_re_reading_the_same_value_does_not_grow_the_view() -> None:
    """ ``:11``'s 重复出现 is not evidence: the same source saying the same thing is not a new fact.

    Without this, a loop that re-reads a shipment on every turn would accumulate identical rows, and the
    "repeated appearance" would look like corroboration.
    """
    view = FactsView()
    for index in range(3):
        view.note(
            key="order_paid_amount_minor",
            value="2599",
            observation=observation(observation_id=f"obs-{index}"),
        )

    assert len(view.facts) == 1
    assert view.facts[0].status is FactStatus.FRESH


# --------------------------------------------------------------------------- conflicts


def test_two_sources_disagreeing_keeps_both_and_marks_both_conflicted() -> None:
    """``:11`` 不同来源冲突同时保留 — and the view does not pick a winner.

    This is the case the whole record exists for: the carrier says the parcel was delivered, the customer says it
    never arrived. A builder that kept the authority would hand the model one settled fact and hide the
    disagreement that a human needs to see.
    """
    view = FactsView()
    view.note(
        key="shipment_status",
        value="SIGNED",
        observation=observation(
            tool="get_shipment_trace",
            source_type=EvidenceSourceType.SHIPMENT,
            source_ref="shipment:7001",
            content_hash=HASH_A,
        ),
    )
    view.note(
        key="shipment_status",
        value="NOT_RECEIVED",
        observation=observation(
            tool="get_case_evidence",
            source_type=EvidenceSourceType.CUSTOMER_STATEMENT,
            source_ref="evidence:claim-1",
            content_hash=HASH_B,
            observation_id="obs-2",
        ),
    )

    assert len(view.live("shipment_status")) == 2
    assert {fact.status for fact in view.live("shipment_status")} == {FactStatus.CONFLICT}
    assert {fact.authority for fact in view.live("shipment_status")} == {
        SourceAuthority.AUTHORITY,
        SourceAuthority.USER_CLAIM,
    }
    assert view.conflicts(), "the conflict is visible without the caller having to compare values itself"


def test_an_authority_disagreeing_with_an_authority_is_also_a_conflict() -> None:
    """The rule is about **values**, not about authorities.

    Resolving the first by rank would be the same mistake as resolving the second: the run has two system reads
    that disagree, and which one is right is a fact about the world, not about the sources' class.
    """
    view = FactsView()
    view.note(
        key="refundable_amount_minor",
        value="2599",
        observation=observation(
            tool="get_order_context",
            source_ref="order:7001",
            content_hash=HASH_A,
        ),
    )
    view.note(
        key="refundable_amount_minor",
        value="0",
        observation=observation(
            tool="get_refund_status",
            source_type=EvidenceSourceType.PAYMENT_LEDGER,
            source_ref="ledger:7001",
            content_hash=HASH_B,
            observation_id="obs-2",
        ),
    )

    assert {fact.status for fact in view.live("refundable_amount_minor")} == {FactStatus.CONFLICT}


def test_a_conflict_resolved_by_a_read_stops_being_a_conflict() -> None:
    """A later read that agrees with one side clears the flag.

    Leaving it set would make every subsequent re-read look contested, and a permanently-conflicted run could
    never reach a decision even after the world settled.
    """
    view = FactsView()
    common = {"tool": "get_order_context"}
    view.note(key="refundable_amount_minor", value="2599", observation=observation(**common, source_ref="order:7001"))
    view.note(
        key="refundable_amount_minor",
        value="0",
        observation=observation(
            **common, source_type=EvidenceSourceType.PAYMENT_LEDGER, source_ref="ledger:7001", content_hash=HASH_B
        ),
    )
    assert view.conflicts()

    # The ledger is read again and now agrees with the order line: the same source supersedes its own value.
    view.note(
        key="refundable_amount_minor",
        value="2599",
        observation=observation(
            **common,
            source_type=EvidenceSourceType.PAYMENT_LEDGER,
            source_ref="ledger:7001",
            content_hash=HASH_C,
            observation_id="obs-3",
        ),
    )

    live = view.live("refundable_amount_minor")
    assert {fact.value for fact in live} == {"2599"}
    assert {fact.status for fact in live} == {FactStatus.FRESH}
    assert not view.conflicts()


def test_a_superseded_fact_does_not_keep_a_conflict_alive() -> None:
    """Only **live** facts conflict. Two versions from one source are history, not a disagreement."""
    view = FactsView()
    common = {"tool": "get_shipment_trace", "source_type": EvidenceSourceType.SHIPMENT, "source_ref": "shipment:7001"}
    view.note(key="shipment_status", value="SIGNED", observation=observation(**common, source_version="1"))
    view.note(
        key="shipment_status",
        value="LOST",
        observation=observation(**common, source_version="2", content_hash=HASH_B, observation_id="obs-2"),
    )

    assert not view.conflicts()
    assert [fact.status for fact in view.facts] == [FactStatus.STALE, FactStatus.FRESH]


# --------------------------------------------------------------------------- shape


def test_a_fact_key_must_be_a_field_not_a_sentence() -> None:
    """``:19`` 精确字段及来源，禁止生成式重写 — the shape is what enforces it."""
    view = FactsView()
    with pytest.raises(ValueError, match="not a fact key"):
        view.note(key="the carrier said the parcel was lost", value="LOST", observation=observation())
    with pytest.raises(ValueError, match="not a fact key"):
        view.note(key="承运商结论", value="LOST", observation=observation())


def test_a_fact_value_must_be_short_enough_to_be_a_value() -> None:
    """A value that long is prose, and prose belongs in the observation it can be read back from."""
    view = FactsView()
    with pytest.raises(ValueError, match="prose"):
        view.note(key="shipment_status", value="承运商" * 100, observation=observation())


def test_a_failed_read_contributes_no_facts() -> None:
    """NOT_FOUND and a broken source are reads that happened with nothing to report (``docs/agent-spec.md:36``)."""
    view = FactsView()
    from resolveflow.harness.context import extract_facts

    assert extract_facts(view, failed()) == []
    assert view.facts == []


# --------------------------------------------------------------------------- the hash


def test_the_protected_fact_hash_covers_what_trimming_may_not_change() -> None:
    """``:35`` protected_fact_hash覆盖必保留值/来源/版本/冲突.

    It changes when a fact is learned, superseded or conflicted, and it is *stable* for an unchanged view — which
    is what lets the裁剪 demonstration assert that trimming preserved every protected field.
    """
    view = FactsView()
    before = facts_hash(view)
    view.note(key="order_paid_amount_minor", value="2599", observation=observation())
    learned = facts_hash(view)
    assert learned != before

    # Learning the same thing again leaves the hash alone: nothing protected changed.
    view.note(key="order_paid_amount_minor", value="2599", observation=observation(observation_id="obs-2"))
    assert facts_hash(view) == learned

    # A conflict does change it, because a conflicted fact is a different protected state.
    view.note(
        key="order_paid_amount_minor",
        value="0",
        observation=observation(
            tool="get_refund_status",
            source_type=EvidenceSourceType.PAYMENT_LEDGER,
            source_ref="ledger:7001",
            content_hash=HASH_B,
            observation_id="obs-3",
        ),
    )
    assert facts_hash(view) != learned


def test_a_stale_fact_is_outside_the_protected_hash() -> None:
    """History is what裁剪 may drop (``:27``), so it is not part of "must not be changed by trimming"."""
    view = FactsView()
    common = {"source_ref": "shipment:7001", "tool": "get_shipment_trace"}
    view.note(key="shipment_status", value="DELAYED", observation=observation(**common, source_version="1"))
    with_history = facts_hash(view)

    view.note(
        key="shipment_status",
        value="LOST",
        observation=observation(**common, source_version="2", content_hash=HASH_B, observation_id="obs-2"),
    )
    # Both a live fact and a stale one exist now; the hash covers the live one plus everything else protected.
    assert facts_hash(view) != with_history
    assert any(fact.status is FactStatus.STALE for fact in view.facts)
