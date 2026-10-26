"""Lab-only HTTP adapter around the existing persistent simulated refund provider."""

import argparse
import json
import sys
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent/src"))
from resolveflow.provider_stub import ProviderConflictError, RefundProviderStub


class Provider:
    def __init__(self, path, port):
        self.stub = RefundProviderStub(path)
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
                    result = owner.stub.query_refund(self.path.rsplit("/", 1)[-1])
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
                    result = owner.stub.request_refund(**body)
                    self.answer(200, asdict(result))
                except ProviderConflictError:
                    self.answer(409, {"detail": "operation payload conflict"})
                except (ValueError, TypeError):
                    self.answer(400, {"detail": "invalid refund request"})

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
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
