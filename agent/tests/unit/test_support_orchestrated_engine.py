"""Actual AgentScope loop with program readiness, not a second scripted controller."""

import json

import httpx

from resolveflow.support.engine import SupportAgent
from resolveflow.support.guide import guide_source
from resolveflow.support.progress import ProgressReporter
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_grounding import FactReads
from tests.unit.test_support_orchestration import plan


class Sources(FactReads):
    def read(self, name, arguments):
        if name == "get_support_guide":
            self.calls.append((name, arguments))
            return guide_source()
        return super().read(name, arguments)


def respond(**kwargs):
    return {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "请核对原因后再确认。"}],
            "refund_reason": "客户表示尚未收到商品，希望准备退款申请，待本人核对。", **kwargs}


def run(script, req=None, sources=None, **kwargs):
    model = TokenizedScript(mode="live", script=script)
    source = sources or Sources()
    agent = SupportAgent(req or request(), model, source, architecture="orchestrated-v1", **kwargs)
    return agent.run(), agent, model, source


def test_early_finish_continues_with_all_gaps_without_format_repair_or_model_ui_read():
    req = request()
    opening = plan(req, needs=["SHIPMENT"]).model_dump()
    result, agent, model, source = run([opening, read(), respond(), read("get_order_context"), respond()], req)
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert agent.repairs == 0 and model.calls == 5
    assert [name for name, _ in source.calls] == ["get_support_guide", "get_shipment_trace", "get_order_context"]
    assert result["spend"]["local_reads"] == 1 and result["spend"]["tool_attempts"] == 2
    assert model.packets[3]["orchestration"]["tasks"][0]["missing"] == ["ORDER"]
    assert model.packets[-1]["orchestration"]["phase"] == "COMPOSE"
    assert result["answer"]["refund_summary"].startswith("客户表示")
    assert "123.45 CNY" in result["answer"]["text"]
    assert "承运商记录结论：丢失" in result["answer"]["text"]


def test_repeated_early_finish_cannot_publish_or_reset_the_budget():
    result, agent, model, _ = run([plan(request()).model_dump(), respond(), respond(), respond()])
    assert result["status"] == "FAILED" and result["reason"] == "NO_PROGRESS"
    assert result["answer"] is None and agent.repairs == 0 and model.calls == 4


def test_pure_policy_has_no_ui_or_business_read_and_still_requires_relevant_policy_reference():
    req = request()
    value = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "须按条款核验条件。",
                                          "citations": ["P1"]}]}
    result, agent, model, source = run([plan(req, intent="ELIGIBILITY", goal="EXPLAIN", needs=[]).model_dump(),
                                      read("search_policy", query="签收争议的核验条件"), value], req)
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.calls == 3 and agent.repairs == 0
    assert [name for name, _ in source.calls] == ["search_policy"]
    assert "refund_summary" not in result["answer"]


def test_nonretryable_order_failure_is_an_honest_unavailable_answer():
    class Failed(Sources):
        def read(self, name, arguments):
            if name == "get_order_context":
                self.calls.append((name, arguments))
                return {"error": "FORBIDDEN", "retryable": False}
            return super().read(name, arguments)

    result, agent, _, _ = run([plan(request()).model_dump(), read("get_order_context"), respond(
        parts=[{"task_id": "trace", "text": "订单来源暂不可用，无法继续准备申请。"}], refund_reason=None)],
        sources=Failed())
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert agent.tasks.tasks[0].status == "UNAVAILABLE" and agent.repairs == 0
    assert "refund_summary" not in result["answer"]


def test_stream_hides_investigation_candidate_and_only_projects_ready_composition():
    batches = []
    reporter = ProgressReporter("http://synthetic.invalid", "run", "test", transport=httpx.MockTransport(
        lambda request: (batches.append(json.loads(request.content)) or httpx.Response(200))))

    class StreamingScript(TokenizedScript):
        def decide(self, **kwargs):
            reply = super().decide(**kwargs)
            reporter.content(json.dumps(reply.decision, ensure_ascii=False))
            return reply

    model = StreamingScript(mode="live", script=[plan(request()).model_dump(),
        respond(parts=[{"task_id": "trace", "text": "不应展示的提前正文"}]), read("get_order_context"), respond()])
    agent = SupportAgent(request(), model, Sources(), architecture="orchestrated-v1", progress=reporter)
    result = agent.run()
    reporter.close()
    assert result["status"] == "SUCCEEDED", result["reason"]
    events = [event for batch in batches for event in batch["events"]]
    text = "".join(event["payload"]["text"] for event in events if event["kind"] == "answer.delta")
    assert text == "请核对原因后再确认。"
    assert [event["attempt_id"] for event in events if event["kind"] == "answer.started"] == ["model-4"]


def test_fabricated_amount_is_still_rejected_after_program_compilation():
    bad = respond(parts=[{"task_id": "trace", "text": "本单实付999元。"}])
    result, agent, model, _ = run([plan(request()).model_dump(), read("get_order_context"), bad, bad])
    assert result["reason"] == "INVALID_DECISION" and result["answer"] is None
    assert agent.repairs == 1 and model.calls == 4


def test_explain_entry_generates_guide_but_no_refund_reason_or_current_order_read():
    req = request()
    result, agent, model, source = run([plan(req, goal="EXPLAIN").model_dump(), respond(refund_reason=None)], req)
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.calls == 2 and agent.repairs == 0
    assert source.calls == [("get_support_guide", {})]
    assert "refund_summary" not in result["answer"]


def test_actual_composition_request_has_goal_specific_complete_output_example():
    req = request()
    opening = plan(req, intent="HANDOFF", goal="MERCHANT_REVIEW").model_dump()
    final = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "请先核对共享内容。"}],
             "handoff_reason": "客户表示未收到，已排查家人和代收点，待本人确认后请商家核查。"}
    result, agent, model, _ = run([opening, final], req)
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert agent.repairs == 0
    system = model.conversations[-1][0].get_content_blocks()[0].text
    example = json.loads(system.split("本轮完整输出示例：\n", 1)[1])
    assert set(example) == {"kind", "parts", "handoff_reason"}
    assert example["parts"][0]["task_id"] == "trace"


def test_refund_request_contract_requires_its_own_reason_not_handoff_or_presentation_fields():
    result, _, model, _ = run([plan(request()).model_dump(), read("get_order_context"), respond()])
    assert result["status"] == "SUCCEEDED"
    system = model.conversations[-1][0].get_content_blocks()[0].text
    example = json.loads(system.split("本轮完整输出示例：\n", 1)[1])
    assert set(example) == {"kind", "parts", "refund_reason"}
