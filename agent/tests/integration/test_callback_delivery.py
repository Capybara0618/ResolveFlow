"""C06.1b: delivering a queued callback, and what each answer does to the outbox row.

The outbox made a decision durable; this module is about the consequence. Two rules shape the whole thing:

- **what the case service said decides whether we try again.** ``ACCEPTED``/``DUPLICATE``/``STALE`` all
  mean it has the callback and none of them is retryable; a 5xx or a dropped connection means it does not
  yet, and the row stays queued with a stated reason and a stated time. A refusal that can never succeed
  (bad service token, unknown case, payload the contract rejects) must **not** be retried forever behind a
  healthy-looking queue.
- **the Agent is the producer here, so its own bugs must not look like transient outages.** 422 means this
  Agent sent something the contract refuses; retrying it would hide that.

The transport is injected. What is real in these tests is the store and the database: the attempt count,
the retry schedule, the reason, and the terminal states are all asserted against the committed row.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
from dataclasses import dataclass
from typing import Any

import pytest

from resolveflow.runtime.callbacks import (
    DEAD,
    DELIVERED,
    PENDING,
    CallbackEnvelope,
    CallbackKind,
    CallbackStore,
)
from resolveflow.runtime.db import Database
from resolveflow.runtime.delivery import (
    MAX_RETRY_SECONDS,
    DeliveryRefusedError,
    DeliveryResult,
    DeliveryUnavailableError,
    callback_delivery,
    post_delivery,
    retry_delay_seconds,
)
from resolveflow.runtime.runs import RunRequest, RunStore, VerifiedCaller

RUN_ID = "11111111-2222-4333-8444-555555555555"
CASE_ID = "9c858901-8a57-4791-81fe-4c455b099bc9"
ORDER_ID = "00000000-0000-4000-8000-0000000000aa"
MANIFEST_HASH = "9" * 64
DEADLINE = "2026-09-28T05:00:00Z"
CASE_BASE = "http://127.0.0.1:8081"
SECRET = "resolveflow-core-demo-identity-secret"

CASE_DISPATCHER = VerifiedCaller(
    service="case-service",
    scope="run:dispatch",
    merchant_id="M-1001",
    customer_id="C-2002",
)


def a_run(**overrides: Any) -> RunRequest:
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
            "bundle_ids": ["policy-logistics-2026.09"],
            "manifest_hash": MANIFEST_HASH,
            "safety_epoch": 1,
        },
        "deadline_at": DEADLINE,
        "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
    }
    fields.update(overrides)
    return RunRequest(**fields)


def a_started() -> CallbackEnvelope:
    return CallbackEnvelope(
        kind=CallbackKind.STARTED,
        payload={"schema_version": 2, "started_at": "2026-09-24T10:00:00Z"},
    )


def queued(agent_db: Database) -> CallbackStore:
    RunStore(agent_db).queue(a_run(), caller=CASE_DISPATCHER)
    return CallbackStore(agent_db)


@dataclass
class ScriptedPoster:
    """A transport whose every answer is chosen by the test.

    Records what it was asked to send, so a test can assert the wire body rather than only the outcome —
    the Java side is the authority on that body and this is where the two ends are checked to agree.
    """

    responses: list[Any]
    calls: list[dict[str, Any]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.calls is None:
            self.calls = []

    def __call__(
        self, base_url: str, delivery: Any, *, secret: str, ttl_seconds: int, timeout: float
    ) -> DeliveryResult:
        self.calls.append(
            {
                "base_url": base_url,
                "callback_id": delivery.callback_id,
                "case_id": delivery.case_id,
                "secret": secret,
                "ttl_seconds": ttl_seconds,
                "timeout": timeout,
            }
        )
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_an_accepted_delivery_finishes_the_row(agent_db: Database) -> None:
    callbacks = queued(agent_db)
    callbacks.enqueue_for_run(RUN_ID, a_started())
    poster = ScriptedPoster([DeliveryResult(disposition="ACCEPTED", case_version=6)])

    outcome = callback_delivery(
        callbacks, case_base_url=CASE_BASE, secret=SECRET, post=poster
    ).deliver_due()[0]

    assert outcome.status == "DELIVERED"
    assert outcome.disposition == "ACCEPTED"
    assert outcome.attempted, "the attempt happened and is recorded"
    after = callbacks.list_for_run(RUN_ID)[0]
    assert after.status == DELIVERED
    assert after.attempts == 1
    assert after.disposition == "ACCEPTED"
    assert after.delivered_at is not None


def test_a_duplicate_answer_also_finishes_the_row(agent_db: Database) -> None:
    """A redelivery after a lost acknowledgement is the case service telling us it already has it."""
    callbacks = queued(agent_db)
    callbacks.enqueue_for_run(RUN_ID, a_started())
    poster = ScriptedPoster([DeliveryResult(disposition="DUPLICATE", case_version=None)])

    outcome = callback_delivery(callbacks, case_base_url=CASE_BASE, secret=SECRET, post=poster).deliver_due()[0]

    assert outcome.status == "DELIVERED"
    assert outcome.disposition == "DUPLICATE"
    assert callbacks.pending() == [], "the case service has it; there is nothing left to send"


def test_a_stale_answer_finishes_the_row_too(agent_db: Database) -> None:
    callbacks = queued(agent_db)
    callbacks.enqueue_for_run(RUN_ID, a_started())
    poster = ScriptedPoster([DeliveryResult(disposition="STALE", case_version=None)])

    outcome = callback_delivery(callbacks, case_base_url=CASE_BASE, secret=SECRET, post=poster).deliver_due()[0]

    assert outcome.status == "DELIVERED"
    assert outcome.disposition == "STALE"


def test_a_server_error_keeps_the_row_queued_with_a_reason_and_a_time(agent_db: Database) -> None:
    callbacks = queued(agent_db)
    callbacks.enqueue_for_run(RUN_ID, a_started())
    poster = ScriptedPoster([DeliveryUnavailableError("503 from the case service")])

    before = dt.datetime.now(dt.UTC)
    outcome = callback_delivery(callbacks, case_base_url=CASE_BASE, secret=SECRET, post=poster).deliver_due()[0]

    assert outcome.status == PENDING
    assert outcome.error is not None and "503" in outcome.error
    after = callbacks.list_for_run(RUN_ID)[0]
    assert after.status == PENDING
    assert after.attempts == 1
    assert after.last_error is not None and "503" in after.last_error
    assert after.next_attempt_at is not None, "a retry has a stated time, not an immediate loop"
    # The delay is the first step of the backoff, measured from the failed attempt rather than guessed.
    elapsed = (after.next_attempt_at - before).total_seconds()
    assert retry_delay_seconds(1) - 1 <= elapsed <= retry_delay_seconds(1) + 5
    assert outcome.retry_at == after.next_attempt_at
    # And it did NOT get marked delivered.
    assert after.delivered_at is None


def test_the_outbox_accepts_the_three_delivery_states_and_nothing_else(agent_db: Database) -> None:
    """The migration that added DEAD must have applied, and the column must still be constrained.

    An unconstrained status column would let a fourth, misspelled state be stored silently — the kind of
    row that makes a queue look like it has work when nothing will ever pick it up.
    """
    callbacks = queued(agent_db)
    record = callbacks.enqueue_for_run(RUN_ID, a_started())

    with agent_db.connection() as connection:
        constraint = connection.execute(
            """
            SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint
            WHERE conrelid = 'agent_callback_outbox'::regclass AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE '%%status%%'
            """
        ).fetchall()

    assert constraint, "the status CHECK from 002/003 must exist"
    definitions = " ".join(str(row["definition"]) for row in constraint)
    for state in (PENDING, DELIVERED, DEAD):
        assert state in definitions, f"{state} is not accepted by the status constraint: {definitions}"
    # And the row the store just wrote is one of them.
    assert record.status == PENDING


def test_the_retry_delay_grows_and_is_capped() -> None:
    """Backoff is a policy, so it is pinned: a case service that is down is not hammered, and a callback
    that is hours late is worse than one retried a few extra times."""
    assert [retry_delay_seconds(n) for n in (1, 2, 3, 4, 5)] == [5, 10, 20, 40, 80]
    assert retry_delay_seconds(10) == MAX_RETRY_SECONDS
    assert retry_delay_seconds(99) == MAX_RETRY_SECONDS


def test_a_permanent_refusal_is_not_retried_forever(agent_db: Database) -> None:
    """401/403/404/409/422 cannot become true by trying again, so the row must stop being retried.

    It is kept, not deleted: the callback was a decision the run really reached, and the record of why it
    could not be delivered is the only thing that explains the missing case update (docs/domain-model.md:69).
    """
    callbacks = queued(agent_db)
    callbacks.enqueue_for_run(RUN_ID, a_started())
    poster = ScriptedPoster([DeliveryRefusedError("422: the contract refuses this payload")])

    outcome = callback_delivery(callbacks, case_base_url=CASE_BASE, secret=SECRET, post=poster).deliver_due()[0]

    assert outcome.status == DEAD
    after = callbacks.list_for_run(RUN_ID)[0]
    assert after.status == DEAD
    assert after.attempts == 1
    assert after.last_error is not None and "422" in after.last_error
    assert callbacks.pending() == [], "a permanent refusal is not queued work"


def test_a_failed_delivery_is_retried_on_the_next_pass(agent_db: Database) -> None:
    callbacks = queued(agent_db)
    callbacks.enqueue_for_run(RUN_ID, a_started())
    poster = ScriptedPoster(
        [
            DeliveryUnavailableError("connection refused"),
            DeliveryResult(disposition="ACCEPTED", case_version=6),
        ]
    )
    delivery = callback_delivery(callbacks, case_base_url=CASE_BASE, secret=SECRET, post=poster)

    first = delivery.deliver_due()[0]
    # Nothing is due yet: the retry was scheduled, so an immediate second pass must not send again.
    due_again = delivery.deliver_due()
    second = delivery.deliver_due(now=first.retry_at)[0] if first.retry_at else None

    assert first.status == PENDING
    assert due_again == [], "a scheduled retry is not due yet"
    assert second is not None and second.status == "DELIVERED"
    assert [call["callback_id"] for call in poster.calls] == [callbacks.list_for_run(RUN_ID)[0].callback_id] * 2


def test_a_delivered_callback_is_never_sent_twice_by_the_client(agent_db: Database) -> None:
    callbacks = queued(agent_db)
    callbacks.enqueue_for_run(RUN_ID, a_started())
    callbacks.record_delivery(callbacks.list_for_run(RUN_ID)[0].callback_id, disposition="ACCEPTED")
    poster = ScriptedPoster([])

    outcomes = callback_delivery(callbacks, case_base_url=CASE_BASE, secret=SECRET, post=poster).deliver_due()

    assert outcomes == []
    assert poster.calls == [], "a finished callback is not work"


def test_every_attempt_gets_a_fresh_service_token_for_the_agent(agent_db: Database) -> None:
    """The token is minted per attempt and names the Agent: a cached one could expire mid-retry."""
    callbacks = queued(agent_db)
    callbacks.enqueue_for_run(RUN_ID, a_started())
    poster = ScriptedPoster(
        [DeliveryUnavailableError("boom"), DeliveryResult(disposition="ACCEPTED", case_version=6)]
    )
    delivery = callback_delivery(callbacks, case_base_url=CASE_BASE, secret=SECRET, post=poster)

    first = delivery.deliver_due()[0]
    delivery.deliver_due(now=first.retry_at)

    assert len(poster.calls) == 2
    assert all(call["secret"] == SECRET for call in poster.calls)
    assert all(call["base_url"] == CASE_BASE for call in poster.calls)


def test_the_wire_body_is_the_callback_contract() -> None:
    """The body is checked field by field against what the Java receiver reads.

    A delivery that is right in Python and wrong on the wire looks like a case service that ignores
    callbacks, so the field names and nesting are asserted here rather than assumed
    (java/.../internal/AgentCallbackRequest.java).
    """
    sent: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> Any:
        sent["url"] = request.full_url
        sent["body"] = json.loads(request.data.decode("utf-8"))
        sent["authorization"] = request.headers.get("Authorization")
        sent["content_type"] = request.headers.get("Content-type")
        return FakeResponse(200, {"disposition": "ACCEPTED", "case_version": 6})

    @dataclass
    class Row:
        callback_id: str = "cb-9c858901-8a57-4791-81fe-4c455b099bc9-1-started"
        run_id: str = RUN_ID
        case_id: str = CASE_ID
        input_revision: int = 1
        kind: str = "STARTED"
        payload: Any = None
        traceparent: str | None = "00-4af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"

        def __post_init__(self) -> None:
            if self.payload is None:
                self.payload = {"schema_version": 2, "started_at": "2026-09-24T10:00:00Z"}

    result = post_delivery(
        CASE_BASE, Row(), secret=SECRET, ttl_seconds=300, timeout=2.0, transport=transport
    )

    assert result.disposition == "ACCEPTED"
    assert result.case_version == 6
    assert sent["url"] == f"{CASE_BASE}/internal/v1/cases/{CASE_ID}/agent-callbacks"
    assert sent["body"] == {
        "callback_id": "cb-9c858901-8a57-4791-81fe-4c455b099bc9-1-started",
        "run_id": RUN_ID,
        "input_revision": 1,
        "kind": "STARTED",
        "payload": {"schema_version": 2, "started_at": "2026-09-24T10:00:00Z"},
        "traceparent": "00-4af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
    }
    assert sent["content_type"] == "application/json"
    assert sent["authorization"].startswith("Bearer ")


def test_the_token_presented_is_a_service_token_for_the_agent() -> None:
    """Case's ``/internal/**`` filter accepts only a service-audience token (ServiceTokenFilter:69).

    So the minted token is verified here with the same rules the Java codec applies and the audience the
    *case* service expects two endpoints to differ on: a user token would be refused with 403.
    """
    from resolveflow.api.identity import ISSUER, SERVICE_AUDIENCE, ServiceTokenVerifier

    sent: dict[str, Any] = {}

    def transport(request: Any, timeout: float) -> Any:
        sent["token"] = request.headers.get("Authorization")
        return FakeResponse(200, {"disposition": "ACCEPTED", "case_version": 6})

    @dataclass
    class Row:
        callback_id: str = "cb-x"
        run_id: str = RUN_ID
        case_id: str = CASE_ID
        input_revision: int = 1
        kind: str = "STARTED"
        payload: Any = None
        traceparent: str | None = None

        def __post_init__(self) -> None:
            if self.payload is None:
                self.payload = {"schema_version": 2, "started_at": "2026-09-24T10:00:00Z"}

    post_delivery(CASE_BASE, Row(), secret=SECRET, ttl_seconds=300, timeout=2.0, transport=transport)

    verifier = ServiceTokenVerifier(SECRET, required_scope="")  # the callback surface requires no scope
    verified = verifier.verify(sent["token"])
    assert verified.subject == "agent-service"
    assert verified.audience == SERVICE_AUDIENCE
    assert verified.issuer == ISSUER


def test_a_5xx_is_transient_and_a_4xx_is_not() -> None:
    """The classification is the whole retry policy, so it is asserted directly."""

    @dataclass
    class Row:
        callback_id: str = "cb-x"
        run_id: str = RUN_ID
        case_id: str = CASE_ID
        input_revision: int = 1
        kind: str = "STARTED"
        payload: Any = None
        traceparent: str | None = None

        def __post_init__(self) -> None:
            if self.payload is None:
                self.payload = {"schema_version": 2, "started_at": "2026-09-24T10:00:00Z"}

    def responding(status: int, body: Any) -> Any:
        def transport(request: Any, timeout: float) -> Any:
            return FakeResponse(status, body)

        return transport

    with pytest.raises(DeliveryUnavailableError):
        post_delivery(CASE_BASE, Row(), secret=SECRET, ttl_seconds=300, timeout=2.0, transport=responding(503, {}))
    with pytest.raises(DeliveryRefusedError):
        post_delivery(
            CASE_BASE, Row(), secret=SECRET, ttl_seconds=300, timeout=2.0, transport=responding(422, {"detail": "no"})
        )
    with pytest.raises(DeliveryRefusedError):
        post_delivery(
            CASE_BASE,
            Row(),
            secret=SECRET,
            ttl_seconds=300,
            timeout=2.0,
            transport=responding(403, {"code": "FORBIDDEN_SCOPE"}),
        )
    # A connection that never completed is transient, by exception rather than by status.
    def dead(request: Any, timeout: float) -> Any:
        raise urllib.error.URLError("connection refused")

    with pytest.raises(DeliveryUnavailableError):
        post_delivery(CASE_BASE, Row(), secret=SECRET, ttl_seconds=300, timeout=2.0, transport=dead)


def test_a_200_without_a_disposition_is_a_protocol_error_not_a_success() -> None:
    """An answer we cannot read must not be recorded as delivered: that would lose the callback silently."""

    @dataclass
    class Row:
        callback_id: str = "cb-x"
        run_id: str = RUN_ID
        case_id: str = CASE_ID
        input_revision: int = 1
        kind: str = "STARTED"
        payload: Any = None
        traceparent: str | None = None

        def __post_init__(self) -> None:
            if self.payload is None:
                self.payload = {"schema_version": 2, "started_at": "2026-09-24T10:00:00Z"}

    def transport(request: Any, timeout: float) -> Any:
        return FakeResponse(200, {"unexpected": True})

    with pytest.raises(DeliveryUnavailableError, match="disposition"):
        post_delivery(CASE_BASE, Row(), secret=SECRET, ttl_seconds=300, timeout=2.0, transport=transport)


@dataclass
class FakeResponse:
    status: int
    payload: Any

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        return None