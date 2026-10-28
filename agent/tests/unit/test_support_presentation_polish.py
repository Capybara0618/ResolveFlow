"""Repeated evidence can serve multiple tasks without repeating its rendered field block."""

from copy import deepcopy

import pytest

from resolveflow.support.grounding import GroundingError, ground_answer
from resolveflow.support.guide import guide_source
from resolveflow.support.navigation import render_navigation
from resolveflow.support.protocol import AnswerParts
from tests.unit.test_support_agent import request
from tests.unit.test_support_grounding import FactReads


def candidate():
    return AnswerParts.model_validate({"kind": "ANSWER_PARTS", "fact_rendering": "fields-v1", "parts": [
        {"task_id": "trace", "status": "ANSWERED", "text": "物流接口提供当前记录。",
         "facts": [{"field": "SHIPMENT_STATUS", "source": "O1"}]},
        {"task_id": "draft", "status": "ANSWERED", "text": "请核对退款原因。",
         "facts": [{"field": "SHIPMENT_STATUS", "source": "O1"}],
         "next_steps": [{"action": "REFUND_APPLICATION", "source": "O2"}]}],
         "refund_summary": "客户陈述：未收到，待本人核对确认。"})


def test_program_fact_dedup_keeps_each_task_evidence_and_independent_summary():
    value = candidate()
    original = value.model_dump()
    source = {"O1": FactReads().read("get_shipment_trace", {})}
    rendered = ground_answer(value, request(), source, deduplicate=True)
    assert sum(p.text.count("物流状态：丢失。") for p in rendered.parts) == 1
    assert rendered.parts[0].citations == rendered.parts[1].citations == ["O1"]
    assert rendered.parts[1].facts == value.parts[1].facts
    assert rendered.refund_summary == value.refund_summary
    assert value.model_dump() == original


def test_different_observations_are_never_collapsed_even_if_the_field_matches():
    value = candidate()
    value.parts[1].facts[0].source = "O3"
    first = FactReads().read("get_shipment_trace", {})
    second = deepcopy(first)
    second["version"] = 4
    second["data"]["status"] = "DELIVERED"
    result = ground_answer(value, request(), {"O1": first, "O3": second}, deduplicate=True)
    assert "物流状态：丢失。" in result.parts[0].text
    assert "物流状态：已签收。" in result.parts[1].text


def test_dedup_does_not_hide_invalid_duplicate_within_one_part():
    value = candidate()
    value.parts[1].facts *= 2
    with pytest.raises(GroundingError, match="唯一"):
        ground_answer(value, request(), {"O1": FactReads().read("get_shipment_trace", {})}, deduplicate=True)


def test_legacy_renderer_remains_unchanged_without_program_dedup():
    result = ground_answer(candidate(), request(), {"O1": FactReads().read("get_shipment_trace", {})})
    assert all("物流状态：丢失。" in p.text for p in result.parts)


def test_prepared_summary_guidance_does_not_send_user_back_to_entry_button():
    result = render_navigation(candidate(), {"O2": guide_source()}, program_owned=True)
    text = result.parts[1].text
    assert '点击“申请退款”' not in text
    assert "卡片" in text and "确认提交申请" in text
    assert "还没提交" in text and "商家审核" in text


def test_no_summary_keeps_generic_entry_and_merchant_guidance_separate():
    value = candidate().model_copy(update={"refund_summary": None})
    result = render_navigation(value, {"O2": guide_source()}, program_owned=True)
    assert '点击“申请退款”' in result.parts[1].text


def test_staged_compatibility_does_not_change_existing_instructions():
    result = render_navigation(candidate(), {"O2": guide_source()}, program_owned=False)
    assert '点击“申请退款”' in result.parts[1].text
