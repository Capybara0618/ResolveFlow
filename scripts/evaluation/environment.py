"""Isolated PostgreSQL and loopback synthetic business sources; production MCP wire."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from resolveflow.harness.mcp_client import McpToolExecutor
from resolveflow.policies import PolicyIndex, ServedBundle, embedder
from resolveflow.runtime.db import Database, create_schema, drop_schema
from scripts.evaluation.dataset import read


@contextmanager
def environment(*, dense=True):
    dsn = os.environ.get("RESOLVEFLOW_AGENT_DB", "postgresql://agent:agent@127.0.0.1:55433/agent_db")
    schema = "eval_" + uuid.uuid4().hex[:16]
    create_schema(dsn, schema)
    database = Database(dsn, schema=schema)
    try:
        database.migrations()
        index = PolicyIndex(database)
        encoder = embedder() if dense else None
        pins = {}
        for document in read("policies/bundles.json"):
            value = {key: document[key] for key in ("bundle_id", "merchant_id", "version", "rules")}
            digest = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            bundle = ServedBundle(**value, manifest_hash=digest, safety_epoch=2)
            index.build(bundle, embedder=encoder)
            pins[bundle.bundle_id] = {
                "merchant_id": bundle.merchant_id,
                "bundle_ids": [bundle.bundle_id],
                "manifest_hash": digest,
                "safety_epoch": bundle.safety_epoch,
            }
        yield database, index, encoder, pins
    finally:
        database.close()
        drop_schema(dsn, schema)


@contextmanager
def business_tools(case, pin, *, run_id, case_id):
    """Serve only this input's scoped reads. No Gold and no application service access."""
    token = secrets.token_urlsafe(24)
    line = case["scope"]["line_id"]
    backend = case["backend"]
    routes = {
        f"/internal/v1/order-lines/{line}/context": ("get_order_context", "order"),
        f"/internal/v1/order-lines/{line}/shipment": ("get_shipment_trace", "shipment"),
        f"/internal/v1/order-lines/{line}/refund-status": ("get_refund_status", "refund"),
        f"/internal/v1/cases/{case_id}/evidence": ("get_case_evidence", "evidence"),
        f"/internal/v1/cases/{case_id}/policy-manifest": ("get_policy_manifest", "manifest"),
    }
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):  # noqa: N802 - stdlib handler method
            path = self.path.split("?", 1)[0]
            requests.append({"path": path, "authorized": self.headers.get("Authorization") == f"Bearer {token}"})
            if not requests[-1]["authorized"]:
                self.answer(403, {"error": "synthetic scope refused"})
            elif path not in routes:
                self.answer(404, {"error": "outside bound case/line"})
            else:
                name, source = routes[path]
                status = backend.get("errors", {}).get(name, 200)
                if status != 200:
                    self.answer(status, {"error": "synthetic unavailable source"})
                elif source == "manifest":
                    self.answer(200, {"bundles": [pin]})
                else:
                    self.answer(200, backend[source])

        def answer(self, status, value):
            body = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    executor = McpToolExecutor(
        line_id=line,
        run_id=run_id,
        case_id=case_id,
        input_revision=1,
        case_base_url=url,
        commerce_base_url=url,
        credential_source=lambda: token,
    )
    try:
        yield executor, requests
    finally:
        executor.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
