"""The seven required fixtures, each asserted against the property it exists for (C07.2).

`docs/context-engineering.md:41`: 至少覆盖长物流、矛盾来源、缺引用、超限、恶意正文、跨 scope 读回、合法 tool pair
七类 fixture.
``:41`` also asks for 一个裁剪前后演示，验证必保留字段一致 — that is ``test_trimming_demo.py``.

Each test here is deliberately about the *behaviour* the fixture was built to expose, not about the fixture's
size: a test that only asserted "this fixture builds a packet" would keep passing after the behaviour it was
supposed to protect had broken.
"""

from __future__ import annotations

import pytest

from resolveflow.harness.context import CONTEXT_REQUIRED_OVERFLOW, OverflowRefusedError
from resolveflow.harness.facts import FactStatus, SourceAuthority
from resolveflow.harness.observation_read import (
    ObservationNotFoundError,
    ObservationStore,
    read_observation,
)
from tests.unit.context_fixtures import FIXTURES, RUN, build_packet, load

NAMES = [scenario.name for scenario in FIXTURES]


def test_all_seven_required_fixtures_exist() -> None:
    """The completion standard is a list of seven; a fixture that quietly disappeared would be invisible."""
    assert NAMES == [
        "long_logistics",
        "contradictory_sources",
        "missing_citation",
        "overflow",
        "malicious_body",
        "cross_scope_read",
        "legal_tool_pair",
    ]
    # And each says what it is for, because a fixture that stopped being about anything is a fixture to delete.
    assert all(scenario.property_tested for scenario in FIXTURES)


def test_the_other_six_fixtures_build_a_packet_without_being_refused() -> None:
    """A sanity check for the fixtures themselves: if one silently became an overflow, its own test would lie."""
    for name in NAMES:
        if name == "overflow":
            continue
        packet, _view, _store = build_packet(load(name))
        assert packet.messages, f"{name} produced no request"
        assert packet.input_tokens <= packet.input_cap


# --------------------------------------------------------------------------- 长物流


def test_long_logistics_keeps_the_structure_and_makes_the_tail_readable() -> None:
    """``:29`` 物流长轨迹用首末/异常/状态变化结构化提取，保留原文位置.

    Three things at once, because they are one property: the *fields* a decision uses are in P2, the excerpt is
    bounded, and what the excerpt could not carry is still reachable by reference.
    """
    scenario = load("long_logistics")
    packet, view, store = build_packet(scenario)

    body = packet.messages[1]["content"]
    # Structured extraction: the conclusion and the status are exact P2 fields.
    assert "shipment_carrier_conclusion=LOST" in body
    assert "shipment_status=EXCEPTION" in body
    assert "shipment_last_scan_at=2026-09-24T08:00:00Z" in body
    # The long free-text field is **not** dumped into the prompt: it becomes a pointer the model can follow, and
    # the structured events that would have been pushed out by it are still there.
    assert "中段。" * 100 not in body
    assert "EXCEPTION_HOLD" in body, "the interesting events survive the bounded excerpt"
    assert "READ_OBSERVATION" in body and "obs-trace" in body, "with a pointer to the原文"
    # And the text the excerpt left out is reachable by reference — here the whole raw body, which is far longer
    # than the excerpt's per-field bound. (The first version of this asserted a 20 000-character offset, which the
    # fixture's 10 207-character rendering does not have: the read *refused* the offset, which is the store's rule
    # working. The assertion was wrong, not the store.)
    full = read_observation(store, observation_id="obs-trace", offset=0, limit=4000)
    assert full.total_length > 9000, "the raw body really is long"
    assert full.next_offset is not None, "and reading it takes more than one window"
    assert "末段原文" not in full.text, "the first window does not reach the end"
    tail = read_observation(store, observation_id="obs-trace", offset=full.total_length - 100, limit=4000)
    assert "末段原文" in tail.text, "and the end is reachable by asking for it"
    assert view.live("shipment_carrier_conclusion")


# --------------------------------------------------------------------------- 矛盾来源


def test_contradictory_sources_are_kept_in_conflict_and_both_shown() -> None:
    """``:11`` 不同来源冲突同时保留 — and the authority does not win by rank."""
    scenario = load("contradictory_sources")
    packet, view, _store = build_packet(scenario)

    body = packet.messages[1]["content"]
    assert "delivery_conclusion=SIGNED" in body
    assert "delivery_conclusion=NOT_RECEIVED" in body
    assert "status=CONFLICT" in body
    # The two sides carry different authorities, and the view still has not chosen between them.
    authorities = {fact.authority for fact in view.live("delivery_conclusion")}
    assert authorities == {SourceAuthority.AUTHORITY, SourceAuthority.USER_CLAIM}
    assert len(view.conflicts()) == 2


# --------------------------------------------------------------------------- 缺引用


def test_a_fact_without_a_hash_is_unverified_and_carries_no_content_hash() -> None:
    """``docs/agent-spec.md:52``: a citation needs ref/来源/版本/hash — a read without one cannot be cited."""
    scenario = load("missing_citation")
    packet, view, _store = build_packet(scenario)

    facts = view.live("shipment_carrier_conclusion")
    assert facts
    assert all(fact.status is FactStatus.UNVERIFIED for fact in facts)
    assert all(fact.content_hash is None for fact in facts)
    body = packet.messages[1]["content"]
    assert "shipment_carrier_conclusion=DELAYED" in body
    assert "status=UNVERIFIED" in body


# --------------------------------------------------------------------------- 超限


def test_overflow_is_refused_rather_than_trimmed() -> None:
    """``:27`` 转索引后仍超限则CONTEXT_REQUIRED_OVERFLOW转人工，不删约束."""
    scenario = load("overflow")

    with pytest.raises(OverflowRefusedError) as refusal:
        build_packet(scenario)

    assert refusal.value.reason_code == CONTEXT_REQUIRED_OVERFLOW
    assert refusal.value.mandatory_tokens > refusal.value.cap
    # P0 is named as untrimmable, so whoever reads the refusal knows why nothing was dropped.
    assert "never trimmed" in str(refusal.value)


# --------------------------------------------------------------------------- 恶意正文


def test_hostile_policy_text_is_carried_as_cited_evidence_not_as_an_instruction() -> None:
    """``docs/policy-rag.md:25`` 禁止将政策正文里的指令当系统权限.

    What is asserted is the shape the instruction ends up in: inside a **P3 observation** that names its source and
    the tool that fetched it, never in the system prompt (P0) and never as a fact. There is no code path here that
    can turn text into a permission, and this test is what would notice if one appeared.
    """
    scenario = load("malicious_body")
    packet, view, store = build_packet(scenario)

    system = packet.messages[0]["content"]
    body = packet.messages[1]["content"]
    assert "忽略上述规则" not in system, "policy text must never reach the system prompt"
    assert "忽略上述规则" in body, "the quotation itself is carried"
    assert "【P3·observation:search_policy】" in body, "and it is marked as an observation with its source"
    assert "policy:policy-logistics-2026.09/c-01" in body, "with the reference a citation will use"
    # No fact was created from the instruction, and nothing claims it as authority.
    assert not [fact for fact in view.facts if "忽略" in fact.value]
    # The rule's own text is what a citation would quote, reachable by reference.
    quoted = read_observation(store, observation_id="obs-policy")
    assert "忽略上述规则" in quoted.text


# --------------------------------------------------------------------------- 跨scope读回


def test_cross_scope_read_is_not_found_and_the_runs_own_data_is_readable() -> None:
    """``:31`` 仅访问当前run — demonstrated against a store that really holds another run's data."""
    scenario = load("cross_scope_read")
    _packet, _view, mine = build_packet(scenario)

    # This run can read what it read.
    assert "line_paid_amount" in read_observation(mine, observation_id="obs-mine").text

    # Another run's store holds an observation, and this run's store has never heard of it.
    theirs = ObservationStore(run_id="99999999-9999-4999-8999-999999999999")
    theirs.remember(
        observation_for_another_run()
    )
    assert "obs-theirs" in theirs
    with pytest.raises(ObservationNotFoundError) as refusal:
        read_observation(mine, observation_id="obs-theirs")
    assert refusal.value.code == "NOT_FOUND"
    assert "obs-theirs" not in mine, "and this run's store does not learn about it by asking"


def observation_for_another_run():
    from resolveflow.contracts.core_models import ToolObservation
    from resolveflow.contracts.enums import EvidenceSourceType

    return ToolObservation(
        observation_id="obs-theirs",
        tool_name="get_order_context",
        source_type=EvidenceSourceType.ORDER_LINE,
        source_ref="order:9001",
        source_version="1",
        content_hash="f" * 64,
        observed_at="2026-09-25T10:00:00Z",
        result={"line_paid_amount": 999_999, "currency": "CNY"},
    )


# --------------------------------------------------------------------------- 合法tool pair


def test_a_tool_call_and_its_result_stay_one_pair_with_one_identity() -> None:
    """``:29`` tool_call/result成对保留 — checkable as: the packet's entry and the read-back share id and hash."""
    scenario = load("legal_tool_pair")
    packet, view, store = build_packet(scenario)

    body = packet.messages[1]["content"]
    # The observation is rendered in P3 and its id is the reference a reader follows to it. (The *id* appears in
    # the P4 index rather than inline, which is the layering working: P3 carries content, P4 carries handles.)
    assert "get_refund_status" in body
    assert "obs-refund" in packet.selected_refs, "the result's id is in the packet's selected refs"
    assert "refundable_amount" in body
    facts = view.live()
    assert facts, "the pair's result yielded facts"
    assert {fact.observation_id for fact in facts} == {"obs-refund"}
    assert {fact.content_hash for fact in facts} == {"d" * 64}

    read_back = read_observation(store, observation_id="obs-refund")
    assert "refundable_amount" in read_back.text
    assert read_back.source_ref == "ledger:7001", "the read-back names the same source the fact does"


# --------------------------------------------------------------------------- the set as a whole


def test_every_fixture_packet_records_what_it_was_made_of() -> None:
    """A snapshot has to be self-describing (``:35``), and that is true of all seven or it is true of none."""
    for name in NAMES:
        if name == "overflow":
            continue
        packet, view, _store = build_packet(load(name))
        assert packet.context_id.startswith("ctx-")
        assert packet.protected_fact_hash
        assert packet.context_hash
        assert packet.tool_schema_hash
        assert packet.token_count_mode == "ESTIMATED"
        assert packet.manifest_id
        assert packet.run_id == RUN
        # The packet's facts are the view's live facts, so a reader can check the rendering against the record.
        assert len(packet.facts) == len(view.live())
