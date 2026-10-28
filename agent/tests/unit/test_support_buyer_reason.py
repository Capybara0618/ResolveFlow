"""Buyers confirm their own words; source facts remain in independent validated citations."""

from copy import deepcopy

import pytest

from resolveflow.support.grounding import GroundingError, ground_summary
from resolveflow.support.protocol import AnswerFact
from tests.unit.test_support_agent import request
from tests.unit.test_support_orchestrated_engine import respond, run
from tests.unit.test_support_orchestration import plan, source_refs


def test_buyer_reason_is_anchored_plain_text_not_an_investigation_report():
    req = request()
    req.context["current_request"] = "耳机一直没收到，请帮我准备退款申请。"
    refs = source_refs()
    original = deepcopy(refs)
    reason = ground_summary(["耳机一直没收到"], [AnswerFact(field="PAID_AMOUNT", source="O3")],
                            req, refs, [], refund=True, buyer_view=True)
    assert reason == "耳机一直没收到"
    assert refs == original
    assert "line_paid_amount" in refs["O3"]["data"]["order_line"]


def test_overlapping_customer_quotes_are_not_printed_twice():
    req = request()
    req.context["current_request"] = "包裹没有收到，希望申请退款。"
    reason = ground_summary(["包裹没有收到", req.context["current_request"]], [], req, {}, [],
                            refund=True, buyer_view=True)
    assert reason == req.context["current_request"]


@pytest.mark.parametrize("mutation", ["foreign", "error", "missing"])
def test_reason_fact_validation_is_not_skipped_just_because_facts_are_not_printed(mutation):
    refs = source_refs()
    if mutation == "foreign":
        refs["O3"]["data"]["order_line"]["line_id"] = "another-line"
    elif mutation == "error":
        refs["O3"]["error"] = "UNAVAILABLE"
    else:
        del refs["O3"]
    req = request()
    with pytest.raises(GroundingError):
        ground_summary([req.context["current_request"]], [AnswerFact(field="PAID_AMOUNT", source="O3")],
                       req, refs, [], refund=True, buyer_view=True)


def test_buyer_reason_never_uses_retired_claims_or_free_model_paraphrases():
    req = request().model_copy(update={"input_version": 3})
    claim = {"quote": "耳机没有收到", "status": "SUPERSEDED", "source": {"quote": "耳机没有收到", "sequence": 1}}
    for quote in [claim["quote"], "商家已核实商品丢失"]:
        with pytest.raises(GroundingError):
            ground_summary([quote], [], req, {}, [claim], refund=True, buyer_view=True)


def test_production_reason_and_citations_stay_separate_without_widening_refund_permissions():
    from tests.unit.test_support_agent import read

    req = request()
    result, agent, model, _ = run([plan(req).model_dump(), read("get_order_context"), respond()], req)
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert result["answer"]["refund_summary"] == req.context["current_request"]
    order = next(c for c in result["answer"]["citations"] if c["source_type"] == "ORDER")
    assert order["data"]["order_line"]["line_paid_amount"] == 12345
    assert result["answer"]["customer_memory"]["origin"] == "GROUNDED_CUSTOMER_CLAIMS"
    assert result["answer"]["text"] == respond()["parts"][0]["text"]
    assert result["answer"]["buyer_view"]["parts"][0]["action"] == "REFUND_APPLICATION"
    assert agent.repairs == 0 and model.calls == 3
