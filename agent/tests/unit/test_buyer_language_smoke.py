import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from resolveflow.support.protocol import SupportFailure

PATH = Path(__file__).resolve().parents[2] / "checks/buyer_language_smoke.py"
SPEC = importlib.util.spec_from_file_location("buyer_language_smoke", PATH)
assert SPEC and SPEC.loader
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def test_allowance_counts_before_send_stops_at_cap_and_preserves_existing_ledger(tmp_path):
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"used": 11, "reserved_usd": 0.5, "old": {"retained": True}}))
    allowance = smoke.Allowance(ledger, limit=2)
    allowance.consume()
    allowance.consume()
    with pytest.raises(SupportFailure, match="SMOKE_REQUEST_LIMIT"):
        allowance.consume()
    assert json.loads(ledger.read_text()) == {"used": 13, "reserved_usd": 0.5, "old": {"retained": True}}
    with pytest.raises(ValueError):
        smoke.Allowance(ledger, limit=31)


def test_existing_report_refuses_before_any_key_or_provider_use(tmp_path, monkeypatch):
    output = tmp_path / "result.json"
    output.write_text("original")
    monkeypatch.delenv("RESOLVEFLOW_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("Deepseek_API_KEY", raising=False)
    with pytest.raises(FileExistsError):
        smoke.execute(output)
    assert output.read_text() == "original"


def test_failed_network_attempt_is_charged_once_and_never_records_headers(tmp_path):
    ledger = tmp_path / "ledger.json"
    row = {"models": []}
    model = smoke.RecordedModel(smoke.Allowance(ledger, limit=1), row, lambda: None,
        endpoint="https://synthetic.invalid/chat/completions", model_id="deepseek-flash",
        stream_transport=httpx.MockTransport(lambda request: httpx.Response(503, text="unavailable")))
    response = model._send(b'{"messages":[]}', {"Authorization": "Bearer never-store-this"})
    assert response.status == 503 and len(row["models"]) == 1
    assert json.loads(ledger.read_text())["used"] == 1
    assert "never-store-this" not in json.dumps(row) and row["models"][0]["response_text"] == "unavailable"
    with pytest.raises(SupportFailure):
        model._send(b'{"messages":[]}', {})
    assert len(row["models"]) == 1


def test_synthetic_failure_and_correction_preserve_real_previous_answer_not_a_template():
    case = smoke.CASES[-1]
    history = []
    first = smoke.request_for(case, 0, history, None)
    row = {"tools": []}
    source = smoke.SyntheticSources(case, first, row)
    assert source.read("get_shipment_trace", {}) == {"error": "SOURCE_UNAVAILABLE", "retryable": False}
    history.append({"message_id": "a", "sequence": 2, "author": "ASSISTANT", "recipient": "CUSTOMER",
                    "text": "实际保存的上一轮答复"})
    second = smoke.request_for(case, 1, history, None)
    assert second.conversation_id == first.conversation_id and second.run_id != first.run_id
    assert second.input_version == 3
    assert second.context["history"][1]["text"] == "实际保存的上一轮答复"
    assert "包裹刚找到了" in second.context["current_request"]
    assert len(smoke.CASES) == 5 and sum(len(c["turns"]) for c in smoke.CASES) == 6


def test_new_acceptance_inputs_do_not_replace_the_original_failed_cohort():
    assert len(smoke.CASES_V2) == 5 and sum(len(c["turns"]) for c in smoke.CASES_V2) == 6
    assert {c["id"] for c in smoke.CASES}.isdisjoint(c["id"] for c in smoke.CASES_V2)
    assert {t for c in smoke.CASES for t in c["turns"]}.isdisjoint(
        t for c in smoke.CASES_V2 for t in c["turns"])


def test_followup_shares_the_original_absolute_ceiling_instead_of_resetting_allowance(tmp_path):
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"used": 28}))
    allowance = smoke.Allowance(ledger, batch_start=0)
    allowance.consume()
    allowance.consume()
    with pytest.raises(SupportFailure, match="SMOKE_REQUEST_LIMIT"):
        allowance.consume()
    assert json.loads(ledger.read_text())["used"] == 30
    for invalid_start in [31, -1, 0.5]:
        with pytest.raises(ValueError):
            smoke.Allowance(ledger, batch_start=invalid_start)


def test_new_twenty_request_authorization_does_not_inherit_the_old_thirty_request_ceiling(tmp_path):
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"used": 3618, "previous_batch_unchanged": 3599}))
    allowance = smoke.Allowance(ledger, limit=20, batch_start=3599)
    allowance.consume()
    with pytest.raises(SupportFailure, match="SMOKE_REQUEST_LIMIT"):
        allowance.consume()
    assert json.loads(ledger.read_text()) == {"used": 3619, "previous_batch_unchanged": 3599}


def test_recorded_failed_logistics_answer_can_use_observed_order_without_claiming_logistics_success():
    from resolveflow.harness.model import MockModelClient
    from resolveflow.support.engine import SupportAgent
    from resolveflow.support.protocol import SupportInput

    class Script(MockModelClient):
        provider = "deepseek"
        model_id = "deepseek-flash"

    path = PATH.parents[1] / "tests/fixtures/regressions/buyer-language-smoke-v1/failure-partial-facts.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    request = SupportInput.model_validate({**saved["input"],
        "deadline_at": datetime.now(UTC) + timedelta(seconds=120)})
    model = Script(script=saved["decisions"], mode="live")
    result = SupportAgent(request, model, smoke.SyntheticSources(smoke.CASES[-1], request, {"tools": []}),
        architecture="orchestrated-v1", provider_capacity=32768).run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert "329.00元" in result["answer"]["text"]
    task = result["answer"]["task_state"]["tasks"][0]
    assert task["status"] == "UNAVAILABLE" and task["blocker"]["tool_name"] == "get_shipment_trace"
    assert "refund_summary" not in result["answer"] and not result["answer"]["handoff_summary"]
    assert model.calls == 3  # Saved third response is now valid, no fourth correction or new provider request.
