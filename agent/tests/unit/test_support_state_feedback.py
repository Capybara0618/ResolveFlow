"""Feedback uses real state; resuming an already open issue is an idempotent continuation."""

import json

import pytest

from tests.unit.test_support_agent import request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_staged import staged, understand


def prior(req, lifecycle, status):
    req.context["previous_tasks"] = {"origin": "MODEL_PREVIOUS_TURN", "input_version": 1,
        "tasks": [{"id": "trace", "intent": "LOGISTICS", "request": "查签收",
                   "status": status, "lifecycle": lifecycle}]}


def test_continue_after_a_failed_pause_does_not_require_inventing_a_successful_pause():
    req = request(input_version=4)
    req.context["current_request"] = "继续原来的调查，我补充材料。"
    prior(req, "OPEN", "ANSWERED")
    opening = understand(req, needs=[], events=[group("RESUME", ["trace"], req.context["current_request"])])
    result, model, _, _ = staged(req, [opening, parts(part("trace", "继续处理原问题。"))])
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.calls == 2 and result["answer"]["task_state"]["tasks"][0]["lifecycle"] == "OPEN"
    assert result["conversation_update"]["dialogue_state"]["events"][0]["change"] == "RESUME"


@pytest.mark.parametrize("lifecycle,status", [("RESOLVED", "ANSWERED"), ("CANCELLED", "CANCELLED")])
def test_closed_issue_reports_actual_state_and_legal_reopen_without_accepting_resume(lifecycle, status):
    req = request(input_version=4)
    req.context["current_request"] = "重新继续调查签收。"
    prior(req, lifecycle, status)
    bad = understand(req, needs=[], events=[group("RESUME", ["trace"], req.context["current_request"])])
    good = understand(req, needs=[], events=[group("REOPEN", ["trace"], req.context["current_request"])])
    result, model, _, _ = staged(req, [bad, good, parts(part("trace", "已重新开始调查。"))])
    assert result["status"] == "SUCCEEDED", result["reason"]
    feedback = json.loads(model.packets[1]["feedback"])
    assert feedback["state_conflict"] == {"task_id": "trace", "actual_lifecycle": lifecycle,
        "proposed_change": "RESUME", "allowed_changes": ["REOPEN"]}
    assert result["answer"]["dialogue_state"]["events"][0]["change"] == "REOPEN"


def test_enum_feedback_provides_expected_actions_instead_of_only_literal_error():
    req = request()
    bad = understand(req, needs=[])
    bad["dialogue_events"][0]["change"] = "SUSPEND"
    result, model, _, _ = staged(req, [bad, understand(req, needs=[]), parts(part("trace", "已记录。"))])
    assert result["status"] == "SUCCEEDED", result["reason"]
    feedback = json.loads(model.packets[1]["feedback"])
    assert feedback["errors"][0]["path"] == "dialogue_events.0.change"
    assert "PAUSE" in feedback["errors"][0]["expected"]
