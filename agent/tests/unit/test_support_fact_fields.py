"""Versioned authoritative fact blocks, independently of model prose and legacy macros."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from resolveflow.support.grounding import GroundingError, check_amounts, ground_answer
from resolveflow.support.protocol import Answer, AnswerParts
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_grounding import FactReads
from tests.unit.test_support_staged import staged, understand


def candidate(text="请结合记录进一步核验。", fields=None):
    piece = part("trace", text)
    piece["facts"] = fields or [{"field": "SHIPMENT_STATUS", "source": "O1"}]
    return {**parts(piece), "fact_rendering": "fields-v1"}


@pytest.mark.parametrize("status,label", [("LOST", "丢失"), ("IN_TRANSIT", "运输中"),
                                         ("DELIVERED", "已签收")])
def test_fields_publish_through_sdk_without_macros_or_an_extra_model_round(status, label):
    class Sources(FactReads):
        def read(self, name, arguments):
            source = super().read(name, arguments)
            source["data"]["status"] = status
            return source

    req = request()
    result, model, _, agent = staged(req, [understand(req), read(), candidate()], Sources())
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert result["answer"]["text"] == "请结合记录进一步核验。\n\n物流状态：" + label + "。"
    assert [c["source_id"] for c in result["answer"]["citations"]] == ["O1"]
    assert model.calls == 3 and agent.repairs == 0


def test_single_answer_renders_authoritative_amount_not_product_price():
    req = request()
    req.context["product"]["amount_minor"] = 99900
    decision = Answer.model_validate({"kind": "ANSWER", "text": "退款申请需本人确认。",
        "fact_rendering": "fields-v1", "facts": [{"field": "PAID_AMOUNT", "source": "O1"}]})
    sources = {"O1": FactReads().read("get_order_context", {})}
    rendered = ground_answer(decision, req, sources)
    assert rendered.text == "退款申请需本人确认。\n\n订单行实付：123.45 CNY。"
    check_amounts(rendered, req, sources)
    assert decision.text == "退款申请需本人确认。" and decision.citations == []


@pytest.mark.parametrize("mutation", ["unread", "wrong_type", "wrong_line", "no_version", "error",
                                      "missing_value", "duplicate", "macro"])
def test_new_format_keeps_source_and_shape_failures(mutation):
    payload = candidate()
    sources = {"O1": FactReads().read("get_shipment_trace", {})}
    if mutation == "unread":
        sources.clear()
    elif mutation == "wrong_type":
        sources["O1"]["source_type"] = "POLICY"
    elif mutation == "wrong_line":
        sources["O1"]["data"]["line_id"] = "foreign"
    elif mutation == "no_version":
        del sources["O1"]["version"]
    elif mutation == "error":
        sources["O1"]["error"] = "unavailable"
    elif mutation == "missing_value":
        del sources["O1"]["data"]["status"]
    elif mutation == "duplicate":
        payload["parts"][0]["facts"] *= 2
    else:
        payload["parts"][0]["text"] = "物流{{SHIPMENT_STATUS}}。"
    with pytest.raises(GroundingError):
        ground_answer(AnswerParts.model_validate(payload), request(), sources)


def test_legacy_missing_macro_remains_rejected_and_old_valid_macro_still_renders():
    payload = candidate()
    del payload["fact_rendering"]
    sources = {"O1": FactReads().read("get_shipment_trace", {})}
    with pytest.raises(GroundingError, match="占位符"):
        ground_answer(AnswerParts.model_validate(payload), request(), sources)
    payload["parts"][0]["text"] = "物流{{SHIPMENT_STATUS}}。"
    rendered = ground_answer(AnswerParts.model_validate(payload), request(), sources)
    assert rendered.parts[0].text == "物流LOST。"


def test_new_fact_block_cannot_legitimize_wrong_literal_amount():
    sources = {"O1": FactReads().read("get_order_context", {})}
    payload = candidate("本单实付999元。", [{"field": "PAID_AMOUNT", "source": "O1"}])
    rendered = ground_answer(AnswerParts.model_validate(payload), request(), sources)
    with pytest.raises(GroundingError, match="数值一致"):
        check_amounts(rendered, request(), sources)


def test_render_limits_apply_after_fact_expansion_without_mutating_raw_candidate():
    payload = candidate("字" * 4000)
    before = deepcopy(payload)
    with pytest.raises(GroundingError, match="4000"):
        ground_answer(AnswerParts.model_validate(payload), request(),
                      {"O1": FactReads().read("get_shipment_trace", {})})
    assert payload == before


@pytest.mark.parametrize("mutation", ["version", "value", "part_version"])
def test_version_and_value_are_closed_contracts(mutation):
    payload = candidate()
    if mutation == "version":
        payload["fact_rendering"] = "fields-v99"
    elif mutation == "value":
        payload["parts"][0]["facts"][0]["value"] = "LOST"
    else:
        del payload["fact_rendering"]
        payload["parts"][0]["fact_rendering"] = "fields-v1"
    with pytest.raises(ValidationError):
        AnswerParts.model_validate(payload)


def test_multiple_fields_select_current_line_and_preserve_unknown_authoritative_status():
    payload = candidate(fields=[{"field": "SHIPMENT_STATUS", "source": "O1"},
                                {"field": "CARRIER_CONCLUSION", "source": "O1"}])
    sources = {"O1": {"source_type": "SHIPMENT", "version": 3, "data": {"lines": [
        {"line_id": "foreign", "status": "LOST", "carrier_conclusion": "LOST"},
        {"line_id": "line-A", "status": "IN_TRANSIT", "carrier_conclusion": "PENDING_CHECK"}]}}}
    rendered = ground_answer(AnswerParts.model_validate(payload), request(), sources)
    assert rendered.parts[0].text.endswith("物流状态：运输中。\n承运商记录结论：PENDING_CHECK。")
    assert rendered.parts[0].citations == ["O1"]
