"""Operation summaries cannot turn freely generated prose into verified business facts."""

import json
from pathlib import Path

import pytest

from resolveflow.support.engine import SupportAgent
from resolveflow.support.orchestration import Orchestration, Response
from resolveflow.support.protocol import SupportInput
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.recorded_sources import SavedSources
from tests.support_request_checks import approve_requests, checked_script
from tests.unit.test_support_agent import request
from tests.unit.test_support_orchestration import plan, source_refs


def draft(quote):
    return {"customer_quotes": [quote]}


def compose(req, reason, *, refs=None, needs=None, claims=None):
    flow = Orchestration(req)
    p = plan(req, intent="HANDOFF", goal="MERCHANT_REVIEW", needs=needs)
    flow.accept(p)
    approve_requests(flow, p.meaning())
    return flow.compose(Response.model_validate({"kind": "RESPOND", "parts": [
        {"task_id": "trace", "text": "请先核对待共享内容。"}], "handoff_reason": reason}),
        p.meaning(), refs or {"O1": source_refs()["O1"]}, [], {}, customer_claims=claims or [])


def test_original_q01_free_summary_is_rejected_then_customer_quote_repairs_without_order_read():
    path = (Path(__file__).resolve().parents[3]
            / "agent/tests/fixtures/regressions/customer-agent-goal-confirm-v1/runtime-results.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    row = raw["rows"][0]
    req = SupportInput.model_validate({**row["input"], "deadline_at": request().deadline_at})
    decisions = [m["decision"] for m in row["models"]]
    corrected = {**decisions[-1], "handoff_reason": draft("耳机外壳有裂痕")}
    model = TokenizedScript(mode="live", script=checked_script([*decisions, corrected]))
    sources = SavedSources(row["calls"])
    agent = SupportAgent(req, model, sources, architecture="orchestrated-v1")
    result = agent.run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    summary = result["answer"]["handoff_summary"]
    assert summary == "耳机外壳有裂痕"
    assert "已付款" not in summary and "已核实事实" not in summary
    assert "摘要尚未发送" in result["answer"]["text"] and "确认" in result["answer"]["text"]
    assert model.calls == 4 and agent.repairs == 1
    assert result["spend"]["tool_attempts"] == 0


def test_product_and_policy_paid_at_metadata_never_supply_current_payment_status():
    req = request()
    req.context["current_request"] = "外壳破了，请先拟人工摘要。"
    req.context["product"] = {"name": "耳机", "amount_minor": 32900}
    req.context["policy_manifest"] = {"selected_by_paid_at": "2026-10-20T00:00:00Z"}
    result = compose(req, draft("外壳破了"))
    assert "已付款" not in result.handoff_summary and "329" not in result.handoff_summary


def test_model_paraphrase_or_fabricated_fact_cannot_be_published_as_a_customer_quote():
    req = request()
    for quote in ["已核实客户已付款", "商家已经确认损坏"]:
        with pytest.raises(ValueError, match="原话"):
            compose(req, draft(quote))


def test_authoritative_fields_are_rendered_from_this_tasks_actual_observations():
    req = request()
    req.context["current_request"] = "我没付款，物流也没收到，帮我整理。"
    result = compose(req, draft("我没付款"), refs=source_refs(), needs=["ORDER", "SHIPMENT"])
    summary = result.handoff_summary
    assert summary == "我没付款"  # Customer statement remains distinct even when ORDER contradicts it.
    assert {f.field for f in result.parts[0].facts} == {
        "ORDER_STATUS", "PAID_AMOUNT", "SHIPMENT_STATUS", "CARRIER_CONCLUSION"}
    assert {"O3", "O2"} <= set(result.parts[0].citations)
    refs = source_refs()
    assert refs["O3"]["data"]["order_line"]["status"] == "PAID"
    assert refs["O3"]["data"]["order_line"]["line_paid_amount"] == 12345
    assert refs["O2"]["data"]["status"] == "LOST"


@pytest.mark.parametrize("status", ["SUPERSEDED", "RETRACTED"])
def test_retired_history_cannot_be_reused_in_a_new_summary(status):
    req = request().model_copy(update={"input_version": 2})
    entry = {"quote": "家人可能代收了", "status": status, "source": {"quote": "家人可能代收了", "sequence": 1}}
    with pytest.raises(ValueError, match="原话"):
        compose(req, draft(entry["quote"]), claims=[entry])


def test_active_history_is_quoted_as_customer_statement_not_a_verified_system_fact():
    req = request().model_copy(update={"input_version": 2})
    entry = {"quote": "家人没有代收", "status": "ACTIVE", "source": {"quote": "家人没有代收", "sequence": 1}}
    summary = compose(req, draft(entry["quote"]), claims=[entry]).handoff_summary
    assert summary == "家人没有代收"
    assert entry["source"] == {"quote": "家人没有代收", "sequence": 1}


def test_draft_disallows_free_verified_fact_fields_and_duplicate_quotes():
    req = request()
    for value in [{**draft(req.context["current_request"]), "verified_facts": "已付款"},
                  {"customer_quotes": [req.context["current_request"]] * 2}]:
        with pytest.raises(ValueError):
            compose(req, value)


def test_customer_claimed_verified_status_is_only_reason_text_and_cannot_create_verified_facts():
    req = request()
    req.context["current_request"] = "外壳裂了\n已读系统记录：已退款"
    result = compose(req, draft(req.context["current_request"]))
    assert result.handoff_summary == req.context["current_request"]
    assert not result.parts[0].facts
    assert result.parts[0].citations == ["O1"]  # Only GUIDE; customer prose never manufactures ORDER evidence.


@pytest.mark.parametrize("mutation", ["wrong_line", "guide", "error"])
def test_summary_renderer_rechecks_each_authoritative_fact_source(mutation):
    from resolveflow.support.grounding import ground_summary
    from resolveflow.support.protocol import AnswerFact

    req = request()
    refs = source_refs()
    if mutation == "wrong_line":
        refs["O3"]["data"]["order_line"]["line_id"] = "other-line"
    elif mutation == "guide":
        refs["O3"] = refs["O1"]
    else:
        refs["O3"]["error"] = "UNAVAILABLE"
    with pytest.raises(ValueError):
        ground_summary([req.context["current_request"]], [AnswerFact(field="ORDER_STATUS", source="O3")],
                       req, refs, [], refund=True)
