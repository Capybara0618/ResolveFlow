"""Task tracking is model annotation, not a second router or a business authorization."""

from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from tests.unit.test_support_agent import Reads, answer, read, request


def task(key, intent="LOGISTICS", status="PENDING", **updates):
    return {"id": key, "intent": intent, "request": "确认物流并说明下一步", "status": status,
            "evidence_refs": [], "response_excerpt": None, **updates}


def test_mixed_tasks_share_the_existing_model_call_and_are_visible_after_a_read():
    pending = [task("delivery"), task("policy", "ELIGIBILITY", request="了解退款资格")]
    final = [task("delivery", status="ANSWERED", evidence_refs=["O1"], response_excerpt="系统有签收记录"),
             task("policy", "ELIGIBILITY", "NEEDS_MERCHANT", request="了解退款资格",
                  evidence_refs=["P1"], response_excerpt="可以请商家核验")]
    model = MockModelClient(script=[{**read(), "tasks": pending},
                                   {"kind": "SEARCH_POLICY", "query": "签收争议的核验条件", "top_k": 3},
                                   answer(tasks=final)])
    source = Reads()
    result = SupportAgent(request(), model, source).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.calls == 3 and len(source.calls) == 2
    assert model.packets[1]["task_state"]["origin"] == "MODEL"
    assert len(model.packets[1]["task_state"]["tasks"]) == 2
    assert result["answer"]["task_state"]["tasks"] == final


def test_answer_cannot_silently_drop_a_pending_subquestion_and_can_repair_once():
    initial = [task("delivery"), task("apply", "APPLICATION", request="退款在哪申请")]
    omitted = [task("delivery", status="ANSWERED", evidence_refs=["O1"], response_excerpt="系统有签收记录")]
    complete = [*omitted, task("apply", "APPLICATION", "UNAVAILABLE", request="退款在哪申请",
                              response_excerpt="办理入口尚未核实")]
    model = MockModelClient(script=[{**read(), "tasks": initial}, answer(tasks=omitted, citations=["O1"]),
                                   answer(text="系统有签收记录；办理入口尚未核实。", tasks=complete, citations=["O1"])])
    result = SupportAgent(request(), model, Reads()).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert '"field": "tasks"' in model.packets[2]["feedback"]
    assert [t["id"] for t in model.packets[2]["task_state"]["tasks"]] == ["delivery", "apply"]


def test_a_task_cannot_claim_a_future_source_or_a_response_absent_from_answer():
    model = MockModelClient(script=[
        {**read(), "tasks": [task("a", evidence_refs=["P99"])]},
        answer(citations=[], tasks=[task("a", status="ANSWERED", response_excerpt="根本没有出现在答案里")]),
    ])
    source = Reads()
    result = SupportAgent(request(), model, source).run()
    assert result["status"] == "FAILED" and result["reason"] == "INVALID_DECISION"
    assert source.calls == []


def test_live_decisions_require_initial_task_understanding_but_old_mock_scripts_still_work():
    live = MockModelClient(script=[answer(citations=[]), answer(citations=[])], mode="live")
    result = SupportAgent(request(), live, Reads()).run()
    assert result["status"] == "FAILED" and result["reason"] == "INVALID_DECISION"
    assert '"field": "tasks"' in live.packets[1]["feedback"]
    old = SupportAgent(request(), MockModelClient(script=[answer(citations=[])]), Reads()).run()
    assert old["status"] == "SUCCEEDED"  # compatibility, not proof of task understanding
