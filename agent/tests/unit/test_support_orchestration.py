"""Program readiness and deterministic presentation over one model-chosen investigation."""

import pytest

from resolveflow.support.guide import guide_source
from resolveflow.support.orchestration import Orchestration, Response, TurnPlan
from resolveflow.support.protocol import SupportFailure
from tests.unit.test_support_agent import request
from tests.unit.test_support_grounding import FactReads
from tests.unit.test_support_staged import understand


def plan(req, *, intent="APPLICATION", goal="PREPARE_REFUND", needs=None):
    value = understand(req, intent=intent, needs=[] if needs is None else needs)
    value["focus"][0]["goal"] = goal
    if goal != "EXPLAIN":
        value["focus"][0]["operation_request"] = req.context["current_request"]
    return TurnPlan.model_validate(value)


def source_refs():
    reads = FactReads()
    return {"O1": guide_source(), "O2": reads.read("get_shipment_trace", {}),
            "O3": reads.read("get_order_context", {})}


def test_program_contract_keeps_order_required_and_does_not_require_model_to_read_guide():
    req = request()
    p = plan(req)
    flow = Orchestration(req)
    meaning = p.meaning()
    flow.accept(p)
    assert meaning.focus[0].needs == ["ORDER"]
    state = flow.snapshot(meaning, {}, [], {})
    assert state["phase"] == "INVESTIGATE"
    assert state["tasks"][0]["missing"] == ["GUIDE", "ORDER"]
    assert flow.needs_ui(meaning, {}, {})


def test_missing_evidence_is_a_normal_state_until_ready_and_early_finish_is_bounded():
    req = request()
    p = plan(req, needs=["SHIPMENT"])
    flow = Orchestration(req)
    flow.accept(p)
    meaning = p.meaning()
    refs = source_refs()
    state = flow.snapshot(meaning, {"O1": refs["O1"], "O2": refs["O2"]}, [], {})
    assert state["tasks"][0]["missing"] == ["ORDER"]
    flow.defer(state)
    flow.defer(state)
    with pytest.raises(SupportFailure, match="NO_PROGRESS"):
        flow.defer(state)
    assert flow.snapshot(meaning, refs, [], {})["phase"] == "COMPOSE"


def test_program_assembles_steps_amount_facts_and_summary_from_one_accepted_goal():
    req = request()
    p = plan(req)
    flow = Orchestration(req)
    flow.accept(p)
    refs = source_refs()
    result = flow.compose(Response.model_validate({"kind": "RESPOND", "parts": [
        {"task_id": "trace", "text": "请核对申请原因，确认后再提交。"}],
        "refund_reason": {"customer_quotes": [req.context["current_request"]]}}), p.meaning(), refs, [], {})
    assert result.fact_rendering == "fields-v1"
    assert result.parts[0].next_steps[0].model_dump() == {"action": "REFUND_APPLICATION", "source": "O1"}
    assert {f.field for f in result.parts[0].facts} == {"ORDER_STATUS", "PAID_AMOUNT"}
    assert result.refund_summary.startswith("客户陈述")
    assert result.parts[0].citations == ["O3", "O1"]


def test_pure_policy_requires_relevant_model_citation_and_no_business_or_ui_read():
    req = request()
    p = plan(req, intent="ELIGIBILITY", goal="EXPLAIN", needs=["POLICY"])
    flow = Orchestration(req)
    flow.accept(p)
    refs = {"P1": {"source_type": "POLICY", "version": "v1", "data": {"text": "须核验条件"}}}
    assert not flow.needs_ui(p.meaning(), refs, {})
    assert flow.snapshot(p.meaning(), refs, [], {})["phase"] == "COMPOSE"
    value = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "若符合条件，仍须人工核验。"}]}
    with pytest.raises(ValueError, match="POLICY"):
        flow.compose(Response.model_validate(value), p.meaning(), refs, [], {})
    value["parts"][0]["citations"] = ["P1"]
    result = flow.compose(Response.model_validate(value), p.meaning(), refs, [], {})
    assert result.parts[0].assessment == "CONDITIONS" and not result.parts[0].next_steps
    assert not result.refund_summary and result.parts[0].citations == ["P1"]


def test_real_nonretryable_order_failure_is_blocked_not_a_fabricated_customer_question():
    req = request()
    p = plan(req)
    flow = Orchestration(req)
    flow.accept(p)
    failures = [{"tool_name": "get_order_context", "arguments": {}, "error": "UNAVAILABLE",
                 "retry_allowed": False}]
    refs = {"O1": guide_source()}
    state = flow.snapshot(p.meaning(), refs, failures, {})
    assert state["phase"] == "COMPOSE" and state["tasks"][0]["state"] == "BLOCKED"
    result = flow.compose(Response.model_validate({"kind": "RESPOND", "parts": [
        {"task_id": "trace", "text": "订单来源暂不可用，需进一步核查。"}]}), p.meaning(), refs, failures, {})
    assert result.parts[0].status == "UNAVAILABLE"
    assert result.parts[0].blocker.tool_name == "get_order_context"
    assert not result.parts[0].next_steps and result.refund_summary is None


def test_cancelled_goal_does_not_read_facts_or_offer_a_new_application():
    req = request()
    p = plan(req)
    flow = Orchestration(req)
    flow.accept(p)
    lifecycle = {"trace": "CANCELLED"}
    assert flow.snapshot(p.meaning(), {}, [], lifecycle)["phase"] == "COMPOSE"
    result = flow.compose(Response.model_validate({"kind": "RESPOND", "parts": [
        {"task_id": "trace", "text": "已记录本轮撤回意愿。"}]}), p.meaning(), {}, [], lifecycle)
    assert result.parts[0].status == "CANCELLED" and not result.parts[0].next_steps
    with pytest.raises(ValueError, match="refund_reason"):
        flow.compose(Response.model_validate({"kind": "RESPOND", "parts": [
            {"task_id": "trace", "text": "已记录。"}], "refund_reason": "仍想退款"}),
            p.meaning(), {}, [], lifecycle)


@pytest.mark.parametrize("field", ["next_steps", "fact_rendering", "refund_summary"])
def test_new_composition_schema_does_not_ask_model_to_repeat_system_presentation(field):
    with pytest.raises(ValueError):
        Response.model_validate({"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "解释"}],
                                 field: "invalid"})


def test_wrong_line_or_missing_payment_does_not_make_refund_ready():
    req = request()
    p = plan(req)
    flow = Orchestration(req)
    flow.accept(p)
    refs = source_refs()
    refs["O3"]["data"]["order_line"]["line_id"] = "another-line"
    assert flow.snapshot(p.meaning(), refs, [], {})["tasks"][0]["missing"] == ["ORDER"]
    refs["O3"]["data"]["order_line"]["line_id"] = req.line_id
    del refs["O3"]["data"]["order_line"]["line_paid_amount"]
    assert flow.snapshot(p.meaning(), refs, [], {})["phase"] == "INVESTIGATE"


def test_retryable_failure_stays_in_investigation_and_evidence_supersedes_failure():
    req = request()
    p = plan(req)
    flow = Orchestration(req)
    flow.accept(p)
    failures = [{"tool_name": "get_order_context", "error": "UPSTREAM_UNAVAILABLE", "retry_allowed": True}]
    assert flow.snapshot(p.meaning(), {"O1": guide_source()}, failures, {})["phase"] == "INVESTIGATE"
    failures[0]["retry_allowed"] = False
    assert flow.snapshot(p.meaning(), source_refs(), failures, {})["tasks"][0]["state"] == "READY"


def test_prepared_refund_requires_reason_and_rejects_unobserved_references():
    req = request()
    p = plan(req)
    flow = Orchestration(req)
    flow.accept(p)
    value = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "待本人核对。"}]}
    with pytest.raises(ValueError, match="refund_reason"):
        flow.compose(Response.model_validate(value), p.meaning(), source_refs(), [], {})
    value["parts"][0]["citations"] = ["O99"]
    with pytest.raises(ValueError, match="citations"):
        flow.compose(Response.model_validate(value), p.meaning(), source_refs(), [], {})


def test_operation_goal_cannot_be_attached_to_unrelated_intent():
    with pytest.raises(ValueError, match="goal"):
        plan(request(), intent="LOGISTICS")


@pytest.mark.parametrize("life", ["PAUSED", "CANCELLED", "RESOLVED"])
def test_output_contract_for_inactive_goal_does_not_request_a_reason(life):
    req = request()
    p = plan(req)
    flow = Orchestration(req)
    flow.accept(p)
    contract = flow.response_contract(p.meaning(), {}, [], {"trace": life})
    assert set(contract["example"]) == {"kind", "parts"}
    assert contract["reason_fields"] == []


def test_output_contract_for_blocked_goal_does_not_suggest_a_usable_application():
    req = request()
    p = plan(req)
    flow = Orchestration(req)
    flow.accept(p)
    failures = [{"tool_name": "get_order_context", "error": "NOT_FOUND", "retry_allowed": False}]
    contract = flow.response_contract(p.meaning(), {"O1": guide_source()}, failures, {})
    assert "refund_reason" not in contract["example"]
    assert contract["reason_fields"] == []
