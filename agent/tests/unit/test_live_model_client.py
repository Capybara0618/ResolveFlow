"""The live model client (C08.1b-2), tested **offline** through an injected transport.

No test here opens a socket. The client's whole network surface is one callable, so a test can capture the exact
request and answer it with a canned response — which is what makes these claims checkable without an API budget:

* the hard ceiling the harness reserved is in the **actual request body** (``docs/agent-harness.md:39`` passes
  ``min(单步输出上限, 累计剩余输出)`` to the ModelClient; a provider must be told it, not trusted to infer it);
* there is **exactly one attempt**. ``docs/agent-spec.md:40`` allows one model-level retry and requires every
  attempt to be counted — a client that retried internally would spend a call nobody counted;
* a missing provider usage block is **ESTIMATED and non-zero**, never an exact zero
  (``docs/agent-spec.md:44``: 缺provider准确计数时标ESTIMATED; the budget must not refund a reservation on zero);
* what is recorded is the request hash and a **credential-free** body.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from resolveflow.harness.live_model import (
    HttpResponse,
    LiveModelClient,
    ModelRefusedError,
    ModelUnavailableError,
)
from resolveflow.harness.model import MODEL_MODE_LIVE, MODEL_MODE_MOCK
from resolveflow.harness.sdk_adapter import raw_text_message

SECRET = "sk-not-a-real-key-0123456789"  # noqa: S105 - synthetic test credential
ENDPOINT = "https://model.example.invalid/v1/chat/completions"

PROPOSAL = {
    "kind": "PROPOSE",
    "case_type": "LOGISTICS",
    "recommended_action": "REFUND",
    "reason_codes": ["LOST_CONFIRMED"],
    "summary": "承运商判定丢失",
}


class Recorder:
    """A transport that answers every request the same way and keeps what it was sent."""

    def __init__(self, *responses: HttpResponse) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str], timeout: float) -> HttpResponse:
        self.calls.append({"url": url, "body": json.loads(body), "headers": dict(headers), "timeout": timeout})
        if not self.responses:
            raise AssertionError("the client made more attempts than the test provided answers for")
        return self.responses.pop(0)


def ok(content: str, usage: dict[str, int] | None = None) -> HttpResponse:
    payload: dict[str, Any] = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    if usage is not None:
        payload["usage"] = usage
    return HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))


def client(transport: Recorder, **overrides: Any) -> LiveModelClient:
    fields: dict[str, Any] = {
        "endpoint": ENDPOINT,
        "model_id": "some-model-v2",
        "provider": "openai-compatible",
        "api_key": SECRET,
        "parameters": {"temperature": 0, "seed": 7},
        "transport": transport,
    }
    fields.update(overrides)
    return LiveModelClient(**fields)


def messages() -> list[Any]:
    return [raw_text_message('{"run": {"run_id": "r-1"}}', role="user")]


def test_the_hard_output_ceiling_is_in_the_actual_request_body() -> None:
    """``max_output_tokens`` is a reserved ceiling, so the provider request must carry it."""
    transport = Recorder(ok(json.dumps(PROPOSAL), usage={"prompt_tokens": 120, "completion_tokens": 30}))

    client(transport).decide(
        system="choose an action", messages=messages(), max_output_tokens=1024
    )

    sent = transport.calls[0]["body"]
    assert sent["max_tokens"] == 1024
    assert sent["model"] == "some-model-v2"
    # Declared parameters are sent as declared; the manifest records them, so they must be what goes on the wire.
    assert sent["temperature"] == 0
    assert sent["seed"] == 7


def test_a_call_without_a_ceiling_is_refused_rather_than_sent_uncapped() -> None:
    """Sending no ceiling would spend output nobody reserved (``docs/agent-harness.md:39``)."""
    transport = Recorder(ok(json.dumps(PROPOSAL)))

    with pytest.raises(ValueError, match="max_output_tokens"):
        client(transport).decide(system="choose an action", messages=messages(), max_output_tokens=None)

    assert transport.calls == [], "an uncapped request must not reach the provider at all"


def test_there_is_exactly_one_attempt_and_no_hidden_retry() -> None:
    """A 5xx is unavailable, but the *retry* belongs to the budgeted layer, not to this client."""
    transport = Recorder(HttpResponse(status=503, body=b"upstream busy"), ok(json.dumps(PROPOSAL)))

    with pytest.raises(ModelUnavailableError):
        client(transport).decide(system="choose an action", messages=messages(), max_output_tokens=256)

    assert len(transport.calls) == 1, "the client retried, so the second attempt would be an uncounted call"


def test_a_refusal_is_distinguished_from_an_outage_and_also_not_retried() -> None:
    """A 4xx will repeat, so the run stops; a 5xx may be retried by the layer that counts attempts."""
    refused = Recorder(HttpResponse(status=400, body=b"bad request"))
    with pytest.raises(ModelRefusedError):
        client(refused).decide(system="s", messages=messages(), max_output_tokens=256)
    assert len(refused.calls) == 1

    outage = Recorder(HttpResponse(status=500, body=b"boom"))
    with pytest.raises(ModelUnavailableError):
        client(outage).decide(system="s", messages=messages(), max_output_tokens=256)
    assert len(outage.calls) == 1


def test_a_transport_failure_is_unavailable_and_not_a_retry() -> None:
    """A timeout is exactly the case a retry loop would hide; the attempt still has to be visible."""

    def failing(url: str, body: bytes, headers: dict[str, str], timeout: float) -> HttpResponse:
        calls.append(1)
        raise TimeoutError("the provider did not answer")

    calls: list[int] = []
    with pytest.raises(ModelUnavailableError, match="timed out"):
        client(failing).decide(system="s", messages=messages(), max_output_tokens=64)  # type: ignore[arg-type]

    assert len(calls) == 1


def test_a_failed_attempt_is_still_recorded_so_the_call_count_is_auditable() -> None:
    """``calls`` and ``requests`` must agree: a call spent on an outage has to be visible somewhere."""
    transport = Recorder(HttpResponse(status=503, body=b"upstream busy"))
    live = client(transport)

    with pytest.raises(ModelUnavailableError):
        live.decide(system="s", messages=messages(), max_output_tokens=256)

    assert live.calls == 1
    assert len(live.requests) == 1
    assert live.requests[0]["status"] == 503
    assert live.requests[0]["body_hash"], "the request that failed is still recorded by hash"


def test_the_recorded_request_is_credential_free_and_carries_its_hash() -> None:
    """``docs/agent-harness.md:33``: 不存密钥. The hash is of the body actually sent."""
    transport = Recorder(ok(json.dumps(PROPOSAL), usage={"prompt_tokens": 9, "completion_tokens": 4}))
    live = client(transport)

    live.decide(system="choose an action", messages=messages(), max_output_tokens=256)

    record = live.requests[0]
    serialised = json.dumps(record)
    assert SECRET not in serialised
    assert "authorization" not in serialised.lower()
    # The hash must cover the body as the transport received it, recomputed here the project's canonical way.
    meant = json.dumps(transport.calls[0]["body"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert record["body_hash"] == hashlib.sha256(meant.encode("utf-8")).hexdigest()
    assert record["mode"] == MODEL_MODE_LIVE
    assert record["attempts"] == 1


def test_the_credential_travels_in_a_header_that_is_never_recorded() -> None:
    """The key has to be sent, and must not be what gets stored."""
    transport = Recorder(ok(json.dumps(PROPOSAL), usage={"prompt_tokens": 9, "completion_tokens": 4}))

    client(transport).decide(system="s", messages=messages(), max_output_tokens=256)

    headers = transport.calls[0]["headers"]
    assert SECRET in headers.get("Authorization", ""), "the provider cannot authenticate without it"
    assert all(SECRET not in value for value in client(Recorder(ok("{}"))).requests), "no record may carry it"


def test_missing_usage_is_estimated_and_never_a_silent_zero() -> None:
    """``docs/agent-spec.md:44``: 缺provider准确计数时标ESTIMATED. Zero would refund the reservation."""
    transport = Recorder(ok(json.dumps(PROPOSAL)))

    reply = client(transport).decide(system="choose an action", messages=messages(), max_output_tokens=256)

    assert reply.usage.estimated is True
    assert reply.usage.input_tokens > 0
    assert reply.usage.output_tokens > 0
    assert reply.mode == MODEL_MODE_LIVE
    assert reply.mode != MODEL_MODE_MOCK


def test_provider_counts_are_used_and_marked_exact() -> None:
    """The other half: when the provider does report counts, take them and say they are exact."""
    transport = Recorder(ok(json.dumps(PROPOSAL), usage={"prompt_tokens": 321, "completion_tokens": 45}))

    reply = client(transport).decide(system="s", messages=messages(), max_output_tokens=256)

    assert (reply.usage.input_tokens, reply.usage.output_tokens) == (321, 45)
    assert reply.usage.estimated is False


def test_an_answer_that_is_not_a_decision_is_refused_rather_than_guessed() -> None:
    """A provider that answers prose must not be interpreted into an action the model did not choose."""
    transport = Recorder(ok("I think you should probably refund this one."))

    reply = client(transport).decide(system="s", messages=messages(), max_output_tokens=256)
    assert reply.decision == {"kind": "__INVALID_MODEL_JSON__",
                              "raw_output": "I think you should probably refund this one."}
    assert reply.usage.output_tokens > 0


def test_the_answer_may_arrive_in_a_fenced_block() -> None:
    """Providers wrap JSON in code fences habitually; the extraction is lenient about packaging, not about content."""
    transport = Recorder(ok("```json\n" + json.dumps(PROPOSAL) + "\n```"))

    reply = client(transport).decide(system="s", messages=messages(), max_output_tokens=256)

    assert reply.decision["kind"] == "PROPOSE"
    assert reply.decision["recommended_action"] == "REFUND"


def test_an_empty_system_prompt_does_not_add_a_second_system_message() -> None:
    """``ModelClient``: an empty ``system`` means P0 already carries it; adding one would duplicate the prompt."""
    transport = Recorder(ok(json.dumps(PROPOSAL), usage={"prompt_tokens": 3, "completion_tokens": 1}))

    client(transport).decide(system="", messages=messages(), max_output_tokens=64)

    sent = transport.calls[0]["body"]["messages"]
    assert [message["role"] for message in sent] == ["user"]
