"""AS01.1: the spike's own stdio upstream, standing in for Case and Commerce.

The spike must exercise the **real** `python -m resolveflow.tools.server` subprocess — that is the thing whose
`mcp` version is in question — but it must not require two running Java services to do it. So this is the same
stub the agent's own integration tests use, restated minimally and for one reason: the spike has its own lock
and its own virtualenv, so it cannot import `agent/tests/integration/stub_upstream.py` without also pinning the
whole agent project into the spike.

It answers the two routes this spike reads, in the contract's shapes. Those shapes are copied from the agent's
stub on purpose: if the agent's stub ever drifts from the contract, this file is a second copy that would *not*
drift, and the difference is worth noticing rather than hiding behind an import.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

__all__ = ["StubUpstream", "start"]

#: The line the spike investigates, and the amount its order row carries.
LINE_ID = "7100"
PAID_AMOUNT = 2599


class StubUpstream:
    """A real HTTP server on a loopback port, logging every request it answers."""

    def __init__(self) -> None:
        self.url: str = ""
        self.requests: list[dict[str, Any]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> str:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # silence the default stderr spam
                return

            def do_GET(self) -> None:  # noqa: N802 - the name http.server calls
                with outer._lock:
                    outer.requests.append(
                        {"path": self.path, "authorization": self.headers.get("Authorization")}
                    )
                body, status = outer._answer(self.path)
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._server.server_address[:2]
        # ``server_address`` is typed ``tuple[str | bytes, int]`` because a unix socket reports bytes; this is a
        # TCP socket, and the check makes that explicit rather than formatting a bytes value into a URL. mypy's
        # `str-bytes-safe` warning is the right one here: an f-string of a bytes value yields "b'127.0.0.1'", and
        # the stub would then be reachable at an address nothing can connect to.
        if not isinstance(host, str):  # pragma: no cover - a TCP socket always reports str
            raise AssertionError(f"the stub upstream bound to a non-TCP address: {host!r}")
        self.url = f"http://{host}:{port}"
        return self.url

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def _answer(self, path: str) -> tuple[dict[str, Any], int]:
        if path.endswith("/context"):
            return (
                {
                    "order_id": "00000000-0000-4000-8000-0000000000aa",
                    "line_id": LINE_ID,
                    "merchant_id": "M-1001",
                    "customer_id": "C-2002",
                    "sku": "SKU-RED-M",
                    "category": "apparel",
                    "quantity": 2,
                    "line_paid_amount": PAID_AMOUNT,
                    "refunded_amount": 0,
                    "reserved_refund_amount": 0,
                    "currency": "CNY",
                    "paid_at": "2026-09-10T08:15:00Z",
                    "order_status": "PAID",
                    "version": 3,
                },
                200,
            )
        if path.endswith("/refund-status"):
            return (
                {
                    "line_id": LINE_ID,
                    "merchant_id": "M-1001",
                    "line_paid_amount": PAID_AMOUNT,
                    "refunded_amount": 0,
                    "reserved_refund_amount": 0,
                    "currency": "CNY",
                    "state": "FREE",
                    "version": 4,
                },
                200,
            )
        if path.endswith("/policy-manifest"):
            # The contract's PolicyManifestResponse: `bundles[0].manifest_hash`, not a top-level `version`.
            return (
                {
                    "bundles": [
                        {"bundle_ids": ["bundle-demo"], "manifest_hash": "d" * 64, "safety_epoch": 1}
                    ],
                    "effective_from": "2026-09-01T00:00:00Z",
                },
                200,
            )
        return {"code": "NOT_FOUND", "message": f"no stub route for {path}", "retryable": False}, 404


def start() -> StubUpstream:
    instance = StubUpstream()
    instance.start()
    return instance
