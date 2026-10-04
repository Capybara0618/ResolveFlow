"""Context precision and evidence-backed refusal; no model APIs or business writes."""

import pytest

from resolveflow.harness.context import extract_facts
from resolveflow.harness.facts import FactsView
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.observation_read import ObservationStore
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.harness.verifier import ProposalVerifier
from tests.unit.test_context_builder import build, observation
from tests.unit.test_harness_loop import FACTS, StubTools
from tests.unit.test_proposal_verifier import POLICY, search


def text_of(packet):
    return "\n".join(message["content"] for message in packet.messages)


def test_policy_body_and_exception_appear_once_even_after_repeated_searches():
    hit = {**POLICY, "text": "允许退款，但超过500000分必须人工核验。"}
    first = search(hit)
    second = first.model_copy(update={"observation_id": "policy-search-second"})
    packet = build(observations=[first, second])
    assert text_of(packet).count(hit["text"]) == 1
    assert "500000" in text_of(packet)
    assert hit["content_hash"] in text_of(packet)


def test_identical_rule_id_with_changed_bytes_keeps_both_versions():
    first = search({**POLICY, "text": "旧政策例外"})
    second = search({**POLICY, "version": "v2", "content_hash": "c" * 64, "text": "新政策例外"})
    second = second.model_copy(update={"observation_id": "second-search"})
    text = text_of(build(observations=[first, second]))
    assert "旧政策例外" in text and "新政策例外" in text


def test_duplicated_order_fields_are_projected_but_unknown_fields_survive():
    source = observation(result={"line_paid_amount": 2599, "currency": "CNY", "future_fact": "必须保留"})
    view = FactsView()
    extract_facts(view, source)
    text = text_of(build(observations=[source], view=view))
    assert "order_paid_amount_minor=2599" in text
    assert '"line_paid_amount":2599' not in text
    assert "必须保留" in text
    assert "obs-1" in text
    assert source.result["line_paid_amount"] == 2599


def test_unextracted_fields_are_not_removed_from_a_tool_result():
    source = observation(result={"line_paid_amount": 2599, "currency": "CNY"})
    text = text_of(build(observations=[source], view=FactsView()))
    assert '"line_paid_amount":2599' in text


def test_progress_reports_missing_reads_and_does_not_turn_empty_hits_into_rejection():
    empty = search()
    text = text_of(build(observations=[empty]))
    assert "调查进展" in text
    assert "未读" in text
    assert "无候选" in text
    assert "拒绝" not in text


def test_reject_without_evidence_or_policy_is_refused():
    result = ProposalVerifier([], frozenset()).verify_citations(
        recommended_action="REJECT", evidence_refs=[], policy_refs=[])
    assert not result.ok
    assert "REJECT_CITATION_REQUIRED" in result.reason_codes


def test_empty_case_materials_cannot_support_rejection_even_with_a_policy():
    source = observation(tool="get_case_evidence", result={"items": []})
    verifier = ProposalVerifier([source, search({**POLICY, "text": "适用政策"})], frozenset({POLICY["bundle_id"]}))
    result = verifier.verify_citations(
        recommended_action="REJECT", evidence_refs=[{
            "observation_id": source.observation_id, "source_ref": source.source_ref,
            "source_version": source.source_version, "content_hash": source.content_hash,
        }], policy_refs=[POLICY])
    assert not result.ok
    assert "REJECT_FACTS_REQUIRED" in result.reason_codes


def test_manual_review_with_a_missing_source_remains_available():
    result = ProposalVerifier([], frozenset()).verify_citations(
        recommended_action="MANUAL_REVIEW", evidence_refs=[], policy_refs=[], missing_evidence=["履约状态"])
    assert result.ok


def cited(source):
    return {"observation_id": source.observation_id, "source_ref": source.source_ref,
            "source_version": source.source_version, "content_hash": source.content_hash}


@pytest.mark.parametrize("conclusion,missing,expected", [
    ("DELIVERED", [], True), ("UNKNOWN", [], False), ("DELIVERED", ["签收凭证"], False),
])
def test_reject_requires_order_shipment_policy_and_no_reported_missing_evidence(conclusion, missing, expected):
    order = observation(observation_id="order", result={"status": "PAID", "line_paid_amount": 2599})
    shipment = observation(tool="get_shipment_trace", observation_id="shipment", source_ref="shipment:1",
                           result={"status": "SIGNED", "carrier_conclusion": conclusion})
    verifier = ProposalVerifier([order, shipment, search({**POLICY, "text": "适用条件与例外"})],
                                frozenset({POLICY["bundle_id"]}))
    result = verifier.verify_citations(recommended_action="REJECT", evidence_refs=[cited(order), cited(shipment)],
                                       policy_refs=[POLICY], missing_evidence=missing)
    assert result.ok is expected
    assert "not Java's approval" in result.note


def test_superseded_facts_leave_p2_but_their_exact_original_remains_readable():
    old = observation(observation_id="old", result={"line_paid_amount": 2599})
    new = old.model_copy(update={"observation_id": "new", "source_version": "4", "content_hash": "c" * 64,
                                 "result": {"line_paid_amount": 32900}})
    view = FactsView()
    for item in (old, new):
        extract_facts(view, item)
    packet = build(observations=[old, new], view=view)
    text = text_of(packet)
    assert "order_paid_amount_minor=32900" in text
    assert "order_paid_amount_minor=2599" not in text
    assert '"line_paid_amount":2599' in text  # Old optional excerpt is explicitly not a current P2 fact.
    assert packet.facts[0]["source_version"] == "4"
    store = ObservationStore("quality-run")
    store.remember(old)
    assert "2599" in store.read("old", limit=4000).as_result()["text"]
    assert old.result == {"line_paid_amount": 2599}


def test_conflicting_live_facts_are_both_retained_after_projection():
    first = observation(observation_id="first", source_ref="order:first", result={"line_paid_amount": 2599})
    second = observation(observation_id="second", source_ref="order:second", content_hash="c" * 64,
                         result={"line_paid_amount": 32900})
    view = FactsView()
    for item in (first, second):
        extract_facts(view, item)
    text = text_of(build(observations=[first, second], view=view))
    assert "order_paid_amount_minor=2599" in text and "order_paid_amount_minor=32900" in text
    assert text.count("status=CONFLICT") == 2


def test_malformed_policy_hit_and_unknown_hit_metadata_are_not_discarded():
    malformed = search({"text": "缺少引用但保留原文", "future_field": "不得丢弃"})
    text = text_of(build(observations=[malformed]))
    assert "缺少引用但保留原文" in text and "不得丢弃" in text
    valid = search({**POLICY, "text": "完整条件", "future_field": "重要新增例外提示"})
    text = text_of(build(observations=[valid]))
    assert "重要新增例外提示" in text
    assert text.count("完整条件") == 1


@pytest.mark.parametrize("next_action", ["MANUAL_REVIEW", "REJECT"])
def test_sdk_refuses_early_rejection_and_allows_one_bounded_repair(next_action):
    early = {"kind": "PROPOSE", "recommended_action": "REJECT", "case_type": "LOGISTICS",
             "summary": "空材料不能支持这个拒绝", "reason_codes": ["NO_MATERIALS"]}
    repaired = {**early, "recommended_action": next_action, "summary": "缺少依据，需要人工复核"}
    model = MockModelClient(script=[early, repaired])
    tools = StubTools()
    result = AgentScopeRunner(model=model, tools=tools, facts=FACTS).run()
    assert model.calls == 2
    assert tools.calls == []
    if next_action == "MANUAL_REVIEW":
        assert result.completed
        assert result.decision.recommended_action == "MANUAL_REVIEW"
    else:
        assert not result.completed
        assert result.reason_code == "REJECT_CITATION_REQUIRED"
    second = "\n".join(block.text for message in model.conversations[1]
                       for block in message.get_content_blocks() if hasattr(block, "text"))
    assert "REJECT_CITATION_REQUIRED" in second
