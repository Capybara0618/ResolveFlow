"""Exercise the diagnostic's actual API/journal wiring with a script before any live transmission."""

import json

from resolveflow.harness.model import MockModelClient
from scripts import customer_rag_live_v2 as runner

from tests.conftest import StubEmbedder


def test_runner_api_journal_and_usage_wiring_without_a_paid_call(postgres_dsn, tmp_path, monkeypatch):
    plan = runner.load_plan()
    plan["cases"] = plan["cases"][:1]
    monkeypatch.setattr(runner, "load_plan", lambda: plan)
    monkeypatch.setattr(runner, "DSN", postgres_dsn)
    monkeypatch.setenv("RESOLVEFLOW_MODEL_API_KEY", "test-only-not-a-key")
    monkeypatch.setattr("resolveflow.support.embeddings.embedder", lambda local_path: StubEmbedder())

    class Scripted(MockModelClient):
        def prepare_request(self, **kwargs):
            return {"model": "scripted", "max_tokens": kwargs["max_output_tokens"], "messages": []}

    original = runner.SupportRuntime._model

    def factory(self):
        if self.model_factory:
            return original(self)
        return Scripted(
            script=[
                {"kind": "READ_TOOL", "tool_name": "get_support_guide", "arguments": {}},
                {"kind": "ANSWER", "text": "请商家核查无需先申请退款，预览摘要后由你确认。", "citations": ["O1"]},
            ]
        )

    monkeypatch.setattr(runner.SupportRuntime, "_model", factory)
    output, usage = tmp_path / "report.json", tmp_path / "usage.json"
    runner.evaluate(output, usage)
    report = json.loads(output.read_text(encoding="utf-8"))
    row = report["rows"][0]
    assert report["state"] == "FINISHED" and report["isolated_schema_dropped"]
    assert row["http_status"] == 200 and row["result"]["status"] == "SUCCEEDED"
    assert row["result"]["mode"] == "mock" and len(row["models"]) == 2
    assert row["run"]["result_json"] == row["result"]
    assert report["usage_after"] == 2 and json.loads(usage.read_text())["used"] == 2
    assert report["preservation"]["equal"]
    assert all(record["state"] == "COMPLETE" for record in row["models"])
