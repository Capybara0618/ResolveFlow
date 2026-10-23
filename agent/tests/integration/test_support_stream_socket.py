"""A local HTTP socket proves the first projected body does not await the tail."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from resolveflow.harness.streaming_model import StreamingLiveModelClient
from resolveflow.support.stream_projection import AnswerDelta, AnswerProjection


def test_actual_socket_flush_reaches_projection_before_server_sends_completion() -> None:
    visible = threading.Event()
    seen: list[AnswerDelta] = []
    recorded: list[dict[str, Any]] = []
    order: list[str] = []

    def frame(text: str) -> bytes:
        value = {"choices": [{"index": 0, "delta": {"content": text}}]}
        return ("data: " + json.dumps(value) + "\n\n").encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            recorded.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(frame('{"kind":"ANSWER_PARTS","parts":[{"text":"您好，我来核查'))
            self.wfile.flush()
            order.append("first_flushed")
            reached_before_tail = visible.wait(2)
            recorded[0]["first_body_before_tail"] = reached_before_tail
            order.append("tail_sent")
            self.wfile.write(frame('。"}]}'))
            tail = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 9}}
            self.wfile.write(("data: " + json.dumps(tail) + "\n\ndata: [DONE]\n\n").encode())
            self.wfile.flush()

    projection = AnswerProjection()

    def observe(fragment: str) -> None:
        deltas = projection.feed(fragment)
        if deltas and not seen:
            order.append("first_body")
            visible.set()
        seen.extend(deltas)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            model = StreamingLiveModelClient(
                endpoint=f"http://127.0.0.1:{server.server_port}/chat/completions", model_id="local-synthetic",
                timeout_seconds=4, on_content=observe,
            )
            started = time.perf_counter()
            reply = model.decide(system="JSON", messages=[], max_output_tokens=80)
            elapsed = time.perf_counter() - started
            order.append("reply_returned")
            projection.finish()
        finally:
            server.shutdown()
            worker.join(timeout=2)

    assert len(recorded) == 1 and recorded[0]["first_body_before_tail"] is True
    assert order.index("first_body") < order.index("tail_sent") < order.index("reply_returned")
    assert "".join(delta.text for delta in seen) == "您好，我来核查。"
    assert model.calls == len(model.requests) == 1
    assert reply.usage.input_tokens == 7 and reply.usage.output_tokens == 9 and not reply.usage.estimated
    assert model.last_stream is not None
    assert model.last_stream["first_content_ms"] < model.last_stream["completed_ms"] <= elapsed * 1000
