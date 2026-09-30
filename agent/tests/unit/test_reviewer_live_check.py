"""The finite acceptance helper must refuse extra calls and redact provider errors."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import reviewer_live_check as live  # noqa: E402
from resolveflow.harness.live_model import HttpResponse, ModelRefusedError


def test_transport_counts_before_sending_caps_timeout_and_refuses_an_extra_attempt(monkeypatch):
    sent = []
    monkeypatch.setattr(live, "_urllib_transport", lambda url, body, headers, timeout:
                        sent.append(timeout) or HttpResponse(200, b'{"usage":{"prompt_tokens":10}}'))
    transport = live.BoundedTransport(limit=1)
    transport("https://api.deepseek.com/chat/completions", b'{}', {}, 90)
    with pytest.raises(ModelRefusedError, match="CALL_LIMIT"):
        transport("https://api.deepseek.com/chat/completions", b'{}', {}, 90)
    assert sent == [30]
    assert transport.calls == 1


def test_provider_error_cannot_put_the_key_in_the_report(monkeypatch):
    monkeypatch.setattr(live, "_urllib_transport", lambda *args: HttpResponse(400, b'{"error":"test-secret"}'))
    transport = live.BoundedTransport()
    transport("https://api.deepseek.com/chat/completions", b'{}', {"Authorization": "Bearer test-secret"}, 20)
    assert "test-secret" not in str(transport.errors)
    with pytest.raises(ModelRefusedError, match="ENDPOINT_REFUSED"):
        transport("https://unrelated.invalid", b'{}', {}, 20)
    assert transport.calls == 1
