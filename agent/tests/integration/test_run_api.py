"""C06.1: the run control plane over HTTP, against a real PostgreSQL.

This is where the slice's headline claim is checked: **202 means the row is committed**. A dispatch that
answered 202 is looked up in ``agent_db`` through a second connection, and a dispatch that could not be
written answers something that is not 202.

The tests go through the real service app (FastAPI's ``TestClient`` runs the lifespan, so the migrations run
and the token verifier is the app's own) and the real database in a schema of this test's own.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from resolveflow.api.app import create_app
from resolveflow.api.identity import RUN_DISPATCH_SCOPE, mint_service_token
from resolveflow.runtime.db import Database
from resolveflow.runtime.runs import RunStore

SECRET = "resolveflow-core-demo-identity-secret"

RUN_ID = "11111111-2222-4333-8444-555555555555"
CASE_ID = "9c858901-8a57-4791-81fe-4c455b099bc9"
ORDER_ID = "00000000-0000-4000-8000-0000000000aa"
MANIFEST_HASH = "9" * 64


@pytest.fixture()
def dispatcher_token() -> str:
    """What case-service presents: a service token that names the run context it was minted for."""
    return mint_service_token(
        "case-service",
        SECRET,
        scope=RUN_DISPATCH_SCOPE,
        merchant_id="M-1001",
        customer_id="C-2002",
    )


@pytest.fixture()
def client(agent_db: Database, tmp_path: Any) -> Any:
    """The real app, over the test's own schema, with the provider stub on a throwaway file."""
    app = create_app(
        provider_db=tmp_path / "provider.sqlite3",
        agent_dsn=agent_db.dsn,
        agent_schema=agent_db.schema,
        jwt_secret=SECRET,
        run_store=RunStore(agent_db),
    )
    with TestClient(app) as test_client:
        yield test_client


def a_body(**overrides: Any) -> dict[str, Any]:
    """One well-formed dispatch body, exactly as the contract spells it (openapi-agent.yaml:53)."""
    body: dict[str, Any] = {
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "input_revision": 1,
        "context": {
            "merchant_id": "M-1001",
            "customer_id": "C-2002",
            "order_id": ORDER_ID,
            "line_id": "7001",
        },
        "request": {
            "description": "包裹丢了，希望退款",
            "requested_actions": ["REFUND"],
            "evidence_refs": ["ev-1"],
        },
        "policy_manifest": {
            "bundle_ids": ["policy-logistics-2026.09"],
            "manifest_hash": MANIFEST_HASH,
            "safety_epoch": 1,
        },
        "deadline_at": "2026-09-28T05:00:00Z",
        "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
    }
    body.update(overrides)
    return body


def post_run(client: Any, token: str, body: dict[str, Any]) -> Any:
    return client.post("/internal/v1/runs", json=body, headers={"Authorization": f"Bearer {token}"})


def test_an_accepted_run_is_committed_and_answers_202_with_its_location(
    client: Any, agent_db: Database, dispatcher_token: str
) -> None:
    response = post_run(client, dispatcher_token, a_body())

    assert response.status_code == 202
    assert response.json() == {"run_id": RUN_ID, "status": "QUEUED"}
    assert response.headers["location"] == f"/internal/v1/runs/{RUN_ID}"

    # The claim: the row is there, read through a connection this request did not use.
    with agent_db.connection() as connection:
        row = connection.execute(
            "SELECT case_id, input_revision, status, version FROM agent_run WHERE run_id = %(run_id)s",
            {"run_id": RUN_ID},
        ).fetchone()
    assert row is not None, "a 202 that is not backed by a committed row is the bug this test exists for"
    assert str(row["case_id"]) == CASE_ID
    assert row["input_revision"] == 1
    assert row["status"] == "QUEUED"
    assert row["version"] == 1


def test_a_redelivered_dispatch_is_the_same_run_and_not_a_second_investigation(
    client: Any, agent_db: Database, dispatcher_token: str
) -> None:
    first = post_run(client, dispatcher_token, a_body())
    second = post_run(client, dispatcher_token, a_body())

    assert first.status_code == 202 and second.status_code == 202
    assert first.json() == second.json()
    with agent_db.connection() as connection:
        count = connection.execute("SELECT count(*) AS n FROM agent_run").fetchone()
    assert count is not None and count["n"] == 1


def test_the_same_run_key_with_a_different_body_is_a_409(client: Any, dispatcher_token: str) -> None:
    post_run(client, dispatcher_token, a_body())

    conflict = post_run(
        client,
        dispatcher_token,
        a_body(request={"description": "换个说法", "requested_actions": ["REFUND"]}),
    )

    assert conflict.status_code == 409
    assert "different request body" in conflict.json()["detail"]


def test_a_body_naming_another_merchants_line_is_refused_with_422(client: Any, dispatcher_token: str) -> None:
    """docs/core-contracts.md:60: the body must agree with the service token and the case binding."""
    body = a_body()
    body["context"]["merchant_id"] = "M-9999"

    refused = post_run(client, dispatcher_token, body)

    assert refused.status_code == 422
    assert "M-9999" in refused.json()["detail"]


def test_a_token_that_forgot_its_context_cannot_dispatch(client: Any) -> None:
    """A plain service token has no subjects, so the body has nothing to agree with.

    Accepting it would leave the identity check silently off while the route looked like it worked.
    """
    token = mint_service_token("case-service", SECRET, scope=RUN_DISPATCH_SCOPE)

    refused = post_run(client, token, a_body())

    assert refused.status_code == 422
    assert "merchant_id" in refused.json()["detail"]


def test_another_service_cannot_dispatch_a_run(client: Any) -> None:
    token = mint_service_token(
        "commerce-service",
        SECRET,
        scope=RUN_DISPATCH_SCOPE,
        merchant_id="M-1001",
        customer_id="C-2002",
    )

    refused = post_run(client, token, a_body())

    assert refused.status_code == 403


def test_a_scope_that_is_not_run_dispatch_cannot_dispatch_a_run(client: Any) -> None:
    token = mint_service_token(
        "case-service", SECRET, scope="commerce:read", merchant_id="M-1001", customer_id="C-2002"
    )

    refused = post_run(client, token, a_body())

    assert refused.status_code == 403


def test_a_missing_or_broken_token_is_401(client: Any) -> None:
    assert client.post("/internal/v1/runs", json=a_body()).status_code == 401
    broken = client.post(
        "/internal/v1/runs", json=a_body(), headers={"Authorization": "Bearer not-a-token"}
    )
    assert broken.status_code == 401


def test_a_structurally_invalid_body_is_422(client: Any, dispatcher_token: str) -> None:
    """``input_revision: 0`` is not a revision, and an unknown action is not a core action."""
    body = a_body()
    body["input_revision"] = 0

    assert post_run(client, dispatcher_token, body).status_code == 422

    unknown_action = a_body()
    unknown_action["request"]["requested_actions"] = ["RESHIP"]
    assert post_run(client, dispatcher_token, unknown_action).status_code == 422


def test_reading_a_run_back_is_the_contract_view(client: Any, dispatcher_token: str) -> None:
    post_run(client, dispatcher_token, a_body())

    view = client.get(f"/internal/v1/runs/{RUN_ID}", headers={"Authorization": f"Bearer {dispatcher_token}"})

    assert view.status_code == 200
    assert view.json() == {
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "input_revision": 1,
        "status": "QUEUED",
        "version": 1,
        "callback_ids": [],
        "result_summary": None,
    }


def test_reading_a_run_needs_a_token_too(client: Any, dispatcher_token: str) -> None:
    post_run(client, dispatcher_token, a_body())

    assert client.get(f"/internal/v1/runs/{RUN_ID}").status_code == 401


def test_an_unknown_run_is_404_and_a_malformed_id_is_404_as_well(client: Any, dispatcher_token: str) -> None:
    headers = {"Authorization": f"Bearer {dispatcher_token}"}

    assert client.get(f"/internal/v1/runs/{uuid.uuid4()}", headers=headers).status_code == 404
    assert client.get("/internal/v1/runs/not-a-uuid", headers=headers).status_code == 404


def test_cancelling_a_queued_run_is_recorded_and_idempotent(client: Any, dispatcher_token: str) -> None:
    post_run(client, dispatcher_token, a_body())
    headers = {"Authorization": f"Bearer {dispatcher_token}"}

    first = client.post(f"/internal/v1/runs/{RUN_ID}/cancel", headers=headers)
    second = client.post(f"/internal/v1/runs/{RUN_ID}/cancel", headers=headers)

    assert first.status_code == 200
    assert first.json() == {"run_id": RUN_ID, "status": "CANCELLED", "cancellation_requested": True}
    assert second.json() == {"run_id": RUN_ID, "status": "CANCELLED", "cancellation_requested": False}


def test_cancelling_an_unknown_run_is_404(client: Any, dispatcher_token: str) -> None:
    headers = {"Authorization": f"Bearer {dispatcher_token}"}

    assert client.post(f"/internal/v1/runs/{uuid.uuid4()}/cancel", headers=headers).status_code == 404


def test_health_still_answers_without_a_token(client: Any) -> None:
    """The liveness probe is not part of the run surface and must not need a service token."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "UP"


def test_the_run_routes_answer_503_when_the_database_is_not_there(tmp_path: Any) -> None:
    """An unavailable store is an availability problem, not a decision about a run.

    ``migrate=False`` plus an unreachable DSN is how this is asserted without stopping the compose database.
    """
    app = create_app(
        provider_db=tmp_path / "provider.sqlite3",
        agent_dsn="postgresql://agent:agent@127.0.0.1:1/agent_db",
        jwt_secret=SECRET,
        migrate=False,
    )
    with TestClient(app) as test_client:
        response = test_client.post(
            "/internal/v1/runs",
            json=a_body(),
            headers={"Authorization": f"Bearer {mint_service_token('case-service', SECRET)}"},
        )

    assert response.status_code == 503
