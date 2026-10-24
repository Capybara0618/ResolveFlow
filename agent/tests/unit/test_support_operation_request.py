"""Preparation goals require a current user request, not merely an application topic."""

import json
from pathlib import Path

import pytest

from resolveflow.support.orchestration import TurnPlan
from tests.unit.test_support_agent import request
from tests.unit.test_support_orchestrated_engine import run
from tests.unit.test_support_orchestration import plan


def test_saved_capability_question_cannot_accept_unexplained_operation_goal():
    raw = json.loads((Path(__file__).resolve().parents[3]
        / "reports/customer-agent-boundary-live-v1/runtime-results.json").read_text(encoding="utf-8"))
    row = next(r for r in raw["rows"] if r["id"] == "B02")
    with pytest.raises(ValueError, match="operation_request"):
        TurnPlan.model_validate(row["models"][0]["decision"])


@pytest.mark.parametrize("text", ["还能在原单补充吗？", "退款一般要满足什么条件？", "先别转交，我只问入口。"])
def test_explanation_has_no_operation_request_and_no_preparation_goal(text):
    req = request()
    req.context["current_request"] = text
    value = plan(req, intent="OTHER", goal="EXPLAIN").model_dump()
    value["focus"][0]["operation_request"] = None
    parsed = TurnPlan.model_validate(value)
    parsed.check_operation_requests(text)
    assert "operation_request" not in parsed.meaning().focus[0].model_dump()


@pytest.mark.parametrize("text,goal,intent", [
    ("能帮我整理一份给商家的摘要吗？", "MERCHANT_REVIEW", "HANDOFF"),
    ("请准备退款原因，稍后由我确认。", "PREPARE_REFUND", "APPLICATION"),
])
def test_polite_question_or_preparation_request_can_anchor_a_readonly_operation(text, goal, intent):
    req = request()
    req.context["current_request"] = text
    value = plan(req, intent=intent, goal=goal).model_dump()
    value["focus"][0]["operation_request"] = text
    parsed = TurnPlan.model_validate(value)
    parsed.check_operation_requests(text)
    with pytest.raises(ValueError, match="本轮原文"):
        parsed.check_operation_requests("上轮想做的先暂停，这次只问说明。")


def test_rejected_goal_can_repair_to_explanation_before_any_operation_state_is_accepted():
    req = request()
    req.context["current_request"] = "已解决后还能补充吗？"
    bad = plan(req, intent="HANDOFF", goal="MERCHANT_REVIEW").model_dump()
    bad["focus"][0].pop("operation_request", None)
    fixed = plan(req, intent="OTHER", goal="EXPLAIN", needs=["GUIDE"]).model_dump()
    response = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "可以，补充会接续原单。",
                                              "citations": ["O1"]}]}
    result, agent, model, _ = run([bad, fixed, response], req)
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.calls == 3 and agent.repairs == 1
    assert agent.orchestration.goals == {"trace": "EXPLAIN"}
    assert result["answer"]["handoff_summary"] is None
    assert "refund_summary" not in result["answer"]


def test_prompt_distinguishes_capability_and_polite_request_without_question_mark_routing():
    from resolveflow.support.orchestration_prompts import PLAN_SYSTEM

    assert "operation_request" in PLAN_SYSTEM
    assert "还能补充吗" in PLAN_SYSTEM and "能帮我整理摘要吗" in PLAN_SYSTEM
    assert "问号" in PLAN_SYSTEM
