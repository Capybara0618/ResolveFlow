"""Refund results are current buyer facts, never inferred from payment or inquiry state."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from resolveflow.support.grounding import GroundingError, check_amounts, ground_answer, value_for
from resolveflow.support.orchestration import Orchestration, Response
from resolveflow.support.protocol import AnswerParts
from tests.unit.test_support_agent import request
from tests.unit.test_support_fact_fields import candidate
from tests.unit.test_support_orchestration import plan


def source(status="CLOSED_SUCCESS", amount=32900):
    fixture = Path(__file__).resolve().parents[3] / "fixtures/support-order-refund-facts.json"
    result = json.loads(fixture.read_text(encoding="utf-8"))["completed"]
    result["data"]["refund_application"].update(status=status, amount_minor=amount)
    return result


def test_completed_refund_uses_refunded_amount_even_when_the_paid_amount_is_different():
    observed = source()
    raw = AnswerParts.model_validate(candidate("这笔{{REFUND_STATUS}}，已退{{REFUNDED_AMOUNT}}，不需要再次申请。", [
        {"field": "REFUND_STATUS", "source": "O1"}, {"field": "REFUNDED_AMOUNT", "source": "O1"}]))
    result = ground_answer(raw, request(), {"O1": observed}, buyer_view=True)
    assert result.parts[0].text == "这笔模拟退款已完成，已退329.00元，不需要再次申请。"
    check_amounts(result, request(), {"O1": observed})
    assert observed["data"]["order_line"]["line_paid_amount"] == 12345


@pytest.mark.parametrize("status", ["AUTHORIZED", "EXECUTING", "RECONCILING", "PENDING_REVIEW", "CLOSED_REJECTED"])
def test_approved_or_unknown_amount_is_never_rendered_as_money_already_refunded(status):
    with pytest.raises(GroundingError):
        value_for("REFUNDED_AMOUNT", source(status), request())


@pytest.mark.parametrize("change", ["missing", "foreign", "failed", "currency", "amount"])
def test_incomplete_or_wrong_subject_refund_facts_cannot_be_completed_from_payment(change):
    observed = source()
    application = observed["data"]["refund_application"]
    if change == "missing":
        del observed["data"]["refund_application"]
    elif change == "foreign":
        application["line_id"] = "line-foreign"
    elif change == "failed":
        observed["error"] = "UNAVAILABLE"
    elif change == "currency":
        application["currency"] = "USD"
    else:
        application["amount_minor"] = None
    with pytest.raises(GroundingError):
        value_for("REFUNDED_AMOUNT", observed, request())


def test_no_application_requires_an_explicit_authoritative_negative():
    observed = source()
    observed["data"]["refund_application"] = {"present": False, "status": "NONE"}
    assert value_for("REFUND_STATUS", observed, request()) == "尚未提交退款申请"
    missing = deepcopy(observed)
    del missing["data"]["refund_application"]
    with pytest.raises(GroundingError):
        value_for("REFUND_STATUS", missing, request())


def test_order_focus_compiles_current_refund_fields_into_the_existing_answer_path():
    req = request()
    req.context["conversation_state"] = {"has_ticket": False}
    accepted = plan(req, intent="OTHER", goal="EXPLAIN", needs=["ORDER"])
    flow = Orchestration(req)
    flow.accept(accepted)
    compiled = flow.compose(Response.model_validate({"kind": "RESPOND", "parts": [
        {"task_id": "trace", "text": "{{REFUND_STATUS}}，已退{{REFUNDED_AMOUNT}}。"}]}),
        accepted.meaning(), {"O1": source()}, [], {})
    rendered = ground_answer(compiled, req, {"O1": source()}, buyer_view=True)
    assert rendered.parts[0].text == "模拟退款已完成，已退329.00元。"
    assert not rendered.refund_summary and not rendered.parts[0].next_steps
