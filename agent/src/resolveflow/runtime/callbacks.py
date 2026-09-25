"""The Agent's callback outbox: the durable record of what the case file must eventually be told.

A run does not decide anything until the model client exists (C06.3), but the *mechanism* has to be real
before then, because the first callback is exactly the moment when a lost delivery would look like a run
that never started. The mechanism is an append-first outbox:

1. ``enqueue`` writes the callback and commits, before anything is sent (docs/domain-model.md:69).
2. delivery is a consequence of the row, and a failed attempt records *why* and *when to retry* rather
   than deleting the fact.
3. the case service is idempotent on ``callback_id``, so a redelivery after a lost acknowledgement is
   recognised as ``DUPLICATE`` instead of applied twice (contracts/core/openapi-case.yaml:752).

Two things are deliberately derived rather than accepted from a caller:

- **``callback_id``** comes from ``(case_id, input_revision, kind)``. The Agent is the only producer of its
  own callbacks, and a derived id is what makes a retry after a crash compute the *same* key — a random
  one would turn every retry into a new callback.
- **``run_id``/``case_id``/``input_revision``** come from the run row. A producer that could name its own
  revision could send a callback that belongs to a revision the case no longer holds.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from resolveflow.contracts.enums import CallbackKind
from resolveflow.runtime.db import Database
from resolveflow.runtime.runs import _require_uuid

__all__ = [
    "DEAD",
    "DELIVERED",
    "PENDING",
    "CallbackEnvelope",
    "CallbackKind",
    "CallbackRecord",
    "CallbackStore",
    "UnknownCallbackError",
]

#: Not yet accepted by the case service. The only state the delivery loop drains.
PENDING = "PENDING"

#: The case service answered. ACCEPTED, DUPLICATE and STALE all end here: none of them is retryable.
DELIVERED = "DELIVERED"

#: The delivery can never succeed: the service token is wrong, the case is unknown, or the contract refuses
#: the payload. Kept as history with its reason, and deliberately not retried (003_agent_callback_dead.sql).
DEAD = "DEAD"

#: The dispositions that mean the case service has the callback (contracts/core/openapi-case.yaml:1282).
_DISPOSITIONS = ("ACCEPTED", "DUPLICATE", "STALE")

#: What each kind's payload must carry. The case contract fixes these shapes
#: (contracts/core/openapi-case.yaml:2214); checking them here means a malformed callback is refused by
#: its producer, where the mistake is, rather than by the consumer, where it looks like a protocol bug.
_REQUIRED_PAYLOAD_KEYS: dict[str, tuple[str, ...]] = {
    CallbackKind.STARTED.value: ("started_at",),
    CallbackKind.QUESTION.value: ("question_id", "questions", "reason_codes"),
    CallbackKind.PROPOSAL.value: ("proposal_id", "recommended_action"),
    CallbackKind.FAILED.value: ("reason_codes", "retryable"),
}

#: The longest ``callback_id`` the case contract accepts (openapi-case.yaml:2206).
_MAX_CALLBACK_ID = 64


class UnknownCallbackError(LookupError):
    """The callback, or the run it belongs to, is not in the outbox.

    A ``LookupError`` rather than a value error: nothing about the request was malformed — the thing it
    names simply is not there.
    """


@dataclass(frozen=True, slots=True)
class CallbackEnvelope:
    """One callback, as it will be sent. The subject is filled in by the store from the run row.

    ``callback_id`` is derived, and ``run_id``/``case_id``/``input_revision`` are not accepted here on
    purpose: a callback that could name its own revision could describe a case state that does not exist.
    """

    kind: CallbackKind
    payload: dict[str, Any]
    traceparent: str | None = None

    def __post_init__(self) -> None:
        required = _REQUIRED_PAYLOAD_KEYS.get(self.kind.value)
        if required is None:
            raise ValueError(f"{self.kind!r} is not a callback kind the case service accepts")
        missing = [key for key in required if key not in self.payload]
        if missing:
            raise ValueError(f"{self.kind.value} callback payload is missing {missing}")

    @staticmethod
    def callback_id_for(case_id: str, input_revision: int, kind: CallbackKind) -> str:
        """``cb-<case_id>-<revision>-<kind>``, the form the published example uses.

        Derived so that a retry computes the same id. The result is checked against the wire limit here
        rather than at delivery time: an id the case service would reject is not a callback that can ever
        be delivered, so it must not be written to the outbox at all.
        """
        callback_id = f"cb-{case_id}-{input_revision}-{kind.value.lower()}"
        if len(callback_id) > _MAX_CALLBACK_ID:
            raise ValueError(
                f"the derived callback_id is {len(callback_id)} characters and the case contract allows "
                f"{_MAX_CALLBACK_ID}: {callback_id}"
            )
        return callback_id


@dataclass(frozen=True, slots=True)
class CallbackRecord:
    """One row of the outbox, as a reader sees it."""

    callback_id: str
    run_id: str
    case_id: str
    input_revision: int
    kind: str
    payload: dict[str, Any]
    status: str
    attempts: int
    disposition: str | None = None
    last_error: str | None = None
    next_attempt_at: dt.datetime | None = None
    created_at: dt.datetime | None = None
    delivered_at: dt.datetime | None = None


class CallbackStore:
    """The outbox, over :class:`~resolveflow.runtime.db.Database`.

    Every method is one transaction's worth of work, and none of them performs a network call: the delivery
    client is what sends, and it calls ``record_delivery``/``record_failure`` afterwards so the record of
    what happened is written separately from the attempt.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    @property
    def database(self) -> Database:
        return self._database

    def pending(self, *, now: dt.datetime | None = None, limit: int = 50) -> list[CallbackRecord]:
        """The deliveries that are due, oldest first.

        A row with no ``next_attempt_at`` is due immediately; one that failed is due when its retry was
        scheduled for. Ordering by ``(next_attempt_at, created_at)`` is what makes a backlog age visibly.
        """
        with self._database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM agent_callback_outbox
                WHERE status = %(status)s
                  AND (next_attempt_at IS NULL OR next_attempt_at <= %(now)s)
                ORDER BY next_attempt_at NULLS FIRST, created_at
                LIMIT %(limit)s
                """,
                {"status": PENDING, "now": now or dt.datetime.now(dt.UTC), "limit": limit},
            ).fetchall()
        return [_as_record(row) for row in rows]

    def list_for_run(self, run_id: str) -> list[CallbackRecord]:
        """Every callback this run has emitted, oldest first. What ``RunView.callback_ids`` reports."""
        _require_uuid("run_id", run_id)
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_callback_outbox WHERE run_id = %(run_id)s ORDER BY created_at",
                {"run_id": run_id},
            ).fetchall()
        return [_as_record(row) for row in rows]

    def record_delivery(self, callback_id: str, *, disposition: str) -> CallbackRecord:
        """The case service answered: finish the callback with the answer it gave.

        Idempotent, and the *first* answer is the one kept. A retry after a lost acknowledgement arrives as
        ``DUPLICATE`` — the callback was already applied, so the delivery that was actually applied is the
        earlier one, and overwriting ``ACCEPTED`` with ``DUPLICATE`` would lose which attempt did the work.
        """
        if disposition not in _DISPOSITIONS:
            raise ValueError(f"{disposition!r} is not a callback disposition: expected one of {_DISPOSITIONS}")
        now = dt.datetime.now(dt.UTC)
        with self._database.connection() as connection:
            row = connection.execute(
                """
                UPDATE agent_callback_outbox
                SET status = %(status)s,
                    disposition = COALESCE(disposition, %(disposition)s),
                    -- Counted only on the first answer. A redelivery after a lost acknowledgement is a second
                    -- transport attempt but the SAME callback, and counting it twice would make attempts
                    -- depend on how flaky the network was rather than on how much work the callback took.
                    attempts = attempts + CASE WHEN delivered_at IS NULL THEN 1 ELSE 0 END,
                    delivered_at = COALESCE(delivered_at, %(now)s),
                    next_attempt_at = NULL,
                    updated_at = %(now)s
                WHERE callback_id = %(callback_id)s
                RETURNING *
                """,
                {
                    "status": DELIVERED,
                    "disposition": disposition,
                    "now": now,
                    "callback_id": callback_id,
                },
            ).fetchone()
        if row is None:
            raise UnknownCallbackError(f"no callback with id {callback_id}")
        return _as_record(row)

    def record_failure(
        self, callback_id: str, *, error: str, retry_after_seconds: int | None = None
    ) -> CallbackRecord:
        """The delivery attempt failed: count it, keep the reason, and schedule the next try.

        The row stays PENDING — the callback has not been communicated, and dropping it here is precisely
        the failure the outbox exists to prevent.
        """
        now = dt.datetime.now(dt.UTC)
        with self._database.connection() as connection:
            row = connection.execute(
                """
                UPDATE agent_callback_outbox
                SET attempts = attempts + 1,
                    last_error = %(error)s,
                    next_attempt_at = %(next_attempt_at)s,
                    updated_at = %(now)s
                WHERE callback_id = %(callback_id)s
                RETURNING *
                """,
                {
                    "error": error,
                    "next_attempt_at": (now + dt.timedelta(seconds=retry_after_seconds))
                    if retry_after_seconds is not None
                    else None,
                    "now": now,
                    "callback_id": callback_id,
                },
            ).fetchone()
        if row is None:
            raise UnknownCallbackError(f"no callback with id {callback_id}")
        return _as_record(row)

    def enqueue_for_run(self, run_id: str, envelope: CallbackEnvelope) -> CallbackRecord:
        """Record a callback for one named run.

        The run is named explicitly rather than inferred, because two runs of the same case at different
        revisions both exist and a callback must belong to the one that reached the state.
        """
        _require_uuid("run_id", run_id)
        with self._database.connection() as connection:
            run = connection.execute(
                "SELECT run_id, case_id, input_revision, traceparent FROM agent_run WHERE run_id = %(run_id)s",
                {"run_id": run_id},
            ).fetchone()
            if run is None:
                raise UnknownCallbackError(f"no run with id {run_id}")
            callback_id = CallbackEnvelope.callback_id_for(
                str(run["case_id"]), int(run["input_revision"]), envelope.kind
            )
            existing = connection.execute(
                "SELECT * FROM agent_callback_outbox WHERE callback_id = %(callback_id)s",
                {"callback_id": callback_id},
            ).fetchone()
            if existing is not None:
                return _as_record(existing)
            now = dt.datetime.now(dt.UTC)
            row = connection.execute(
                """
                INSERT INTO agent_callback_outbox (
                    callback_id, run_id, case_id, input_revision, kind, payload, traceparent,
                    status, attempts, created_at, updated_at
                ) VALUES (
                    %(callback_id)s, %(run_id)s, %(case_id)s, %(input_revision)s, %(kind)s, %(payload)s,
                    %(traceparent)s, %(status)s, 0, %(now)s, %(now)s
                )
                RETURNING *
                """,
                {
                    "callback_id": callback_id,
                    "run_id": run["run_id"],
                    "case_id": run["case_id"],
                    "input_revision": run["input_revision"],
                    "kind": envelope.kind.value,
                    "payload": _json(envelope.payload),
                    "traceparent": envelope.traceparent or run["traceparent"],
                    "status": PENDING,
                    "now": now,
                },
            ).fetchone()
        assert row is not None
        return _as_record(row)


    def record_dead(self, callback_id: str, *, error: str) -> CallbackRecord:
        """The delivery can never succeed: count the attempt, keep the reason, stop retrying.

        A distinct transition rather than "a failure with no retry time", because the two mean different
        things to a reader: a PENDING row with no time is work waiting to be picked up, while this row is
        finished-with-a-problem. It is what makes a queue full of permanent refusals visible as such.
        """
        now = dt.datetime.now(dt.UTC)
        with self._database.connection() as connection:
            row = connection.execute(
                """
                UPDATE agent_callback_outbox
                SET status = %(status)s,
                    attempts = attempts + 1,
                    last_error = %(error)s,
                    next_attempt_at = NULL,
                    updated_at = %(now)s
                WHERE callback_id = %(callback_id)s
                RETURNING *
                """,
                {"status": DEAD, "error": error, "now": now, "callback_id": callback_id},
            ).fetchone()
        if row is None:
            raise UnknownCallbackError(f"no callback with id {callback_id}")
        return _as_record(row)


def _json(value: dict[str, Any]) -> Any:
    """The payload as jsonb.

    ``psycopg`` adapts a dict to jsonb only when it is wrapped, so the wrapper is explicit here rather than
    relying on the driver's guess.
    """
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _as_record(row: dict[str, Any]) -> CallbackRecord:
    return CallbackRecord(
        callback_id=str(row["callback_id"]),
        run_id=str(row["run_id"]),
        case_id=str(row["case_id"]),
        input_revision=int(row["input_revision"]),
        kind=str(row["kind"]),
        payload=dict(row["payload"]),
        status=str(row["status"]),
        attempts=int(row["attempts"]),
        disposition=row["disposition"],
        last_error=row["last_error"],
        next_attempt_at=row["next_attempt_at"],
        created_at=row["created_at"],
        delivered_at=row["delivered_at"],
    )