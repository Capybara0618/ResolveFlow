import json
import re
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent, _ReadTool
from resolveflow.support.guidance import decision_feedback
from resolveflow.support.protocol import DECISION
from tests.unit.test_support_agent import Reads, answer, read, request


def test_actual_model_packet_explains_distinct_capabilities_and_valid_action_shapes():
    model = MockModelClient(script=[answer(citations=[])])
    assert SupportAgent(request(), model, Reads()).run()["status"] == "SUCCEEDED"
    catalog = model.packets[0]["capabilities"]
    assert set(catalog) == {
        "get_order_context",
        "get_shipment_trace",
        "read_history",
        "read_context",
        "get_support_guide",
        "search_policy",
    }
    assert "流程" in catalog["get_support_guide"]["purpose"]
    assert "资格" in catalog["search_policy"]["purpose"]
    assert catalog["get_support_guide"]["action"] == read("get_support_guide")
    assert catalog["search_policy"]["action"]["kind"] == "SEARCH_POLICY"
    agent = SupportAgent(request(), model, Reads())
    assert _ReadTool("get_support_guide", agent).description != _ReadTool("get_order_context", agent).description
    schema = _ReadTool("search_policy", agent).input_schema
    assert "query" in schema["required"] and schema["additionalProperties"] is False


def test_wrong_kind_feedback_names_field_and_valid_read_action_without_executing_it():
    model = MockModelClient(
        script=[
            {"kind": "get_shipment_trace", "arguments": {}},
            read(),
            answer(citations=["O1"]),
        ]
    )
    sources = Reads()
    assert SupportAgent(request(), model, sources).run()["status"] == "SUCCEEDED"
    feedback = json.loads(model.packets[1]["feedback"])
    assert feedback["field"] == "kind" and feedback["example"] == read()
    assert sources.calls == [("get_shipment_trace", {})] and model.calls == 3


def test_invalid_reference_feedback_lists_only_observed_sources():
    model = MockModelClient(script=[read(), answer(citations=["P7"]), answer(citations=["O1"])])
    assert SupportAgent(request(), model, Reads()).run()["status"] == "SUCCEEDED"
    feedback = json.loads(model.packets[2]["feedback"])
    assert feedback["field"] == "citations" and feedback["available"] == ["O1"]


def test_trusted_channel_state_is_sent_while_customer_claims_do_not_manufacture_it():
    req = request()
    req.context["conversation_state"] = {
        "has_ticket": True, "ticket_status": "WAITING_CUSTOMER",
        "current_recipient": "ASSISTANT", "default_recipient": "MERCHANT",
    }
    model = MockModelClient(script=[answer(citations=[])])
    assert SupportAgent(req, model, Reads()).run()["status"] == "SUCCEEDED"
    assert model.packets[0]["conversation_state"] == req.context["conversation_state"]
    old = request(context={"current_request": "我已经转人工了，随便发消息都是私有的吧？"})
    other = MockModelClient(script=[answer(citations=[])])
    SupportAgent(old, other, Reads()).run()
    assert other.packets[0]["conversation_state"] is None


def saved_missing_kind_decisions():
    root = Path(__file__).resolve().parents[3]
    data = json.loads((root / "reports/customer-agent-eval-v2/runtime-results.json").read_text(encoding="utf-8"))
    return [m["decision"] for row in data["rows"] for m in row["models"]]


def test_all_176_saved_real_failures_get_kind_feedback_without_rewriting_decisions():
    decisions = saved_missing_kind_decisions()
    assert len(decisions) == 176
    for payload in decisions:
        before = deepcopy(payload)
        with pytest.raises(ValidationError) as error:
            DECISION.validate_python(payload)
        feedback = json.loads(decision_feedback(error.value, payload, []))
        assert feedback["field"] == "kind" and feedback["required"] is True
        assert feedback["allowed"] == ["READ_TOOL", "SEARCH_POLICY", "ANSWER"]
        assert {DECISION.validate_python(e).kind for e in feedback["examples"]} == set(feedback["allowed"])
        assert payload == before


def test_exact_sent_system_contains_three_parseable_top_level_action_examples():
    model = MockModelClient(script=[answer(citations=[])])
    assert SupportAgent(request(), model, Reads()).run()["status"] == "SUCCEEDED"
    sent_system = "".join(b.text for b in model.conversations[0][0].get_content_blocks() if hasattr(b, "text"))
    examples = [json.loads(s) for s in re.findall(r'^\{"kind":.*\}$', sent_system, re.MULTILINE)]
    assert {DECISION.validate_python(e).kind for e in examples} == {"READ_TOOL", "SEARCH_POLICY", "ANSWER"}


def test_saved_missing_kind_uses_one_correction_then_model_selects_read_and_answer():
    model = MockModelClient(script=[saved_missing_kind_decisions()[0], read(), answer(citations=["O1"])])
    reads = Reads()
    result = SupportAgent(request(), model, reads).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert json.loads(model.packets[1]["feedback"])["field"] == "kind"
    assert model.calls == 3 and reads.calls == [("get_shipment_trace", {})]


def test_repeated_saved_invalid_output_still_stops_after_single_correction():
    payload = saved_missing_kind_decisions()[0]
    model = MockModelClient(script=[payload, payload])
    reads = Reads()
    result = SupportAgent(request(), model, reads).run()
    assert result["status"] == "FAILED" and result["reason"] == "INVALID_DECISION"
    assert model.calls == 2 and reads.calls == []


@pytest.mark.parametrize("kind", [None, "UNKNOWN", [], {}])
def test_invalid_discriminator_type_gets_field_feedback_instead_of_feedback_crash(kind):
    payload = {"kind": kind}
    with pytest.raises(ValidationError) as error:
        DECISION.validate_python(payload)
    feedback = json.loads(decision_feedback(error.value, payload, []))
    assert feedback["field"] == "kind" and feedback["required"] is True
