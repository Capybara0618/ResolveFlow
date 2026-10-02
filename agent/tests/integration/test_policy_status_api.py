"""Merchant metadata is scoped and reads the exact persisted hash without indexing."""

import pytest
from fastapi.testclient import TestClient

from resolveflow.api.app import create_app
from resolveflow.api.identity import mint_service_token
from resolveflow.policies.index import PolicyIndex, ServedBundle
from resolveflow.runtime.runs import RunStore

SECRET = "resolveflow-core-demo-identity-secret"


@pytest.fixture
def client(agent_db, tmp_path):
    with TestClient(
        create_app(
            provider_db=tmp_path / "provider.sqlite3",
            run_store=RunStore(agent_db),
            jwt_secret=SECRET,
            worker_loop=False,
            delivery_loop=False,
        )
    ) as client:
        yield client


def headers(merchant="M-status", subject="case-service", scope="policy:read"):
    return {"Authorization": "Bearer " + mint_service_token(subject, SECRET, merchant_id=merchant, scope=scope)}


def test_exact_generation_missing_and_cross_merchant(client, agent_db):
    index = PolicyIndex(agent_db)
    bundle = ServedBundle(
        "status-policy", "M-status", "v1", "a" * 64, 1, [{"rule_id": "R1", "title": "原文", "text": "退款条件"}]
    )
    index.build(bundle)
    path = "/internal/v1/policies/status-policy/index-status"
    response = client.get(path, params={"manifest_hash": "a" * 64}, headers=headers())
    assert response.status_code == 200
    assert response.json()["status"] == "READY"
    assert response.json()["chunk_count"] > 0
    for merchant, hash_value in [("M-other", "a" * 64), ("M-status", "b" * 64)]:
        body = client.get(path, params={"manifest_hash": hash_value}, headers=headers(merchant)).json()
        assert body["status"] == "MISSING" and body["generation_id"] is None
    assert len(index.generations()) == 1
    generation = index.generations()[0]
    index.fail(bundle.bundle_id, generation.generation_id, "synthetic failure")
    assert client.get(path, params={"manifest_hash": "a" * 64}, headers=headers()).json()["status"] == "FAILED"
    with agent_db.connection() as connection:
        connection.execute(
            "UPDATE policy_index_generation SET status='BUILDING' WHERE generation_id=%s", (generation.generation_id,)
        )
    assert client.get(path, params={"manifest_hash": "a" * 64}, headers=headers()).json()["status"] == "BUILDING"


def test_requires_scoped_service_identity(client):
    path = "/internal/v1/policies/status-policy/index-status?manifest_hash=" + "a" * 64
    assert client.get(path).status_code == 401
    for bad in [
        headers(scope="run:review"),
        headers(scope=None),
        headers(subject="commerce-service"),
        headers(merchant=None),
    ]:
        assert client.get(path, headers=bad).status_code == 403
    assert (
        client.get(
            "/internal/v1/policies/status-policy/index-status?manifest_hash=wrong", headers=headers()
        ).status_code
        == 422
    )
