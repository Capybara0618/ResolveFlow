"""Opt-in provider SSE transport; the SDK still receives one complete ModelReply.

Not wired into production yet. ``on_content`` is an internal JSON fragment observer,
never a browser callback. Only the support projection may turn fragments into a
provisional view; the ordinary domain validators still own the final answer.
"""

from __future__ import annotations

import codecs
import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from resolveflow.harness.live_model import HttpResponse, LiveModelClient, ModelUnavailableError

if TYPE_CHECKING:
    from agentscope.message import Msg as Message

MAX_STREAM_BYTES = 2_000_000
MAX_EVENT_CHARS = 65_536
MAX_CONTENT_CHARS = 131_072


def _sse_data(response: httpx.Response) -> Iterator[str]:
    """Decode UTF-8 strictly, including split code points and CR/LF boundaries."""
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    line_chars: list[str] = []
    skip_lf = False
    data: list[str] = []
    event_chars = total = 0
    for raw in response.iter_bytes():
        total += len(raw)
        if total > MAX_STREAM_BYTES:
            raise ModelUnavailableError("provider stream exceeds byte limit")
        for character in decoder.decode(raw):
            if skip_lf and character == "\n":
                skip_lf = False
                continue
            skip_lf = character == "\r"
            if character not in "\r\n":
                line_chars.append(character)
                if len(line_chars) + event_chars > MAX_EVENT_CHARS:
                    raise ModelUnavailableError("provider SSE line exceeds limit")
                continue
            line = "".join(line_chars)
            line_chars.clear()
            if not line:
                if data:
                    yield "\n".join(data)
                data, event_chars = [], 0
            elif line.startswith("data:"):
                value = line[5:].removeprefix(" ")
                data.append(value)
                event_chars += len(value)
            if event_chars > MAX_EVENT_CHARS:
                raise ModelUnavailableError("provider SSE event exceeds limit")
    decoder.decode(b"", final=True)
    # Missing event terminator is not silently turned into a complete event.


@dataclass(slots=True)
class StreamingLiveModelClient(LiveModelClient):
    """One HTTP stream, one normal usage settlement, no automatic provider retry."""

    stream_transport: httpx.BaseTransport | None = None
    on_content: Callable[[str], None] | None = None
    last_stream: dict[str, Any] | None = field(default=None, init=False)

    def _body(self, *, system: str, messages: list[Message], max_output_tokens: int) -> dict[str, Any]:
        if self.transport is not None:
            raise ValueError("streaming uses stream_transport, not the buffered transport")
        if self.parameters.get("n", 1) != 1:
            raise ValueError("streaming supports exactly one completion")
        body = super(StreamingLiveModelClient, self)._body(
            system=system, messages=messages, max_output_tokens=max_output_tokens,
        )
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
        return body

    def _send(self, payload: bytes, headers: dict[str, str]) -> HttpResponse:
        started = time.perf_counter()
        self.last_stream = {"first_content_ms": None, "completed_ms": None, "content_fragments": 0,
                            "content_chars": 0}
        headers = {**headers, "Accept": "text/event-stream"}
        try:
            with httpx.Client(transport=self.stream_transport, timeout=self.timeout_seconds,
                              follow_redirects=False, trust_env=False) as client:
                with client.stream("POST", self.endpoint, content=payload, headers=headers) as response:
                    if not 200 <= response.status_code < 300:
                        # Preserve the existing refusal/rate-limit classification, with a bounded error body.
                        error = bytearray()
                        for piece in response.iter_bytes():
                            error.extend(piece[:400 - len(error)])
                            if len(error) >= 400:
                                break
                        return HttpResponse(response.status_code, bytes(error), dict(response.headers))
                    envelope = self._completion(response, started)
                    return HttpResponse(response.status_code, json.dumps(envelope).encode(), dict(response.headers))
        except ModelUnavailableError:
            raise
        except (httpx.HTTPError, OSError, UnicodeError, ValueError) as error:
            # The parent records this one failed attempt; partial text is not a reusable ModelReply.
            raise ModelUnavailableError(f"provider stream failed ({type(error).__name__})") from error

    def _completion(self, response: httpx.Response, started: float) -> dict[str, Any]:
        content: list[str] = []
        usage: Any = None
        served: str | None = None
        finished = False
        assert self.last_stream is not None
        for data in _sse_data(response):
            if data == "[DONE]":
                if not finished or not content:
                    raise ModelUnavailableError("provider stream ended without a finished completion")
                self.last_stream["completed_ms"] = (time.perf_counter() - started) * 1000
                return {"model": served, "choices": [{"message": {"content": "".join(content)}}], "usage": usage}
            packet = json.loads(data)
            if not isinstance(packet, dict) or "error" in packet:
                raise ModelUnavailableError("provider stream contains no valid completion chunk")
            model = packet.get("model")
            if isinstance(model, str) and model:
                if served is not None and served != model:
                    raise ModelUnavailableError("provider model changed during stream")
                served = model
            if packet.get("usage") is not None:
                usage = packet["usage"]
            choices = packet.get("choices")
            if not isinstance(choices, list) or len(choices) > 1:
                raise ModelUnavailableError("provider stream has invalid choices")
            if not choices:  # Compatible usage-only tails, as well as DeepSeek's finish chunk.
                continue
            choice = choices[0]
            if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                raise ModelUnavailableError("provider stream has invalid choice index")
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                raise ModelUnavailableError("provider stream has invalid delta")
            text = delta.get("content")
            if text is not None and not isinstance(text, str):
                raise ModelUnavailableError("provider stream content is not text")
            if text:
                if finished:
                    raise ModelUnavailableError("provider sent content after finishing")
                self.last_stream["content_chars"] += len(text)
                if self.last_stream["content_chars"] > MAX_CONTENT_CHARS:
                    raise ModelUnavailableError("provider stream content exceeds limit")
                content.append(text)
                self.last_stream["content_fragments"] += 1
                if self.last_stream["first_content_ms"] is None:
                    self.last_stream["first_content_ms"] = (time.perf_counter() - started) * 1000
                if self.on_content is not None:
                    try:
                        self.on_content(text)
                    except Exception as error:
                        raise ModelUnavailableError("provider stream observer failed") from error
            if choice.get("finish_reason") is not None:
                finished = True
        raise ModelUnavailableError("provider stream interrupted before [DONE]")
