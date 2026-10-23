"""Offline provider streams: callbacks happen during the one counted request."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from resolveflow.harness.live_model import ModelRateLimitedError, ModelRefusedError, ModelUnavailableError
from resolveflow.harness.streaming_model import StreamingLiveModelClient


def event(value: Any) -> bytes:
    return ("data: " + json.dumps(value, ensure_ascii=False) + "\r\n\r\n").encode()


def chunk(text: str = "", **extra: Any) -> dict[str, Any]:
    return {"model": "served-model", "choices": [{"index": 0, "delta": {"content": text},
                                                "finish_reason": None}], **extra}


def ending(*, usage: bool = True, empty_choices: bool = False) -> bytes:
    value = chunk()
    value["choices"] = [] if empty_choices else [{"index": 0, "delta": {}, "finish_reason": "stop"}]
    if usage:
        value["usage"] = {"prompt_tokens": 123, "completion_tokens": 17}
    return event(value) + b"data: [DONE]\n\n"


class Pieces(httpx.SyncByteStream):
    def __init__(self, pieces: list[bytes], seen: list[str], *, fail: bool = False) -> None:
        self.pieces, self.seen, self.fail = pieces, seen, fail
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        for index, piece in enumerate(self.pieces):
            if index == 1:
                assert self.seen, "first callback must precede receiving the second network piece"
            yield piece
        if self.fail:
            raise httpx.ReadError("synthetic interruption")

    def close(self) -> None:
        self.closed = True


def client(stream: httpx.SyncByteStream, seen: list[str], *, status: int = 200) -> StreamingLiveModelClient:
    def respond(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        assert sent["stream"] is True and sent["stream_options"]["include_usage"] is True
        assert sent["max_tokens"] == 80
        assert request.headers["accept"] == "text/event-stream"
        return httpx.Response(status, stream=stream, headers={"Retry-After": "7"})

    return StreamingLiveModelClient(
        endpoint="https://synthetic.invalid/chat/completions", model_id="requested-model", api_key="test-only-key",
        parameters={"temperature": 0}, stream_transport=httpx.MockTransport(respond), on_content=seen.append,
    )


def test_content_precedes_tail_and_one_complete_reply_retains_usage() -> None:
    seen: list[str] = []
    stream = Pieces([event(chunk('{"kind":"ANSWER_PARTS",')), event(chunk('"parts":[]}')), ending()], seen)
    model = client(stream, seen)
    prepared = model.prepare_request(system="JSON", messages=[], max_output_tokens=80)
    reply = model.decide(system="JSON", messages=[], max_output_tokens=80)
    assert "".join(seen) == '{"kind":"ANSWER_PARTS","parts":[]}'
    assert reply.decision == {"kind": "ANSWER_PARTS", "parts": []}
    assert (reply.usage.input_tokens, reply.usage.output_tokens, reply.usage.estimated) == (123, 17, False)
    assert reply.model_alias == "served-model"
    assert model.calls == len(model.requests) == 1 and model.requests[0]["body"] == prepared
    assert "test-only-key" not in json.dumps(model.requests)
    assert stream.closed
    assert model.last_stream is not None
    assert model.last_stream["first_content_ms"] <= model.last_stream["completed_ms"]


@pytest.mark.parametrize("tail", [ending(usage=False), ending(empty_choices=True)])
def test_missing_usage_is_estimated_and_legacy_empty_choice_usage_tail_is_accepted(tail: bytes) -> None:
    seen: list[str] = []
    finish = event({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    model = client(Pieces([event(chunk('{"kind":"ANSWER_PARTS","parts":[]}')), finish, tail], seen), seen)
    reply = model.decide(system="JSON", messages=[], max_output_tokens=80)
    assert reply.usage.input_tokens > 0 and reply.usage.output_tokens > 0
    assert reply.usage.estimated == (b'"usage"' not in tail)


def test_utf8_byte_boundaries_comments_crlf_and_multiline_sse() -> None:
    raw = b": heartbeat\r\n\r\n" + event(chunk('{"text":"中文😀"}')) + ending()

    class Bytes(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield from (bytes([value]) for value in raw)

    seen: list[str] = []
    model = client(Bytes(), seen)
    assert model.decide(system="JSON", messages=[], max_output_tokens=80).decision == {"text": "中文😀"}
    assert "".join(seen) == '{"text":"中文😀"}'


@pytest.mark.parametrize("tail", [b"", b"data: [DONE]\n\n", b"data: invalid\n\n", b"data: \xff\n\n"])
def test_truncated_or_invalid_stream_fails_once_even_after_content(tail: bytes) -> None:
    seen: list[str] = []
    stream = Pieces([event(chunk('{"kind":"ANSWER_PARTS","parts":[]}')), tail], seen)
    model = client(stream, seen)
    with pytest.raises(ModelUnavailableError):
        model.decide(system="JSON", messages=[], max_output_tokens=80)
    assert model.calls == len(model.requests) == 1 and model.requests[0]["failure"]
    assert stream.closed


def test_interrupted_stream_has_no_retry_or_successful_reply() -> None:
    seen: list[str] = []
    stream = Pieces([event(chunk('{"text":"partial')), event(chunk(' answer"}'))], seen, fail=True)
    model = client(stream, seen)
    with pytest.raises(ModelUnavailableError, match="stream"):
        model.decide(system="JSON", messages=[], max_output_tokens=80)
    assert model.calls == len(model.requests) == 1 and stream.closed
    assert model.last_stream is not None and model.last_stream["completed_ms"] is None


@pytest.mark.parametrize("status,error", [(401, ModelRefusedError), (429, ModelRateLimitedError),
                                         (503, ModelUnavailableError)])
def test_http_failure_uses_existing_classification_without_retry(status: int, error: type[Exception]) -> None:
    seen: list[str] = []
    model = client(httpx.ByteStream(b"synthetic provider refusal"), seen, status=status)
    with pytest.raises(error) as caught:
        model.decide(system="JSON", messages=[], max_output_tokens=80)
    assert model.calls == len(model.requests) == 1 and seen == []
    if status == 429:
        assert caught.value.retry_after_seconds == 7  # type: ignore[attr-defined]


def test_ceiling_required_before_any_provider_request() -> None:
    seen: list[str] = []
    model = client(httpx.ByteStream(b""), seen)
    with pytest.raises(ValueError, match="max_output_tokens"):
        model.decide(system="JSON", messages=[])
    assert model.calls == 0


def test_multiline_data_and_cr_only_sse_are_decoded() -> None:
    seen: list[str] = []
    first = b'data: {"choices":\rdata: [{"delta":{"content":"{}"}}]}\r\r'
    tail = b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\r\rdata: [DONE]\r\r'
    model = client(Pieces([first, tail], seen), seen)
    assert model.decide(system="JSON", messages=[], max_output_tokens=80).decision == {}


def test_oversized_event_and_observer_failure_are_counted_as_failed_attempts() -> None:
    seen: list[str] = []
    model = client(httpx.ByteStream(b"data: " + b" " * 65_537), seen)
    with pytest.raises(ModelUnavailableError, match="limit"):
        model.decide(system="JSON", messages=[], max_output_tokens=80)
    assert model.calls == len(model.requests) == 1

    def broken(text: str) -> None:
        raise RuntimeError("synthetic callback failure")

    model = client(httpx.ByteStream(event(chunk("{}")) + ending()), seen)
    model.on_content = broken
    with pytest.raises(ModelUnavailableError, match="observer"):
        model.decide(system="JSON", messages=[], max_output_tokens=80)
    assert model.calls == len(model.requests) == 1


def test_reasoning_is_not_forwarded_to_content_observer() -> None:
    seen: list[str] = []
    reason = {"choices": [{"delta": {"reasoning_content": "internal only"}}]}
    model = client(httpx.ByteStream(event(reason) + event(chunk("{}")) + ending()), seen)
    model.decide(system="JSON", messages=[], max_output_tokens=80)
    assert seen == ["{}"]
