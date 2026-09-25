"""C06.1b: the callback outbox, against a real PostgreSQL.

The outbox exists because a callback is a fact the Agent has already decided: once a run has reached
STARTED or a PROPOSAL, the case file must eventually learn it, and a delivery that failed must not be the
reason the fact disappears (docs/domain-model.md:69 — outbox 按至少一次). So the tests here are about the
two halves of that promise:

- **enqueue is durable and idempotent.** The row is committed before delivery is attempted, and the same
  callback twice is one row rather than a second delivery.
- **the delivery record is at-most-once from the case side.** ``callback_id`` is the primary key, so a
  redelivery after a lost acknowledgement is recognisably the same callback, and ``record_delivery``
  converges on the same answer instead of incrementing forever.

The store's own public methods are used, and the table is read directly where the claim is about what was
committed rather than about what was returned.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from resolveflow.runtime.callbacks import (
    DELIVERED,
    PENDING,
    CallbackEnvelope,
    CallbackKind,
    CallbackStore,
    UnknownCallbackError,
)
from resolveflow.runtime.db import Database
from resolveflow.runtime.runs import RunRequest, RunStore, VerifiedCaller

RUN_ID = "11111111-2222-4333-8444-555555555555"
CASE_ID = "9c858901-8a57-4791-81fe-4c455b099bc9"
ORDER_ID = "00000000-0000-4000-8000-0000000000aa"
MANIFEST_HASH = "9" * 64
DEADLINE = "2026-09-28T05:00:00Z"

CASE_DISPATCHER = VerifiedCaller(
    service="case-service",
    scope="run:dispatch",
    merchant_id="M-1001",
    customer_id="C-2002",
)

STARTED_AT = "2026-09-24T10:00:00Z"


def a_run(**overrides: Any) -> RunRequest:
    """The dispatch this test's run was opened by; the outbox derives its subject from this row."""
    fields: dict[str, Any] = {
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "input_revision": 1,
        "merchant_id": "M-1001",
        "customer_id": "C-2002",
        "order_id": ORDER_ID,
        "line_id": "7001",
        "description": "包裹丢了，希望退款",
        "requested_actions": ["REFUND"],
        "evidence_refs": ["ev-1"],
        "policy_manifest": {
            "merchant_id": "M-1001",
            "bundle_ids": ["policy-logistics-2026.09"],
            "manifest_hash": MANIFEST_HASH,
            "safety_epoch": 1,
        },
        "deadline_at": DEADLINE,
        "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
    }
    fields.update(overrides)
    return RunRequest(**fields)


def started_payload() -> dict[str, Any]:
    return {"schema_version": 2, "started_at": STARTED_AT}


def a_started(**overrides: Any) -> CallbackEnvelope:
    fields: dict[str, Any] = {"kind": CallbackKind.STARTED, "payload": started_payload()}
    fields.update(overrides)
    return CallbackEnvelope(**fields)


def queued(agent_db: Database) -> CallbackStore:
    """A run in the database plus the outbox that belongs to it."""
    RunStore(agent_db).queue(a_run(), caller=CASE_DISPATCHER)
    return CallbackStore(agent_db)


def test_callback_id_follows_the_documented_form_and_is_derived_not_chosen() -> None:
    """``cb-<case_id>-<revision>-<kind>``, the form the published example uses.

    It is derived rather than caller-chosen because the Agent is the only producer of its own callbacks:
    derivable means a retry after a crash computes the *same* id, and the case service recognises the
    redelivery as a duplicate instead of applying a second one.
    """
    assert CallbackEnvelope.callback_id_for(CASE_ID, 1, CallbackKind.STARTED) == f"cb-{CASE_ID}-1-started"
    assert CallbackEnvelope.callback_id_for(CASE_ID, 4, CallbackKind.PROPOSAL) == f"cb-{CASE_ID}-4-proposal"
    assert len(CallbackEnvelope.callback_id_for(CASE_ID, 1, CallbackKind.STARTED)) <= 64
    # Two revisions of one case are two callbacks; the revision is in the id, not assumed.
    assert CallbackEnvelope.callback_id_for(CASE_ID, 1, CallbackKind.STARTED) != CallbackEnvelope.callback_id_for(
        CASE_ID, 2, CallbackKind.STARTED
    )


def test_an_enqueued_callback_is_committed_before_any_delivery_is_attempted(agent_db: Database) -> None:
    callbacks = queued(agent_db)

    record = callbacks.enqueue_for_run(RUN_ID, a_started())

    assert record.callback_id == f"cb-{CASE_ID}-1-started"
    assert record.run_id == RUN_ID
    assert record.case_id == CASE_ID
    assert record.input_revision == 1
    assert record.kind == "STARTED"
    assert record.status == PENDING
    assert record.attempts == 0
    assert record.delivered_at is None
    # Committed: a second connection sees it, so "durable" is not a claim about this object.
    with agent_db.connection() as connection:
        row = connection.execute(
            "SELECT callback_id, run_id, case_id, input_revision, kind, payload, status, attempts "
            "FROM agent_callback_outbox WHERE callback_id = %(callback_id)s",
            {"callback_id": record.callback_id},
        ).fetchone()
    assert row is not None, "the outbox row must exist before the first delivery is attempted"
    assert str(row["run_id"]) == RUN_ID
    assert row["kind"] == "STARTED"
    assert row["status"] == PENDING
    assert row["payload"]["started_at"] == STARTED_AT


def test_the_same_callback_twice_is_one_row_and_not_a_second_delivery(agent_db: Database) -> None:
    """At-least-once delivery is only safe if the *record* is not duplicated by a retry."""
    callbacks = queued(agent_db)

    first = callbacks.enqueue_for_run(RUN_ID, a_started())
    second = callbacks.enqueue_for_run(RUN_ID, a_started())

    assert first.callback_id == second.callback_id
    with agent_db.connection() as connection:
        count = connection.execute("SELECT count(*) AS n FROM agent_callback_outbox").fetchone()
    assert count is not None and count["n"] == 1


def test_a_delivered_callback_is_not_enqueued_again(agent_db: Database) -> None:
    """Once Java has applied it, re-enqueueing must not turn an accepted callback back into a pending one."""
    callbacks = queued(agent_db)
    record = callbacks.enqueue_for_run(RUN_ID, a_started())
    callbacks.record_delivery(record.callback_id, disposition="ACCEPTED")

    again = callbacks.enqueue_for_run(RUN_ID, a_started())

    assert again.status == DELIVERED
    assert again.attempts == 1


def test_recording_a_delivery_is_idempotent_and_says_which_answer_won(agent_db: Database) -> None:
    """A lost acknowledgement makes the Agent redeliver; the second answer must not double-count."""
    callbacks = queued(agent_db)
    record = callbacks.enqueue_for_run(RUN_ID, a_started())

    first = callbacks.record_delivery(record.callback_id, disposition="ACCEPTED")
    second = callbacks.record_delivery(record.callback_id, disposition="DUPLICATE")

    assert first.status == DELIVERED
    assert first.attempts == 1
    assert second.status == DELIVERED
    assert second.attempts == 1, "converged on one delivery, not two"
    assert second.disposition == "ACCEPTED", "the first answer is the one that was applied"


def test_a_stale_callback_is_finished_rather_than_retried_forever(agent_db: Database) -> None:
    """STALE is not an error (contracts/core/openapi-case.yaml:1284), but it is also not deliverable later.

    The revision it belonged to is gone. Retrying it would keep asking a question whose answer can no
    longer matter, so it is recorded as finished and kept in the history with the reason.
    """
    callbacks = queued(agent_db)
    record = callbacks.enqueue_for_run(RUN_ID, a_started())

    stale = callbacks.record_delivery(record.callback_id, disposition="STALE")

    assert stale.status == DELIVERED
    assert stale.disposition == "STALE"
    assert callbacks.pending() == [], "a stale callback is not pending work"


def test_a_failed_delivery_stays_pending_and_carries_the_reason(agent_db: Database) -> None:
    callbacks = queued(agent_db)
    record = callbacks.enqueue_for_run(RUN_ID, a_started())

    failed = callbacks.record_failure(record.callback_id, error="connect timeout")

    assert failed.status == PENDING
    assert failed.attempts == 1
    assert failed.last_error == "connect timeout"
    assert [item.callback_id for item in callbacks.pending()] == [record.callback_id]


def test_pending_returns_the_oldest_waiting_delivery_first(agent_db: Database) -> None:
    """A backlog must be visible as an age, exactly as the run queue is (agent_run_queue_idx)."""
    callbacks = queued(agent_db)
    first = callbacks.enqueue_for_run(RUN_ID, a_started())
    later = callbacks.enqueue_for_run(RUN_ID, 
        CallbackEnvelope(
            kind=CallbackKind.FAILED,
            payload={"schema_version": 2, "reason_codes": ["TOOL_UNAVAILABLE"], "retryable": True},
        )
    )
    callbacks.record_delivery(first.callback_id, disposition="ACCEPTED")

    waiting = callbacks.pending()

    assert [item.callback_id for item in waiting] == [later.callback_id]


def test_a_callback_for_a_run_that_does_not_exist_is_refused(agent_db: Database) -> None:
    """The subject comes from the run row, so there is nothing to fill in when the run is missing."""
    callbacks = CallbackStore(agent_db)

    with pytest.raises(UnknownCallbackError, match="no run"):
        callbacks.enqueue_for_run(RUN_ID, a_started())


def test_a_payload_that_does_not_match_its_kind_is_refused(agent_db: Database) -> None:
    """The Agent is the producer, so a malformed payload is caught here rather than by the case service."""
    with pytest.raises(ValueError, match="started_at"):
        CallbackEnvelope(kind=CallbackKind.STARTED, payload={"schema_version": 2})
    with pytest.raises(ValueError, match="recommended_action"):
        CallbackEnvelope(kind=CallbackKind.PROPOSAL, payload={"schema_version": 2, "proposal_id": "p-1"})


def test_deliveries_are_listable_for_one_run(agent_db: Database) -> None:
    """What ``RunView.callback_ids`` will report: the callbacks this run has emitted, not another run's."""
    callbacks = queued(agent_db)
    record = callbacks.enqueue_for_run(RUN_ID, a_started())

    listed = callbacks.list_for_run(RUN_ID)

    assert [item.callback_id for item in listed] == [record.callback_id]
    assert callbacks.list_for_run("0f0f0f0f-1111-4222-8333-444444444444") == []


def test_recording_a_delivery_for_an_unknown_callback_is_refused(agent_db: Database) -> None:
    callbacks = queued(agent_db)

    with pytest.raises(UnknownCallbackError):
        callbacks.record_delivery("cb-never-enqueued", disposition="ACCEPTED")
    with pytest.raises(UnknownCallbackError):
        callbacks.record_failure("cb-never-enqueued", error="boom")


def test_run_view_reports_the_callbacks_the_run_has_emitted(agent_db: Database) -> None:
    """``RunView.callback_ids`` is the list case-service reconciles against, so it must be the real one.

    It was an empty tuple while the outbox did not exist, and that was honest; now that callbacks can be
    emitted, an empty list would be a lie in exactly the view that exists to explain what happened
    (contracts/core/openapi-agent.yaml:509).
    """
    callbacks = queued(agent_db)
    first = callbacks.enqueue_for_run(RUN_ID, a_started())

    view = RunStore(agent_db).read(RUN_ID)

    assert view.callback_ids == (first.callback_id,)
    assert "cb-" in view.callback_ids[0]


def test_run_view_does_not_report_another_runs_callbacks(agent_db: Database) -> None:
    callbacks = queued(agent_db)
    callbacks.enqueue_for_run(RUN_ID, a_started())

    other = RunStore(agent_db).queue(
        a_run(run_id="22222222-3333-4444-8555-666666666666", case_id="0f0f0f0f-1111-4222-8333-444444444444"),
        caller=CASE_DISPATCHER,
    )

    view = RunStore(agent_db).read(other.run_id)

    assert view.callback_ids == (), "the other run has emitted nothing"


def test_the_next_attempt_is_recorded_so_a_redelivery_is_scheduled_not_immediate(agent_db: Database) -> None:
    """A delivery that failed gets a time to be tried again, rather than being retried in a tight loop."""
    callbacks = queued(agent_db)
    record = callbacks.enqueue_for_run(RUN_ID, a_started())

    failed = callbacks.record_failure(record.callback_id, error="503", retry_after_seconds=30)

    assert failed.attempts == 1
    assert failed.next_attempt_at is not None
    assert failed.next_attempt_at > dt.datetime.now(dt.UTC)