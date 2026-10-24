"""A support run owns one HTTP session; responses and the session close on every exit."""

import json

import httpx
import pytest

from resolveflow.harness.live_model import ModelUnavailableError
from resolveflow.harness.streaming_model import StreamingLiveModelClient
from resolveflow.support.engine import SupportAgent
from tests.unit.test_streaming_model import chunk, ending, event
from tests.unit.test_support_agent import request
from tests.unit.test_support_evidence_batch import fast_script
from tests.unit.test_support_orchestrated_engine import Sources


class Tracked(httpx.MockTransport):
    def __init__(self, decisions):
        self.calls = []
        self.close_count = 0
        self.decisions = decisions
        super().__init__(self.respond)

    def respond(self, req):
        assert self.close_count == 0, "transport was closed between decisions"
        self.calls.append(req)
        text = json.dumps(self.decisions[len(self.calls) - 1], ensure_ascii=False)
        return httpx.Response(200, content=event(chunk(text)) + ending())

    def close(self):
        self.close_count += 1
        return super().close()


def model_for(transport):
    return StreamingLiveModelClient(endpoint="https://synthetic.invalid/chat/completions", provider="deepseek",
                                    model_id="deepseek-flash", api_key="test-only", stream_transport=transport)


def test_explicit_session_reuses_transport_and_headers_remain_per_request():
    transport = Tracked([{"kind": "one"}, {"kind": "two"}])
    model = model_for(transport)
    with model.request_session():
        first = model.decide(system="JSON", messages=[], max_output_tokens=80)
        model.api_key = "test-rotated"
        second = model.decide(system="JSON", messages=[], max_output_tokens=80)
        assert transport.close_count == 0
    assert transport.close_count == 1 and model.calls == 2
    assert (first.decision["kind"], second.decision["kind"]) == ("one", "two")
    assert transport.calls[-1].headers["authorization"] == "Bearer test-rotated"


def test_session_closes_when_provider_stream_is_invalid_without_automatic_retry():
    transport = Tracked([])

    def invalid(req):
        transport.calls.append(req)
        return httpx.Response(200, content=b"data: invalid\n\n")

    transport.handler = invalid
    model = model_for(transport)
    with pytest.raises(ModelUnavailableError), model.request_session():
        model.decide(system="JSON", messages=[], max_output_tokens=80)
    assert transport.close_count == 1 and len(transport.calls) == model.calls == 1


def test_nested_session_is_rejected_without_replacing_or_closing_active_connection():
    transport = Tracked([{"kind": "ok"}])
    model = model_for(transport)
    with model.request_session():
        with pytest.raises(ValueError, match="active"):
            with model.request_session():
                pass
        assert transport.close_count == 0
        model.decide(system="JSON", messages=[], max_output_tokens=80)
    assert transport.close_count == 1


def test_actual_sdk_support_run_reuses_session_and_closes_after_final_answer():
    transport = Tracked(fast_script())
    model = model_for(transport)
    result = SupportAgent(request(), model, Sources(), architecture="orchestrated-v1").run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.calls == 3 and transport.close_count == 1
    assert all(req.headers["accept"] == "text/event-stream" for req in transport.calls)


def test_nonstream_model_failure_still_releases_run_session():
    transport = Tracked([{"kind": "invalid"}, {"kind": "invalid"}])
    model = model_for(transport)
    result = SupportAgent(request(), model, Sources(), architecture="orchestrated-v1").run()
    assert result["status"] == "FAILED" and transport.close_count == 1
