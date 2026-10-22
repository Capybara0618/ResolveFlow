"""Refining evidence needs is bounded and monotonic, never a second interpretation loop."""

import json

import pytest

from tests.unit.test_support_agent import GuideReads, read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_staged import staged, understand


def refine(key="trace", needs=None, **updates):
    return {"kind": "REFINE_NEEDS", "task_id": key, "add": needs or ["GUIDE"],
            "reason": "回答还需要核查操作入口。", **updates}


def test_additional_need_is_accepted_and_checked_without_changing_prior_event_or_focus():
    req = request()
    script = [understand(req), read(), refine(),
              parts(part("trace", "请商家核查。", ["O1"])), read("get_support_guide"),
              parts(part("trace", "系统有签收记录；从售后咨询预览确认核查。", ["O1", "O2"]))]
    result, model, sources, agent = staged(req, script, GuideReads())
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.calls == 6 and len(sources.calls) == 2
    assert json.loads(model.packets[4]["feedback"])["gaps"] == [{"task_id": "trace", "need": "GUIDE"}]
    assert agent.stage.packet()["focus"][0]["needs"] == ["SHIPMENT", "GUIDE"]
    assert [e["change"] for e in result["answer"]["dialogue_state"]["events"]] == ["ADD"]


@pytest.mark.parametrize("bad", [refine("foreign"), refine(needs=["SHIPMENT"]),
    refine(dialogue_events=[{"change": "CANCEL"}]), refine(add=[]), refine(needs=["arbitrary"])])
def test_invalid_refinement_keeps_focus_and_sources_unchanged(bad):
    req = request()
    result, model, sources, agent = staged(req, [understand(req, needs=[]), bad,
        parts(part("trace", "已记录。"))] if bad.get("add") != ["SHIPMENT"] else [
            understand(req), bad, read(), parts(part("trace", "已读取本轮物流。", ["O1"]))])
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert agent.stage.packet()["focus"][0]["id"] == "trace"
    assert agent.stage.packet().get("refinements", 0) == 0
    assert any(p["feedback"] for p in model.packets)


def test_refinement_cap_cannot_reset_or_evade_run_budget():
    req = request()
    script = [understand(req, needs=[]), refine(needs=["SHIPMENT"]), refine(needs=["GUIDE"]),
              refine(needs=["ORDER"]), refine(needs=["POLICY"])]
    result, model, sources, agent = staged(req, script)
    assert result["status"] == "FAILED" and result["reason"] == "INVALID_DECISION"
    assert model.calls == 5 and sources.calls == []
    assert agent.stage.packet()["refinements"] == 2
    assert agent.stage.packet()["focus"][0]["needs"] == ["SHIPMENT", "GUIDE"]
