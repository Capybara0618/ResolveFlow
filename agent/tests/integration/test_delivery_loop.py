"""C06.3b: the resident worker that drains the callback outbox, and what starting the app does to it.

C06.1b-2 built ``CallbackDelivery`` and nothing called it. A decision the Agent had already made sat in
``agent_callback_outbox`` until a human ran a drain, which means the case service — the side that acts on the
decision — never heard about it. This module is the caller.

Four things are worth asserting separately, because they fail for different reasons:

- **the worker delivers without being asked.** A queued callback reaches the transport and the row reaches
  DELIVERED with no test and no operator in the loop.
- **it stops.** ``close()`` ends the loop and no further attempts happen; a worker that cannot be stopped is a
  shutdown that either hangs or races a write.
- **one tick is callable on its own.** The loop's *act* is separate from the loop's *schedule*, which is what
  makes the app-level test below possible and what a manual drain would use.
- **a tick never kills the loop.** A database that is not there is logged and retried; a thread whose first
  exception ends it is a worker that silently stops delivering everything behind the failure.

The transport is injected so each answer can be chosen, and the store is real: what is asserted is the
committed outbox row, not a mock's opinion.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Any

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from resolveflow.api.app import create_app
from resolveflow.runtime.callbacks import DELIVERED, PENDING, CallbackEnvelope, CallbackKind, CallbackStore
from resolveflow.runtime.db import Database, drop_schema
from resolveflow.runtime.delivery import CallbackDelivery, DeliveryResult, DeliveryUnavailableError
from resolveflow.runtime.dispatch import CallbackDeliveryLoop
from resolveflow.runtime.runs import RunRequest, RunStore, VerifiedCaller
from tests.integration import future_deadline

RUN_ID = "11111111-2222-4333-8444-555555555555"
CASE_ID = "9c858901-8a57-4791-81fe-4c455b099bc9"
ORDER_ID = "00000000-0000-4000-8000-0000000000aa"
MANIFEST_HASH = "9" * 64
CASE_BASE = "http://127.0.0.1:8083"
SECRET = "resolveflow-core-demo-identity-secret"  # noqa: S105 - the published local demonstration secret

CASE_DISPATCHER = VerifiedCaller(
    service="case-service",
    scope="run:dispatch",
    merchant_id="M-1001",
    buyer_id="C-2002",
)


def a_run() -> RunRequest:
    return RunRequest(
        run_id=RUN_ID,
        case_id=CASE_ID,
        input_revision=1,
        merchant_id="M-1001",
        buyer_id="C-2002",
        order_id=ORDER_ID,
        line_id="7001",
        description="包裹丢了，希望退款",
        requested_actions=["REFUND"],
        evidence_refs=["ev-1"],
        policy_manifest={
            "merchant_id": "M-1001",
            "bundle_ids": ["policy-logistics-2026.09"],
            "manifest_hash": MANIFEST_HASH,
            "safety_epoch": 1,
        },
        deadline_at=future_deadline(),
        traceparent="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
    )


def a_started() -> CallbackEnvelope:
    return CallbackEnvelope(
        kind=CallbackKind.STARTED,
        payload={"schema_version": 2, "started_at": "2026-09-24T10:00:00Z"},
    )


def queued(agent_db: Database) -> CallbackStore:
    """One queued callback, as a run that reached the Agent would leave it."""
    RunStore(agent_db).queue(a_run(), caller=CASE_DISPATCHER)
    return CallbackStore(agent_db)


@dataclass
class CountingPoster:
    """A transport that records how often it was asked and can be told to fail."""

    answers: list[Any] = field(default_factory=list)
    calls: int = 0
    unavailable: bool = False

    def __call__(
        self, base_url: str, delivery: Any, *, secret: str, ttl_seconds: int, timeout: float
    ) -> DeliveryResult:
        self.calls += 1
        if self.unavailable:
            raise DeliveryUnavailableError("the case service could not be reached (stub)")
        if self.answers:
            answer = self.answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return DeliveryResult(disposition="ACCEPTED", case_version=2)


def a_loop(store: CallbackStore, poster: CountingPoster, *, interval: float = 0.01) -> CallbackDeliveryLoop:
    return CallbackDeliveryLoop(
        CallbackDelivery(store, case_base_url=CASE_BASE, secret=SECRET, post=poster),
        interval_seconds=interval,
        batch_size=10,
    )


def _row_status(store: CallbackStore, callback_id: str) -> str:
    rows = [row for row in store.list_for_run(RUN_ID) if row.callback_id == callback_id]
    assert rows, f"no outbox row for {callback_id}"
    return rows[0].status


# ── the worker delivers ──────────────────────────────────────────────────────────────────────────────


def test_the_worker_delivers_a_queued_callback_without_being_asked(agent_db: Database) -> None:
    store = queued(agent_db)
    record = store.enqueue_for_run(RUN_ID, a_started())
    poster = CountingPoster()

    loop = a_loop(store, poster)
    loop.start()
    try:
        deadline = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=5)
        while dt.datetime.now(dt.UTC) < deadline:
            if _row_status(store, record.callback_id) == DELIVERED:
                break
            time.sleep(0.02)
    finally:
        loop.close()

    assert _row_status(store, record.callback_id) == DELIVERED
    # At least one attempt, and exactly one *accepted* delivery: the row is DELIVERED with a recorded
    # disposition. A second attempt would only be needed if the first had not been recorded, which is the
    # duplicate the Java side would have to answer. The loop may tick again while this test is reading, and a
    # delivered row is no longer due, so nothing more is sent.
    assert poster.calls >= 1
    assert store.list_for_run(RUN_ID)[0].disposition == "ACCEPTED"


def test_closing_the_worker_stops_it(agent_db: Database) -> None:
    store = queued(agent_db)
    poster = CountingPoster()

    loop = a_loop(store, poster)
    loop.start()
    assert loop.running
    loop.close()
    assert not loop.running

    # Nothing is queued any more, so a loop still running would have no work to show — which is exactly why
    # a fresh row proves the loop is gone rather than idle.
    poster.calls = 0
    store.enqueue_for_run(RUN_ID, a_started())
    time.sleep(0.2)
    assert poster.calls == 0


def test_one_tick_can_be_run_without_starting_the_thread(agent_db: Database) -> None:
    store = queued(agent_db)
    record = store.enqueue_for_run(RUN_ID, a_started())
    poster = CountingPoster()

    loop = a_loop(store, poster)
    assert not loop.running
    attempted = loop.run_once()

    assert attempted == 1
    assert poster.calls == 1
    assert _row_status(store, record.callback_id) == DELIVERED
    assert not loop.running


def test_a_tick_that_cannot_reach_the_database_does_not_kill_the_loop(agent_db: Database) -> None:
    # A store whose connections fail: the tick must report "nothing done" rather than propagate, because the
    # thread it runs on has nobody to catch it and a dead worker stops delivering everything behind it.
    class BrokenStore:
        def pending(self, **_: Any) -> list[Any]:
            raise RuntimeError("agent_db is not reachable")

        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"the tick reached {name} on a store that cannot connect")

    broken = CallbackDelivery(
        BrokenStore(),  # type: ignore[arg-type]
        case_base_url=CASE_BASE,
        secret=SECRET,
        post=CountingPoster(),
    )
    loop = CallbackDeliveryLoop(broken, interval_seconds=0.01)

    assert loop.run_once() == 0
    # And afterwards it is still usable, which is the property that matters: a warning, not a funeral.
    assert loop.run_once() == 0


def test_a_failed_delivery_is_retried_rather_than_lost(agent_db: Database) -> None:
    store = queued(agent_db)
    record = store.enqueue_for_run(RUN_ID, a_started())
    poster = CountingPoster(unavailable=True)

    loop = a_loop(store, poster)
    assert loop.run_once() == 1

    assert _row_status(store, record.callback_id) == PENDING
    assert poster.calls == 1
    row = store.list_for_run(RUN_ID)[0]
    # A reason and a stated time, so an operator can tell "waiting" from "stuck".
    assert row.last_error
    assert row.next_attempt_at is not None


# ── starting the app ─────────────────────────────────────────────────────────────────────────────────


def test_the_app_starts_the_worker_and_stops_it_at_shutdown(agent_db: Database, postgres_dsn: str) -> None:
    app = create_app(
        provider=object(),  # type: ignore[arg-type]
        agent_dsn=postgres_dsn,
        agent_schema=agent_db.schema,
        case_base_url="http://127.0.0.1:9",
        delivery_interval_seconds=0.01,
        migrate=False,
    )

    with TestClient(app) as http:
        assert http.get("/health").status_code == 200
        loop = app.state.delivery_loop
        assert loop is not None, "the app must start the callback delivery worker by default"
        assert loop.running

    assert not loop.running, "shutdown must stop the worker rather than leaving a thread writing"


def test_the_worker_can_be_switched_off(tmp_path: Any) -> None:
    app = create_app(
        provider_db=tmp_path / "provider.sqlite3",
        run_store=None,
        agent_dsn="postgresql://agent:agent@127.0.0.1:1/agent_db",
        delivery_loop=False,
    )
    with TestClient(app) as http:
        assert http.get("/health").status_code == 200
        assert app.state.delivery_loop is None


def test_starting_still_works_when_agent_db_is_unreachable(tmp_path: Any) -> None:
    """The lazy database property, now with a worker attached to it.

    The worker's first tick asks whether the store is usable. If that question were asked while the app was
    starting, this test would not get a client at all — an Agent that cannot reach its own database must
    still start and report its health, which is what a deployment's readiness probe reads.
    """
    app = create_app(
        provider_db=tmp_path / "provider.sqlite3",
        agent_dsn="postgresql://agent:agent@127.0.0.1:1/agent_db",
        delivery_interval_seconds=0.01,
    )
    with TestClient(app) as http:
        assert http.get("/health").status_code == 200
        assert app.state.delivery_loop is not None


def test_starting_the_app_does_not_create_the_schema(postgres_dsn: str, tmp_path: Any) -> None:
    """The worker must not make "start the Agent" and "create the tables" the same act.

    Found by ``test_run_store.py::test_the_schema_is_where_the_tables_are`` going red when this worker was
    added: the loop's first tick called the store holder's ``require()``, which migrates on first use, so
    merely starting an app against the shared ``public`` schema wrote ``agent_run`` there. A test that
    constructs and starts an app must be able to do so without owning anyone's schema — and in production the
    tables belong to whoever dispatches a run, not to the fact that a process booted.
    """
    schema = f"boot_{dt.datetime.now(dt.UTC).strftime('%H%M%S%f')}"
    app = create_app(
        provider_db=tmp_path / "provider.sqlite3",
        agent_dsn=postgres_dsn,
        agent_schema=schema,
        delivery_interval_seconds=0.01,
    )
    try:
        with TestClient(app) as http:
            assert http.get("/health").status_code == 200
            time.sleep(0.15)  # several ticks, so a tick that migrated would have had its chance

            with psycopg.connect(postgres_dsn, row_factory=dict_row) as connection:
                created = connection.execute(
                    "SELECT count(*) AS n FROM information_schema.schemata WHERE schema_name = %s",
                    (schema,),
                ).fetchone()
        assert created is not None and created["n"] == 0, "starting the app created its schema"
    finally:
        # Nothing to drop: the point of the test is that no schema was made. This is only a guard in case a
        # future change makes one, so the suite does not leak it into the shared server.
        drop_schema(postgres_dsn, schema)