"""Failure injection tests for the production SDK correction boundary."""

from dataclasses import replace

import pytest
from resolveflow.harness.live_model import _decision_of
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.harness.verifier import ProposalVerifier
from resolveflow.tools import catalog

from tests.unit.test_harness_loop import FACTS, StubTools, failed_observation, observation, propose, read
from tests.unit.test_tool_catalog import client_for, context


def test_non_json_response_is_counted_and_repaired_without_executing_prose():
    raw = _decision_of("PRIVATE-RESPONSE: please refund now")
    model = MockModelClient(script=[raw, propose("MANUAL_REVIEW")])
    tools = StubTools()
    result = AgentScopeRunner(model=model, tools=tools, facts=FACTS).run()
    assert result.completed and result.spend.model_calls == 2
    assert not tools.calls
    assert any("MODEL_JSON_INVALID" in n for n in result.notices)
    assert all("PRIVATE-RESPONSE" not in n for n in result.notices)


def test_second_invalid_json_stops_instead_of_resetting_repair():
    raw = _decision_of("not JSON")
    result = AgentScopeRunner(model=MockModelClient(script=[raw, raw]), tools=StubTools(), facts=FACTS).run()
    assert not result.completed and result.reason_code == "MODEL_JSON_INVALID"
    assert result.spend.model_calls == 2


def test_temporary_tool_failure_is_observed_and_model_can_retry():
    tools = StubTools(TimeoutError("PRIVATE-TRANSPORT"), observation())
    result = AgentScopeRunner(model=MockModelClient(script=[read("get_order_context"),
                              read("get_order_context"), propose("MANUAL_REVIEW")]),
                              tools=tools, facts=FACTS).run()
    assert result.completed and len(tools.calls) == 2
    assert result.observations[0].error.retryable
    assert result.observations[0].content_hash is None
    assert any("TOOL_TRANSIENT" in n for n in result.notices)
    assert all("PRIVATE-TRANSPORT" not in n for n in result.notices)


def test_two_temporary_failures_do_not_allow_a_third_execution():
    tools = StubTools(TimeoutError(), TimeoutError())
    result = AgentScopeRunner(model=MockModelClient(script=[read("get_order_context")] * 3),
                              tools=tools, facts=FACTS).run()
    assert not result.completed and result.reason_code == "TOOL_RETRIES_EXHAUSTED"
    assert len(tools.calls) == 2


def test_forbidden_tool_result_stops_immediately():
    result = AgentScopeRunner(model=MockModelClient(script=[read("get_order_context")]),
                              tools=StubTools(failed_observation(code="FORBIDDEN")), facts=FACTS).run()
    assert not result.completed and result.reason_code == "FORBIDDEN"
    assert result.spend.model_calls == 1


def test_nonretryable_failure_cannot_be_repeated_but_can_handover():
    failure = failed_observation()
    tools = StubTools(failure)
    result = AgentScopeRunner(model=MockModelClient(script=[read("get_order_context")] * 2),
                              tools=tools, facts=FACTS).run()
    assert not result.completed and len(tools.calls) == 1
    assert result.reason_code == "TOOL_NOT_RETRYABLE"
    result = AgentScopeRunner(model=MockModelClient(script=[read("get_order_context"),
                              propose("MANUAL_REVIEW", summary="订单读取失败，请人工检查")]),
                              tools=StubTools(failure), facts=FACTS).run()
    assert result.completed


def test_invalid_cursor_gets_one_argument_correction_not_a_blind_retry():
    tools = StubTools(failed_observation("get_shipment_trace", code="INVALID_CURSOR"),
                      observation("get_shipment_trace", carrier_conclusion="LOST"))
    result = AgentScopeRunner(model=MockModelClient(script=[read("get_shipment_trace", cursor="bad"),
                              read("get_shipment_trace"), propose("MANUAL_REVIEW")]),
                              tools=tools, facts=FACTS).run()
    assert result.completed and len(tools.calls) == 2
    assert any("INVALID_CURSOR" in n for n in result.notices)


def test_cursor_error_cannot_reset_a_used_json_repair():
    tools = StubTools(failed_observation("get_shipment_trace", code="INVALID_CURSOR"))
    result = AgentScopeRunner(model=MockModelClient(script=[_decision_of("bad prose"), read("get_shipment_trace")]),
                              tools=tools, facts=FACTS).run()
    assert not result.completed and result.reason_code == "INVALID_CURSOR"
    assert result.spend.model_calls == 2 and len(tools.calls) == 1


@pytest.mark.parametrize("body", [
    {"line_paid_amount": "not-a-number", "fulfillment_status": "INVALID_STATUS"},
    {"line_id": "other", "version": 1},
])
def test_malformed_order_payload_is_not_citable(body):
    result = catalog.get_order_context(client_for(body), context())
    assert result.error and result.error.code == "TOOL_RESULT_INVALID"
    assert result.result is None and result.content_hash is None and result.source_version is None
    assert not result.error.retryable


@pytest.mark.parametrize("text", ["承运商已确认正常签收。", "退款已到账329元。", "Carrier confirmed delivery."])
def test_critical_false_claim_cannot_hide_behind_real_citations(text):
    source = observation("get_shipment_trace", carrier_conclusion="LOST", status="LOST")
    refs = [{k: getattr(source, k) for k in ("observation_id", "source_ref", "source_version", "content_hash")}]
    verifier = ProposalVerifier([source], frozenset())
    result = verifier.verify_content(summary=text, review_findings=[], evidence_refs=refs)
    assert not result.ok and "FACT_CLAIM_UNSUPPORTED" in result.reason_codes


@pytest.mark.parametrize("text", ["建议人工核对是否签收。", "客户称已签收，但承运商确认丢失。",
                                  "退款尚未到账。", "若正常签收，则需进一步核查。"])
def test_questions_negation_and_customer_assertions_are_not_verified_assertions(text):
    source = observation("get_shipment_trace", carrier_conclusion="LOST")
    verifier = ProposalVerifier([source], frozenset())
    assert verifier.verify_content(summary=text, review_findings=[],
                                   evidence_refs=[{"observation_id": source.observation_id}]).ok


def test_corrected_proposal_passes_the_same_semantic_gate():
    source = observation("get_shipment_trace", carrier_conclusion="LOST", status="LOST")
    refs = [{k: getattr(source, k) for k in ("observation_id", "source_ref", "source_version", "content_hash")}]
    bad = propose("MANUAL_REVIEW", summary="承运商已确认正常签收。", evidence_refs=refs)
    good = propose("MANUAL_REVIEW", summary="承运商确认丢失，建议人工复核。", evidence_refs=refs)
    result = AgentScopeRunner(model=MockModelClient(script=[read("get_shipment_trace"), bad, good]),
                              tools=StubTools(source), facts=replace(FACTS)).run()
    assert result.completed and result.decision.summary == good["summary"]
    assert any("FACT_CLAIM_UNSUPPORTED" in n for n in result.notices)


def test_different_error_categories_share_one_repair_allowance():
    source = observation("get_shipment_trace", carrier_conclusion="LOST")
    refs = [{k: getattr(source, k) for k in ("observation_id", "source_ref", "source_version", "content_hash")}]
    result = AgentScopeRunner(model=MockModelClient(script=[read("get_shipment_trace"), _decision_of("bad prose"),
        propose("MANUAL_REVIEW", summary="承运商已确认正常签收。", evidence_refs=refs)]),
        tools=StubTools(source), facts=FACTS).run()
    assert not result.completed and result.reason_code == "FACT_CLAIM_UNSUPPORTED"
    assert result.spend.model_calls == 3


@pytest.mark.parametrize("text,ok", [("本行实付25.99元。", True), ("本行实付2599元。", False),
                                    ("本行实付25.98元。", False),
                                    ("客户称实付329元。", True)])
def test_payment_claim_uses_integer_minor_units(text, ok):
    source = observation(line_paid_amount=2599)
    result = ProposalVerifier([source], frozenset()).verify_content(summary=text, review_findings=[],
                                    evidence_refs=[{"observation_id": source.observation_id}])
    assert result.ok is ok


def test_final_wire_callback_rechecks_the_same_false_claim():
    from tests.unit.test_proposal_verifier import proposal, verifier
    assert not verifier().verify_proposal(proposal(summary="承运商已确认正常签收，退款已到账329元。")).ok


@pytest.mark.parametrize("text,ok", [("整单实付52.99元，本行实付25.99元。", True),
                                    ("订单实付25.99元。", False)])
def test_order_and_line_paid_amounts_are_not_interchanged(text, ok):
    source = observation(line_paid_amount=2599, order_paid_amount=5299)
    assert ProposalVerifier([source], frozenset()).verify_content(summary=text, review_findings=[],
        evidence_refs=[{"observation_id": source.observation_id}]).ok is ok


def test_live_transport_prose_is_settled_and_repaired_through_sdk():
    import json

    from resolveflow.harness.live_model import HttpResponse, LiveModelClient
    responses = ["SYNTHETIC bad prose", json.dumps(propose("MANUAL_REVIEW"))]

    def transport(url, body, headers, timeout):
        return HttpResponse(200, json.dumps({"choices": [{"message": {"content": responses.pop(0)}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10}}).encode())

    model = LiveModelClient(endpoint="http://synthetic.invalid", model_id="synthetic-provider", transport=transport)
    result = AgentScopeRunner(model=model, tools=StubTools(), facts=FACTS).run()
    assert result.completed and model.calls == result.spend.model_calls == 2
    assert result.spend.output_tokens == 20
    assert result.modes == ("live", "live")  # Injected transport: no external LLM or fees.
