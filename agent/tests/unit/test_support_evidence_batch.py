"""A model-selected general policy query can travel with independent bound fact reads."""

import pytest

from resolveflow.harness.budget import RunBudget
from tests.support_request_checks import checked_script
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_fact_batch import batch, final, script
from tests.unit.test_support_orchestrated_engine import Sources, respond, run
from tests.unit.test_support_orchestration import plan

QUERY = "签收未收到、运输中或丢失等物流情形的退款条件与人工核验要求"


def evidence_batch(query=QUERY):
    return {**batch(), "policy_query": query}


def fast_script():
    return checked_script([plan(request(), needs=["SHIPMENT"]).model_dump(), evidence_batch(), final()])


def test_same_evidence_and_answer_need_three_decisions_instead_of_four():
    previous, _, old_model, _ = run(script())
    result, agent, model, sources = run(fast_script())
    assert result["status"] == previous["status"] == "SUCCEEDED", result["reason"]
    assert model.calls == 4 and old_model.calls == 5 and agent.repairs == 0
    assert result["spend"]["tool_attempts"] == previous["spend"]["tool_attempts"] == 2
    assert result["spend"]["local_reads"] == previous["spend"]["local_reads"] == 2
    assert [n for n, _ in sources.calls] == ["get_support_guide", "get_order_context",
                                          "get_shipment_trace", "search_policy"]
    assert sources.calls[-1][1]["query"] == QUERY
    assert result["answer"] == previous["answer"]


@pytest.mark.parametrize("query", ["", "   ", "x" * 1001, {"line_id": "foreign"}, [QUERY]])
def test_invalid_queries_fail_before_any_child_read(query):
    bad = evidence_batch(query)
    result, agent, _, sources = run([fast_script()[0], bad, bad])
    assert result["status"] == "FAILED" and agent.repairs == 1
    assert sources.calls == [("get_support_guide", {})]


def test_model_can_investigate_related_policy_without_a_second_declaration_channel():
    opening = plan(request(), intent="LOGISTICS", goal="EXPLAIN", needs=["ORDER", "SHIPMENT"]).model_dump()
    answer = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "按相关条款需核验。",
                                            "citations": ["P1"]}]}
    result, agent, _, sources = run([opening, evidence_batch(), answer])
    assert result["status"] == "SUCCEEDED" and agent.repairs == 0
    assert [n for n, _ in sources.calls] == ["get_support_guide", "get_order_context",
                                          "get_shipment_trace", "search_policy"]
    assert sources.calls[-1][1]["query"] == QUERY


@pytest.mark.parametrize(("tool", "intent", "needs"), [
    ("get_order_context", "OTHER", ["ORDER", "POLICY"]),
    ("get_shipment_trace", "LOGISTICS", ["SHIPMENT", "POLICY"]),
])
def test_one_fact_and_one_policy_are_two_independent_guarded_reads(tool, intent, needs):
    opening = plan(request(), intent=intent, goal="EXPLAIN", needs=needs).model_dump()
    selected = {"kind": "READ_FACTS", "tools": [tool], "policy_query": QUERY}
    answer = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "按相关条款需核验。",
                                            "citations": ["P1"]}]}
    result, agent, model, sources = run([opening, selected, answer])
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.calls == 3 and agent.repairs == 0 and result["spend"]["tool_attempts"] == 1
    assert result["spend"]["local_reads"] == 2
    assert [n for n, _ in sources.calls] == ["get_support_guide", tool, "search_policy"]


def test_guide_and_policy_have_separate_local_budget_charges():
    result, _, model, sources = run(fast_script(), budget=RunBudget(local_reads=1))
    assert result["reason"] == "BUDGET_LOCAL_READS"
    assert model.calls == 3 and result["spend"]["tool_attempts"] == 2
    assert [n for n, _ in sources.calls] == ["get_support_guide", "get_order_context", "get_shipment_trace"]


def test_policy_failure_stays_unavailable_without_prepared_action():
    class Failed(Sources):
        def search(self, query, top_k):
            self.calls.append(("search_policy", {"query": query, "top_k": top_k}))
            return [{"error": "POLICY_INDEX_NOT_READY", "retryable": False}]

    unavailable = respond(parts=[{"task_id": "trace", "text": "政策来源暂不可用，无法完整解释处理条件。"}],
                          refund_reason=None)
    result, _, model, _ = run([fast_script()[0], evidence_batch(), unavailable], sources=Failed())
    assert result["status"] == "SUCCEEDED" and model.calls == 4
    assert result["answer"]["task_state"]["tasks"][0]["status"] == "UNAVAILABLE"
    assert not result["answer"].get("refund_summary")


def test_model_can_refine_query_after_actual_facts_disagree_with_original_premise():
    # A broad or mistaken first query is not an excuse to skip a newly relevant condition.
    revised = "实际物流记录为丢失时的退款条件"
    result, _, model, sources = run([fast_script()[0], evidence_batch("签收争议退款条件"),
                                     read("search_policy", query=revised), final()])
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.calls == 5
    assert [args["query"] for name, args in sources.calls if name == "search_policy"] == [
        "签收争议退款条件", revised]
