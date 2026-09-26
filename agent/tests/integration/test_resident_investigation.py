from __future__ import annotations

import base64
import json
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resolveflow.api.app import create_app
from resolveflow.runtime.callbacks import CallbackStore
from resolveflow.runtime.db import Database
from resolveflow.runtime.factory import MODE_ENV, DeploymentRefusedError
from resolveflow.runtime.runs import RunStore
from tests.integration import stub_upstream
from tests.integration.test_deployment_factory import CASE_DISPATCHER, a_run, propose_json


def test_disabled_worker_leaves_preexisting_queue_untouched(agent_db: Database, tmp_path: Path) -> None:
    store = RunStore(agent_db)
    store.queue(a_run(), caller=CASE_DISPATCHER)
    app = create_app(provider_db=tmp_path / "provider.db", run_store=store, delivery_loop=False, worker_loop=False)
    with TestClient(app):
        assert app.state.investigation_loop is None
        assert store.read(a_run().run_id).status == "QUEUED"


def test_enabled_worker_requires_explicit_model_mode(
    agent_db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(MODE_ENV, raising=False)
    app = create_app(
        provider_db=tmp_path / "provider.db", run_store=RunStore(agent_db), delivery_loop=False, worker_loop=True
    )
    with pytest.raises(DeploymentRefusedError, match=MODE_ENV), TestClient(app):
        pass


def test_enabled_mock_requires_a_supplied_script(
    agent_db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MODE_ENV, "mock")
    monkeypatch.delenv("RESOLVEFLOW_MOCK_SCRIPT", raising=False)
    app = create_app(
        provider_db=tmp_path / "provider.db", run_store=RunStore(agent_db), delivery_loop=False, worker_loop=True
    )
    with pytest.raises(DeploymentRefusedError, match="script"), TestClient(app):
        pass


@pytest.mark.parametrize(
    "raw", ["{", "[]", "{}", '["not a decision"]', "[{}]", "x" * 65537],
    ids=["invalid-json", "empty", "object", "non-decision", "invalid-action", "oversize"],
)
def test_malformed_mock_script_refuses_startup(
    agent_db: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    script = tmp_path / "invalid-script.json"
    script.write_text(raw, encoding="utf-8")
    monkeypatch.setenv(MODE_ENV, "mock")
    monkeypatch.setenv("RESOLVEFLOW_MOCK_SCRIPT", str(script))
    app = create_app(
        provider_db=tmp_path / "provider.db",
        run_store=RunStore(agent_db),
        delivery_loop=False,
        worker_loop=True,
    )
    with pytest.raises(DeploymentRefusedError, match="mock script"), TestClient(app):
        pass


def test_live_missing_endpoint_refuses_startup(
    agent_db: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(MODE_ENV, "live")
    monkeypatch.delenv("RESOLVEFLOW_MODEL_ENDPOINT", raising=False)
    app = create_app(
        provider_db=tmp_path / "provider.db",
        run_store=RunStore(agent_db),
        delivery_loop=False,
        worker_loop=True,
    )
    with pytest.raises(DeploymentRefusedError, match="endpoint"), TestClient(app):
        pass


def test_startup_consumes_existing_queue_and_uses_fresh_mock_per_run(
    agent_db: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = RunStore(agent_db)
    first = a_run()
    second = a_run(run_id=str(uuid.uuid4()), case_id=str(uuid.uuid4()))
    for request in (first, second):
        store.queue(request, caller=CASE_DISPATCHER)
    script = tmp_path / "model-script.json"
    script.write_text(json.dumps([json.loads(propose_json())]), encoding="utf-8")
    monkeypatch.setenv("RESOLVEFLOW_INVESTIGATION_ENABLED", "1")
    monkeypatch.setenv(MODE_ENV, "mock")
    monkeypatch.setenv("RESOLVEFLOW_MOCK_SCRIPT", str(script))
    monkeypatch.setenv("RESOLVEFLOW_POLICY_INDEX", "0")
    app = create_app(
        provider_db=tmp_path / "provider.db",
        agent_dsn=agent_db.dsn,
        agent_schema=agent_db.schema,
        delivery_loop=False,
        worker_interval_seconds=0.01,
    )
    with TestClient(app):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if all(store.read(request.run_id).status == "CALLBACK_PENDING" for request in (first, second)):
                break
            time.sleep(0.01)
        assert not app.state.investigation_loop.failed
        for request in (first, second):
            assert store.read(request.run_id).status == "CALLBACK_PENDING"
            assert [record.kind for record in CallbackStore(agent_db).list_for_run(request.run_id)] == [
                "STARTED",
                "PROPOSAL",
            ]
    assert not app.state.investigation_loop.running
    assert app.state.run_store.database._pool.closed


def test_resident_worker_uses_a_fresh_deployment_identity_to_fetch_run_credentials(
    agent_db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = RunStore(agent_db)
    store.queue(a_run(line_id="7100"), caller=CASE_DISPATCHER)
    server = stub_upstream.start(tmp_path / "requests.log")
    script = tmp_path / "read-script.json"
    script.write_text(json.dumps([
        {"kind": "READ_TOOL", "tool_name": "get_shipment_trace", "arguments": {}},
        json.loads(propose_json()),
    ]), encoding="utf-8")
    monkeypatch.setenv(MODE_ENV, "mock")
    monkeypatch.setenv("RESOLVEFLOW_MOCK_SCRIPT", str(script))
    monkeypatch.setenv("RESOLVEFLOW_CASE_BASE_URL", server.url)
    monkeypatch.setenv("RESOLVEFLOW_COMMERCE_BASE_URL", server.url)
    try:
        app = create_app(
            provider_db=tmp_path / "provider.db", run_store=store, delivery_loop=False,
            worker_loop=True, worker_interval_seconds=0.01,
        )
        with TestClient(app):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and store.read(a_run().run_id).status != "CALLBACK_PENDING":
                time.sleep(0.01)
            assert store.read(a_run().run_id).status == "CALLBACK_PENDING"
            assert not app.state.investigation_loop.failed
    finally:
        server.stop()
    requests = [json.loads(line) for line in (tmp_path / "requests.log").read_text(encoding="utf-8").splitlines()]
    assert len(requests) == 2
    assert requests[0]["path"].endswith(f"/internal/v1/runs/{a_run().run_id}/tool-credential")
    identity = requests[0]["authorization"].removeprefix("Bearer ")
    encoded = identity.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    assert claims["sub"] == "agent-service" and "scope" not in claims
    assert requests[1]["authorization"] == f"Bearer token-for-{a_run().run_id}"
