"""Real ASGI support route, AgentScope and isolated PG; scripted model and upstream current-check HTTP."""

import hashlib
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from resolveflow.api.app import create_app
from resolveflow.api.identity import mint_service_token
from resolveflow.harness.model import MockModelClient
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.service import SupportRuntime
from resolveflow.support.sources import BoundSources
from tests.unit.test_support_agent import request

SECRET = "support-test-only-secret-at-least-16"


def test_http_guide_answer_pins_asset_and_duplicate_dispatch_reuses_exact_result(agent_db, tmp_path):
    req = request()
    calls = []

    def current(call):
        calls.append(call.url.path)
        return httpx.Response(200, json={"conversation_id": req.conversation_id, "input_version": req.input_version})

    model = MockModelClient(script=[
        {"kind": "READ_TOOL", "tool_name": "get_support_guide", "arguments": {}},
        {"kind": "ANSWER", "text": "点击请商家核查，确认共享内容即可，无须先申请退款。", "citations": ["O1"]},
    ])
    with httpx.Client(transport=httpx.MockTransport(current)) as upstream:
        runtime = SupportRuntime(
            agent_db, DeploymentConfig(mode="mock"), model_factory=lambda: model,
            sources_factory=lambda bound, token, journal: BoundSources(
                bound, case_url="http://case.local", token=token, journal=journal, client=upstream
            ),
        )
        app = create_app(
            provider_db=tmp_path / "provider.db", delivery_loop=False, worker_loop=False,
            migrate=False, jwt_secret=SECRET, support_runtime=runtime,
        )
        token = mint_service_token(
            "case-service", SECRET, scope="support:run", merchant_id=req.merchant_id, customer_id=req.customer_id
        )
        headers = {"Authorization": "Bearer " + token}
        body = {**req.model_dump(mode="json"), "tool_token": "bound-test-read-token"}
        with TestClient(app) as client:
            result = client.post("/internal/v1/support-runs", json=body, headers=headers)
            assert result.status_code == 200 and result.json()["status"] == "SUCCEEDED"
            first = result.json()
            assert first["answer"]["citations"][0]["source_type"] == "KNOWLEDGE"
            assert first["spend"]["local_reads"] == 1
            assert client.post("/internal/v1/support-runs", json=body, headers=headers).json() == first
    assert model.calls == 2 and calls and all(path.endswith("/current") for path in calls)
    with agent_db.connection() as c:
        manifest = c.execute("SELECT manifest_json FROM support_agent_run").fetchone()["manifest_json"]
    asset = Path(__file__).resolve().parents[2] / "src/resolveflow/assets/support-guide-v1.json"
    assert manifest["support_guide_version"] == "2026.10.21-v1"
    assert manifest["code"]["../assets/support-guide-v1.json"] == hashlib.sha256(asset.read_bytes()).hexdigest()
