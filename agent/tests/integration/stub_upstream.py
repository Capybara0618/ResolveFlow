"""A stub Case+Commerce for the MCP tool tests, and the log that makes retries visible.

The MCP server runs as a **child process**, so a counter in this process could never see its requests. The stub
therefore answers over HTTP and appends one line per request to a file the test can read: that is what turns
"the tool stopped instead of retrying" from a claim about code into a count of requests.

Choosing the behaviour by **line id** rather than by a mutable flag keeps each test independent without
restarting the server: ``docs/agent-spec.md:36``'s two rules are about *what was asked for*, so
"line 7001 has no shipment" and "line 7002 is not yours" are naturally different lines.
"""

from __future__ import annotations

import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

__all__ = ["StubUpstream", "start"]

#: line id -> the upstream's answer for that line. Anything not listed is a 200 with the ordinary bodies.
_REFUSALS: dict[str, int] = {
    # 404: the shipment route has nothing for this line.
    "7001": 404,
    # 403: the caller may not read this line at all.
    "7002": 403,
}


def _events(count: int) -> list[dict[str, Any]]:
    return [
        {
            "code": f"EVENT_{index}",
            "occurred_at": f"2026-09-1{index}T00:00:00Z",
            "source_version": index,
        }
        for index in range(1, count + 1)
    ]


class StubUpstream:
    """A real HTTP server on a loopback port, with a request log on disk."""

    def __init__(self, log_path: pathlib.Path) -> None:
        self.log_path = log_path
        self.url: str = ""
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> str:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # silences the default stderr spam
                return

            def do_GET(self) -> None:  # noqa: N802 - the name http.server calls
                outer._record(self.path, dict(self.headers), None)
                body, status = outer._answer(self.path)
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self) -> None:  # noqa: N802 - the name http.server calls
                """C06.4④: the one POST this stub answers is the tool-credential route.

                The body is recorded as well as the path, because "a credential was requested" and "it was
                requested for the right run and revision" are different claims, and only the second one scopes a
                read. Reading it here is also how the test can assert the request carries no member the contract
                does not declare.
                """
                length = int(self.headers.get("Content-Length") or 0)
                sent = self.rfile.read(length).decode("utf-8") if length else ""
                outer._record(self.path, dict(self.headers), sent)
                body, status = outer._answer_post(self.path, sent)
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
        self.url = f"http://{host}:{port}"
        return self.url

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def _record(self, path: str, headers: dict[str, str], body: str | None) -> None:
        entry = {"path": path, "authorization": headers.get("Authorization")}
        if body:
            entry["body"] = body
        with self._lock, self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def _answer_post(self, path: str, body: str) -> tuple[dict[str, Any], int]:
        """The tool-credential route (C06.4④), and a 404 for every other POST.

        The minted token names the run it was issued for. That is what lets a test see a credential for the wrong
        run: a stub that answered a fixed string would make "the executor presented this run's credential" and
        "the executor presented some credential" look the same.
        """
        if path.startswith("/internal/v1/runs/") and path.endswith("/tool-credential"):
            run_id = path.split("/")[4]
            try:
                request = json.loads(body)
            except (ValueError, TypeError):
                return {"code": "SEMANTIC_INVALID", "message": "not JSON"}, 422
            if not isinstance(request, dict) or "case_id" not in request or "input_revision" not in request:
                # The refusal is the contract's: a credential request is exactly {case_id, input_revision}.
                return {"code": "SEMANTIC_INVALID", "message": "a credential request needs case_id and revision"}, 422
            return (
                {
                    "token": f"token-for-{run_id}",
                    "expires_at": "2026-09-25T04:40:00Z",
                    "scopes": ["commerce:read", "policy:read"],
                },
                200,
            )
        return {"code": "NOT_FOUND", "message": f"no stub route for {path}", "retryable": False}, 404

    def _answer(self, path: str) -> tuple[dict[str, Any], int]:
        line = _line_of(path)
        refusal = _REFUSALS.get(line)
        if refusal is not None:
            return {"code": "NOT_FOUND", "message": f"nothing for line {line}", "retryable": False}, refusal

        if path.endswith("/context"):
            return (
                {
                    "order_id": "00000000-0000-4000-8000-0000000000aa",
                    "line_id": line,
                    "merchant_id": "M-1001",
                    "customer_id": "C-2002",
                    "sku": "SKU-RED-M",
                    "category": "apparel",
                    "quantity": 2,
                    "line_paid_amount": 2599,
                    "refunded_amount": 0,
                    "reserved_refund_amount": 0,
                    "currency": "CNY",
                    "paid_at": "2026-09-10T08:15:00Z",
                    "order_status": "PAID",
                    "version": 3,
                },
                200,
            )
        if path.endswith("/shipment"):
            # Six events, so the two-page budget is visibly smaller than the story.
            return (
                {
                    "line_id": line,
                    "synthetic": True,
                    "status": "IN_TRANSIT",
                    "carrier_conclusion": "IN_TRANSIT",
                    "events": _events(6),
                    "source_version": 6,
                    "updated_at": "2026-09-16T00:00:00Z",
                },
                200,
            )
        if path.endswith("/refund-status"):
            return (
                {
                    "line_id": line,
                    "merchant_id": "M-1001",
                    "line_paid_amount": 2599,
                    "refunded_amount": 0,
                    "reserved_refund_amount": 0,
                    "currency": "CNY",
                    "state": "FREE",
                    "version": 4,
                },
                200,
            )
        if "/evidence" in path:
            # The contract's EvidenceListResponse (C06.4⑤): `{case_id, input_revision, evidence:[EvidenceRef]}`.
            # `source_version` is a per-record string, and the two records carry *different* ones — a stub that
            # echoed the current revision for both would hide a tool that read the wrong member.
            return (
                {
                    "case_id": "case-1",
                    "input_revision": 2,
                    "evidence": [
                        {
                            "observation_id": "obs-stub-1",
                            "source_ref": "case:customer_statement:stub",
                            "source_version": "1",
                            "content_hash": "e" * 64,
                        }
                    ],
                },
                200,
            )
        if path.endswith("/policy-manifest"):
            # The contract's PolicyManifestResponse, member for member — `bundles[0].manifest_hash`, not a
            # top-level `version`. The stub used to answer `{"version": "1.2.0"}`, which no service produces:
            # the tool read `version` too, so the two agreed with each other and disagreed with Case, and every
            # read against the real service produced an empty `source_version` (C06.4⑤). A stub that invents its
            # own shape is worse than no stub, because it makes the tool look tested.
            return (
                {
                    "bundles": [
                        {
                            "bundle_ids": ["bundle-demo"],
                            "manifest_hash": "d" * 64,
                            "safety_epoch": 1,
                        }
                    ],
                    "effective_from": "2026-09-01T00:00:00Z",
                },
                200,
            )
        return {"code": "NOT_FOUND", "message": f"no stub route for {path}", "retryable": False}, 404


def _line_of(path: str) -> str:
    """The line id inside a route path, for the two routes that carry one."""
    parts = [part for part in path.split("/") if part]
    for index, part in enumerate(parts):
        if part == "order-lines" and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def start(log_path: pathlib.Path) -> StubUpstream:
    instance = StubUpstream(log_path)
    instance.start()
    return instance