"""Explanations and accepted commands share evidence but not a forced execution route."""

import pytest

from resolveflow.support.navigation import NavigationError, render_navigation
from tests.unit.test_support_agent import request
from tests.unit.test_support_orchestrated_engine import run
from tests.unit.test_support_orchestration import plan


@pytest.mark.parametrize("intent,text", [
    ("OTHER", "售后咨询保留原核查记录，已解决后仍可以接续。"),
    ("HANDOFF", "没有。表达想找人工不等于已经发给商家；目前没有已提交核查记录。"),
    ("APPLICATION", "我的售后展示已经提交的申请；本轮只是说明入口，没有替你创建申请。"),
])
def test_explain_pages_or_submission_state_does_not_turn_into_an_application(intent, text):
    req = request()
    req.context["conversation_state"] = {"has_ticket": False, "current_recipient": "ASSISTANT",
                                          "default_recipient": "ASSISTANT"}
    opening = plan(req, intent=intent, goal="EXPLAIN", needs=["GUIDE"]).model_dump()
    final = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": text, "citations": ["O1"]}]}
    result, agent, model, sources = run([opening, final], req)
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert result["answer"]["text"] == text
    assert "refund_summary" not in result["answer"] and result["answer"]["handoff_summary"] is None
    assert agent.repairs == 0 and model.calls == 2
    assert sources.calls == [("get_support_guide", {})]


def test_explicit_handoff_preserves_direct_explanation_even_with_only_guide_evidence():
    req = request()
    req.context["conversation_state"] = {"has_ticket": True, "ticket_status": "RESOLVED"}
    text = "可以，已解决后再次补充会接续原记录，之前的沟通仍保留。"
    opening = plan(req, intent="HANDOFF", goal="MERCHANT_REVIEW").model_dump()
    final = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": text, "citations": ["O1"]}],
             "handoff_reason": "客户希望在原核查单补充说明新的问题，待本人核对。"}
    result, agent, _, _ = run([opening, final], req)
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert result["answer"]["text"].startswith(text + "\n\n")
    assert result["answer"]["text"].count("补充给商家") == 1
    assert "请商家核查" not in result["answer"]["text"] and agent.repairs == 0


def test_observed_guide_can_ground_page_explanation_without_model_selecting_an_action():
    from resolveflow.support.guide import guide_source
    from tests.unit.test_support_navigation import decision

    original = decision([], text="售后咨询与我的售后是不同记录入口。")
    rendered = render_navigation(original, {"O1": guide_source()}, strict=True, program_owned=True)
    assert rendered.parts[0].text == original.parts[0].text
    assert rendered.parts[0].citations == ["O1"]
    assert not rendered.parts[0].next_steps
    with pytest.raises(NavigationError):
        render_navigation(original, {}, strict=True, program_owned=True)
    with pytest.raises(NavigationError):
        render_navigation(decision([], text="在我的售后点击请商家核查。"), {"O1": guide_source()},
                          strict=True, program_owned=True)


def test_only_accepted_operation_goals_require_steps_and_cancelled_goals_require_none():
    from resolveflow.support.orchestration import Orchestration

    req = request()
    for goal, intent, expected in [("EXPLAIN", "HANDOFF", {}),
                                   ("MERCHANT_REVIEW", "HANDOFF", {"trace": "MERCHANT_REVIEW"}),
                                   ("PREPARE_REFUND", "APPLICATION", {"trace": "REFUND_APPLICATION"})]:
        flow = Orchestration(req)
        flow.accept(plan(req, goal=goal, intent=intent))
        assert flow.required_actions({}) == expected
        assert flow.required_actions({"trace": "PAUSED"}) == {}


def test_streamed_direct_explanation_is_preserved_when_program_appends_handoff_instructions():
    import json

    import httpx

    from resolveflow.support.engine import SupportAgent
    from resolveflow.support.progress import ProgressReporter
    from tests.integration.test_support_dialogue_api import TokenizedScript
    from tests.unit.test_support_orchestrated_engine import Sources

    batches = []
    reporter = ProgressReporter("http://synthetic.invalid", "run", "test", transport=httpx.MockTransport(
        lambda req: (batches.append(json.loads(req.content)) or httpx.Response(200))))
    text = "您选择的原文可以单独共享，其他私有聊天不会默认发给商家。"
    req = request()
    opening = plan(req, intent="HANDOFF", goal="MERCHANT_REVIEW").model_dump()
    final = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": text, "citations": ["O1"]}],
             "handoff_reason": "客户希望商家核查，待本人确认所选原文和摘要后共享。"}

    class Script(TokenizedScript):
        def decide(self, **kwargs):
            reply = super().decide(**kwargs)
            reporter.content(json.dumps(reply.decision, ensure_ascii=False))
            return reply

    model = Script(script=[opening, final], mode="live")
    try:
        result = SupportAgent(req, model, Sources(), architecture="orchestrated-v1", progress=reporter).run()
    finally:
        reporter.close()
    assert result["status"] == "SUCCEEDED", result["reason"]
    events = [event for batch in batches for event in batch["events"]]
    streamed = "".join(e["payload"]["text"] for e in events if e["kind"] == "answer.delta")
    assert streamed == text and result["answer"]["text"].startswith(streamed + "\n\n")
    assert "确认后才转交商家" in result["answer"]["text"]
