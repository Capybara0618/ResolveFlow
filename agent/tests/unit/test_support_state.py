"""Canonical consultation state, atomic meaning updates and derived evidence readiness."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from resolveflow.support.orchestration import TurnPlan
from resolveflow.support.protocol import SupportInput, SupportTask
from resolveflow.support.state import SupportState


def make_state() -> SupportState:
    request = SupportInput(
        run_id=str(uuid4()), conversation_id=str(uuid4()), input_version=3,
        merchant_id="M-1001", buyer_id="buyer-1", line_id="line-1",
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
        context={"current_request": "家人和代收点问过了，请继续查物流。"},
    )
    return SupportState.create(request, "orchestrated-v1")


def plan() -> TurnPlan:
    return TurnPlan.model_validate({
        "kind": "TURN_UNDERSTANDING",
        "focus": [{"id": "trace", "intent": "LOGISTICS", "request": "查物流",
                   "needs": ["SHIPMENT"], "goal": "EXPLAIN"}],
        "dialogue_events": [{"change": "ADD", "task_id": "trace", "reference": "CURRENT",
                             "quote": "请继续查物流"}],
        "customer_claims": [{"topic": "CHECKS", "change": "APPEND", "reference": "CURRENT",
                             "quote": "家人和代收点问过了"}],
    })


def accept(state: SupportState) -> None:
    value = plan()
    state.accept_understanding(value.meaning(), plan=value)


def test_focus_and_dialogue_views_follow_one_canonical_issue_record():
    state = make_state()
    original = deepcopy(state.request.context)
    accept(state)
    issue = state.memory.tasks.issues["trace"]
    issue.status = "NEEDS_MERCHANT"
    issue.lifecycle = "PAUSED"
    assert state.focus_tasks[0].status == "NEEDS_MERCHANT"
    assert state.memory.tasks.before == {"trace": "NEEDS_MERCHANT"}
    assert state.memory.tasks.lifecycles == {"trace": "PAUSED"}
    assert state.turn.focus_ids == ("trace",)
    assert state.request.context == original
    packet = state.focus_packet()
    packet["tasks"][0]["status"] = "CANCELLED"
    assert issue.status == "NEEDS_MERCHANT"


def test_invalid_meaning_cannot_partially_accept_memory_tasks_or_plan():
    state = make_state()
    value = plan()
    value.dialogue_events[0].quote = "客户没有说过的暂停请求"
    with pytest.raises(ValueError, match="原句"):
        state.accept_understanding(value.meaning(), plan=value)
    assert state.memory.claims.entries == []
    assert state.memory.tasks.issues == {}
    assert state.turn.focus_ids == ()
    assert state.turn.stage.understanding is None
    assert state.turn.orchestration is not None and state.turn.orchestration.goals == {}


def test_readiness_is_recomputed_from_valid_current_line_evidence():
    state = make_state()
    accept(state)
    waiting = state.readiness()
    assert waiting["phase"] == "INVESTIGATE"
    assert waiting["tasks"][0]["missing"] == ["SHIPMENT"]
    waiting["tasks"][0]["missing"].clear()
    assert state.readiness()["tasks"][0]["missing"] == ["SHIPMENT"]
    state.turn.evidence["O1"] = {
        "source_type": "SHIPMENT", "version": 1,
        "data": {"line_id": "another-line", "status": "IN_TRANSIT"},
    }
    assert state.readiness()["phase"] == "INVESTIGATE"
    state.turn.evidence["O1"]["data"]["line_id"] = state.request.line_id
    assert state.readiness()["phase"] == "COMPOSE"
    assert state.readiness()["tasks"][0]["refs_by_need"] == {"SHIPMENT": ["O1"]}
    assert state.turn.stage.understanding is not None
    assert state.turn.stage.understanding.focus[0].needs == ["SHIPMENT"]


def test_rejected_answer_candidate_does_not_change_accepted_conversation():
    state = make_state()
    accept(state)
    tasks, claims, dialogue = state.annotation_candidate()
    tasks.tasks[0].status = "CANCELLED"
    claims.entries.clear()
    dialogue.issues.clear()
    assert state.focus_tasks[0].status == "PENDING"
    assert len(state.memory.claims.entries) == 1
    assert state.memory.tasks.before == {"trace": "PENDING"}


def test_legacy_script_annotations_still_commit_without_dialogue_events():
    state = make_state()
    tasks, claims, dialogue = state.annotation_candidate()
    task = SupportTask(id="legacy", intent="OTHER", request="查询", status="PENDING")
    tasks.accept([task], set())
    dialogue.apply([], tasks.tasks, [], require=False)
    state.commit_annotations(tasks, claims, dialogue)
    assert state.focus_tasks == [task]
    assert state.memory.tasks.lifecycles == {}
    assert state.memory.tasks.events == []
    assert state.conversation_snapshot(for_answer=True)["task_state"]["tasks"][0]["lifecycle"] == "OPEN"
    assert state.conversation_snapshot()["task_state"]["tasks"] == []


def test_focus_projection_preserves_old_unfocused_issues_and_clears_stale_evidence():
    state = make_state()
    state.request.context["previous_tasks"] = {
        "origin": "MODEL_PREVIOUS_TURN", "input_version": 1,
        "tasks": [{"id": "old", "intent": "OTHER", "request": "旧问题", "status": "ANSWERED",
                   "lifecycle": "OPEN", "evidence_refs": ["O99"], "response_excerpt": "旧回答"}],
    }
    state = SupportState.create(state.request, "orchestrated-v1")
    accept(state)
    assert [task.id for task in state.focus_tasks] == ["trace"]
    snapshot = state.memory.tasks.task_snapshot(state.focus_tasks)
    assert [task["id"] for task in snapshot["tasks"]] == ["old", "trace"]
    assert snapshot["focus_ids"] == ["trace"]
    assert snapshot["tasks"][0]["evidence_refs"] == []
    assert snapshot["tasks"][0]["response_excerpt"] is None
    assert state.turn.evidence == {}
