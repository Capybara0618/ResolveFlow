"""Prepare resumable synthetic purchases for customer-agent design; no Case or model calls."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from pathlib import Path

import logistics_simulator as simulator
import reviewer_demo as demo

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "tmp/logistics-samples-v1/state.json"
PUBLIC = ROOT / "reports/customer-agent-design-v1/runtime-samples.json"
SAMPLES = (
    ("A-TRANSIT", "M-1001", "IN_TRANSIT"),
    ("A-DELAYED", "M-1001", "DELAYED"),
    ("A-SIGNED", "M-1001", "DELIVERED"),
    ("B-LOST", "M-1002", "LOST"),
    ("B-UNKNOWN", "M-1002", "UNKNOWN"),
    ("B-QUERYFAIL", "M-1002", "UNAVAILABLE"),
    ("B-SIGNED", "M-1002", "DELIVERED"),
)


def save(document: dict) -> None:
    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    temporary = LOCAL.with_suffix(".pending")
    temporary.write_bytes(
        (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()
    )
    temporary.replace(LOCAL)


def fingerprint(settings) -> dict:
    """Hash complete rows, keeping existing-row witnesses without exporting their contents."""
    result = {}
    tables = {
        "commerce_db": (
            "orders",
            "order_line",
            "payment_ledger",
            "line_refund",
            "refund_operation",
            "shipment",
            "shipment_event",
        ),
        "case_db": ("aftersale_case", "case_authorization"),
    }
    for database, names in tables.items():
        for table in names:
            columns = demo.mysql_rows(
                f"SELECT column_name FROM information_schema.columns WHERE table_schema='{database}' AND table_name='{table}' ORDER BY ordinal_position",
                settings,
            )
            if not columns:
                raise RuntimeError(
                    f"required preservation table missing: {database}.{table}"
                )
            columns_sql = ",".join("`" + row[0] + "`" for row in columns)
            rows = demo.mysql_rows(
                f"SELECT SHA2(CAST(JSON_ARRAY({columns_sql}) AS CHAR),256) FROM `{table}`",
                settings,
                database=database,
            )
            result[f"{database}.{table}"] = [row[0] for row in rows]
    return result


def main() -> None:
    settings = demo.settings_from_environ()
    demo.guard(settings)
    password = os.environ.get(
        "RESOLVEFLOW_DEMO_PASSWORD", "123456"
    )  # synthetic local demo default
    buyer = demo.login(settings, "buyer01", password, base_url=settings.case_url)
    admins = {
        m: demo.login(settings, u, password, base_url=settings.case_url)
        for m, u in (("M-1001", "admin01"), ("M-1002", "admin02"))
    }
    state = (
        json.loads(LOCAL.read_text(encoding="utf-8"))
        if LOCAL.exists()
        else {"synthetic": True, "samples": {}}
    )
    if "baseline" not in state:
        state["baseline"] = fingerprint(settings)
        save(state)

    def api(method, path, token=None, body=None, headers=None, expected=200):
        code, value = demo.http(
            method, settings.case_url + path, token=token, body=body, headers=headers
        )
        if code != expected:
            raise RuntimeError(f"{method} {path} answered {code}, expected {expected}")
        return value

    mysql = simulator.LocalMysql()
    published = []
    for name, merchant, scenario in SAMPLES:
        record = state["samples"].setdefault(
            name,
            {
                "keys": {
                    action: f"design-v1-{name}-{action}"
                    for action in ("draft", "pay", "ship", "scenario")
                }
            },
        )
        save(state)
        if "draft" not in record:
            products = api(
                "GET", f"/api/v1/shop/products?store_id={merchant}&limit=24"
            )["items"]
            product = api("GET", "/api/v1/shop/products/" + products[0]["product_id"])
            sku = product["skus"][0]
            record["draft"] = api(
                "POST",
                "/api/v1/shop/drafts",
                buyer,
                {
                    "sku_id": sku["sku_id"],
                    "quantity": 1,
                    "expected_sku_version": sku["version"],
                },
                {"Idempotency-Key": record["keys"]["draft"]},
            )
            save(state)
        draft = record["draft"]
        if "payment" not in record:
            record["payment"] = api(
                "POST",
                f"/api/v1/shop/drafts/{draft['draft_id']}/payment",
                buyer,
                {},
                {"Idempotency-Key": record["keys"]["pay"]},
            )
            save(state)
        payment = record["payment"]
        if payment["status"] != "SUCCEEDED":
            raise RuntimeError(
                f"{name}: payment is not confirmed; preserve original attempt"
            )
        order = payment["order_id"]
        if "first_shipment" not in record:
            record["first_shipment"] = api(
                "POST",
                f"/api/v1/merchant/orders/{order}/simulated-shipment",
                admins[merchant],
                {"expected_version": 1},
                {"Idempotency-Key": record["keys"]["ship"]},
            )
            save(state)
        receipts = mysql.execute(
            simulator.call_sql(
                order, merchant, 2, scenario, record["keys"]["scenario"], None
            )
        )
        snapshot = simulator.inspect(mysql, order, merchant)
        expected = 503 if scenario == "UNAVAILABLE" else 200
        token = demo.mint_service_token("case-service", scope="commerce:read")
        status, _ = demo.http(
            "GET",
            settings.commerce_url
            + "/internal/v1/order-lines/"
            + payment["line_id"]
            + "/shipment",
            token=token,
        )
        if status != expected:
            raise RuntimeError(
                f"{name}: live shipment read answered {status}, expected {expected}"
            )
        own = api("GET", f"/api/v1/shop/purchases/draft:{draft['draft_id']}", buyer)
        other = "M-1002" if merchant == "M-1001" else "M-1001"
        api("GET", f"/api/v1/merchant/orders/{order}", admins[other], expected=404)
        sample = {
            "name": name,
            "merchant_id": merchant,
            "store_name": draft["store_name"],
            "product_name": draft["product_name"],
            "variant": draft["variant"],
            "scenario": scenario,
            "order_id": order,
            "line_id": payment["line_id"],
            "purchase_id": own["purchase_id"],
            "amount_minor": payment["total_amount"],
            "receipt": receipts[0],
            "snapshot": snapshot,
            "live_shipment_http": status,
            "wrong_merchant_http": 404,
        }
        record["verified"] = sample
        save(state)
        published.append(sample)
        print(f"{name}: {snapshot['status']} / shipment HTTP {status}", flush=True)

    after = fingerprint(settings)
    checks = {}
    for table, before in state["baseline"].items():
        missing = Counter(before) - Counter(after[table])
        if missing:
            raise RuntimeError(
                f"existing records changed in {table}; preserve evidence for review"
            )
        checks[table] = {
            "before_rows": len(before),
            "after_rows": len(after[table]),
            "all_original_rows_unchanged": True,
            "baseline_digest": hashlib.sha256(
                "\n".join(sorted(before)).encode()
            ).hexdigest(),
        }
    PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC.write_bytes(
        (
            json.dumps(
                {
                    "synthetic": True,
                    "buyer": "buyer01",
                    "model_calls": 0,
                    "sample_count": len(published),
                    "samples": published,
                    "preservation": checks,
                    "case_witness_captured_after_purchase_preparation": state.get(
                        "case_witness_captured_after_purchase_preparation", False
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode()
    )
    print(f"prepared {len(published)} independent samples; original rows preserved")


if __name__ == "__main__":
    main()
