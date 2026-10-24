"""New explicit profile through API, real temporary PG, HTTP streaming and fenced journal."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from resolveflow.api.app import create_app
from resolveflow.api.identity import mint_service_token
from resolveflow.harness.streaming_model import StreamingLiveModelClient
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.orchestration_prompts import COMPOSE_SYSTEM, INVESTIGATE_SYSTEM, PLAN_SYSTEM
from resolveflow.support.progress import ProgressReporter
from resolveflow.support.protocol import SupportFailure
from resolveflow.support.service import SupportRuntime
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.integration.test_support_staged_api import SECRET
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_orchestrated_engine import Sources, respond
from tests.unit.test_support_orchestration import plan


def test_explicit_mock_script_validation_accepts_new_profile_without_old_answer_fields(monkeypatch, tmp_path):
    script = [plan(request()).model_dump(), read("get_order_context"), respond()]
    path = tmp_path / "script.json"
    path.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("RESOLVEFLOW_SUPPORT_MOCK_SCRIPT", str(path))
    runtime = SupportRuntime(None, DeploymentConfig(mode="mock"), architecture="orchestrated-v1")
    assert runtime._model().script == script


def test_api_persists_raw_protocol_and_reconstructs_plan_guide_gaps_without_new_calls(
    agent_db, monkeypatch, tmp_path,
):
    req = request()
    script = [plan(req, needs=["SHIPMENT"]).model_dump(), read(), respond(), read("get_order_context"), respond()]
    models, sources = [TokenizedScript(mode="live", script=script)], Sources()
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode="mock"), architecture="orchestrated-v1",
                             model_factory=lambda: models[0], sources_factory=lambda *_: sources)
    monkeypatch.setenv("RESOLVEFLOW_SUPPORT_ARCHITECTURE", "orchestrated-v1")
    app = create_app(provider_db=tmp_path / "provider.db", delivery_loop=False, worker_loop=False,
                     migrate=False, jwt_secret=SECRET, support_runtime=runtime)
    with TestClient(app) as api:
        assert api.get("/health").json()["support_architecture"] == "orchestrated-v1"
        token = mint_service_token("case-service", SECRET, scope="support:run",
                                   merchant_id=req.merchant_id, customer_id=req.customer_id)
        headers = {"Authorization": "Bearer " + token}
        body = {**req.model_dump(mode="json"), "tool_token": "test-bound"}
        response = api.post("/internal/v1/support-runs", json=body, headers=headers)
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "SUCCEEDED", result["reason"]
        with agent_db.connection() as c:
            row = c.execute("SELECT manifest_json FROM support_agent_run WHERE run_id=%s", (req.run_id,)).fetchone()
            manifest = row["manifest_json"]
            assert manifest["architecture"] == "orchestrated-v1"
            assert manifest["prompt_hash"] == hashlib.sha256(
                (PLAN_SYSTEM + INVESTIGATE_SYSTEM + COMPOSE_SYSTEM).encode()).hexdigest()
            root = Path(__file__).parents[2] / "src/resolveflow/support"
            for name in ("orchestration.py", "orchestration_prompts.py"):
                assert manifest["code"][name] == hashlib.sha256((root / name).read_bytes()).hexdigest()
            calls = c.execute("SELECT kind,position,response_json FROM support_agent_call "
                              "WHERE run_id=%s ORDER BY kind,position", (req.run_id,)).fetchall()
            assert [r["response_json"]["decision"] for r in calls if r["kind"] == "model"] == script
            assert len([r for r in calls if r["kind"] == "tool"]) == 3
            c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                      "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
        models[0] = TokenizedScript(mode="live", script=script)
        before = list(sources.calls)
        assert api.post("/internal/v1/support-runs", json=body, headers=headers).json() == result
        assert models[0].calls == 0 and sources.calls == before
        runtime.architecture = "staged-v1"
        assert runtime.run(req, "new-token") == result  # Completed original result remains reusable.
        with agent_db.connection() as c:
            c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                      "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
        with pytest.raises(SupportFailure, match="MANIFEST_MISMATCH"):
            runtime.run(req, "new-token")
        assert models[0].calls == 0 and sources.calls == before


def test_http_stream_projects_only_ready_response_and_recovery_does_not_resend(agent_db, monkeypatch):
    req = request()
    script = [plan(req).model_dump(), respond(parts=[{"task_id": "trace", "text": "未就绪正文不可展示"}]),
              read("get_order_context"), respond()]
    calls, batches = [], []

    class Stream(httpx.SyncByteStream):
        def __init__(self, value):
            self.text = json.dumps(value, ensure_ascii=False)

        def __iter__(self):
            for offset in range(0, len(self.text), 7):
                chunk = {"choices": [{"index": 0, "delta": {"content": self.text[offset:offset + 7]}}]}
                yield ("data: " + json.dumps(chunk) + "\n\n").encode()
            yield ("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50}}) + "\n\ndata: [DONE]\n\n").encode()

    def provider(call):
        calls.append(json.loads(call.content))
        return httpx.Response(200, stream=Stream(script[len(calls) - 1]))

    def progress(*args):
        return ProgressReporter(*args, transport=httpx.MockTransport(
            lambda request: (batches.append(json.loads(request.content)) or httpx.Response(200))))

    monkeypatch.setattr("resolveflow.support.service.ProgressReporter", progress)
    model = StreamingLiveModelClient(endpoint="http://synthetic.invalid", model_id="deepseek-flash",
                                    provider="deepseek", stream_transport=httpx.MockTransport(provider))
    sources = Sources()
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode="live", provider="deepseek", model_id="deepseek-flash"),
                             architecture="orchestrated-v1", model_factory=lambda: model,
                             sources_factory=lambda *_: sources)
    result = runtime.run(req, "test-bound", progress_token="test-progress")
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert len(calls) == result["spend"]["model_calls"] == 4
    assert all(call["stream"] for call in calls)
    events = [event for batch in batches for event in batch["events"]]
    assert [event["attempt_id"] for event in events if event["kind"] == "answer.started"] == ["model-4"]
    streamed = "".join(event["payload"]["text"] for event in events if event["kind"] == "answer.delta")
    assert streamed == "请核对原因后再确认。"
    assert "123.45 CNY" in result["answer"]["text"] and "refund_summary" in result["answer"]
    before = list(sources.calls)
    with agent_db.connection() as c:
        c.execute("UPDATE support_agent_run SET status='RUNNING',result_json=NULL,"
                  "lease_until=now()-interval '1 second' WHERE run_id=%s", (req.run_id,))
    assert runtime.run(req, "new-bound", progress_token="new-progress") == result
    assert len(calls) == 4 and sources.calls == before
