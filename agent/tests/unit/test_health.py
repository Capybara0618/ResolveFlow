"""T01 acceptance: the Agent process starts and reports health.

Mirrors the Java services' health check, so one smoke suite can verify every
process in the system the same way.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from resolveflow.api.app import SERVICE_NAME, create_app


def test_health_reports_up() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UP"
    assert body["service"] == SERVICE_NAME
    assert body["version"]


def test_unknown_route_is_404_not_a_health_lie() -> None:
    client = TestClient(create_app())

    assert client.get("/does-not-exist").status_code == 404


def test_health_does_not_expose_internals() -> None:
    """Health must not leak configuration or credentials."""
    client = TestClient(create_app())

    body = client.get("/health").json()

    assert set(body) == {"status", "service", "version"}


def test_interactive_docs_are_not_published() -> None:
    """The Agent exposes no browseable surface (docs/architecture.md)."""
    client = TestClient(create_app())

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_openapi_schema_is_available_for_contract_generation() -> None:
    """openapi.json stays reachable on purpose.

    T02 generates contracts/openapi-agent.yaml from it, and the service is only
    ever reachable on the internal network, so hiding the schema buys nothing.
    """
    client = TestClient(create_app())

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]