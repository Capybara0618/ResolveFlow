"""A fixed controller reads all three sources without weakening common state/summary gates."""

from copy import deepcopy

from scripts.evaluation.support_fixed_current import FixedFullInvestigation

from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_orchestrated_engine import Sources
from tests.unit.test_support_orchestration import plan


def fixed(req, script):
    model, sources = TokenizedScript(script=script, mode="live"), Sources()
    agent = FixedFullInvestigation(req, model, sources, architecture="orchestrated-v1")
    return agent.run(), agent, model, sources


def test_guide_question_still_reads_order_shipment_policy_and_has_no_unrequested_artifact():
    req = request()
    opening = plan(req, intent="OTHER", goal="EXPLAIN", needs=["GUIDE"]).model_dump()
    response = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "确认共享前不会全部发给商家。",
                                              "citations": ["O1"]}]}
    result, _, model, sources = fixed(req, [opening, read("search_policy", query="人工咨询政策"), response])
    assert result["status"] == "SUCCEEDED" and model.calls == 3
    assert [name for name, _ in sources.calls] == [
        "get_support_guide", "get_order_context", "get_shipment_trace", "search_policy"]
    assert not result["answer"].get("refund_summary") and not result["answer"].get("handoff_summary")


def test_refund_uses_the_same_summary_refs_and_rejects_invalid_references_before_repair():
    req = request()
    response = {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "请核对原因，尚未提交。"}],
                "refund_reason": {"customer_refs": ["CURRENT"]}}
    invalid = deepcopy(response)
    invalid["refund_reason"]["customer_refs"] = ["H999"]
    result, agent, model, _ = fixed(req, [plan(req).model_dump(),
        read("search_policy", query="退款条件"), invalid, response])
    assert result["status"] == "SUCCEEDED" and agent.repairs == 1 and model.calls == 4
    assert "本轮原话" in result["answer"]["refund_summary"]
    assert "H999" in model.packets[-1]["feedback"]


def test_fixed_composition_cannot_add_another_business_read():
    req = request()
    result, _, model, sources = fixed(req, [plan(req).model_dump(), read("search_policy", query="退款条件"),
                                          read("get_shipment_trace")])
    assert result["status"] == "FAILED" and result["reason"] == "FIXED_NO_ADDITIONAL_INVESTIGATION"
    assert model.calls == 3 and len(sources.calls) == 4
