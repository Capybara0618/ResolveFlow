"""Model-proposed conversation changes must have current customer anchors and consistent task transitions."""

from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from tests.unit.test_support_agent import Reads, answer, read, request
from tests.unit.test_support_context import message
from tests.unit.test_support_tasks import task


def event(kind, task_id, quote, **updates):
    return {"change": kind, "task_id": task_id, "reference": "CURRENT", "offset": 0,
            "quote": quote, **updates}


def previous(req, tasks):
    req.context["previous_tasks"] = {"origin": "MODEL_PREVIOUS_TURN", "input_version": 1, "tasks": tasks}


def test_interruption_pauses_old_task_and_new_subquestion_does_not_delete_it():
    req = request(input_version=5)
    text = "先问一下退款在哪申请，签收问题稍后继续。"
    req.context["current_request"] = text
    previous(req, [task("trace", status="NEEDS_MERCHANT", evidence_refs=["O8"])])
    tasks = [task("trace", status="SUSPENDED", response_excerpt="签收核查保留，稍后继续"),
             task("entry", "APPLICATION", "ANSWERED", response_excerpt="办理入口需先核实")]
    model = MockModelClient(script=[answer(text="签收核查保留，稍后继续。办理入口需先核实。", citations=[], tasks=tasks,
                                          dialogue_events=[event("PAUSE", "trace", text),
                                                           event("ADD", "entry", text)])])
    result = SupportAgent(req, model, Reads()).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    state = result["answer"]["dialogue_state"]
    assert [e["change"] for e in state["events"]] == ["PAUSE", "ADD"]
    assert state["events"][0]["source"]["sequence"] == 5
    assert result["answer"]["task_state"]["tasks"][0]["evidence_refs"] == []


def test_suspended_task_can_resume_then_use_new_run_evidence():
    req = request(input_version=5)
    text = "回到刚才签收核查的问题，继续查吧。"
    req.context["current_request"] = text
    previous(req, [task("trace", status="SUSPENDED")])
    model = MockModelClient(script=[{**read(), "tasks": [task("trace")],
                                    "dialogue_events": [event("RESUME", "trace", text)]},
                                   answer(citations=["O1"], tasks=[task("trace", status="NEEDS_MERCHANT",
                                          evidence_refs=["O1"], response_excerpt="可以请商家核验")])])
    result = SupportAgent(req, model, Reads()).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.packets[1]["dialogue_state"]["events"][0]["change"] == "RESUME"
    assert result["answer"]["task_state"]["tasks"][0]["evidence_refs"] == ["O1"]


def test_cancellation_is_explicit_and_missing_old_task_is_not_silently_accepted():
    req = request(input_version=5)
    text = "家人找到了，不要退款也不用核查了。"
    req.context["current_request"] = text
    previous(req, [task("trace", status="NEEDS_MERCHANT")])
    new = task("new", "OTHER", "ANSWERED", response_excerpt="已记录")
    model = MockModelClient(script=[answer(text="已记录。", citations=[], tasks=[new],
                                          dialogue_events=[event("ADD", "new", text)]),
                                   answer(text="已记录，不再核查。", citations=[],
                                          tasks=[task("trace", status="CANCELLED")],
                                          dialogue_events=[event("CANCEL", "trace", text)])])
    result = SupportAgent(req, model, Reads()).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert '"field": "dialogue_events"' in model.packets[1]["feedback"]
    assert result["answer"]["task_state"]["tasks"][0]["status"] == "CANCELLED"


def test_live_first_decision_requires_explicit_change_but_not_an_extra_classifier_call():
    req = request()
    t = task("a", status="ANSWERED", response_excerpt="已记录")
    model = MockModelClient(script=[answer(text="已记录。", citations=[], tasks=[t]),
                                   answer(text="已记录。", citations=[], tasks=[t], dialogue_events=[
                                       event("ADD", "a", req.context["current_request"])])], mode="live")
    result = SupportAgent(req, model, Reads()).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert '"field": "dialogue_events"' in model.packets[1]["feedback"] and model.calls == 2


def test_invalid_resume_and_old_message_cannot_authorize_a_current_change():
    req = request(input_version=5)
    req.context["current_request"] = "继续"
    previous(req, [task("trace", status="NEEDS_MERCHANT")])
    model = MockModelClient(script=[{**read(), "tasks": [task("trace")],
                                    "dialogue_events": [event("RESUME", "trace", "继续")]},
                                   answer(text="请说明需要继续哪件事。", citations=[], tasks=[
                                       task("trace", status="NEEDS_CUSTOMER", response_excerpt="请说明需要继续哪件事")],
                                       dialogue_events=[event("CLARIFY", "trace", "继续")])])
    source = Reads()
    result = SupportAgent(req, model, source).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert source.calls == [] and '"field": "dialogue_events"' in model.packets[1]["feedback"]


def test_old_cancellation_quote_cannot_cancel_the_current_request():
    req = request(input_version=5)
    req.context.update(current_request="继续核查", history=[message(1, "不用查了")])
    previous(req, [task("trace", status="NEEDS_MERCHANT")])
    model = MockModelClient(script=[answer(citations=[], tasks=[task("trace", status="CANCELLED")],
                                          dialogue_events=[event("CANCEL", "trace", "不用查了", reference="H1")]),
                                   answer(citations=[], tasks=[task("trace", status="NEEDS_MERCHANT",
                                          response_excerpt="可以请商家核验")], dialogue_events=[
                                       event("CONTINUE", "trace", "继续核查")])])
    result = SupportAgent(req, model, Reads()).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert result["answer"]["task_state"]["tasks"][0]["status"] == "NEEDS_MERCHANT"
    assert len(result["answer"]["dialogue_state"]["events"]) == 1
