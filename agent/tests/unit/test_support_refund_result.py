"""Program-owned result replies cannot acquire model-written arrival promises."""

import pytest

from resolveflow.support.grounding import ground_answer
from resolveflow.support.orchestration import Orchestration, Response
from tests.unit.test_support_agent import request
from tests.unit.test_support_orchestration import plan
from tests.unit.test_support_refund_facts import source


def compile_result(status="CLOSED_SUCCESS", amount=32900, message="模拟退款已完成"):
    req = request()
    accepted = plan(req, intent="OTHER", goal="EXPLAIN", needs=["ORDER"])
    flow = Orchestration(req)
    flow.accept(accepted)
    observed = source(status, amount)
    observed["data"]["refund_application"]["message"] = message
    response = Response.model_validate({"kind": "RESPOND", "parts": [
        {"task_id": "trace", "presentation": "REFUND_RESULT", "citations": ["O1"]}]})
    result = flow.compose(response, accepted.meaning(), {"O1": observed}, [], {})
    return ground_answer(result, req, {"O1": observed}, buyer_view=True)


def test_result_reply_is_generated_from_current_java_facts_and_never_model_prose():
    result = compile_result()
    assert result.parts[0].text == "这笔模拟退款已完成，金额329.00元，你不需要再操作。本次不涉及真实资金到账。"
    assert result.parts[0].guidance is None
    assert not result.parts[0].next_steps and not result.refund_summary


@pytest.mark.parametrize(("status", "message"), [
    ("AUTHORIZED", "退款已批准"), ("EXECUTING", "正在处理模拟退款"),
    ("RECONCILING", "模拟退款结果待确认"), ("PENDING_REVIEW", "等待商家核验申请情况"),
    ("CLOSED_REJECTED", "申请未获批准"), ("CANCELLED", "申请已撤销"),
])
def test_unfinished_or_other_terminal_results_never_turn_approved_amount_into_refunded_amount(status, message):
    text = compile_result(status, message=message).parts[0].text
    assert message in text
    assert "329" not in text and "已完成" not in text and "到账后" not in text


def test_completed_result_without_amount_keeps_the_gap_instead_of_using_paid_amount():
    text = compile_result(amount=None).parts[0].text
    assert "已完成" in text and "金额暂时无法确认" in text
    assert "329" not in text and "123.45" not in text


@pytest.mark.parametrize("extra", [{"text": "留意到账"}, {"guidance": "三个工作日到账"}])
def test_result_contract_rejects_model_supplements(extra):
    with pytest.raises(ValueError):
        Response.model_validate({"kind": "RESPOND", "parts": [
            {"task_id": "trace", "presentation": "REFUND_RESULT", **extra}]})


def test_missing_source_is_not_a_negative_application_result():
    req = request()
    accepted = plan(req, intent="OTHER", goal="EXPLAIN", needs=["ORDER"])
    flow = Orchestration(req)
    flow.accept(accepted)
    observed = source()
    del observed["data"]["refund_application"]
    response = Response.model_validate({"kind": "RESPOND", "parts": [
        {"task_id": "trace", "presentation": "REFUND_RESULT"}]})
    with pytest.raises(ValueError):
        flow.compose(response, accepted.meaning(), {"O1": observed}, [], {})


def test_result_cannot_prepare_an_application_or_replace_a_paused_task():
    req = request()
    accepted = plan(req)
    flow = Orchestration(req)
    flow.accept(accepted)
    response = Response.model_validate({"kind": "RESPOND", "parts": [
        {"task_id": "trace", "presentation": "REFUND_RESULT"}]})
    from tests.support_request_checks import approve_requests
    from tests.unit.test_support_orchestration import source_refs

    approve_requests(flow, accepted.meaning())
    for lives in ({}, {"trace": "PAUSED"}):
        with pytest.raises(ValueError, match="REFUND_RESULT"):
            flow.compose(response, accepted.meaning(), source_refs(), [], lives)


def test_result_and_an_independent_question_both_survive_the_normal_sdk_loop():
    from tests.unit.test_support_agent import read
    from tests.unit.test_support_orchestrated_engine import Sources, run

    req = request()
    req.context["current_request"] = "退款办完了吗？另外耳机怎么开启降噪？"
    opening = plan(req, intent="OTHER", goal="EXPLAIN", needs=["ORDER"]).model_dump()
    opening["focus"].append({"id": "product", "intent": "PRODUCT", "goal": "EXPLAIN",
                             "request": "询问耳机降噪操作", "needs": [], "context_refs": []})
    opening["dialogue_events"].append({"change": "ADD", "task_ids": ["product"],
                                       "reference": "CURRENT", "quote": "另外耳机怎么开启降噪"})

    class ResultSources(Sources):
        def read(self, name, arguments):
            if name == "get_order_context":
                self.calls.append((name, arguments))
                return source()
            return super().read(name, arguments)

    result, agent, _, _ = run([opening, read("get_order_context"), {"kind": "RESPOND", "parts": [
        {"task_id": "trace", "presentation": "REFUND_RESULT"},
        {"task_id": "product", "text": "暂时没有这款耳机的操作说明，可以查看商品随附说明书。"}]}],
        req=req, sources=ResultSources())
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert "329.00元" in result["answer"]["text"]
    assert "商品随附说明书" in result["answer"]["text"]
    assert len(result["answer"]["buyer_view"]["parts"]) == 2 and agent.repairs == 0
