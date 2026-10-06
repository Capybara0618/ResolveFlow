"""Generic source/ownership and termination checks; no fixed evaluation cases or model API."""

import copy

import pytest
from resolveflow.contracts.enums import CallbackKind
from resolveflow.harness.actions import ActionRefusedError, validate_decision
from resolveflow.harness.context import _domain_guidance
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.references import ReferenceCatalog
from resolveflow.harness.sdk_runner import ActionGateMiddleware, AgentScopeRunner
from resolveflow.harness.verifier import ProposalVerifier
from resolveflow.runtime.worker import callback_payload, verified_callback

from tests.conftest import input_text_of
from tests.unit.test_callback_payloads_match_the_case_contract import claimed_run, contract_errors, result_for
from tests.unit.test_harness_loop import FACTS, StubTools, failed_observation, observation, propose, read


def refs(*sources):
    return [{k: getattr(source, k) for k in ("observation_id", "source_ref", "source_version", "content_hash")}
            for source in sources]


@pytest.mark.parametrize("ids", [["one"], ["one", "one"]])
def test_conflict_feedback_names_the_finding_path_without_inventing_sources(ids):
    gate = ActionGateMiddleware()
    raw = propose("MANUAL_REVIEW", evidence_refs=refs(observation().model_copy(update={"observation_id": "one"})),
                  review_findings=[{"kind": "CONFLICT", "text": "two sources disagree", "observation_ids": ids}])
    saved = copy.deepcopy(raw)
    assert gate.check(raw) is None
    assert gate.refusals[-1]["category"] == "SOURCE"
    assert "review_findings.0.observation_ids" in gate.repair_message
    assert "unrelated" in gate.repair_message
    assert raw == saved and gate.repairs_used == 1


@pytest.mark.parametrize("missing", ["second", "third"])
def test_finding_feedback_names_uncited_source_not_just_a_root_schema_error(missing):
    first = observation().model_copy(update={"observation_id": "first"})
    gate = ActionGateMiddleware()
    assert gate.check(propose("MANUAL_REVIEW", evidence_refs=refs(first), review_findings=[
        {"kind": "FACT", "text": "source claim", "observation_ids": [missing]}])) is None
    assert gate.refusals[-1]["category"] == "SOURCE"
    assert missing in gate.repair_message and "evidence_refs" in gate.repair_message


@pytest.mark.parametrize("field", ["fulfillment_status", "reserved_refund_amount", "carrier_conclusion",
                                  "verification_result", "order_status"])
def test_customer_cannot_be_asked_to_supply_authoritative_system_fields(field):
    raw = {"kind": "ASK_CUSTOMER", "questions": [{"question_id": "q", "field": field, "prompt": "请提供该信息"}]}
    with pytest.raises(ActionRefusedError) as error:
        validate_decision(raw)
    assert error.value.reason_code == "QUESTION_RESPONSIBILITY_INVALID"
    assert field in str(error.value)


@pytest.mark.parametrize("field", ["package_photo", "damage_description", "receipt_claim"])
def test_customer_provided_material_fields_remain_allowed(field):
    assert validate_decision({"kind": "ASK_CUSTOMER", "questions": [
        {"question_id": "q", "field": field, "prompt": "请补充说明或照片"}]}).kind == "ASK_CUSTOMER"


@pytest.mark.parametrize("missing", [[], [" "], ["\t", "照片"]])
def test_request_info_needs_explicit_nonblank_material_gaps(missing):
    with pytest.raises(ActionRefusedError) as error:
        validate_decision(propose("REQUEST_INFO", missing_evidence=missing))
    assert error.value.reason_code == "REQUEST_INFO_INCOMPLETE"


def test_request_info_is_still_a_merchant_proposal_not_an_automatic_customer_question():
    decision = validate_decision(propose("REQUEST_INFO", missing_evidence=["破损位置照片"],
                                         summary="请商家向客户索取破损位置照片后核验"))
    assert decision.kind == "PROPOSE" and not decision.questions


@pytest.mark.parametrize("state", ["RESERVED", "UNKNOWN", "CONSUMED"])
def test_occupied_current_refund_source_is_flagged_with_its_read_alias(state):
    source = observation(line_refund_state=state)
    catalog = ReferenceCatalog([source])
    text = _domain_guidance([source], None, catalog=catalog)
    assert f"O1:line_refund_state={state}" in text
    assert "关键阻碍" in text and "摘要" in text


def test_new_failed_source_supersedes_old_success_in_blocker_guidance():
    first = observation(line_refund_state="RESERVED")
    last = failed_observation()
    text = _domain_guidance([first, last], None, catalog=ReferenceCatalog([first, last]))
    assert "O2:get_order_context=失败:NOT_FOUND" in text
    assert "O1:line_refund_state=RESERVED" not in text
    assert "商家" in text


def test_no_blocker_is_not_a_new_refund_entitlement_or_additional_context_paragraph():
    source = observation(line_refund_state="FREE", reserved_refund_amount=0)
    assert "关键阻碍" not in _domain_guidance([source], None, catalog=ReferenceCatalog([source]))


def test_refusal_control_reply_is_a_harness_stop_not_a_model_escalation():
    model = MockModelClient(script=[{"kind": "BAD"}, {"kind": "BAD"}])
    result = AgentScopeRunner(model=model, tools=StubTools(), facts=FACTS).run()
    assert not result.completed and result.decision is None and result.reason_code == "ACTION_REFUSED"
    assert result.spend.model_calls == 2
    assert result.trajectory[-1] == {"action": "STOP", "outcome": "REFUSED", "detail": "ACTION_REFUSED",
                                     "origin": "HARNESS"}
    assert not any(t["action"] == "ESCALATE" and t["outcome"] == "DECIDED" for t in result.trajectory)


def test_genuine_model_escalation_remains_a_model_decision():
    raw = {"kind": "ESCALATE", "reason_codes": ["NEEDS_HUMAN"], "summary": "需商家核实承运来源"}
    result = AgentScopeRunner(model=MockModelClient(script=[raw]), tools=StubTools(), facts=FACTS).run()
    assert result.completed and result.decision.kind == "ESCALATE"
    assert result.trajectory[-1] == {"action": "ESCALATE", "outcome": "DECIDED", "detail": "ESCALATE",
                                     "origin": "MODEL"}


def test_short_finding_feedback_uses_the_model_visible_alias_and_never_adds_citations():
    first = observation()
    second = observation("get_refund_status").model_copy(update={"source_ref": "refund:line"})
    catalog = ReferenceCatalog([first, second])
    for source in (first, second):
        catalog.evidence(refs(source)[0])
    gate = ActionGateMiddleware()
    gate.references, gate.read_ids = catalog.references, catalog.read_ids
    raw = propose("MANUAL_REVIEW", evidence_refs=["O1"], review_findings=[
        {"kind": "FACT", "text": "source claim", "observation_ids": ["O2"]}])
    assert gate.check(raw) is None
    assert "'O2' absent from evidence_refs" in gate.repair_message
    assert second.observation_id not in gate.repair_message
    assert raw["evidence_refs"] == ["O1"]


def test_final_verifier_also_refuses_empty_request_info_not_only_the_model_action_gate():
    result = ProposalVerifier(observations=[], pinned_bundle_ids=frozenset()).verify_citations(
        recommended_action="REQUEST_INFO", evidence_refs=[], policy_refs=[], missing_evidence=[])
    assert result.reason_codes == ("REQUEST_INFO_INCOMPLETE",)


def test_final_wire_verifier_retains_string_material_gaps_after_schema_validation():
    result = result_for(propose("REQUEST_INFO", missing_evidence=["破损位置照片"]))
    payload = callback_payload(CallbackKind.PROPOSAL, claimed_run(), result)
    assert payload["missing_evidence"] == ["破损位置照片"]
    assert ProposalVerifier(observations=[], pinned_bundle_ids=frozenset()).verify_proposal(payload).ok


@pytest.mark.parametrize("codes", [["CARRIER_SOURCE_UNAVAILABLE"], []])
def test_valid_model_handover_callback_uses_its_reason_not_completed(codes):
    result = result_for({"kind": "ESCALATE", "reason_codes": codes, "summary": "商家核实承运来源"})
    payload = callback_payload(CallbackKind.FAILED, claimed_run(), result)
    assert payload == {"reason_codes": codes or ["NEEDS_HUMAN_VERIFICATION"], "retryable": False}
    assert contract_errors("FailedPayload", payload) == []


def test_failed_handover_does_not_replace_the_harness_failure_reason_with_model_reason():
    result = result_for({"kind": "ESCALATE", "reason_codes": ["NEEDS_HUMAN"]}, completed=False)
    assert callback_payload(CallbackKind.FAILED, claimed_run(), result)["reason_codes"] == ["ACTION_REFUSED"]


def test_blocker_guidance_reaches_actual_next_model_input_without_replacing_original_facts():
    source = observation(line_refund_state="RESERVED", line_paid_amount=2599)
    model = MockModelClient(script=[read("get_order_context"), propose("MANUAL_REVIEW", summary="需商家核查资金占用")])
    result = AgentScopeRunner(model=model, tools=StubTools(source), facts=FACTS).run()
    text = input_text_of(model)
    assert result.completed and "关键阻碍" in text and "O1:line_refund_state=RESERVED" in text
    assert "order_paid_amount_minor=2599" in text and result.observations[0] == source


def test_complete_request_info_uses_verified_proposal_callback_not_question_callback():
    result = result_for(propose("REQUEST_INFO", missing_evidence=["包装照片"], summary="商家请求包装照片后核查"))
    kind, _, payload, verified = verified_callback(claimed_run(), result)
    assert kind is CallbackKind.PROPOSAL and verified.completed
    assert payload["missing_evidence"] == ["包装照片"] and "questions" not in payload
