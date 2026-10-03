"""Verify browser-created simulated checkout samples without resetting or creating business data.

Run snapshot before restarting the preserved demo and creating samples through the UI;
verify afterwards. Credentials are synthetic demo accounts; tokens/keys/raw baselines
never appear in the committed report. No model calls or public provider fault switches.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent/src"))
import reviewer_demo as demo
from product_flow_acceptance import baseline_state
from resolveflow.contracts._schemaio import component_validator
from resolveflow.runtime.db import Database


def snapshot(settings: demo.Settings, database: Database) -> dict:
    state = baseline_state(settings, database)
    queries = {
        "accounts": ("case_db", "SELECT username,merchant_id,role,customer_id,password_hash,enabled,identity_version,account_version FROM identity_account ORDER BY username"),
        "orders": ("commerce_db", "SELECT order_id,merchant_id,customer_id,order_status,paid_at FROM orders ORDER BY order_id"),
        "drafts": ("commerce_db", "SELECT draft_id,merchant_id,customer_id,idempotency_key,sku_id,quantity,total_amount,status,created_at,expires_at FROM checkout_draft ORDER BY draft_id"),
    }
    for name, (db_name, sql) in queries.items():
        state[name] = demo.mysql_rows(sql, settings, database=db_name)
    with database.connection() as connection:
        state["run_spend"] = [{**row, "run_id": str(row["run_id"])} for row in connection.execute(
            "SELECT run_id,budget_spent FROM agent_run ORDER BY run_id").fetchall()]
    return state


def verify(settings: demo.Settings, database: Database, before: dict, samples_path: Path, report_path: Path) -> dict:
    checks: list[dict] = []
    buyer = demo.login(settings, "demo-buyer", "demo-pass-4001")

    def check(label: str, path: str, expected: int = 200, *, token=buyer, body=None, headers=None, internal=False):
        code, data = demo.http("POST" if body is not None else "GET",
                               (settings.commerce_url if internal else settings.gateway_url) + path,
                               token=token, body=body, headers=headers)
        checks.append({"check": label, "status": code, "expected": expected, "passed": code == expected})
        assert code == expected, (label, code)
        return data

    def schema(name: str, value: dict) -> None:
        validator = component_validator("case", name, "contracts/core")
        assert validator.accepts(value), (name, validator.error_messages(value))

    check("no session private list", "/api/v1/shop/purchases", 401, token=None)
    for username, password in [("demo-customer", "demo-pass-1001"), ("demo-admin", "demo-pass-1100")]:
        check(username + " is not a platform buyer", "/api/v1/shop/purchases", 403,
              token=demo.login(settings, username, password))
    page = check("personal mixed new and old purchases", "/api/v1/shop/purchases")
    schema("CheckoutPurchases", page)
    assert len({p["purchase_id"] for p in page["items"]}) == len(page["items"])
    check("invalid limit", "/api/v1/shop/purchases?limit=49", 400)
    check("invalid state", "/api/v1/shop/purchases?status=FORGED", 400)
    check("invalid cursor", "/api/v1/shop/purchases?cursor=not-a-cursor", 400)
    scoped = check("client customer query cannot change ownership", "/api/v1/shop/purchases?customer_id=C-1001")
    assert {p["purchase_id"] for p in scoped["items"]} == {p["purchase_id"] for p in page["items"]}

    samples = json.loads(samples_path.read_text(encoding="utf-8"))["samples"]
    assert len(samples) == 4 and len({s["purpose"] for s in samples}) == 4
    outcomes = []
    for sample in samples:
        draft_id = str(uuid.UUID(sample["url"].split("#/shop/drafts/")[1]))
        purchase = check(sample["purpose"] + " own detail", "/api/v1/shop/purchases/draft%3A" + draft_id)
        schema("CheckoutPurchase", purchase)
        payment = check(sample["purpose"] + " original attempt lookup", f"/api/v1/shop/drafts/{draft_id}/payment")
        schema("CheckoutPaymentLookup", payment)
        rows = demo.mysql_rows(
            f"SELECT merchant_id,customer_id,total_amount,status,order_id,line_id FROM checkout_draft WHERE draft_id='{draft_id}'",
            settings, database="commerce_db")
        assert len(rows) == 1
        merchant, customer, amount, state, order_id, line_id = rows[0]
        amount = int(amount)
        assert customer == ("C-B3001-M1001" if merchant == "M-1001" else "C-B3001-M1002")
        assert purchase["total_amount"] == amount
        if sample["purpose"].startswith("paid-"):
            assert state == "PAID" and payment["payment"]["status"] == "SUCCEEDED"
            p = payment["payment"]
            attempt_id = str(uuid.UUID(p["attempt_id"]))
            keys = demo.mysql_rows(f"SELECT idempotency_key FROM checkout_payment_attempt WHERE attempt_id='{attempt_id}'",
                                   settings, database="commerce_db")
            replay = check("terminal original payment replay " + merchant, f"/api/v1/shop/drafts/{draft_id}/payment",
                           body={}, headers={"Idempotency-Key": keys[0][0]})
            assert replay == p
            check("paid draft new key refused " + merchant, f"/api/v1/shop/drafts/{draft_id}/payment", 409,
                  body={}, headers={"Idempotency-Key": "synthetic-another-payment"})
            check("paid cannot cancel " + merchant, f"/api/v1/shop/drafts/{draft_id}/cancel", 409, body={})
            original_view = check("published line in original order API " + merchant, f"/api/v1/orders/{order_id}")
            assert len(original_view["items"]) == 1
            assert original_view["items"][0]["line_id"] == line_id
            assert original_view["items"][0]["line_paid_amount"] == amount
            ledger = demo.mysql_rows(f"SELECT paid_amount,refunded_amount,reserved_refund_amount,version FROM payment_ledger WHERE order_id='{order_id}'",
                                     settings, database="commerce_db")
            assert ledger == [[str(amount), "0", "0", "1"]]
            slot = demo.mysql_rows(f"SELECT state,operation_id,version FROM line_refund WHERE line_id='{line_id}'",
                                   settings, database="commerce_db")
            assert slot == [["FREE", "NULL", "1"]]
            attempts = demo.mysql_rows(f"SELECT COUNT(*) FROM checkout_payment_attempt WHERE draft_id='{draft_id}'",
                                       settings, database="commerce_db")
            receipts = demo.mysql_rows(f"SELECT COUNT(*) FROM simulated_checkout_receipt WHERE attempt_id='{attempt_id}'",
                                       settings, database="commerce_db")
            assert attempts == [["1"]] and receipts == [["1"]]
        elif sample["purpose"] == "cancelled-home":
            assert state == "CANCELLED" and purchase["status"] == "CANCELLED" and payment["payment"] is None
            check("cancelled draft cannot pay", f"/api/v1/shop/drafts/{draft_id}/payment", 409,
                  body={}, headers={"Idempotency-Key": "synthetic-cancelled-pay"})
            assert check("cancellation replay", f"/api/v1/shop/drafts/{draft_id}/cancel", body={})["status"] == "CANCELLED"
        else:
            assert state == "WAITING_PAYMENT" and purchase["status"] in {"WAITING_PAYMENT", "EXPIRED"}
            assert payment["payment"] is None
            check("public payment cannot supply money", f"/api/v1/shop/drafts/{draft_id}/payment", 400,
                  body={"total_amount": 1}, headers={"Idempotency-Key": "synthetic-bad-body"})
        if not sample["purpose"].startswith("paid-"):
            assert order_id == line_id == "NULL"
            assert demo.mysql_rows(f"SELECT COUNT(*) FROM checkout_payment_attempt WHERE draft_id='{draft_id}'",
                                   settings, database="commerce_db") == [["0"]]
        check("foreign composite draft " + merchant, f"/internal/v1/shop/drafts/{draft_id}/payment?merchant_id={merchant}&customer_id=OTHER",
              404, token=demo.mint_service_token("case-service", scope="commerce:checkout"), internal=True)
        outcomes.append({"purpose": sample["purpose"], "draft_id": draft_id, "store_id": merchant,
                         "status": purchase["status"], "amount_minor": amount,
                         "order_id": None if order_id == "NULL" else order_id,
                         "line_id": None if line_id == "NULL" else line_id})

    for row in before["drafts"]:
        draft_id = str(uuid.UUID(row[0]))
        assert check("old draft remains expired", "/api/v1/shop/purchases/draft%3A" + draft_id)["status"] == "EXPIRED"
        check("old expired draft cannot pay", f"/api/v1/shop/drafts/{draft_id}/payment", 409,
              body={}, headers={"Idempotency-Key": "synthetic-expired-pay"})
    check("unknown purchase is 404", "/api/v1/shop/purchases/order%3A00000000-0000-4000-8000-000000009999", 404)
    for subject, scope in [("agent-service", "commerce:read policy:read"), ("agent-service", "commerce:checkout"),
                           ("case-service", "commerce:read")]:
        check(subject + " " + scope + " cannot read private transactions",
              "/internal/v1/shop/purchases?merchant_id=M-1001&customer_id=C-B3001-M1001", 403,
              token=demo.mint_service_token(subject, scope=scope), internal=True)
    seen = []
    cursor = None
    first_cursor = None
    for i in range(20):
        route = "/api/v1/shop/purchases?limit=1" + ("&cursor=" + cursor if cursor else "")
        part = check(f"real one-item merged page {i + 1}", route)
        schema("CheckoutPurchases", part)
        seen.extend(p["purchase_id"] for p in part["items"])
        cursor = part["next_cursor"]
        first_cursor = first_cursor or cursor
        if not cursor:
            break
    assert cursor is None and len(seen) == len(set(seen)) == len(page["items"])
    if first_cursor:
        check("cursor cannot change store filter", "/api/v1/shop/purchases?store_id=M-1001&cursor=" + first_cursor, 400)

    after = snapshot(settings, database)
    canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
    unchanged = {}
    for name, rows in before.items():
        ids = {row["run_id"] if isinstance(row, dict) else row[0] for row in rows}
        current = [row for row in after[name] if (row["run_id"] if isinstance(row, dict) else row[0]) in ids]
        assert canonical(rows) == canonical(current), "Protected original rows changed: " + name
        unchanged[name] = {"rows": len(rows), "unchanged": True,
                           "sha256": hashlib.sha256(json.dumps(canonical(rows)).encode()).hexdigest()}
    assert len(after["cases"]) == len(before["cases"]) and len(after["runs"]) == len(before["runs"])
    assert len(after["orders"]) == len(before["orders"]) + 2
    assert len(after["payments"]) == len(before["payments"]) + 2
    assert len(after["drafts"]) == len(before["drafts"]) + 4
    report = {"date": "2026-10-03", "synthetic": True, "model_calls": 0, "checks": checks,
              "samples": outcomes, "protected_originals": unchanged,
              "new_paid_orders": 2, "new_drafts": 4, "new_refund_operations": 0,
              "unknown_and_fault_injection": "isolated Java database tests only; not injected into preserved demo"}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["snapshot", "verify"])
    parser.add_argument("--baseline", type=Path, default=ROOT / "tmp/checkout-before.json")
    parser.add_argument("--samples", type=Path, default=ROOT / "reports/checkout-payment/samples.json")
    parser.add_argument("--report", type=Path, default=ROOT / "reports/checkout-payment/verification.json")
    args = parser.parse_args()
    settings = demo.Settings()
    demo.guard(settings)
    database = Database(settings.agent_dsn)
    try:
        if args.command == "snapshot":
            state = snapshot(settings, database)
            args.baseline.parent.mkdir(parents=True, exist_ok=True)
            args.baseline.write_bytes(json.dumps(state).encode())
            print({k: len(v) for k, v in state.items()})
        else:
            report = verify(settings, database, json.loads(args.baseline.read_text(encoding="utf-8")),
                            args.samples, args.report)
            print(f"{len(report['checks'])} HTTP checks passed; originals preserved; 2 paid / 1 cancelled / 1 unpaid; model calls 0")
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
