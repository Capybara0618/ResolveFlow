"""C06.1: the durable run record, against a real PostgreSQL.

What is being proved here is the part of the contract a caller is allowed to rely on: a run whose
submission returned 202 is in the database, the same ``(case_id, input_revision)`` never becomes two runs,
the same run key with a different body is refused rather than overwritten, and a cancelled run says so.
Everything else C06.1 needs (the HTTP surface, the token, the callback outbox) is asserted in its own
module; this one is about the record.

The store is used through its own public methods, and the database is inspected directly when the claim is
about what was committed rather than about what was returned.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from resolveflow.runtime.db import Database
from resolveflow.runtime.runs import (
    REJECTED_IDENTITY_MISMATCH,
    RunConflictError,
    RunIdentityMismatchError,
    RunNotFoundError,
    RunRequest,
    RunStore,
    VerifiedCaller,
)
from tests.integration import future_deadline

RUN_ID = "11111111-2222-4333-8444-555555555555"
CASE_ID = "9c858901-8a57-4791-81fe-4c455b099bc9"
OTHER_CASE_ID = "0f0f0f0f-1111-4222-8333-444444444444"
ORDER_ID = "00000000-0000-4000-8000-0000000000aa"
MANIFEST_HASH = "9" * 64
DEADLINE = future_deadline()

#: The identity case-service derived from the verified principal and then minted the run token for
#: (docs/core-contracts.md:60-61).
CASE_DISPATCHER = VerifiedCaller(
    service="case-service",
    scope="run:dispatch",
    merchant_id="M-1001",
    customer_id="C-2002",
)


def a_request(**overrides: Any) -> RunRequest:
    """One well-formed dispatch, as case-service would send it (contracts/core/openapi-agent.yaml:53)."""
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


def test_a_queued_run_is_committed_before_the_caller_is_told(agent_db: Database) -> None:
    store = RunStore(agent_db)

    accepted = store.queue(a_request(), caller=CASE_DISPATCHER)

    # The 202 the caller will see is built from this, and it is the status of the committed row.
    assert accepted.run_id == RUN_ID
    assert accepted.status == "QUEUED"
    # Committed, not merely "written in this session": a second connection sees the row.
    with agent_db.connection() as connection:
        row = connection.execute(
            "SELECT run_id, case_id, input_revision, status, version, deadline_at FROM agent_run"
        ).fetchone()
    assert row is not None, "the row must be in the table, not only in the object that was returned"
    assert str(row["run_id"]) == RUN_ID
    assert str(row["case_id"]) == CASE_ID
    assert row["input_revision"] == 1
    assert row["status"] == "QUEUED"
    assert row["version"] == 1


def test_the_binding_of_run_to_case_is_stored_not_implied(agent_db: Database) -> None:
    """A run that cannot say which case and which revision it belongs to is not a durable record.

    ``(case_id, input_revision)`` is the pair case-service derives ``run_id`` from and the pair it
    reconciles against (docs/core-contracts.md:38), so both have to be readable back.
    """
    store = RunStore(agent_db)
    store.queue(a_request(), caller=CASE_DISPATCHER)

    view = store.read(RUN_ID)

    assert view.run_id == RUN_ID
    assert view.case_id == CASE_ID
    assert view.input_revision == 1
    assert view.status == "QUEUED"
    assert view.version == 1
    assert view.callback_ids == (), "no callback has been emitted yet, and the list is empty rather than absent"
    assert view.result_summary is None


def test_the_same_run_key_with_the_same_body_is_the_same_run(agent_db: Database) -> None:
    """Redelivery is normal: case-service retries a dispatch, and a retry is not a second investigation."""
    store = RunStore(agent_db)
    first = store.queue(a_request(), caller=CASE_DISPATCHER)
    second = store.queue(a_request(), caller=CASE_DISPATCHER)

    assert first == second
    with agent_db.connection() as connection:
        count = connection.execute("SELECT count(*) AS n FROM agent_run").fetchone()
    assert count is not None and count["n"] == 1


def test_the_same_run_key_with_a_different_body_is_refused(agent_db: Database) -> None:
    """The contract answers this 409 (contracts/core/openapi-agent.yaml:105), and nothing is overwritten."""
    store = RunStore(agent_db)
    store.queue(a_request(), caller=CASE_DISPATCHER)

    with pytest.raises(RunConflictError):
        store.queue(a_request(description="同一个 run key，换一个说法"), caller=CASE_DISPATCHER)

    with agent_db.connection() as connection:
        row = connection.execute("SELECT request_description FROM agent_run").fetchone()
    assert row is not None and row["request_description"] == "包裹丢了，希望退款"


def test_one_case_revision_is_one_run_even_when_the_run_id_differs(agent_db: Database) -> None:
    """The database refuses a second run for a revision, whoever derives the id.

    ``run_id`` is derived upstream from the pair, so two derivations that disagree would be a bug in the
    dispatcher — and this is the index that turns it into a visible refusal instead of two competing runs
    for one revision.
    """
    store = RunStore(agent_db)
    store.queue(a_request(), caller=CASE_DISPATCHER)

    with pytest.raises(RunConflictError):
        store.queue(a_request(run_id=str(uuid.uuid4())), caller=CASE_DISPATCHER)

    with agent_db.connection() as connection:
        count = connection.execute("SELECT count(*) AS n FROM agent_run").fetchone()
    assert count is not None and count["n"] == 1


def test_a_body_that_disagrees_with_the_token_identity_is_refused(agent_db: Database) -> None:
    """The body must agree with the service token and the case binding (docs/core-contracts.md:60).

    The dispatched context is what the run investigates, so a body naming another merchant's line is not a
    typo to store: it is a request to investigate someone else's order, and it is refused before any row
    exists.
    """
    store = RunStore(agent_db)

    # Both spellings of "whose policy this is" move together: the run's context and the pinned manifest. Since
    # C07.1 the two are required to agree with each other as well, so a body that changed only one of them
    # would be refused for *that* reason and this test would stop being about the token identity.
    with pytest.raises(RunIdentityMismatchError) as refused:
        store.queue(
            a_request(
                merchant_id="M-9999",
                policy_manifest={
                    "merchant_id": "M-9999",
                    "bundle_ids": ["policy-logistics-2026.09"],
                    "manifest_hash": MANIFEST_HASH,
                    "safety_epoch": 1,
                },
            ),
            caller=CASE_DISPATCHER,
        )

    assert refused.value.reason_code == REJECTED_IDENTITY_MISMATCH
    with agent_db.connection() as connection:
        count = connection.execute("SELECT count(*) AS n FROM agent_run").fetchone()
    assert count is not None and count["n"] == 0


def test_only_the_case_dispatcher_may_open_a_run(agent_db: Database) -> None:
    """The run's identity binding is to the token's subject: another service cannot dispatch one."""
    store = RunStore(agent_db)

    with pytest.raises(RunIdentityMismatchError):
        store.queue(a_request(), caller=VerifiedCaller(service="commerce-service", scope="run:dispatch"))

    with agent_db.connection() as connection:
        count = connection.execute("SELECT count(*) AS n FROM agent_run").fetchone()
    assert count is not None and count["n"] == 0


def test_cancelling_a_queued_run_is_recorded_and_repeating_it_is_not_a_second_cancellation(agent_db: Database) -> None:
    store = RunStore(agent_db)
    store.queue(a_request(), caller=CASE_DISPATCHER)

    first = store.cancel(RUN_ID)
    assert first.status == "CANCELLED"
    assert first.cancellation_requested is True

    second = store.cancel(RUN_ID)
    assert second.status == "CANCELLED"
    assert second.cancellation_requested is False, "the second call asked for something already true"


def test_cancelling_a_terminal_run_reports_what_it_actually_is(agent_db: Database) -> None:
    """A cancellation answer of RUNNING would be a lie, and so would CANCELLED for a finished run.

    ``CancelAck`` is deliberately narrower than ``RunView`` for this reason
    (contracts/core/openapi-agent.yaml:528).
    """
    store = RunStore(agent_db)
    store.queue(a_request(), caller=CASE_DISPATCHER)
    # The outcome a later slice's worker would reach. It is written directly here because no worker exists
    # in C06.1 — and the cancellation rule is about what the record says, not about who said it.
    with agent_db.connection() as connection:
        connection.execute(
            "UPDATE agent_run SET status = 'COMPLETED', version = version + 1 WHERE run_id = %(run_id)s",
            {"run_id": RUN_ID},
        )

    ack = store.cancel(RUN_ID)

    assert ack.status == "COMPLETED"
    assert ack.cancellation_requested is False


def test_reading_a_run_that_does_not_exist_is_not_an_empty_run(agent_db: Database) -> None:
    store = RunStore(agent_db)

    with pytest.raises(RunNotFoundError):
        store.read(str(uuid.uuid4()))

    with pytest.raises(RunNotFoundError):
        store.cancel(str(uuid.uuid4()))


def test_a_malformed_run_id_is_not_found_rather_than_a_server_error(agent_db: Database) -> None:
    """An id that cannot name a run gets the same answer as an id that does not: 404."""
    store = RunStore(agent_db)

    with pytest.raises(RunNotFoundError):
        store.read("not-a-uuid")


def test_the_deadline_is_stored_as_sent_and_never_recomputed(agent_db: Database) -> None:
    """Recovery must not extend the window (docs/agent-spec.md:42), so the stored instant is the sent one."""
    store = RunStore(agent_db)
    store.queue(a_request(deadline_at="2026-09-28T05:00:00+00:00"), caller=CASE_DISPATCHER)

    with agent_db.connection() as connection:
        row = connection.execute("SELECT deadline_at, active_deadline_at FROM agent_run").fetchone()

    assert row is not None
    assert row["deadline_at"].isoformat() == "2026-09-28T05:00:00+00:00"
    assert row["active_deadline_at"] is None, "no worker has started, so no window has been granted"


def test_the_stored_row_carries_the_typed_columns_not_only_a_json_blob(agent_db: Database) -> None:
    """The facts a later slice queries on are columns: a status to filter, a revision to compare.

    A store that kept the whole request as one document would answer the test above and fail this one,
    which is why both exist.
    """
    store = RunStore(agent_db)
    store.queue(a_request(), caller=CASE_DISPATCHER)

    with agent_db.connection() as connection:
        row = connection.execute(
            """
            SELECT merchant_id, customer_id, order_id, line_id, requested_actions, evidence_refs,
                   policy_manifest, traceparent, request_hash
            FROM agent_run
            """
        ).fetchone()

    assert row is not None
    assert row["merchant_id"] == "M-1001"
    assert row["customer_id"] == "C-2002"
    assert str(row["order_id"]) == ORDER_ID
    assert row["line_id"] == "7001"
    assert list(row["requested_actions"]) == ["REFUND"]
    assert list(row["evidence_refs"]) == ["ev-1"]
    assert row["policy_manifest"]["bundle_ids"] == ["policy-logistics-2026.09"]
    assert row["policy_manifest"]["manifest_hash"] == MANIFEST_HASH
    assert row["traceparent"] == "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    assert len(row["request_hash"]) == 64, "a canonical content hash, so two spellings of one body agree"


def test_two_spellings_of_one_request_are_one_request(agent_db: Database) -> None:
    """The hash is taken over a canonical form, so member order is not part of the body's identity."""
    store = RunStore(agent_db)
    store.queue(a_request(), caller=CASE_DISPATCHER)

    reordered = a_request(
        requested_actions=["REFUND"],
        evidence_refs=["ev-1"],
        policy_manifest={
            "safety_epoch": 1,
            "manifest_hash": MANIFEST_HASH,
            "merchant_id": "M-1001",
            "bundle_ids": ["policy-logistics-2026.09"],
        },
    )

    assert store.queue(reordered, caller=CASE_DISPATCHER).status == "QUEUED"
    with agent_db.connection() as connection:
        count = connection.execute("SELECT count(*) AS n FROM agent_run").fetchone()
    assert count is not None and count["n"] == 1


def test_a_run_for_another_case_is_its_own_row(agent_db: Database) -> None:
    """Two cases, two runs: the uniqueness is per (case_id, input_revision), not per revision."""
    store = RunStore(agent_db)
    store.queue(a_request(), caller=CASE_DISPATCHER)
    store.queue(a_request(run_id=str(uuid.uuid4()), case_id=OTHER_CASE_ID), caller=CASE_DISPATCHER)

    with agent_db.connection() as connection:
        count = connection.execute("SELECT count(*) AS n FROM agent_run").fetchone()
    assert count is not None and count["n"] == 2


def test_the_schema_is_where_the_tables_are(agent_db: Database, postgres_dsn: str) -> None:
    """The isolation the fixture promises is real: nothing was **written** outside the test's schema.

    The property is about rows, not about the tables' existence, and the first version of this test asserted the
    wrong one: it required ``public.agent_run`` not to exist at all. That held only while nothing ever migrated
    the service's own schema, and C07.1 gave the project a legitimate reason to — ``scripts/policy_index_ingest.py``
    and the e2e driver write the index into the service's schema, exactly as ``Database(default_dsn())`` means.
    With the table legitimately present and empty, the old assertion reported a leak that had not happened.

    So the count is taken **before and after** the write instead: that is unfalsifiable by a table's existence and
    tests what the fixture actually promises — a run queued in the test's schema cannot appear in the service's.
    """
    def public_rows() -> int:
        with psycopg.connect(postgres_dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT count(*) AS n FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'agent_run'"
            ).fetchone()
            if row is None or row["n"] == 0:
                # Nothing to leak into: the service's schema has never been migrated on this machine.
                return 0
            outer = connection.execute("SELECT count(*) AS n FROM public.agent_run").fetchone()
        return int(outer["n"]) if outer else 0

    before = public_rows()
    store = RunStore(agent_db)
    store.queue(a_request(), caller=CASE_DISPATCHER)

    assert public_rows() == before