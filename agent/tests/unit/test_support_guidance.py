import json

from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent, _ReadTool
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
