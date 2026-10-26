"""Lab-only HTTP adapter around the existing persistent simulated refund provider."""

import argparse
import json
import os
import socket
import sys
import threading
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent/src"))
from resolveflow.provider_stub import ProviderConflictError, RefundProviderStub


class Provider:
    def __init__(self, path, port, *, trace_path=None):
        self.stub = RefundProviderStub(path)
        self.gate = threading.Event()
        self.gate.set()
        self.lose_response = set()
        self.no_receipt = set()
        self.hidden_until = {}
        self.visibility_delay_seconds = 10
        self.trace = []
        self.trace_path = trace_path
        self.trace_lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def answer(self, status, value):
                encoded = json.dumps(value, default=str).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self):
                if self.path == "/health":
                    self.answer(200, {"status": "UP", "kind": "persistent simulated provider only"})
                elif self.path.startswith("/provider/v1/refunds/"):
                    operation = self.path.rsplit("/", 1)[-1]
                    if time.monotonic() < owner.hidden_until.get(operation, 0):
                        owner.record("query_hidden", operation)
                        self.answer(404, {"operation_id": operation, "state": "NOT_FOUND"})
                        return
                    result = owner.stub.query_refund(operation)
                    owner.record("query", operation, state=result.state)
                    self.answer(404 if result.state == "NOT_FOUND" else 200, asdict(result))
                else:
                    self.answer(404, {"detail": "not found"})

            def do_POST(self):
                if self.path != "/provider/v1/refunds":
                    self.answer(404, {"detail": "not found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 1 or length > 16384:
                        raise ValueError("invalid body size")
                    body = json.loads(self.rfile.read(length))
                    if set(body) != {"operation_id", "line_id", "amount_minor", "currency"}:
                        raise ValueError("invalid refund fields")
                    operation = body["operation_id"]
                    owner.record("request", operation)
                    if not owner.gate.wait(120):
                        owner.record("gate_timeout", operation)
                        self.answer(503, {"detail": "lab gate not released"})
                        return
                    if operation in owner.no_receipt:
                        owner.record("no_receipt", operation)
                        self.answer(200, {"operation_id": operation, "state": "UNKNOWN", "responded": False})
                        return
                    result = owner.stub.request_refund(**body)
                    owner.record("receipt", operation, state=result.state)
                    if operation in owner.lose_response:
                        owner.lose_response.remove(operation)
                        owner.hidden_until[operation] = time.monotonic() + owner.visibility_delay_seconds
                        owner.record("socket_lost", operation, visibility_delay_seconds=owner.visibility_delay_seconds,
                                     visible_monotonic=owner.hidden_until[operation])
                        self.close_connection = True
                        self.connection.shutdown(socket.SHUT_RDWR)
                        return
                    self.answer(200, asdict(result))
                except ProviderConflictError:
                    self.answer(409, {"detail": "operation payload conflict"})
                except (ValueError, TypeError):
                    self.answer(400, {"detail": "invalid refund request"})

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def record(self, stage, operation, **values):
        row = {"stage": stage, "operation_id": operation, "monotonic": time.monotonic(), **values}
        with self.trace_lock:
            self.trace.append(row)
            if self.trace_path:
                with Path(self.trace_path).open("a", encoding="utf-8") as output:
                    output.write(json.dumps(row) + "\n")
                    output.flush()
                    os.fsync(output.fileno())

    def close(self):
        self.gate.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.stub.close()


def main():
    from evaluation.backend_lab import Settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    settings = Settings(args.run_id)
    state = settings.load()
    provider = Provider(settings.folder / "provider.sqlite3", state["ports"]["provider"])
    try:
        provider.thread.join()
    finally:
        provider.close()


if __name__ == "__main__":
    main()
