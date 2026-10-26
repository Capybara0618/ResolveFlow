"""Durable, credential-free request evidence for the owned backend laboratory."""

import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path


def durable(path, value):
    with path.open("xb") as file:
        file.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())
        file.flush()
        os.fsync(file.fileno())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class UnknownRequest(ValueError):
    """An intent may have been sent; never infer absence of its business effect."""


def overlap(rows):
    events = []
    for row in rows:
        start, finish = row["started_ns"], row["finished_ns"]
        if type(start) is not int or type(finish) is not int or start >= finish:
            raise ValueError("invalid measured request interval")
        events.extend(((start, 1), (finish, -1)))
    active = peak = 0
    for _, delta in sorted(events):  # Equal endpoints do not overlap.
        active += delta
        peak = max(active, peak)
    return peak


class RequestJournal:
    def __init__(self, folder, *, create=True):
        self.folder = Path(folder)
        self.read_only = not create
        self.condition = threading.Condition()
        self.active = {}
        self.started = {}
        self.tokens = {}
        self.counter = 0
        if create:
            self.folder.mkdir(parents=True, exist_ok=False)
            self.clock = uuid.uuid4().hex
            durable(self.folder / "journal.json", {"clock_session": self.clock, "pid": os.getpid(),
                                                  "clock": "perf_counter_ns; completed intervals only"})
        else:
            self.clock = json.loads((self.folder / "journal.json").read_text(encoding="utf-8"))["clock_session"]

    def register(self, token, actor):
        if not token or not isinstance(actor, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", actor):
            raise ValueError("invalid actor registration")
        self.tokens[token] = actor  # Memory only; no bearer token is written.

    def actor(self, token):
        if token is None:
            return "anonymous"
        if token not in self.tokens:
            raise ValueError("token must be registered with an evaluation actor")
        return self.tokens[token]

    def prepare(self, path, actor, inputs, method="POST"):
        if self.read_only:
            raise ValueError("read-only recovery cannot send requests")
        if not re.match(r"^/api/v1/(shop/|merchant/products(?:/|$))", path):
            raise ValueError("route outside recorded business scope")
        if not inputs or not actor:
            raise ValueError("request needs an actor and input")
        requests = []
        with self.condition:
            for index, (body, key) in enumerate(inputs):
                request = f"{self.counter:06d}"
                self.counter += 1
                folder = self.folder / request
                folder.mkdir()
                intent = {"request_id": request, "method": method, "path": path, "actor": actor,
                          "index": index, "body": body, "idempotency_key": key,
                          "body_sha256": digest(body), "clock_session": self.clock,
                          "state": "MAY_HAVE_BEEN_SENT"}
                durable(folder / "intent.json", intent)
                requests.append(request)
        return requests

    def start(self, request):
        with self.condition:
            if request in self.started:
                raise ValueError("request cannot start twice")
            intent = json.loads((self.folder / request / "intent.json").read_text(encoding="utf-8"))
            if self.read_only or (self.folder / request / "completed.json").exists():
                raise ValueError("completed/read-only request cannot be resent")
            start = time.perf_counter_ns()
            self.started[request] = start
            self.active[request] = intent["path"]
            self.condition.notify_all()
            return start

    def finish(self, request, result):
        finish = time.perf_counter_ns()
        with self.condition:
            start = self.started[request]
            self.active.pop(request)
            self.condition.notify_all()
        intent = json.loads((self.folder / request / "intent.json").read_text(encoding="utf-8"))
        completion = {**result, "request_id": request, "started_ns": start, "finished_ns": finish,
                      "clock_session": self.clock, "intent_sha256": digest(intent)}
        durable(self.folder / request / "completed.json", completion)
        return completion

    def wait_active(self, path, count, *, timeout=10):
        deadline = time.monotonic() + timeout
        with self.condition:
            while sum(p == path for p in self.active.values()) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("concurrency window not reached")
                self.condition.wait(remaining)

    def recover(self, requests):
        rows = []
        for request in requests:
            if not re.fullmatch(r"[0-9]{6}", request):
                raise ValueError("invalid request identifier")
            intent = json.loads((self.folder / request / "intent.json").read_text(encoding="utf-8"))
            target = self.folder / request / "completed.json"
            if not target.exists():
                raise UnknownRequest(request + ": missing response; inspect original key read-only")
            completed = json.loads(target.read_text(encoding="utf-8"))
            if (completed.get("request_id") != request or completed.get("intent_sha256") != digest(intent)
                    or completed.get("clock_session") != self.clock):
                raise ValueError("completion does not match original intent")
            overlap([completed])
            rows.append(completed)
        return rows

    def audit(self):
        rows, unknown = [], []
        for folder in sorted(self.folder.glob("[0-9]" * 6)):
            try:
                rows += self.recover([folder.name])
            except UnknownRequest:
                unknown.append(folder.name)
        return {"recorded": len(rows), "unknown": unknown, "peak_client_inflight": overlap(rows),
                "clock_session": self.clock, "complete": not unknown}


class RecordedSettings:
    """Keep resource ownership in Settings; attach only measurement behavior."""

    def __init__(self, base, journal, burst_gate=None):
        self.base, self.request_journal, self.burst_gate = base, journal, burst_gate

    def __getattr__(self, name):
        return getattr(self.base, name)
