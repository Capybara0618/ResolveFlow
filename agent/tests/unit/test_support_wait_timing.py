"""Cold counting belongs before readiness; timing must not change run semantics or log content."""

import logging
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resolveflow.api.app import create_app
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_orchestrated_engine import respond, run
from tests.unit.test_support_orchestration import plan


@pytest.mark.parametrize("policy", ["0", "1"])
def test_live_flash_counter_prewarms_before_ready_independently_of_policy_index(monkeypatch, tmp_path, policy):
    calls = []
    monkeypatch.setenv("RESOLVEFLOW_MODEL_MODE", "live")
    monkeypatch.setenv("RESOLVEFLOW_MODEL_PROVIDER", "deepseek")
    monkeypatch.setenv("RESOLVEFLOW_MODEL_ID", "deepseek-flash")
    monkeypatch.setenv("RESOLVEFLOW_POLICY_INDEX", policy)
    monkeypatch.setenv("RESOLVEFLOW_SUPPORT_PREWARM", "1")
    monkeypatch.setattr("resolveflow.api.app.prewarm_counter", lambda **kwargs: calls.append(kwargs) or 10.0)
    monkeypatch.setattr("resolveflow.support.embeddings.SupportEmbeddings.prewarm", lambda *args: 0)
    app = create_app(provider_db=tmp_path / "provider.db", delivery_loop=False, worker_loop=False, migrate=False)
    with TestClient(app):
        assert calls == [{"provider": "deepseek", "model_id": "deepseek-flash"}]
        assert app.state.support_counter_warmup == {"status": "READY", "elapsed_ms": 10.0}


@pytest.mark.parametrize("mode,prewarm", [("mock", "1"), ("live", "0")])
def test_nonlive_or_disabled_counting_stays_lazy(monkeypatch, tmp_path, mode, prewarm):
    monkeypatch.setenv("RESOLVEFLOW_MODEL_MODE", mode)
    monkeypatch.setenv("RESOLVEFLOW_SUPPORT_PREWARM", prewarm)
    monkeypatch.setenv("RESOLVEFLOW_POLICY_INDEX", "0")
    monkeypatch.setattr("resolveflow.api.app.prewarm_counter", lambda **kwargs: pytest.fail("must stay lazy"))
    app = create_app(provider_db=tmp_path / "provider.db", delivery_loop=False, worker_loop=False, migrate=False)
    with TestClient(app):
        assert app.state.support_counter_warmup == {"status": "DISABLED"}


def test_corrupt_counter_asset_refuses_ready_without_starting_workers(monkeypatch, tmp_path):
    monkeypatch.setenv("RESOLVEFLOW_MODEL_MODE", "live")
    monkeypatch.setenv("RESOLVEFLOW_SUPPORT_PREWARM", "1")
    monkeypatch.setenv("RESOLVEFLOW_POLICY_INDEX", "0")

    def broken(**kwargs):
        raise ValueError("tokenizer integrity check failed")

    monkeypatch.setattr("resolveflow.api.app.prewarm_counter", broken)
    app = create_app(provider_db=tmp_path / "provider.db", delivery_loop=False, worker_loop=False, migrate=False)
    with pytest.raises(ValueError, match="integrity"), TestClient(app):
        pytest.fail("must not publish READY")
    assert app.state.support_counter_warmup["status"] == "FAILED"
    assert app.state.investigation_loop is None


def test_phase_and_tool_timings_have_no_customer_text_or_credentials(caplog):
    caplog.set_level(logging.INFO, logger="resolveflow.support.engine")
    result, _, model, _ = run([plan(request()).model_dump(), read("get_order_context"), respond()])
    assert result["status"] == "SUCCEEDED" and model.calls == 4
    messages = [r.message for r in caplog.records if r.name == "resolveflow.support.engine"]
    phases = [m for m in messages if "support_model_timing" in m]
    assert len(phases) == 4
    assert all("prepare_ms=" in m and "provider_ms=" in m and "current_ms=" in m for m in phases)
    expected = ["UNDERSTAND", "CHECK_REQUEST", "INVESTIGATE", "COMPOSE"]
    assert all(any("phase=" + p in m for m in phases) for p in expected)
    assert sum("support_tool_timing" in m for m in messages) == 2
    assert not any(request().context["current_request"] in m for m in messages)


def test_model_exception_is_timed_without_logging_exception_message(caplog):
    caplog.set_level(logging.INFO, logger="resolveflow.support.engine")
    result, _, _, _ = run([])
    assert result["status"] == "FAILED"
    phases = [r.message for r in caplog.records if "support_model_timing" in r.message]
    assert len(phases) == 1 and "outcome=ERROR" in phases[0]


@pytest.mark.parametrize("provider,model,expected", [
    ("deepseek", "deepseek-flash", 1), ("openai-compatible", "deepseek-flash", 0),
    ("deepseek", "other", 0),
])
def test_prewarm_uses_only_the_same_exact_profile_as_live_counting(monkeypatch, provider, model, expected):
    from resolveflow.harness.token_counting import prewarm_counter

    calls = []
    monkeypatch.setattr("resolveflow.harness.token_counting.load_tokenizer", lambda: calls.append("load"))
    elapsed = prewarm_counter(provider=provider, model_id=model)
    assert len(calls) == expected
    assert (elapsed is not None) == bool(expected)


def test_real_stream_transport_timing_reports_current_request_first_content_only(caplog):
    from resolveflow.support.engine import SupportAgent
    from tests.unit.test_streaming_request_session import Tracked, model_for
    from tests.unit.test_support_evidence_batch import fast_script
    from tests.unit.test_support_orchestrated_engine import Sources

    caplog.set_level(logging.INFO, logger="resolveflow.support.engine")
    model = model_for(Tracked(fast_script()))
    result = SupportAgent(request(), model, Sources(), architecture="orchestrated-v1").run()
    assert result["status"] == "SUCCEEDED" and model.calls == 4
    messages = [r.message for r in caplog.records if "support_model_timing" in r.message]
    assert len(messages) == 4 and all("first_content_ms=None" not in m for m in messages)
    assert not any("test-only" in m or "Bearer" in m for m in messages)


def test_launcher_log_config_actually_emits_scoped_info_without_enabling_httpx():
    config = Path(__file__).parents[3] / "infra/logging.agent.json"
    result = subprocess.run([sys.executable, "-c", (  # noqa: S603 - fixed local Python and fixed diagnostic code
        "import logging,sys,uvicorn; "
        "uvicorn.Config('resolveflow.api.app:app',log_config=sys.argv[1]); "
        "logging.getLogger('resolveflow.support.engine').info('phase-timing-witness'); "
        "logging.getLogger('resolveflow.api.app').info('warmup-witness'); "
        "logging.getLogger('httpx').info('unrelated-http-trace')"
    ), str(config)], capture_output=True, text=True, timeout=20, check=True)
    assert "phase-timing-witness" in result.stderr and "warmup-witness" in result.stderr
    assert "unrelated-http-trace" not in result.stderr
