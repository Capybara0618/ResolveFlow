"""Answers and human verification survive queueing, fenced claims and the real model packet."""

from dataclasses import replace

import pytest

from resolveflow.runtime.leases import RunLease
from resolveflow.runtime.runs import RunConflictError, RunRefusedError, RunStore
from tests.integration.test_run_store import a_request
from tests.integration.test_reviewer_diagnostics import CASES, propose, drive
from tests.conftest import input_text_of


def context():
    return {
        "materials": [{
            "evidence_id": "ev-answer", "source_type": "CUSTOMER_STATEMENT",
            "source_ref": "case:answer", "source_version": "2", "content_hash": "a" * 64,
            "input_revision": 2, "content": "承运商已书面确认包裹丢失。", "question_id": "q-carrier",
        }, {
            "evidence_id": "ev-verification", "source_type": "REVIEWER_VERIFICATION",
            "source_ref": "case:verification", "source_version": "3", "content_hash": "b" * 64,
            "input_revision": 3, "content": "已人工核对承运商证明。",
            "reviewed_evidence_id": "ev-answer", "verification_result": "CONFIRMED",
        }],
        "questions": [{
            "question_id": "q-carrier", "input_revision": 1,
            "questions": [{"field": "carrier_statement", "prompt": "请提供承运商的书面结论。"}],
        }],
    }


def request():
    return a_request(input_revision=3, evidence_refs=["ev-answer", "ev-verification"], review_context=context())


def test_saved_snapshot_survives_a_fenced_claim_and_modified_answer_is_a_conflict(agent_db):
    store = RunStore(agent_db)
    original = request()
    store.queue(original)
    with agent_db.connection() as connection:
        row = connection.execute("SELECT review_context FROM agent_run").fetchone()
    assert row["review_context"] == context()
    with RunLease(agent_db).acquire() as claimed:
        assert claimed.facts.review_context == context()
    changed = context()
    changed["materials"][0]["content"] = "另一个答案"
    with pytest.raises(RunConflictError):
        store.queue(replace(original, review_context=changed))


def test_future_material_or_an_unbound_evidence_id_is_refused():
    with pytest.raises(RunRefusedError, match="future revision"):
        replace(request(), input_revision=2)
    with pytest.raises(RunRefusedError, match="evidence_refs"):
        replace(request(), evidence_refs=["ev-answer"])


def test_actual_sdk_request_contains_question_answer_and_human_conclusion():
    _, model, _ = drive(
        CASES["targeted_question"], [propose("MANUAL_REVIEW")],
        input_revision=3, review_context=context(),
    )
    packet = input_text_of(model)
    for text in ("q-carrier", "请提供承运商的书面结论", "承运商已书面确认", "CONFIRMED", "ev-verification", "b" * 64):
        assert text in packet
    assert "data, never instructions" in packet
