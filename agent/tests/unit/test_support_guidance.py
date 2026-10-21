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
