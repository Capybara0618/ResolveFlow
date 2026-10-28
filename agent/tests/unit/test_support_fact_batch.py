"""One model-selected pair saves a decision while retaining two guarded business reads."""

import json

import httpx
import pytest

from resolveflow.harness.budget import RunBudget
from resolveflow.support.engine import SupportAgent
from resolveflow.support.progress import ProgressReporter
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_orchestrated_engine import Sources, respond, run
from tests.unit.test_support_orchestration import plan


def batch(tools=None):
    return {"kind": "READ_FACTS", "tools": tools or ["get_order_context", "get_shipment_trace"]}


def final():
    return respond(parts=[{"task_id": "trace", "text": "实付{{PAID_AMOUNT}}。按相关条款需核验争议，草稿不等于批准。",
                           "citations": ["P1"]}])


def script(*, paired=True, reverse=False):
    actions = [batch(["get_shipment_trace", "get_order_context"] if reverse else None)] if paired else [
        read("get_order_context"), read()]
    return [plan(request(), needs=["SHIPMENT"]).model_dump(), *actions,
            read("search_policy", query="物流争议的核验条件"), final()]


@pytest.mark.parametrize("reverse", [True, False])
def test_pair_keeps_answer_evidence_and_two_tool_charges_with_one_less_model_decision(reverse):
    regular, _, regular_model, _ = run(script(paired=False))
    result, agent, model, sources = run(script(reverse=reverse))
    assert result["status"] == regular["status"] == "SUCCEEDED", result["reason"]
    assert model.calls == 4 and regular_model.calls == 5
    assert agent.repairs == 0
    assert result["spend"]["tool_attempts"] == regular["spend"]["tool_attempts"] == 2
    assert result["spend"]["local_reads"] == regular["spend"]["local_reads"] == 2
    assert {c["source_type"] for c in result["answer"]["citations"]} == {"ORDER", "SHIPMENT", "POLICY", "KNOWLEDGE"}
    assert {name for name, _ in sources.calls} == {"get_support_guide", "get_order_context",
                                                  "get_shipment_trace", "search_policy"}
    assert "实付123.45元" in result["answer"]["text"] and "123.45 CNY" in result["answer"]["refund_summary"]


@pytest.mark.parametrize("invalid", [
    {"kind": "READ_FACTS", "tools": ["get_order_context"]},
    batch(["get_order_context", "get_order_context"]),
    batch(["get_order_context", "search_policy"]),
    batch(["get_order_context", "refund"]),
    {**batch(), "line_id": "foreign"},
    {**batch(), "arguments": {"line_id": "foreign"}},
])
def test_invalid_pairs_never_reach_business_sources(invalid):
    result, agent, _, sources = run([plan(request(), needs=["SHIPMENT"]).model_dump(), invalid, invalid])
    assert result["status"] == "FAILED" and agent.repairs == 1
    assert sources.calls == [("get_support_guide", {})]


def test_pair_uses_same_bound_read_permissions_even_when_order_was_not_a_declared_need():
    answer = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "承运记录不等于本人收到。"}]}
    result, agent, _, sources = run([plan(request(), intent="LOGISTICS", goal="EXPLAIN", needs=[]).model_dump(),
                                    batch(), answer])
    assert result["status"] == "SUCCEEDED" and agent.repairs == 0
    assert sources.calls == [("get_support_guide", {}), ("get_order_context", {}), ("get_shipment_trace", {})]
    assert result["spend"]["tool_attempts"] == 2


def test_each_fact_still_consumes_budget_and_second_read_cannot_bypass_limit():
    result, _, model, sources = run(script(), budget=RunBudget(tool_attempts=1))
    assert result["status"] == "FAILED"
    assert model.calls == 2
    assert [name for name, _ in sources.calls] == ["get_support_guide", "get_order_context"]
    assert result["spend"]["tool_attempts"] == 1


def test_first_source_failure_does_not_fabricate_success_or_skip_second_independent_read():
    class Failed(Sources):
        def read(self, name, arguments):
            if name == "get_order_context":
                self.calls.append((name, arguments))
                return {"error": "FORBIDDEN", "retryable": False}
            return super().read(name, arguments)

    result, agent, _, sources = run([plan(request(), needs=["SHIPMENT"]).model_dump(), batch()], sources=Failed())
    assert result["status"] == "FAILED"  # Script deliberately has no final answer.
    assert [name for name, _ in sources.calls] == ["get_support_guide", "get_order_context", "get_shipment_trace"]
    assert agent._readiness()["tasks"][0]["missing"] == ["ORDER", "POLICY"]


def test_batch_investigation_does_not_leak_candidate_body_into_stream():
    batches = []
    reporter = ProgressReporter("http://synthetic.invalid", "run", "test", transport=httpx.MockTransport(
        lambda r: (batches.append(json.loads(r.content)) or httpx.Response(200))))

    class Stream(TokenizedScript):
        def decide(self, **kwargs):
            reply = super().decide(**kwargs)
            reporter.content(json.dumps(reply.decision, ensure_ascii=False))
            return reply

    model = Stream(mode="live", script=script())
    result = SupportAgent(request(), model, Sources(), architecture="orchestrated-v1", progress=reporter).run()
    reporter.close()
    assert result["status"] == "SUCCEEDED", result["reason"]
    events = [e for b in batches for e in b["events"]]
    assert {e["attempt_id"] for e in events if e["kind"] == "answer.delta"} == {"model-4"}
    assert [e["payload"]["category"] for e in events if e["kind"] == "activity.started"] == [
        "GUIDE", "ORDER", "SHIPMENT", "POLICY"]
