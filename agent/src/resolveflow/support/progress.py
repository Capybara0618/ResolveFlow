"""Optional bounded progress delivery, isolated from the model's request/accounting path."""

from __future__ import annotations

import queue
import threading
import time
from typing import Any
from urllib.parse import quote

import httpx

from resolveflow.support.stream_projection import AnswerProjection, ProjectionError


class ProgressReporter:
    def __init__(self, case_url: str, run: str, token: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self._url = case_url.rstrip("/") + "/internal/v1/support/turns/" + quote(run, safe="") + "/stream-events"
        self._token, self._transport = token, transport
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=500)
        self._stop = threading.Event()
        self.failure: str | None = None
        self._projection: AnswerProjection | None = None
        self._attempt = ""
        self._view_attempt: str | None = None
        self._step = 0
        self._started = False
        self._pending: dict[str, dict[str, Any]] = {}
        self._last_flush = time.monotonic()
        self._events = 0
        self._worker = threading.Thread(target=self._deliver, name="support-progress", daemon=True)
        self._worker.start()

    def _emit(self, kind: str, payload: dict[str, Any], attempt: str | None = None) -> None:
        if self._stop.is_set():
            return
        self._events += 1
        if self._events > 490:
            self.failure = "PROGRESS_LIMIT"
            self._stop.set()
            return
        try:
            self._queue.put_nowait({"kind": kind, "attempt_id": attempt, "payload": payload})
        except queue.Full:
            self.failure = "PROGRESS_BACKPRESSURE"
            self._stop.set()

    def begin(self, step: int) -> None:
        if self._started:
            self.reject()
        self._attempt = f"model-{step}"
        self._step = step
        if self._view_attempt is not None and self._view_attempt != self._attempt:
            self._emit("answer.reset", {}, self._attempt)
            self._view_attempt = self._attempt
        self._projection = AnswerProjection()
        self._pending.clear()
        self._last_flush = time.monotonic()

    def content(self, fragment: str) -> None:
        if self._projection is None or self._stop.is_set():
            return
        try:
            deltas = self._projection.feed(fragment)
        except ProjectionError:
            # Complete provider output still settles usage and reaches the existing correction gate.
            self.reject()
            self._projection = None
            return
        first = bool(deltas) and not self._started
        if first:
            self._emit("answer.started", {}, self._attempt)
            self._view_attempt = self._attempt
            self._started = True
        for delta in deltas:
            pending = self._pending.setdefault(
                delta.part_id, {"part_id": delta.part_id, "offset": delta.offset, "text": ""})
            pending["text"] += delta.text
        due = time.monotonic() - self._last_flush >= .08
        if first or due or sum(len(p["text"]) for p in self._pending.values()) >= 40:
            self._flush()

    def _flush(self) -> None:
        for pending in self._pending.values():
            self._emit("answer.delta", pending, self._attempt)
        self._pending.clear()
        self._last_flush = time.monotonic()

    def end(self) -> None:
        if self._projection is not None:
            try:
                self._projection.finish()
            except ProjectionError:
                self.reject()
            self._projection = None
        self._flush()

    def reject(self) -> None:
        self._pending.clear()
        if self._started:
            self._view_attempt = f"model-{self._step + 1}"
            self._emit("answer.reset", {}, self._view_attempt)
        self._started = False

    def activity(self, category: str, started: bool) -> None:
        self._emit("activity.started" if started else "activity.completed", {"category": category})

    def _deliver(self) -> None:
        sequence = 0
        try:
            with httpx.Client(timeout=1, transport=self._transport, follow_redirects=False, trust_env=False) as client:
                closing = False
                while not self._stop.is_set():
                    first = self._queue.get()
                    if first is None:
                        return
                    events = [first]
                    # Small queue batch; no sleep delaying a real first fragment.
                    while len(events) < 16:
                        try:
                            value = self._queue.get_nowait()
                        except queue.Empty:
                            break
                        if value is None:
                            closing = True
                            break
                        events.append(value)
                    sequence += 1
                    response = client.post(self._url, headers={"Authorization": "Bearer " + self._token},
                                           json={"batch_sequence": sequence, "events": events})
                    if response.status_code != 200:
                        self.failure = f"PROGRESS_HTTP_{response.status_code}"
                        return  # Unknown result is never retried with a new key or a model call.
                    if closing:
                        return
        except (httpx.HTTPError, OSError, ValueError) as error:
            self.failure = type(error).__name__
        finally:
            self._stop.set()

    def close(self) -> None:
        self._flush()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            self.failure = "PROGRESS_BACKPRESSURE"
            self._stop.set()
        self._worker.join(timeout=2)
        if self._worker.is_alive():
            self.failure = "PROGRESS_DRAIN_TIMEOUT"
            self._stop.set()
