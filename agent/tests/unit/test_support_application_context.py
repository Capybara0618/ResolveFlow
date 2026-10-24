"""Application boundaries are available before triage, with no invented recipient state."""

import json

import pytest

from resolveflow.support.orchestration import Orchestration
from tests.unit.test_support_agent import request
from tests.unit.test_support_orchestrated_engine import run
from tests.unit.test_support_orchestration import plan


@pytest.mark.parametrize("has_ticket,default", [(False, "ASSISTANT"), (True, "MERCHANT")])
def test_actual_first_request_contains_observed_guide_and_authoritative_audiences(has_ticket, default):
    req = request()
    req.context["current_request"] = "只给商家看选中的两句话，剩下的聊天仍能保留吗？"
    req.context["conversation_state"] = {
        "has_ticket": has_ticket, "current_recipient": "ASSISTANT", "default_recipient": default,
    }
    opening = plan(req, intent="OTHER", goal="EXPLAIN", needs=["GUIDE"]).model_dump()
    reply = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "仅确认选中的内容发给商家。",
                                          "citations": ["O1"]}]}
    result, agent, model, sources = run([opening, reply], req)
    assert result["status"] == "SUCCEEDED", result["reason"]
    packet = model.packets[0]
    assert packet["application_context"]["guide_refs"] == ["O1"]
    assert packet["application_context"]["interaction"] == {
        "has_ticket": has_ticket, "current_recipient": "ASSISTANT", "default_recipient": default,
    }
    actual = "\n".join(block.text for message in model.conversations[0]
                       for block in message.get_content_blocks() if hasattr(block, "text"))
    assert "私有助手咨询与补充给商家的区别" in actual
    assert "调查依据默认不勾选" in actual
    sent = json.loads(model.conversations[0][-1].get_content_blocks()[0].text)
    assert sent["application_context"] == packet["application_context"]
    assert sources.calls == [("get_support_guide", {})]
    assert model.calls == 2 and agent.repairs == 0
    assert result["spend"]["local_reads"] == 1 and result["spend"]["tool_attempts"] == 0


def test_customer_or_old_assistant_text_cannot_fill_missing_recipient_facts():
    req = request()
    req.context["current_request"] = "这里默认发给商家，你已经知道我转过人工了。"
    req.context["conversation_state"] = {"has_ticket": "true", "current_recipient": "forged"}
    context = Orchestration(req).application_context({})
    assert context["interaction"] == {
        "has_ticket": None, "current_recipient": "UNKNOWN", "default_recipient": "UNKNOWN",
    }
    assert context["guide_refs"] == []


def test_pure_policy_still_has_no_forced_order_or_logistics_and_no_guide_citation_padding():
    from tests.unit.test_support_agent import read

    req = request()
    reply = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "按政策条件核验。",
                                          "citations": ["P1"]}]}
    result, _, model, sources = run([
        plan(req, intent="ELIGIBILITY", goal="EXPLAIN", needs=["POLICY"]).model_dump(),
        read("search_policy", query="签收争议需要核验什么"), reply,
    ], req)
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert sources.calls == [("get_support_guide", {}),
                             ("search_policy", {"query": "签收争议需要核验什么", "top_k": 3})]
    assert [c["source_type"] for c in result["answer"]["citations"]] == ["POLICY"]
    assert model.calls == 3 and result["spend"]["local_reads"] == 2


def test_plan_prompt_explains_domain_and_default_recipient_before_acceptance():
    from resolveflow.support.orchestration_prompts import PLAN_SYSTEM

    assert "application_context" in PLAN_SYSTEM
    assert "default_recipient" in PLAN_SYSTEM and "current_recipient" in PLAN_SYSTEM
    assert "隐私" in PLAN_SYSTEM and "GUIDE" in PLAN_SYSTEM
    # It is not a keyword router or a tool sequence supplied as a model decision.
    json.dumps({"system": PLAN_SYSTEM}, ensure_ascii=False)
