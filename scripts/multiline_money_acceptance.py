"""Read-only verification of current line/order money facts on the preserved demo.

No refund creation, settlement, model call, provider call, or database mutation. Snapshot
contains synthetic credentials/hashes and stays in ignored tmp; report only contains
public synthetic line identities and aggregate preservation hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import reviewer_demo as demo
from checkout_payment_acceptance import snapshot
from resolveflow.contracts._schemaio import component_validator
from resolveflow.runtime.db import Database

ROOT = Path(__file__).resolve().parents[1]


def baseline(settings: demo.Settings, database: Database) -> dict:
    state = snapshot(settings, database)
    state["line_slots"] = demo.mysql_rows(
        "SELECT line_id,state,operation_id,version,updated_at FROM line_refund ORDER BY line_id",
        settings, database="commerce_db")
    return state


def verify(settings: demo.Settings, database: Database, before: dict) -> dict:
    token = demo.mint_service_token("case-service", scope="commerce:read")
    buyer = demo.login(settings, "demo-buyer", "demo-pass-4001")
    customer = demo.login(settings, "demo-customer", "demo-pass-1001")
    paid = json.loads((ROOT / "reports/checkout-payment/verification.json").read_text(encoding="utf-8"))
    new_lines = [s["line_id"] for s in paid["samples"] if s["status"] == "PAID"]
    checks = []
    for line in ["7001", "7002", *new_lines]:
        observations = {}
        for suffix, schema in [("context", "LineContext"), ("refund-status", "LineRefundStatus")]:
            status, body = demo.http("GET", settings.commerce_url + f"/internal/v1/order-lines/{line}/{suffix}",
                                     token=token)
            assert status == 200, (line, suffix, status)
            validator = component_validator("commerce", schema, "contracts/core")
            assert validator.accepts(body), validator.error_messages(body)
            assert "order_paid_amount" in body
            assert body["refunded_amount"] + body["reserved_refund_amount"] <= body["order_paid_amount"]
            observations[suffix] = body
            checks.append({"line_id": line, "read": suffix, "status": status, "schema": schema, "passed": True})
        context, slot = observations["context"], observations["refund-status"]
        assert context["order_paid_amount"] == slot["order_paid_amount"]
        assert context["line_refund_state"] == slot["state"]
        assert slot["line_refunded_amount"] == (slot["line_paid_amount"] if slot["state"] == "CONSUMED" else 0)
        assert slot["line_reserved_refund_amount"] == (slot["line_paid_amount"] if slot["state"] == "RESERVED" else 0)
        status, eligibility = demo.http("GET", settings.gateway_url + f"/api/v1/customer/order-lines/{line}",
                                       token=buyer if line in new_lines else customer)
        assert status == 200, (line, "eligibility", status)
        if slot["state"] != "FREE":
            assert not eligibility["can_apply"]
        if line in new_lines:
            assert slot["state"] == "FREE" and eligibility["can_apply"]
        checks.append({"line_id": line, "read": "customer-eligibility", "status": status, "passed": True})

    after = baseline(settings, database)
    assert before == after, "Preserved demo changed during read-only deployment verification"
    preserved = {key: {"rows": len(rows), "unchanged": True,
                       "sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}
                 for key, rows in before.items()}
    return {"date": "2026-10-03", "synthetic": True, "read_only": True, "model_calls": 0,
            "checks": checks, "preserved": preserved, "multi_line_writes": "isolated Java MySQL tests only"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["snapshot", "verify"])
    parser.add_argument("--baseline", type=Path, default=ROOT / "tmp/multiline-before.json")
    parser.add_argument("--report", type=Path, default=ROOT / "reports/multiline-refunds/verification.json")
    args = parser.parse_args()
    settings = demo.Settings()
    demo.guard(settings)
    database = Database(settings.agent_dsn)
    try:
        if args.command == "snapshot":
            args.baseline.parent.mkdir(parents=True, exist_ok=True)
            data = baseline(settings, database)
            args.baseline.write_bytes(json.dumps(data).encode())
            print({key: len(rows) for key, rows in data.items()})
        else:
            report = verify(settings, database, json.loads(args.baseline.read_text(encoding="utf-8")))
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
            print(f"{len(report['checks'])} HTTP reads passed; all original rows unchanged; model calls 0")
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
