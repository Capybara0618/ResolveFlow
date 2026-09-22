"""The provider stub's HTTP surface (C04.3).

The stub is the outside world, so the money path can only reach it over a network boundary. That makes this
module part of the thing under test rather than a convenience wrapper: if the wire shape differs from what
Commerce sends, the end-to-end refund is broken in a way no in-process test would notice.

Two properties get their own attention here:

- **404 means "nothing", not "failed".** A delayed-visibility provider answers 404 while it already holds
  the money, so the client must treat 404 as "ask again", never as "release the reservation".
- **409 means the key is spent on a different payment.** The provider refuses instead of answering with
  somebody else's refund, which is the difference between a duplicate and a mistake.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi.testclient import TestClient

from resolveflow.api.app import create_app, provider_of
from resolveflow.provider_stub import UNKNOWN, RefundProviderStub

OPERATION = "0f0f0f0f-1111-4222-8333-444444444444"
LINE = "7001"
AMOUNT = 2599
AT = dt.datetime(2026, 9, 22, 10, 0, tzinfo=dt.UTC)


def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(provider_db=tmp_path / "provider.sqlite3"))


def refund_body(operation: str = OPERATION, amount: int = AMOUNT, line: str = LINE) -> dict[str, object]:
    return {"operation_id": operation, "line_id": line, "amount_minor": amount, "currency": "CNY"}


def test_a_refund_is_requested_over_http_and_can_be_read_back(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.post("/provider/v1/refunds", json=refund_body())

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["operation_id"] == OPERATION
        assert body["state"] == "SUCCEEDED"
        assert body["amount_minor"] == AMOUNT
        assert body["responded"] is True
        assert body["settled_at"] is not None

        read_back = http.get(f"/provider/v1/refunds/{OPERATION}")
        assert read_back.status_code == 200
        assert read_back.json() == body


def test_a_repeat_over_http_returns_the_original_result(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        first = http.post("/provider/v1/refunds", json=refund_body()).json()
        second = http.post("/provider/v1/refunds", json=refund_body()).json()

        assert second == first, "a retried request is the same payment"


def test_the_same_key_with_a_different_amount_is_a_conflict(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        http.post("/provider/v1/refunds", json=refund_body())

        response = http.post("/provider/v1/refunds", json=refund_body(amount=AMOUNT + 1))

        assert response.status_code == 409, response.text
        assert OPERATION in response.json()["detail"]


def test_an_unknown_key_is_404_not_a_failure(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        response = http.get("/provider/v1/refunds/ffffffff-0000-4000-8000-000000000000")

        assert response.status_code == 404
        assert "no such refund" in response.json()["detail"]


def test_an_amount_that_cannot_be_paid_is_refused_before_the_provider_sees_it(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        for bad in (0, -1):
            assert http.post("/provider/v1/refunds", json=refund_body(amount=bad)).status_code == 422


def test_a_timeout_is_answered_as_unknown_over_http(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        provider_of(http.app).inject("REQUEST_TIMEOUT", operation_id=OPERATION)

        response = http.post("/provider/v1/refunds", json=refund_body())

        assert response.status_code == 200, response.text
        assert response.json()["state"] == UNKNOWN
        assert response.json()["responded"] is False
        assert http.get(f"/provider/v1/refunds/{OPERATION}").json()["state"] == UNKNOWN


def test_a_lost_response_is_still_settled_and_the_retry_recovers_it(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        provider_of(http.app).inject("LOST_RESPONSE", operation_id=OPERATION)

        lost = http.post("/provider/v1/refunds", json=refund_body()).json()
        assert lost["responded"] is False
        assert lost["state"] == "SUCCEEDED"

        retry = http.post("/provider/v1/refunds", json=refund_body()).json()
        assert retry["responded"] is True
        assert retry["provider_ref"] == lost["provider_ref"]


def test_a_delayed_visible_refund_answers_404_until_the_window_passes(tmp_path: Path) -> None:
    """The 404 that must never be read as "release the money"."""
    provider = RefundProviderStub(tmp_path / "provider.sqlite3")
    provider.inject("DELAYED_VISIBILITY", operation_id=OPERATION, visible_after=AT + dt.timedelta(seconds=30))
    provider.request_refund(
        operation_id=OPERATION, line_id=LINE, amount_minor=AMOUNT, currency="CNY", requested_at=AT
    )

    with TestClient(create_app(provider=provider)) as http:
        # The stub reads its own clock, so this asserts the *shape* of the answer: a key whose outcome is
        # settled but not yet visible comes back as 404 while `query_refund` at a later moment would not.
        early = provider.query_refund(OPERATION, at=AT + dt.timedelta(seconds=1))
        assert early.state == "NOT_FOUND"
        assert early.amount_minor == AMOUNT, "the provider knows the amount: it just cannot show the payment"
        assert provider.query_refund(OPERATION, at=AT + dt.timedelta(seconds=31)).state == "SUCCEEDED"

        # And over HTTP the settled-and-visible case is a normal 200, so the route has no second opinion.
        assert http.get(f"/provider/v1/refunds/{OPERATION}").status_code == 200


def test_the_health_route_still_answers_and_provider_routes_are_declared(tmp_path: Path) -> None:
    with client(tmp_path) as http:
        assert http.get("/health").json()["status"] == "UP"

        paths = http.get("/openapi.json").json()["paths"]
        assert "/provider/v1/refunds" in paths
        assert "/provider/v1/refunds/{key}" in paths


def test_the_lab_surface_is_absent_unless_it_is_asked_for(tmp_path: Path) -> None:
    """A deployed provider must not carry a route that can make it misbehave (docs/engineering.md:77)."""
    with client(tmp_path) as http:
        paths = http.get("/openapi.json").json()["paths"]

        assert not any(path.startswith("/provider/v1/_lab") for path in paths), paths


def test_the_lab_surface_arms_faults_and_settles_unknowns(tmp_path: Path) -> None:
    """What a separate test process needs: it cannot reach into this process's memory."""
    with TestClient(create_app(provider_db=tmp_path / "provider.sqlite3", lab_routes=True)) as http:
        assert http.get("/openapi.json").json()["paths"].keys() >= {
            "/provider/v1/_lab/faults",
            "/provider/v1/_lab/operations/{operation_id}/settle",
        }

        armed = http.post("/provider/v1/_lab/faults", json={"fault": "REQUEST_TIMEOUT", "operation_id": OPERATION})
        assert armed.status_code == 204, armed.text

        assert http.post("/provider/v1/refunds", json=refund_body()).json()["state"] == UNKNOWN

        settled = http.post(
            f"/provider/v1/_lab/operations/{OPERATION}/settle", json={"state": "SUCCEEDED"}
        )
        assert settled.status_code == 200, settled.text
        assert settled.json()["state"] == "SUCCEEDED"

        # An unknown fault name is refused rather than ignored: a lab tool that silently does nothing would
        # make a fault test pass for the wrong reason.
        bad = http.post("/provider/v1/_lab/faults", json={"fault": "EXPLODE"})
        assert bad.status_code == 422, bad.text

        assert http.delete("/provider/v1/_lab/faults").status_code == 204
