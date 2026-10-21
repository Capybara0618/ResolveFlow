"""Regress real metadata failures while keeping atomic updates and a single model repair."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from resolveflow.support.guidance import decision_feedback
from resolveflow.support.protocol import DECISION
from tests.unit.test_support_agent import Reads, answer, read, request
from tests.unit.test_support_dialogue import event
from tests.unit.test_support_tasks import task


def saved_reference_failure():
    root = Path(__file__).resolve().parents[3]
    path = root / "reports/customer-agent-action-smoke-v1/runtime-results.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    return saved["rows"][0]["models"][0]["decision"]


def test_first_packet_shows_exact_current_quote_and_metadata_without_selecting_a_tool():
    req = request()
    model = MockModelClient(script=[read(), answer(citations=["O1"])])
    assert SupportAgent(req, model, Reads()).run()["status"] == "SUCCEEDED"
    example = model.packets[0]["first_action_annotations"]
    assert set(example) == {"tasks", "dialogue_events"}
    assert example["dialogue_events"][0]["reference"] == "CURRENT"
    assert example["dialogue_events"][0]["offset"] == 0
    assert example["dialogue_events"][0]["quote"] == req.context["current_request"][:300]
    DECISION.validate_python({**read(), **example})
    assert "first_action_annotations" not in model.packets[1]


def test_saved_null_source_gets_reference_contract_and_full_action_resubmission():
    payload = saved_reference_failure()
    with pytest.raises(ValidationError) as error:
        DECISION.validate_python(payload)
    feedback = json.loads(decision_feedback(error.value, payload, []))
    assert feedback["field"] == "dialogue_events.reference"
    assert feedback["reference"] == "CURRENT" and feedback["resubmit"] == "FULL_ACTION"
    assert feedback["rejected_annotations_committed"] is False


def test_failed_first_annotations_are_reissued_in_full_and_only_selected_read_runs():
    req = request()
    corrected = {**read(), "tasks": [task("t1")], "dialogue_events": [
        event("ADD", "t1", req.context["current_request"])]}
    model = MockModelClient(mode="live", script=[saved_reference_failure(), corrected,
        answer(citations=["O1"], tasks=[task("t1", status="NEEDS_MERCHANT", evidence_refs=["O1"],
                                           response_excerpt="可以请商家核验")])])
    source = Reads()
    result = SupportAgent(req, model, source).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert json.loads(model.packets[1]["feedback"])["resubmit"] == "FULL_ACTION"
    assert model.packets[1]["task_state"]["tasks"] == []
    assert source.calls == [("get_shipment_trace", {})] and model.calls == 3
