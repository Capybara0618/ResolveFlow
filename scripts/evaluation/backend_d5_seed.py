"""Deterministic synthetic read-model dataset for a new, explicitly owned D5 lab."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import uuid
from collections import defaultdict
from pathlib import Path

from evaluation.backend_lab import Settings, sha256
from evaluation.trade_request_journal import durable

STORES = ("M-1001", "M-1002", "M-1003")
CREATED = "2026-10-20 00:00:00.000000"
EXPIRES = "2027-01-01 00:00:00.000000"  # Waiting read fixtures stay stable throughout the timed experiment.


def literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def insert(table, columns, rows):
    if not re.fullmatch(r"[a-z_.]+", table) or any(
        not re.fullmatch(r"[a-z_]+", c) for c in columns
    ):
        raise ValueError("non-constant SQL identifier")
    for start in range(0, len(rows), 500):
        block = rows[start : start + 500]
        yield (
            "INSERT INTO "
            + table
            + "("
            + ",".join(columns)
            + ") VALUES "
            + ",".join("(" + ",".join(literal(v) for v in row) + ")" for row in block)
            + ";"
        )


def generate(settings):
    if (settings.folder / "dataset-started.json").exists():
        raise ValueError(
            "dataset already started; inspect original data, never refill blindly"
        )
    settings.assert_owned("mysql")
    assert (
        settings.sql(
            "SELECT COUNT(*) FROM case_db.aftersale_case WHERE customer_id LIKE 'D5-%';"
        )
        == "0"
    )
    assert (
        settings.sql(
            "SELECT COUNT(*) FROM commerce_db.orders WHERE customer_id LIKE 'D5-%';"
        )
        == "0"
    )
    durable(
        settings.folder / "dataset-started.json",
        {"seed": 42, "generator_sha256": sha256(Path(__file__))},
    )
    namespace = uuid.UUID(settings.identity)

    def identity(label):
        return str(uuid.uuid5(namespace, label))

    randomizer = random.Random(42)
    sql = ["SET time_zone='+00:00';", "SET NAMES utf8mb4;"]
    tables = defaultdict(list)

    def add(table, columns, row):
        tables[(table, tuple(columns.split(",")))].append(row)

    sql += [
        "INSERT INTO commerce_db.catalog_store(store_id,name,description) VALUES('M-1003','D5 outdoor','synthetic D5 store');",
        "INSERT INTO case_db.identity_merchant(merchant_id,display_name) VALUES('M-1003','D5 outdoor');",
    ]
    for i, store in enumerate(STORES):
        sql.append(
            "INSERT INTO case_db.identity_account(username,merchant_id,role,display_name,password_hash) SELECT "
            + literal("d5-merchant-" + str(i))
            + ","
            + literal(store)
            + ",'MERCHANT_ADMIN','D5 synthetic staff',password_hash FROM case_db.identity_account WHERE username='demo-buyer';"
        )
    for i in range(100):
        buyer = f"D5-B{i:03d}"
        add("case_db.platform_buyer", "buyer_id", (buyer,))
        for store in STORES:
            add(
                "case_db.buyer_customer_binding",
                "buyer_id,merchant_id,customer_id",
                (buyer, store, f"D5-C{i:03d}-{store}"),
            )
    # Foreign keys require buyers before their bindings/accounts.
    for key in list(tables):
        if key[0] == "case_db.platform_buyer":
            sql.extend(insert(*key, tables.pop(key)))
    for i in range(100):
        sql.append(
            "INSERT INTO case_db.identity_account(username,role,buyer_id,display_name,password_hash) SELECT "
            + literal(f"d5-buyer-{i:03d}")
            + ",'CUSTOMER',"
            + literal(f"D5-B{i:03d}")
            + ",'D5 synthetic buyer',password_hash FROM case_db.identity_account WHERE username='demo-buyer';"
        )
    catalog = [
        json.loads(row)
        for row in settings.sql(
            "SELECT JSON_OBJECT('id',product_id,'store',store_id,'name',name,'asset',asset_key,'category',category) FROM commerce_db.catalog_product ORDER BY product_id;"
        ).splitlines()
    ]
    assert len(catalog) == 6, (
        "new lab must still have exactly the original migration catalog"
    )
    for i in range(24):
        store = STORES[i % 3]
        product = {
            "id": f"P-D5-{i:02d}",
            "store": store,
            "name": f"synthetic-product-{i:02d}",
            "asset": "headphones",
            "category": "electronics",
        }
        catalog.append(product)
        add(
            "commerce_db.catalog_product",
            "product_id,store_id,name,description,category,asset_key",
            (
                product["id"],
                store,
                product["name"],
                "D5 read fixture",
                product["category"],
                product["asset"],
            ),
        )
        add(
            "commerce_db.catalog_sku",
            "sku_id,product_id,variant,unit_amount,max_quantity",
            ("SKU-D5-" + str(i), product["id"], "primary", 1000 + 100 * i, 10),
        )
    for i, product in enumerate(catalog[1:15]):
        add(
            "commerce_db.catalog_sku",
            "sku_id,product_id,variant,unit_amount,max_quantity",
            (f"SKU-D5-EXTRA-{i:02d}", product["id"], "secondary", 1500 + i * 100, 10),
        )
    # Commit catalog in FK order before querying the authoritative price/snapshot fixture.
    for table in ("commerce_db.catalog_product", "commerce_db.catalog_sku"):
        for key in list(tables):
            if key[0] == table:
                sql.extend(insert(*key, tables.pop(key)))
    first_sql = "\n".join(sql)
    with (settings.folder / "dataset-catalog.sql").open("xb") as output:
        output.write(first_sql.encode())
    settings.sql(first_sql)
    sql = []
    skus = [
        json.loads(row)
        for row in settings.sql(
            "SELECT JSON_OBJECT('id',k.sku_id,'product',p.product_id,'store',p.store_id,'name',p.name,'variant',k.variant,'asset',p.asset_key,'category',p.category,'price',k.unit_amount) FROM commerce_db.catalog_sku k JOIN commerce_db.catalog_product p ON p.product_id=k.product_id ORDER BY k.sku_id;"
        ).splitlines()
    ]
    assert len(catalog) == 30 and len(skus) == 45
    by_store = {store: [s for s in skus if s["store"] == store] for store in STORES}
    eligible, purchases, case_links = defaultdict(list), [], {}

    def cart(index, store):
        choices = by_store[store]
        count = 1 + index % 3
        values = []
        for j in range(count):
            sku = choices[(index + j) % len(choices)]
            quantity = 1 + (index + j) % 2
            values.append(
                {
                    **sku,
                    "quantity": quantity,
                    "amount": sku["price"] * quantity,
                    "line": "D5-L-" + identity(f"line-{index}-{j}"),
                }
            )
        return sorted(values, key=lambda s: s["id"])

    def draft(index, store, customer, lines, status, order=None, close=None):
        did = identity(f"draft-{index}")
        first, multi = lines[0], len(lines) > 1
        total = sum(s["amount"] for s in lines)
        add(
            "commerce_db.checkout_draft",
            "draft_id,merchant_id,customer_id,idempotency_key,product_id,product_name,store_name,asset_key,sku_id,variant,quantity,unit_amount,total_amount,sku_version,created_at,expires_at,category,status,order_id,line_id,paid_at,kind,line_count,cart_revision,multiline_request_hash,close_reason",
            (
                did,
                store,
                customer,
                f"D5-{index}",
                first["product"],
                first["name"],
                "D5 " + store,
                first["asset"],
                first["id"],
                first["variant"],
                first["quantity"],
                first["price"],
                total,
                1,
                CREATED,
                EXPIRES,
                first["category"],
                status,
                order,
                first["line"] if order else None,
                CREATED if order else None,
                "MULTI" if multi else "SINGLE",
                len(lines),
                0 if multi else None,
                hashlib.sha256(str(index).encode()).hexdigest() if multi else None,
                close,
            ),
        )
        if multi:
            for s in lines:
                add(
                    "commerce_db.checkout_draft_line",
                    "draft_id,sku_id,product_id,product_name,variant,asset_key,category,quantity,unit_amount,line_amount,sku_version",
                    (
                        did,
                        s["id"],
                        s["product"],
                        s["name"],
                        s["variant"],
                        s["asset"],
                        s["category"],
                        s["quantity"],
                        s["price"],
                        s["amount"],
                        1,
                    ),
                )
        payment = None
        if status in ("PAID", "PAYMENT_PENDING"):
            aid = identity(f"attempt-{index}")
            planned = order or identity(f"unpublished-{index}")
            payment = {
                "attempt": aid,
                "state": "SUCCEEDED" if order else "UNKNOWN",
                "order": planned,
                "line": first["line"],
            }
            add(
                "commerce_db.checkout_payment_attempt",
                "attempt_id,draft_id,sequence_no,idempotency_key,total_amount,currency,status,order_id,line_id,created_at,finished_at,paid_at",
                (
                    aid,
                    did,
                    1,
                    "D5-pay",
                    total,
                    "CNY",
                    payment["state"],
                    planned,
                    first["line"],
                    CREATED,
                    CREATED if order else None,
                    CREATED if order else None,
                ),
            )
            if multi:
                for s in lines:
                    add(
                        "commerce_db.checkout_payment_line",
                        "attempt_id,sku_id,line_id",
                        (aid, s["id"], s["line"]),
                    )
            if order:
                add(
                    "commerce_db.simulated_checkout_receipt",
                    "attempt_id,total_amount,status,finished_at",
                    (aid, total, "SUCCEEDED", CREATED),
                )
        return did, payment

    for i in range(10000):
        buyer = i % 100
        store = STORES[(i // 100) % 3]
        customer = f"D5-C{buyer:03d}-{store}"
        order = identity(f"order-{i}")
        lines = cart(i, store)
        total = sum(s["amount"] for s in lines)
        refunded = reserved = 0
        state = "FREE"
        case_id = identity(f"case-{4000 + i}")
        if store != "M-1003" and i % 4 in (0, 1):
            state = "RESERVED" if i % 4 == 0 else "CONSUMED"
            reserved = lines[0]["amount"] if state == "RESERVED" else 0
            refunded = lines[0]["amount"] if state == "CONSUMED" else 0
            case_links[4000 + i] = (
                store,
                customer,
                order,
                lines[0]["line"],
                "EXECUTING" if state == "RESERVED" else "CLOSED_SUCCESS",
            )
        add(
            "commerce_db.orders",
            "order_id,merchant_id,customer_id,order_status,currency,paid_at,created_at",
            (order, store, customer, "PAID", "CNY", CREATED, CREATED),
        )
        add(
            "commerce_db.payment_ledger",
            "order_id,paid_amount,refunded_amount,reserved_refund_amount,version",
            (order, total, refunded, reserved, 1),
        )
        for j, s in enumerate(lines):
            add(
                "commerce_db.order_line",
                "line_id,order_id,merchant_id,customer_id,sku,category,quantity,line_paid_amount,currency,paid_at,order_status,version,product_name,variant_text",
                (
                    s["line"],
                    order,
                    store,
                    customer,
                    s["id"],
                    s["category"],
                    s["quantity"],
                    s["amount"],
                    "CNY",
                    CREATED,
                    "PAID",
                    1,
                    s["name"],
                    s["variant"],
                ),
            )
            current = state if j == 0 else "FREE"
            op = identity(f"refund-{i}") if current != "FREE" else None
            add(
                "commerce_db.line_refund",
                "line_id,state,operation_id,version,updated_at",
                (s["line"], current, op, 1, CREATED),
            )
            add(
                "commerce_db.shipment",
                "line_id,status,carrier_conclusion,source_version",
                (s["line"], "DELIVERED", "DELIVERED", 2),
            )
            add(
                "commerce_db.shipment_event",
                "line_id,code,occurred_at,source_version",
                (s["line"], "ORDER_PAID", CREATED, 1),
            )
            add(
                "commerce_db.shipment_event",
                "line_id,code,occurred_at,source_version",
                (s["line"], "DELIVERED", "2026-10-21 00:00:00.000000", 2),
            )
            eligible[s["product"]].append((s, customer))
            if op:
                add(
                    "commerce_db.refund_operation",
                    "operation_id,authorization_id,case_id,input_revision,merchant_id,line_id,action,quantity,currency,amount_minor,payload_hash,policy_version,state,provider_key,provider_ref,reserved_at,settled_at,version",
                    (
                        op,
                        identity(f"authorization-{i}"),
                        case_id,
                        1,
                        store,
                        s["line"],
                        "REFUND",
                        s["quantity"],
                        "CNY",
                        s["amount"],
                        "a" * 64,
                        "D5-synthetic",
                        "UNKNOWN" if current == "RESERVED" else "SUCCEEDED",
                        op,
                        None if current == "RESERVED" else "D5-synthetic-receipt",
                        CREATED,
                        None if current == "RESERVED" else CREATED,
                        1,
                    ),
                )
        did, payment = (
            draft(i, store, customer, lines, "PAID", order)
            if i < 5000
            else (None, None)
        )
        purchases.append(
            {
                "id": ("draft:" + did) if did else ("order:" + order),
                "buyer": buyer,
                "store": store,
                "status": "PAID",
                "total": total,
                "lines": lines,
                "order": order,
                "draft": did,
                "payment": payment,
                "refunded": refunded,
                "reserved": reserved,
            }
        )
    for i in range(10000, 12000):
        buyer = i % 100
        store = STORES[(i // 100) % 3]
        customer = f"D5-C{buyer:03d}-{store}"
        lines = cart(i, store)
        state = ("WAITING_PAYMENT", "PAYMENT_PENDING", "CANCELLED", "CANCELLED")[i % 4]
        close = "EXPIRED" if i % 4 == 3 else None
        did, payment = draft(i, store, customer, lines, state, close=close)
        purchases.append(
            {
                "id": "draft:" + did,
                "buyer": buyer,
                "store": store,
                "status": "EXPIRED" if close else state,
                "total": sum(s["amount"] for s in lines),
                "lines": lines,
                "order": None,
                "draft": did,
                "payment": payment,
                "refunded": 0,
                "reserved": 0,
            }
        )
    for product in catalog:
        available = eligible[product["id"]]
        if len(available) < 200:
            raise ValueError(
                "not enough independent paid lines for 200 reviews: " + product["id"]
            )
        randomizer.shuffle(available)
        for j, (line, customer) in enumerate(available[:200]):
            add(
                "commerce_db.product_review",
                "line_id,product_id,product_name,merchant_id,customer_id,variant,rating,body,version,created_at,updated_at",
                (
                    line["line"],
                    product["id"],
                    line["name"],
                    product["store"],
                    customer,
                    line["variant"],
                    j % 5 + 1,
                    f"D5 synthetic review {j:03d}",
                    1,
                    CREATED,
                    CREATED,
                ),
            )
        add(
            "commerce_db.product_review_epoch", "product_id,version", (product["id"], 1)
        )
    for i in range(20000):
        store = STORES[i % 2]
        status = (
            "PENDING_REVIEW"
            if i < 4000
            else ("WAITING_CUSTOMER", "EXECUTING", "RECONCILING", "CLOSED_SUCCESS")[
                i % 4
            ]
        )
        customer, order, line = (
            f"D5-C{i % 100:03d}-{store}",
            identity(f"case-only-order-{i}"),
            f"D5-CASE-L{i:05d}",
        )
        if i in case_links:
            store, customer, order, line, status = case_links[i]
        case = identity(f"case-{i}")
        updated = f"2026-10-25 00:{i % 60:02d}:{(i // 60) % 60:02d}.000000"
        add(
            "case_db.aftersale_case",
            "case_id,merchant_id,customer_id,order_id,line_id,description,status,input_revision,version,created_at,updated_at",
            (
                case,
                store,
                customer,
                order,
                line,
                f"D5 synthetic work item {i:05d}",
                status,
                1,
                1,
                CREATED,
                updated,
            ),
        )
        add("case_db.case_requested_action", "case_id,action", (case, "REFUND"))
        if i % 3:
            add(
                "case_db.case_collaboration",
                "case_id,owner_username,version,updated_at",
                (case, "d5-merchant-" + str(STORES.index(store)), 1, updated),
            )
    order = [
        "commerce_db.orders",
        "commerce_db.payment_ledger",
        "commerce_db.order_line",
        "commerce_db.line_refund",
        "commerce_db.shipment",
        "commerce_db.shipment_event",
        "commerce_db.refund_operation",
        "commerce_db.checkout_draft",
        "commerce_db.checkout_draft_line",
        "commerce_db.checkout_payment_attempt",
        "commerce_db.checkout_payment_line",
        "commerce_db.simulated_checkout_receipt",
        "commerce_db.product_review",
        "commerce_db.product_review_epoch",
        "case_db.buyer_customer_binding",
        "case_db.aftersale_case",
        "case_db.case_requested_action",
        "case_db.case_collaboration",
    ]
    for table in order:
        for key in list(tables):
            if key[0] == table:
                sql.extend(insert(*key, tables.pop(key)))
    assert not tables
    text = "SET time_zone='+00:00';\n" + "\n".join(sql)
    with (settings.folder / "dataset.sql").open("xb") as output:
        output.write((first_sql + "\n" + text).encode())
    # Every statement keeps foreign-key and CHECK validation enabled; no cleanup or truncate.
    settings.sql(text)
    durable(
        settings.folder / "dataset-oracle.json",
        {
            "run_id": settings.identity,
            "seed": 42,
            "purchases": purchases,
            "products": catalog,
            "boundary": "synthetic read model, not genuine user orders/provider execution; waiting expiry intentionally outside all measurement windows",
        },
    )
    checks = {}
    for name, query, expected in [
        (
            "cases",
            "SELECT COUNT(*) FROM case_db.aftersale_case WHERE customer_id LIKE 'D5-%'",
            20000,
        ),
        (
            "pending_review",
            "SELECT COUNT(*) FROM case_db.aftersale_case WHERE description LIKE 'D5 synthetic%' AND status='PENDING_REVIEW'",
            4000,
        ),
        (
            "orders",
            "SELECT COUNT(*) FROM commerce_db.orders WHERE customer_id LIKE 'D5-%'",
            10000,
        ),
        (
            "unpaid_drafts",
            "SELECT COUNT(*) FROM commerce_db.checkout_draft WHERE customer_id LIKE 'D5-%' AND status<>'PAID'",
            2000,
        ),
        (
            "reviews",
            "SELECT COUNT(*) FROM commerce_db.product_review WHERE customer_id LIKE 'D5-%'",
            6000,
        ),
        ("products", "SELECT COUNT(*) FROM commerce_db.catalog_product", 30),
        ("skus", "SELECT COUNT(*) FROM commerce_db.catalog_sku", 45),
        (
            "bad_amounts",
            "SELECT COUNT(*) FROM commerce_db.payment_ledger p JOIN (SELECT order_id,SUM(line_paid_amount) amount FROM commerce_db.order_line WHERE customer_id LIKE 'D5-%' GROUP BY order_id) l ON l.order_id=p.order_id WHERE l.amount<>p.paid_amount OR p.refunded_amount+p.reserved_refund_amount>p.paid_amount",
            0,
        ),
        (
            "bad_review_eligibility",
            "SELECT COUNT(*) FROM commerce_db.product_review r JOIN commerce_db.shipment s ON s.line_id=r.line_id WHERE r.customer_id LIKE 'D5-%' AND s.status<>'DELIVERED'",
            0,
        ),
    ]:
        actual = int(settings.sql(query + ";"))
        checks[name] = {"actual": actual, "expected": expected}
        if actual != expected:
            raise ValueError("dataset check failed: " + name)
    durable(
        settings.folder / "dataset-checked.json",
        {
            "checks": checks,
            "generator_sha256": sha256(Path(__file__)),
            "sql_sha256": sha256(settings.folder / "dataset.sql"),
            "oracle_sha256": sha256(settings.folder / "dataset-oracle.json"),
            "model_requests": 0,
        },
    )
    print(json.dumps(checks))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    settings = Settings(args.run_id)
    with settings.operation_lock():
        generate(settings)


if __name__ == "__main__":
    main()
