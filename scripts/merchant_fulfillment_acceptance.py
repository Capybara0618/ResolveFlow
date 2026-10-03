"""Preserved demo fulfillment checks; only dedicated new synthetic purchases are written.

Raw baseline and original keys stay in ignored tmp. Browser performs M-1001 first shipment.
No Case creation, refund execution, model call, data reset or fault switch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from pathlib import Path

import reviewer_demo as demo
from multiline_money_acceptance import baseline
from resolveflow.contracts._schemaio import component_validator
from resolveflow.runtime.db import Database

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "tmp/merchant-fulfillment"
PUBLIC = ROOT / "reports/merchant-fulfillment/verification.json"


def snapshot(settings, database):
    state = baseline(settings, database)
    for name, sql in {
        "shipments": "SELECT line_id,status,carrier_conclusion,source_version FROM shipment ORDER BY line_id",
        "shipment_events": "SELECT line_id,source_version,code,occurred_at FROM shipment_event ORDER BY line_id,source_version",
        "cart_heads": "SELECT merchant_id,customer_id,revision FROM shopping_cart ORDER BY merchant_id,customer_id",
        "cart_items": "SELECT merchant_id,customer_id,sku_id,quantity,observed_sku_version FROM shopping_cart_item ORDER BY merchant_id,customer_id,sku_id",
        "cart_requests": "SELECT merchant_id,customer_id,idempotency_key,request_hash,result_revision FROM shopping_cart_request ORDER BY merchant_id,customer_id,idempotency_key",
    }.items():
        state[name] = demo.mysql_rows(sql, settings, database="commerce_db")
    return state


def request(settings, method, path, token, body=None, headers=None, expected=200):
    code, value = demo.http(
        method, settings.gateway_url + path, token=token, body=body, headers=headers
    )
    assert code == expected, (method, path, code, expected)
    return value


def prepare(settings):
    file = LOCAL / "samples.json"
    document = (
        json.loads(file.read_text(encoding="utf-8"))
        if file.exists()
        else {"samples": []}
    )

    def save():
        file.write_bytes((json.dumps(document) + "\n").encode())

    buyer = demo.login(settings, "demo-buyer", "demo-pass-4001")
    for merchant, sku, purpose in [
        ("M-1001", "SKU-1001-BLACK", "browser_first_shipment"),
        ("M-1002", "SKU-2001-CREAM", "unshipped_read"),
    ]:
        if any(sample["store_id"] == merchant for sample in document["samples"]):
            continue
        pending = document.setdefault(
            "pending",
            {
                "store_id": merchant,
                "sku": sku,
                "create_key": str(uuid.uuid4()),
                "payment_key": str(uuid.uuid4()),
            },
        )
        assert pending["store_id"] == merchant and pending["sku"] == sku
        save()
        if not pending.get("draft_id"):
            draft = request(
                settings,
                "POST",
                "/api/v1/shop/drafts",
                buyer,
                {"sku_id": sku, "quantity": 1, "expected_sku_version": 1},
                {"Idempotency-Key": pending["create_key"]},
            )
            pending["draft_id"] = draft["draft_id"]
            save()
        payment = request(
            settings,
            "POST",
            f"/api/v1/shop/drafts/{pending['draft_id']}/payment",
            buyer,
            {},
            {"Idempotency-Key": pending["payment_key"]},
        )
        assert payment["status"] == "SUCCEEDED"
        document["samples"].append(
            {
                "purpose": purpose,
                "store_id": merchant,
                "draft_id": pending["draft_id"],
                "purchase_id": "draft:" + pending["draft_id"],
                "order_id": payment["order_id"],
                "line_id": payment["line_id"],
                "amount": payment["total_amount"],
            }
        )
        del document["pending"]
        save()
    print(json.dumps({"samples": document["samples"]}, ensure_ascii=False))


def verify(settings, database):
    before = json.loads((LOCAL / "before.json").read_text(encoding="utf-8"))
    samples = json.loads((LOCAL / "samples.json").read_text(encoding="utf-8"))[
        "samples"
    ]
    assert len(samples) == 2
    buyer = demo.login(settings, "demo-buyer", "demo-pass-4001")
    admins = {
        m: demo.login(settings, u, password)
        for m, u, password in [
            ("M-1001", "demo-admin", "demo-pass-1100"),
            ("M-1002", "demo-admin-m2", "demo-pass-2100"),
        ]
    }
    checks = []

    def check(label, path, token, expected=200, body=None, headers=None):
        value = request(
            settings,
            "POST" if body is not None else "GET",
            path,
            token,
            body,
            headers,
            expected,
        )
        checks.append({"check": label, "status": expected, "passed": True})
        return value

    def schema(name, value):
        v = component_validator("case", name, "contracts/core")
        assert v.accepts(value), v.error_messages(value)

    check("anonymous trade list rejected", "/api/v1/merchant/orders", None, 401)
    for user, password in [
        ("demo-buyer", "demo-pass-4001"),
        ("demo-reviewer", "demo-pass-1003"),
        ("demo-customer", "demo-pass-1001"),
    ]:
        check(
            user + " cannot use admin trade list",
            "/api/v1/merchant/orders",
            demo.login(settings, user, password),
            403,
        )
    for sample in samples:
        merchant, order = sample["store_id"], sample["order_id"]
        trade = check(
            "own merchant all-line detail",
            "/api/v1/merchant/orders/" + order,
            admins[merchant],
        )
        schema("MerchantTrade", trade)
        assert (
            trade["purchase"]["total_amount"] == sample["amount"]
            and trade["line_aftercare"][0]["state"] == "FREE"
        )
        fact = check(
            "own buyer fulfillment",
            "/api/v1/shop/purchases/" + sample["purchase_id"] + "/fulfillment",
            buyer,
        )
        schema("OrderFulfillment", fact)
        assert trade["fulfillment"] == fact
        expected = "IN_TRANSIT" if merchant == "M-1001" else "NOT_SHIPPED"
        assert fact["status"] == expected and fact["version"] == (
            2 if merchant == "M-1001" else 1
        )
        assert [e["code"] for e in fact["lines"][0]["events"]] == (
            ["ORDER_PAID", "SIMULATED_SHIPPED"]
            if merchant == "M-1001"
            else ["ORDER_PAID"]
        )
        foreign = admins["M-1002" if merchant == "M-1001" else "M-1001"]
        check(
            "foreign merchant detail rejected",
            "/api/v1/merchant/orders/" + order,
            foreign,
            404,
        )
        check(
            "foreign merchant shipment rejected",
            "/api/v1/merchant/orders/" + order + "/simulated-shipment",
            foreign,
            404,
            {"expected_version": 1},
            {"Idempotency-Key": str(uuid.uuid4())},
        )
        page = check(
            "merchant state filter",
            "/api/v1/merchant/orders?status=" + expected,
            admins[merchant],
        )
        schema("MerchantTrades", page)
        assert all(
            t["purchase"]["store_id"] == merchant
            and t["fulfillment"]["status"] == expected
            for t in page["items"]
        )
        bundle = (
            "policy-logistics-2026.10"
            if merchant == "M-1001"
            else "policy-demo-m1002-logistics-2026.10"
        )
        policy = check(
            "new exact policy index ready",
            "/api/v1/admin/policies/" + bundle,
            admins[merchant],
        )
        assert (
            policy["index"]["status"] == "READY"
            and policy["index"]["manifest_hash"] == policy["policy"]["manifest_hash"]
        )
        citation = demo.policy_ref(
            settings,
            merchant_id=merchant,
            bundle_id=bundle,
            manifest_hash=policy["policy"]["manifest_hash"],
            query="已付款未发货 NOT_SHIPPED ORDER_PAID",
            rule_id="R-UNSHIPPED-001",
        )
        assert citation["content_hash"] == policy["rules"][0]["content_hash"]
        checks.append(
            {
                "check": "local dense retrieval preserves exact new unshipped citation",
                "passed": True,
            }
        )
        if merchant == "M-1001":
            receipt = demo.mysql_rows(
                f"SELECT shipment_key,shipment_actor,expected_version FROM order_fulfillment WHERE order_id='{order}'",
                settings,
                database="commerce_db",
            )[0]
            assert receipt[1] == "demo-admin" and receipt[2] == "1"
            replay = check(
                "browser original shipment replay",
                "/api/v1/merchant/orders/" + order + "/simulated-shipment",
                admins[merchant],
                body={"expected_version": 1},
                headers={"Idempotency-Key": receipt[0]},
            )
            assert replay == fact
            check(
                "second key shipment rejected",
                "/api/v1/merchant/orders/" + order + "/simulated-shipment",
                admins[merchant],
                409,
                {"expected_version": 2},
                {"Idempotency-Key": str(uuid.uuid4())},
            )
    after = snapshot(settings, database)
    protected = {}
    for name, rows in before.items():
        ids = {r["run_id"] if isinstance(r, dict) else r[0] for r in rows}
        current = [
            r
            for r in after[name]
            if (r["run_id"] if isinstance(r, dict) else r[0]) in ids
        ]
        canonical = lambda values: sorted(
            values, key=lambda value: json.dumps(value, sort_keys=True)
        )
        assert canonical(rows) == canonical(current), "Original rows changed: " + name
        protected[name] = {
            "rows": len(rows),
            "unchanged": True,
            "sha256": hashlib.sha256(json.dumps(canonical(rows)).encode()).hexdigest(),
        }
    for name in [
        "cases",
        "runs",
        "run_spend",
        "accounts",
        "operations",
        "authorizations",
        "cart_heads",
        "cart_items",
        "cart_requests",
    ]:
        assert len(after[name]) == len(before[name]), name
    for name, increment in [
        ("orders", 2),
        ("payments", 2),
        ("drafts", 2),
        ("line_slots", 2),
        ("policies", 2),
    ]:
        assert len(after[name]) == len(before[name]) + increment, name
    report = {
        "date": "2026-10-03",
        "synthetic": True,
        "model_calls": 0,
        "checks": checks,
        "samples": samples,
        "protected_originals": protected,
        "new_paid_orders": 2,
        "new_lines": 2,
        "new_refunds": 0,
        "browser_shipments": 1,
        "rag": "Actual stored Java manifests and local cached dense encoder; no live model calls",
    }
    PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC.write_bytes(
        (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    )
    print(
        f"{len(checks)} checks passed; original rows preserved; one browser shipment; live model calls 0"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["snapshot", "prepare", "verify"])
    args = parser.parse_args()
    settings = demo.Settings()
    demo.guard(settings)
    LOCAL.mkdir(parents=True, exist_ok=True)
    database = Database(settings.agent_dsn)
    try:
        if args.command == "snapshot":
            if (LOCAL / "before.json").exists():
                raise RuntimeError(
                    "Baseline already exists; refusing to overwrite original evidence."
                )
            state = snapshot(settings, database)
            (LOCAL / "before.json").write_bytes(json.dumps(state).encode())
            print({name: len(rows) for name, rows in state.items()})
        elif args.command == "prepare":
            prepare(settings)
        else:
            verify(settings, database)
    finally:
        database.close()


if __name__ == "__main__":
    main()
