"""Aggregate accepted-stage requirements even when summary validation fails first."""

import datetime as dt
import json
from copy import deepcopy
from pathlib import Path

from resolveflow.support.guide import guide_source
from resolveflow.support.protocol import SupportInput
from tests.unit.test_support_agent import GuideReads, read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_staged import staged, understand


def recorded():
    root = Path(__file__).resolve().parents[3]
    run = json.loads((root / "reports/customer-agent-acceptance-gate-v1/primary/runtime-results.json").read_text(
        encoding="utf-8"))["support_runs"][0]
    req = SupportInput.model_validate({**run["input_json"],
        "deadline_at": dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120)})
    models = [c["response_json"]["decision"] for c in run["calls"] if c["kind"] == "model"]
    shipment = next(c["response_json"][0] for c in run["calls"] if c["kind"] == "tool")
    return req, models, shipment


class SavedSources:
    def __init__(self, req, shipment):
        self.req, self.shipment, self.calls = req, shipment, []

    def read(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "get_shipment_trace":
            return deepcopy(self.shipment)
        if name == "get_support_guide":
            return guide_source()
        assert name == "get_order_context"
        # Explicit synthetic repair branch, never presented as a saved real tool call.
        return {"source_type": "ORDER", "version": 1, "data": {"order_line": {
            "line_id": self.req.line_id, "status": "PAID", "line_paid_amount": 32900, "currency": "CNY"}}}


def test_saved_summary_failure_reports_sources_and_application_step_in_one_feedback():
    req, models, shipment = recorded()
    before = deepcopy(models)
    fixed = deepcopy(models[-1])
    application = next(p for p in fixed["parts"] if p["task_id"] == "t2")
    application["citations"] = ["O2", "O3"]
    application["next_steps"] = [{"action": "REFUND_APPLICATION", "source": "O2"}]
    fixed["refund_summary"] = models[2]["refund_summary"]
    result, model, sources, agent = staged(req, models[:3] + [
        read("get_support_guide"), read("get_order_context"), fixed], SavedSources(req, shipment))
    assert result["status"] == "SUCCEEDED", result["reason"]
    feedback = json.loads(model.packets[3]["feedback"])
    assert feedback["field"] == "refund_summary"
    assert {g["need"] for g in feedback["source_gaps"]} == {"ORDER", "GUIDE"}
    assert all(g["task_id"] == "t2" for g in feedback["source_gaps"])
    assert feedback["action_gaps"] == [{"task_id": "t2", "action": "REFUND_APPLICATION"}]
    assert "REFUND_APPLICATION" in feedback["repair_note"]
    assert agent.repairs == 1 and model.calls == 6 and len(sources.calls) == 3
    assert result["answer"]["refund_summary"] == models[2]["refund_summary"]
    assert all(t["status"] == "PENDING" for t in model.packets[3]["task_state"]["tasks"])
    assert models == before


def test_unchanged_real_actions_remain_failed_without_new_reads_or_summary_publication():
    req, models, shipment = recorded()
    result, model, sources, agent = staged(req, models, SavedSources(req, shipment))
    assert result["reason"] == "INVALID_DECISION" and result["answer"] is None
    assert agent.repairs == 1 and model.calls == 4 and len(sources.calls) == 1
    assert json.loads(model.packets[3]["feedback"])["field"] == "refund_summary"


def test_missing_handoff_step_also_has_source_and_action_gaps_without_a_refund_summary():
    req = request()
    bad = parts(part("trace", "可以让商家协助说明。"))
    good = parts({**part("trace", "可以让商家协助说明。"),
                  "next_steps": [{"action": "MERCHANT_REVIEW", "source": "O1"}]})
    result, model, _, agent = staged(req, [understand(req, intent="HANDOFF", needs=["GUIDE"]), bad,
        read("get_support_guide"), good], GuideReads())
    assert result["status"] == "SUCCEEDED", result["reason"]
    feedback = json.loads(model.packets[2]["feedback"])
    assert feedback["action_gaps"] == [{"task_id": "trace", "action": "MERCHANT_REVIEW"}]
    assert feedback["source_gaps"] == [{"task_id": "trace", "need": "GUIDE"}]
    assert agent.repairs == 1 and model.calls == 4


def test_empty_summary_with_valid_step_reports_summary_not_an_invented_source_failure():
    req = request()
    good = parts({**part("trace", "请核对原因后自行确认。"),
                  "next_steps": [{"action": "REFUND_APPLICATION", "source": "O1"}]})
    good["refund_summary"] = "客户反馈未收到商品，申请整件退款，待本人核对提交。"
    bad = {**good, "refund_summary": " "}
    result, model, _, _ = staged(req, [understand(req, intent="APPLICATION", needs=["GUIDE"]),
        read("get_support_guide"), bad, good], GuideReads())
    assert result["status"] == "SUCCEEDED", result["reason"]
    feedback = json.loads(model.packets[3]["feedback"])
    assert feedback["field"] == "refund_summary"
    assert "source_gaps" not in feedback and "action_gaps" not in feedback
