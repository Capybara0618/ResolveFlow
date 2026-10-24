"""The evaluation recorder remains a streaming client through the real SDK and temporary PG."""

import json

import httpx
from scripts.customer_current_eval import RecordedStreamingModel, stream_times

from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.progress import ProgressReporter
from resolveflow.support.service import SupportRuntime
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_orchestrated_engine import Sources, respond
from tests.unit.test_support_orchestration import plan


def test_recorder_streams_with_normal_manifest_and_cached_recovery(agent_db, monkeypatch):
    req = request()
    script = [plan(req).model_dump(), read("get_order_context"), respond()]
    requests, saved, events = [], [], []
    ledger = {"used": 0, "save": lambda: None}

    class Stream(httpx.SyncByteStream):
        def __init__(self, value):
            self.text = json.dumps(value, ensure_ascii=False)

        def __iter__(self):
            for offset in range(0, len(self.text), 11):
                packet = {"choices": [{"index": 0, "delta": {"content": self.text[offset:offset + 11]}}]}
                yield ("data: " + json.dumps(packet) + "\n\n").encode()
            yield ("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50}}) + "\n\ndata: [DONE]\n\n").encode()

    def provider(call):
        requests.append(json.loads(call.content))
        return httpx.Response(200, stream=Stream(script[len(requests) - 1]))

    def progress(*args):
        def receive(call):
            events.extend({**e, "elapsed_ms": len(events)} for e in json.loads(call.content)["events"])
            return httpx.Response(200)
        return ProgressReporter(*args, transport=httpx.MockTransport(receive))

    monkeypatch.setattr("resolveflow.support.service.ProgressReporter", progress)
    model = RecordedStreamingModel(usage=ledger, save=lambda rows: saved.append(len(rows)),
        endpoint="https://synthetic.invalid/completions", model_id="deepseek-flash", provider="deepseek",
        stream_transport=httpx.MockTransport(provider))
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode="live", provider="deepseek", model_id="deepseek-flash"),
        architecture="orchestrated-v1", model_factory=lambda: model, sources_factory=lambda *_: Sources())
    result = runtime.run(req, "local-read", progress_token="local-progress")
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert ledger["used"] == len(model.records) == len(requests) == result["spend"]["model_calls"] == 3
    assert all(r["body"]["stream"] and r["state"] == "COMPLETE" and r["stream"] for r in model.records)
    assert stream_times(events, True)["first_retained_ms"] is not None
    assert runtime.run(req, "again", progress_token="again") == result
    assert ledger["used"] == 3
    with agent_db.connection() as connection:
        row = connection.execute(
            "SELECT manifest_json FROM support_agent_run WHERE run_id=%s", (req.run_id,)
        ).fetchone()
        assert row["manifest_json"]["architecture"] == "orchestrated-v1"
        assert row["manifest_json"]["streaming"] is True
