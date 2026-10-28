"""Corrections retain independent facts; summary references are resolved by the program."""

from copy import deepcopy

import pytest

from resolveflow.support.memory import CustomerMemory
from resolveflow.support.orchestration import Orchestration, Response
from tests.support_request_checks import approve_requests
from tests.unit.test_support_agent import request
from tests.unit.test_support_orchestrated_engine import run
from tests.unit.test_support_orchestration import plan, source_refs


def seeded_memory():
    req = request(input_version=1)
    req.context["current_request"] = "本人尚未收到；我仍未拿到；家人还没回复；外箱有破损"
    mem = CustomerMemory(req)
    mem.propose([{"topic": "RECEIPT", "reference": "CURRENT", "quote": q}
                 for q in ("本人尚未收到", "我仍未拿到", "家人还没回复")]
                + [{"topic": "MATERIAL", "reference": "CURRENT", "quote": "外箱有破损"}], [])
    next_req = request(input_version=3)
    next_req.context.update(current_request="包裹已找到，未收到的问题结束。", previous_customer_memory=mem.snapshot())
    return next_req, CustomerMemory(next_req)


@pytest.mark.parametrize("change,expected", [("REPLACE", "SUPERSEDED"), ("RETRACT", "RETRACTED")])
def test_one_explicit_correction_invalidates_all_selected_claims_and_keeps_independent_facts(change, expected):
    req, mem = seeded_memory()
    ids = [e["id"] for e in mem.entries[:2]]
    mem.propose([{"topic": "RECEIPT", "reference": "CURRENT", "quote": req.context["current_request"],
                  "change": change, "targets": ids}], [])
    assert mem.warnings == []
    assert [e["status"] for e in mem.entries] == [expected, expected, "ACTIVE", "ACTIVE", "ACTIVE"]
    assert mem.entries[-1]["supersedes" if change == "REPLACE" else "retracts"] == ids
    restored = request(input_version=5)
    restored.context["previous_customer_memory"] = mem.snapshot()
    assert [e["quote"] for e in CustomerMemory(restored).packet()["active"]] == [
        "家人还没回复", "外箱有破损", req.context["current_request"]]


@pytest.mark.parametrize("bad", ["missing", "different_topic", "duplicate", "both"])
def test_multi_target_correction_is_atomic_if_any_selected_target_is_invalid(bad):
    req, mem = seeded_memory()
    before = deepcopy(mem.snapshot())
    first = mem.entries[0]["id"]
    target = {"missing": "unknown", "different_topic": mem.entries[3]["id"], "duplicate": first,
              "both": mem.entries[1]["id"]}[bad]
    proposal = {"topic": "RECEIPT", "reference": "CURRENT", "quote": req.context["current_request"],
                "change": "REPLACE", "targets": [first, target]}
    if bad == "both":
        proposal["target"] = first
    mem.propose([proposal], [])
    assert mem.snapshot() == before and len(mem.warnings) == 1


def test_multi_target_extension_of_same_quote_is_atomic_and_idempotent():
    req, mem = seeded_memory()
    original_ids = [e["id"] for e in mem.entries[:2]]
    base = {"topic": "RECEIPT", "reference": "CURRENT", "quote": req.context["current_request"]}
    mem.propose([base], [])
    before = deepcopy(mem.snapshot())
    mem.propose([{**base, "change": "REPLACE", "targets": [original_ids[0], "unknown"]}], [])
    assert mem.snapshot() == before and mem.warnings
    correction = {**base, "change": "REPLACE", "targets": original_ids}
    mem.propose([correction, correction], [])
    assert not mem.warnings and len(mem.entries) == 5
    assert mem.entries[-1]["supersedes"] == original_ids


def test_summary_selects_only_bound_program_candidates_and_resolves_original_quote():
    req, mem = seeded_memory()
    flow = Orchestration(req)
    p = plan(req, intent="HANDOFF", goal="MERCHANT_REVIEW")
    flow.accept(p)
    approve_requests(flow, p.meaning())
    candidates = flow.quote_candidates(mem.packet()["active"])
    assert candidates[0] == {"ref": "CURRENT", "quote": req.context["current_request"]}
    old = mem.entries[0]
    assert {"ref": old["id"], "quote": old["quote"]} in candidates
    result = flow.compose(Response.model_validate({"kind": "RESPOND", "parts": [
        {"task_id": "trace", "text": "核查内容待您确认，不会自动共享。"}],
        "handoff_reason": {"customer_refs": [old["id"], "CURRENT"]}}),
        p.meaning(), source_refs(), [], {}, customer_claims=mem.packet()["active"])
    assert old["quote"] in result.handoff_summary and "未经核验" not in result.handoff_summary
    assert old["quote"] == old["source"]["quote"]
    assert "CURRENT" not in result.handoff_summary


@pytest.mark.parametrize("bad", ["H1", "foreign-claim", "SUPERSEDED-claim"])
def test_unknown_or_inactive_summary_reference_has_specific_feedback_and_cannot_publish(bad):
    req, mem = seeded_memory()
    flow = Orchestration(req)
    p = plan(req, intent="HANDOFF", goal="MERCHANT_REVIEW")
    flow.accept(p)
    approve_requests(flow, p.meaning())
    response = Response.model_validate({"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "待确认"}],
                                       "handoff_reason": {"customer_refs": [bad]}})
    with pytest.raises(ValueError, match="CURRENT") as error:
        flow.compose(response, p.meaning(), source_refs(), [], {}, customer_claims=mem.packet()["active"])
    assert bad in str(error.value)


def test_current_summary_candidate_is_never_a_blind_truncation_of_a_long_request():
    req = request()
    flow = Orchestration(req)
    opening = plan(req, intent="HANDOFF", goal="MERCHANT_REVIEW").model_dump()
    req.context["current_request"] = "请核查。" + "说明情况；" * 80 + "不要退款。"
    opening["focus"][0]["operation_request"] = "请核查。"
    from resolveflow.support.orchestration import TurnPlan

    flow.accept(TurnPlan.model_validate(opening))
    assert flow.quote_candidates([]) == [{"ref": "REQUEST-trace", "quote": "请核查。"}]


def test_real_loop_carries_candidates_and_repairs_an_unknown_ref_without_guessing_it():
    req, mem = seeded_memory()
    req.context["previous_customer_memory"]["entries"][0]["status"] = "SUPERSEDED"
    opening = plan(req, intent="HANDOFF", goal="MERCHANT_REVIEW").model_dump()
    final = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "供您核对，尚未发送。"}],
             "handoff_reason": {"customer_refs": ["CURRENT"]}}
    bad = deepcopy(final)
    bad["handoff_reason"]["customer_refs"] = ["H1"]
    result, agent, model, source = run([opening, bad, final], req)
    assert result["status"] == "SUCCEEDED" and agent.repairs == 1 and model.calls == 4
    refs = [c["ref"] for c in model.packets[-1]["summary_candidates"]]
    assert "CURRENT" in refs and mem.entries[0]["id"] not in refs
    assert "H1" in model.packets[-1]["feedback"] and "CURRENT" in model.packets[-1]["feedback"]
    assert req.context["current_request"] in result["answer"]["handoff_summary"]
    assert source.calls == [("get_support_guide", {})]


def test_resume_reuses_original_issue_while_changing_intent_and_goal():
    req = request(input_version=5)
    req.context["current_request"] = "继续原来的问题，请准备退款原因，我先核对。"
    req.context["previous_tasks"] = {"origin": "MODEL_PREVIOUS_TURN", "input_version": 3,
        "tasks": [{"id": "trace", "intent": "LOGISTICS", "request": "查询收货问题", "status": "SUSPENDED",
                   "lifecycle": "PAUSED"}]}
    opening = plan(req).model_dump()
    opening["dialogue_events"][0]["change"] = "RESUME"
    final = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "原因待本人确认，尚未提交。"}],
             "refund_reason": {"customer_refs": ["CURRENT"]}}
    from tests.unit.test_support_agent import read

    result, agent, model, _ = run([opening, read("get_order_context"), final], req)
    assert result["status"] == "SUCCEEDED" and agent.repairs == 0 and model.calls == 4
    tasks = result["answer"]["task_state"]["tasks"]
    assert [(t["id"], t["intent"], t["lifecycle"]) for t in tasks] == [("trace", "APPLICATION", "OPEN")]


def test_normal_investigation_does_not_expose_goal_review_contract():
    from tests.unit.test_support_agent import read

    req = request()
    final = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "原因待本人确认。"}],
             "refund_reason": {"customer_refs": ["CURRENT"]}}
    result, _, model, _ = run([plan(req).model_dump(), read("get_order_context"), final], req)
    assert result["status"] == "SUCCEEDED"
    investigation = model.conversations[1][0].get_content_blocks()[0].text
    assert "REVIEW_GOAL" not in investigation


def test_pause_acknowledgement_cannot_hide_a_new_policy_question_from_readiness():
    from resolveflow.support.orchestration import TurnPlan
    from tests.unit.test_support_agent import read

    req = request(input_version=3)
    req.context["current_request"] = "先不准备申请，只问这种情况的政策材料要求。"
    req.context["previous_tasks"] = {"origin": "MODEL_PREVIOUS_TURN", "input_version": 1,
        "tasks": [{"id": "trace", "intent": "APPLICATION", "request": "准备申请", "status": "ANSWERED"}]}
    bad = plan(req, goal="EXPLAIN", needs=["POLICY"]).model_dump()
    bad["dialogue_events"][0]["change"] = "PAUSE"
    with pytest.raises(ValueError, match="独立焦点"):
        TurnPlan.model_validate(bad)
    fixed = deepcopy(bad)
    fixed["focus"][0].update(id="policy", intent="OTHER")
    fixed["dialogue_events"].append({"change": "ADD", "task_ids": ["policy"], "reference": "CURRENT",
                                     "quote": req.context["current_request"]})
    final = {"kind": "RESPOND", "parts": [{"task_id": "policy", "text": "须按政策核验，未规定固定材料清单。",
                                            "citations": ["P1"]}]}
    result, agent, model, sources = run([bad, fixed, read("search_policy", query="当前场景的材料要求"), final], req)
    assert result["status"] == "SUCCEEDED" and agent.repairs == 1 and model.calls == 4
    assert "独立焦点" in model.packets[1]["feedback"]
    assert [name for name, _ in sources.calls] == ["get_support_guide", "search_policy"]
    assert {t["id"]: t["lifecycle"] for t in result["answer"]["task_state"]["tasks"]} == {
        "trace": "PAUSED", "policy": "OPEN"}
