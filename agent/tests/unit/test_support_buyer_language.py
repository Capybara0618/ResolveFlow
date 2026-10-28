"""Buyer prose uses observed values without publishing the internal fact dump."""

import pytest

from resolveflow.support.grounding import GroundingError, check_amounts, ground_answer
from resolveflow.support.navigation import render_navigation
from resolveflow.support.protocol import AnswerParts
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_fact_fields import candidate
from tests.unit.test_support_grounding import FactReads
from tests.unit.test_support_orchestrated_engine import respond, run
from tests.unit.test_support_orchestration import plan


def test_buyer_prose_uses_only_requested_fields_but_keeps_all_validated_sources():
    sources = {"O1": FactReads().read("get_shipment_trace", {})}
    raw = AnswerParts.model_validate(candidate("物流记录显示{{SHIPMENT_STATUS}}，还需要商家核实。", [
        {"field": "SHIPMENT_STATUS", "source": "O1"},
        {"field": "CARRIER_CONCLUSION", "source": "O1"}]))
    result = ground_answer(raw, request(), sources, buyer_view=True)
    assert result.parts[0].text == "物流记录显示丢失，还需要商家核实。"
    assert result.parts[0].facts == raw.parts[0].facts
    assert result.parts[0].citations == ["O1"]
    assert raw.parts[0].text.startswith("物流记录显示{{")


def test_buyer_amount_is_observed_paid_amount_in_yuan_not_display_price():
    req = request()
    req.context["product"]["amount_minor"] = 99900
    raw = AnswerParts.model_validate(candidate("这件商品实付{{PAID_AMOUNT}}。", [
        {"field": "PAID_AMOUNT", "source": "O1"}]))
    result = ground_answer(raw, req, {"O1": FactReads().read("get_order_context", {})}, buyer_view=True)
    assert result.parts[0].text == "这件商品实付123.45元。"
    check_amounts(result, req, {"O1": FactReads().read("get_order_context", {})})


@pytest.mark.parametrize("text", ["暂时还需要核实。", "物流显示{{SHIPMENT_STATUS}}。"])
def test_undisplayed_fact_still_requires_current_bound_source(text):
    raw = AnswerParts.model_validate(candidate(text))
    with pytest.raises(GroundingError):
        ground_answer(raw, request(), {}, buyer_view=True)


def test_unknown_carrier_code_stays_in_source_and_is_plain_language_in_prose():
    source = FactReads().read("get_shipment_trace", {})
    source["data"]["carrier_conclusion"] = "PENDING_CHECK"
    raw = AnswerParts.model_validate(candidate("承运商的核查结果{{CARRIER_CONCLUSION}}。", [
        {"field": "CARRIER_CONCLUSION", "source": "O1"}]))
    rendered = ground_answer(raw, request(), {"O1": source}, buyer_view=True)
    assert rendered.parts[0].text == "承运商的核查结果暂未确认。"
    assert source["data"]["carrier_conclusion"] == "PENDING_CHECK"


def test_no_unselected_slot_can_pass_the_buyer_renderer():
    raw = AnswerParts.model_validate(candidate("实付{{PAID_AMOUNT}}。"))
    with pytest.raises(GroundingError, match="占位符"):
        ground_answer(raw, request(), {"O1": FactReads().read("get_shipment_trace", {})}, buyer_view=True)


def test_production_composition_does_not_append_amount_status_and_click_tutorial():
    final = respond(parts=[{"task_id": "trace", "text": "请先核对申请原因。"}])
    result, agent, model, _ = run([plan(request()).model_dump(), read("get_order_context"), final])
    assert result["status"] == "SUCCEEDED", result["reason"]
    text = result["answer"]["text"]
    assert "订单状态：" not in text and "订单行实付：" not in text
    assert text == "请先核对申请原因。"
    assert result["answer"]["buyer_view"]["parts"][0]["action"] == "REFUND_APPLICATION"
    assert len(text) < 110
    assert result["answer"]["refund_summary"] == request().context["current_request"]
    order = next(c for c in result["answer"]["citations"] if c["source_type"] == "ORDER")
    assert order["data"]["order_line"]["line_paid_amount"] == 12345
    assert result["answer"]["citations"] and agent.repairs == 0 and model.calls == 3


def test_buyer_navigation_keeps_confirmation_and_privacy_without_internal_terms():
    from resolveflow.support.guide import guide_source
    from tests.unit.test_support_navigation import decision

    rendered = render_navigation(decision(["MERCHANT_REVIEW"]), {"O1": guide_source()}, program_owned=True)
    text = rendered.parts[0].text
    assert "确认" in text and "商家" in text and "私有聊天不会自动共享" in text
    assert "退款" in text and len(text) < 150
    assert "人工核查：打开" not in text


def test_stream_never_exposes_fact_slots_and_final_answer_uses_the_observed_value():
    import json

    import httpx

    from resolveflow.support.engine import SupportAgent
    from resolveflow.support.progress import ProgressReporter
    from tests.integration.test_support_dialogue_api import TokenizedScript
    from tests.unit.test_support_orchestrated_engine import Sources

    batches = []
    reporter = ProgressReporter("http://synthetic.invalid", "run", "test", transport=httpx.MockTransport(
        lambda req: (batches.append(json.loads(req.content)) or httpx.Response(200))))

    class StreamingScript(TokenizedScript):
        def decide(self, **kwargs):
            reply = super().decide(**kwargs)
            for char in json.dumps(reply.decision, ensure_ascii=False):
                reporter.content(char)
            return reply

    final = respond(parts=[{"task_id": "trace", "text": "这件商品实付{{PAID_AMOUNT}}。"}])
    model = StreamingScript(mode="live", script=[plan(request()).model_dump(), read("get_order_context"), final])
    try:
        result = SupportAgent(request(), model, Sources(), architecture="orchestrated-v1", progress=reporter).run()
    finally:
        reporter.close()
    streamed = "".join(event["payload"]["text"] for batch in batches for event in batch["events"]
                       if event["kind"] == "answer.delta")
    assert "{{" not in streamed and "PAID_AMOUNT" not in streamed
    assert result["status"] == "SUCCEEDED" and result["answer"]["text"].startswith("这件商品实付123.45元。")
    assert model.calls == 3


def test_prepared_refund_status_does_not_repeat_the_confirmation_card_walkthrough():
    from resolveflow.support.guide import guide_source
    from tests.unit.test_support_navigation import decision

    raw = decision(["REFUND_APPLICATION"]).model_copy(update={"refund_summary": "耳机一直没收到"})
    rendered = render_navigation(raw, {"O1": guide_source()}, program_owned=True)
    text = rendered.parts[0].text
    assert text.endswith("退款申请还没提交，确认后交商家审核；私有聊天不会自动共享。")
    assert "下方卡片准备好" not in text and "再点击" not in text
    assert rendered.refund_summary == "耳机一直没收到"
    assert rendered.parts[0].next_steps == []
