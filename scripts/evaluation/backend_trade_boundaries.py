"""T03/T08 ordered development probes; all business requests use the real Gateway."""

import argparse
import json
import re
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend_resume_lab import start_java_services

from evaluation.backend_lab import Settings, sha256, wait
from evaluation.backend_smoke import api, login
from evaluation.backend_trade import (
    burst,
    cart_group,
    payment_counts,
    setup_cart,
    validate_payment,
)
from evaluation.backend_trade_faults import MysqlSession, save

FIELDS = ("sku_id", "quantity", "unit_amount", "line_amount", "variant", "sku_version")


def validate_snapshot(actual, expected, total):
    normalize = lambda rows: sorted(({k: r[k] for k in FIELDS} for r in rows), key=lambda r: r["sku_id"])
    assert normalize(actual) == normalize(expected)
    assert sum(r["line_amount"] for r in actual) == total > 0


def validate_expired(state, rows):
    assert state["status"] == "CANCELLED" and state["close_reason"] == "EXPIRED"
    assert state["attempts"] == state["receipts"] == state["orders"] == 0
    assert rows and all(r["status"] == 409 for r in rows)


def validate_catalog_rejection(rows, factor, count):
    assert rows and count == 0
    expected = 404 if factor == "unlisted" else 409
    assert all(r["status"] == expected for r in rows)
    if factor == "unlisted":
        assert all(r["body"]["code"] == "NOT_FOUND" for r in rows)


def actor_pending(settings, statement):
    return int(settings.sql("SELECT COUNT(*) FROM information_schema.PROCESSLIST "
                            f"WHERE DB='commerce_db' AND STATE LIKE 'Waiting%lock%' AND INFO LIKE '{statement}%';"))


def snapshot(settings, draft):
    rows = settings.sql("SELECT JSON_OBJECT('sku_id',sku_id,'quantity',quantity,'unit_amount',unit_amount,"
                        "'line_amount',line_amount,'variant',variant,'sku_version',sku_version) "
                        f"FROM commerce_db.checkout_draft_line WHERE draft_id='{draft}' ORDER BY sku_id;")
    return [json.loads(line) for line in rows.splitlines()]


def product_write(product):
    return {**{k: product[k] for k in ("name", "description", "category", "asset_key", "listed")},
            "expected_version": product["version"],
            "skus": [{k: s[k] for k in ("sku_id", "variant", "unit_amount", "max_quantity", "listed")}
                     for s in product["skus"]]}


def expected_snapshot(product):
    return [{"sku_id": s["sku_id"], "quantity": 1, "unit_amount": s["unit_amount"],
             "line_amount": s["unit_amount"], "variant": s["variant"], "sku_version": s["version"]}
            for s in product["skus"]]


def catalog_round(settings, buyer, merchant, factor, order, concurrency, folder):
    initial = {"name": "D1 boundary " + uuid.uuid4().hex[:8], "description": "Synthetic evaluation product",
               "category": "electronics", "asset_key": "headphones", "listed": True,
               "skus": [{"variant": variant, "unit_amount": amount, "max_quantity": 10, "listed": True}
                        for variant, amount in (("first", 2000), ("second", 3000))]}
    product = api(settings, "POST", "/api/v1/merchant/products", merchant, initial, expected=201)
    group = cart_group(settings, buyer)
    for sku in product["skus"]:
        api(settings, "POST", "/api/v1/shop/cart/M-1001/items", buyer,
            {"sku_id": sku["sku_id"], "quantity": 1, "expected_revision": group["revision"],
             "expected_sku_version": sku["version"]}, {"Idempotency-Key": uuid.uuid4().hex})
        group = cart_group(settings, buyer)
    body = {"expected_revision": group["revision"], "lines": [
        {"sku_id": s["sku_id"], "quantity": 1, "expected_sku_version": s["version"]} for s in product["skus"]]}
    key = uuid.uuid4().hex
    update = product_write(product)
    if factor == "price":
        update["skus"][0]["unit_amount"] += 777
    elif factor == "variant":
        update["skus"][0]["variant"] = "updated variant"
    else:
        update["listed"] = False
    path = "/api/v1/shop/cart/M-1001/drafts"
    save(folder, "prepared", {"scenario": "T03", "factor": factor, "order": order, "concurrency": concurrency,
                             "product": product, "update": update, "draft_body": body, "draft_key": key})
    table = "checkout_draft_line" if order == "checkout-first" else "catalog_management_audit"
    with MysqlSession(settings) as gate, ThreadPoolExecutor(max_workers=3) as pool:
        gate.execute(f"LOCK TABLES {table} WRITE")
        def modify():
            return api(settings, "POST", "/api/v1/merchant/products/" + product["product_id"], merchant, update)
        def checkout(size=concurrency):
            return burst(settings, path, buyer, [(body, key) for _ in range(size)])
        first = pool.submit(checkout, 1) if order == "checkout-first" else pool.submit(modify)
        # LOCK TABLES also locks the FK parent; checkout is paused at its draft insert,
        # after catalog row locks and validation, before either snapshot can commit.
        statement = "INSERT INTO checkout_draft(" if order == "checkout-first" else "INSERT INTO catalog_management_audit("
        wait("T03 first actor before commit", lambda: actor_pending(settings, statement) > 0, seconds=15)
        save(folder, "gate", {"table": table, "first_actor_pending_statement": statement, "order": order})
        second = pool.submit(modify if order == "checkout-first" else checkout)
        # Require the second actor to reach a real InnoDB lock wait before allowing commit.
        second_statement = "SELECT store_id FROM catalog_store" if order == "checkout-first" else "SELECT k.sku_id FROM catalog_sku"
        wait("T03 second actor blocked", lambda: int(settings.sql(
            "SELECT COUNT(*) FROM performance_schema.data_lock_waits w JOIN performance_schema.threads t "
            f"ON t.THREAD_ID=w.REQUESTING_THREAD_ID WHERE t.PROCESSLIST_INFO LIKE '{second_statement}%';")) > 0, seconds=15)
        save(folder, "second-actor", {"blocked_statement": second_statement})
        rest = pool.submit(checkout, concurrency - 1) if order == "checkout-first" else None
        gate.execute("UNLOCK TABLES")
        a, b = first.result(timeout=30), second.result(timeout=30)
        if rest:
            a += [{**r, "index": r["index"] + 1} for r in rest.result(timeout=30)]
    rows, updated = (a, b) if order == "checkout-first" else (b, a)
    save(folder, "requests", rows)
    save(folder, "updated-product", updated)
    count = int(settings.sql(f"SELECT COUNT(*) FROM commerce_db.checkout_draft WHERE idempotency_key='{key}';"))
    if order == "checkout-first":
        assert all(r["status"] == 200 for r in rows) and count == 1
        drafts = {r["body"]["draft_id"] for r in rows}
        assert len(drafts) == 1
        draft = drafts.pop()
        lines = snapshot(settings, draft)
        total = int(settings.sql(f"SELECT total_amount FROM commerce_db.checkout_draft WHERE draft_id='{draft}';"))
        validate_snapshot(lines, expected_snapshot(product), total)
        save(folder, "accepted-snapshot", {"draft_id": draft, "lines": lines, "total": total})
    else:
        validate_catalog_rejection(rows, factor, count)
        if factor != "unlisted":
            fresh = {**body, "lines": [{**line, "expected_sku_version": 2} for line in body["lines"]]}
            accepted = api(settings, "POST", path, buyer, fresh, {"Idempotency-Key": uuid.uuid4().hex})
            lines = snapshot(settings, accepted["draft_id"])
            total = int(settings.sql(f"SELECT total_amount FROM commerce_db.checkout_draft WHERE draft_id='{accepted['draft_id']}';"))
            validate_snapshot(lines, expected_snapshot(updated), total)
            save(folder, "fresh-snapshot", {"draft_id": accepted["draft_id"], "lines": lines, "total": total})
    result = {"scenario": "T03", "order": order, "factor": factor, "concurrency": concurrency,
              "status": "PASSED", "original_key_drafts": count,
              "http_200": sum(r["status"] == 200 for r in rows), "http_409": sum(r["status"] == 409 for r in rows)}
    result["http_404"] = sum(r["status"] == 404 for r in rows)
    save(folder, "result", result)
    return result


def expiry_state(settings, draft):
    return json.loads(settings.sql(f"""SELECT JSON_OBJECT('status',d.status,'close_reason',d.close_reason,
      'attempts',(SELECT COUNT(*) FROM commerce_db.checkout_payment_attempt WHERE draft_id=d.draft_id),
      'receipts',(SELECT COUNT(*) FROM commerce_db.simulated_checkout_receipt r JOIN commerce_db.checkout_payment_attempt a ON r.attempt_id=a.attempt_id WHERE a.draft_id=d.draft_id),
      'orders',(SELECT COUNT(*) FROM commerce_db.orders o JOIN commerce_db.checkout_payment_attempt a ON o.order_id=a.order_id WHERE a.draft_id=d.draft_id))
      FROM commerce_db.checkout_draft d WHERE draft_id='{draft}';"""))


def expiry_round(settings, token, order, concurrency, folder):
    if order == "reserve-first":
        state = settings.load()
        settings.stop_children({"pids": {"commerce": state["pids"]["commerce"]}})
        start_java_services(settings, settings.load(), ("commerce",), checkout_poll_ms=10000)
        save(folder, "scheduler-config", {"checkout_poll_ms": 10000, "purpose": "initial preparation window", "frozen_jar": True})
    body = setup_cart(settings, token)
    draft_key, pay_key = uuid.uuid4().hex, uuid.uuid4().hex
    save(folder, "prepared", {"scenario": "T08", "order": order, "concurrency": concurrency,
                             "draft_key": draft_key, "pay_key": pay_key, "draft_body": body})
    draft = api(settings, "POST", "/api/v1/shop/cart/M-1001/drafts", token, body, {"Idempotency-Key": draft_key})["draft_id"]
    path = f"/api/v1/shop/drafts/{draft}/payment"
    save(folder, "draft", {"draft_id": draft})
    with MysqlSession(settings) as gate, ThreadPoolExecutor(max_workers=2) as pool:
        if order == "expiry-first":
            # Only the synthetic deadline changes. Status is closed by the actual Java scheduler.
            gate.execute("START TRANSACTION; "
                         f"UPDATE checkout_draft SET expires_at=created_at+INTERVAL 1 MICROSECOND WHERE draft_id='{draft}'; "
                         f"COMMIT; START TRANSACTION; SELECT draft_id FROM checkout_draft WHERE draft_id='{draft}' FOR UPDATE")
            assert expiry_state(settings, draft)["status"] == "WAITING_PAYMENT", "expiry window not reached"
            closer = """SELECT COUNT(*) FROM performance_schema.data_lock_waits w
              JOIN performance_schema.threads t ON t.THREAD_ID=w.REQUESTING_THREAD_ID
              WHERE t.PROCESSLIST_INFO LIKE 'UPDATE checkout_draft SET status=%EXPIRED%';"""
            wait("actual expiry scheduler queued", lambda: int(settings.sql(closer)) > 0, seconds=15)
            save(folder, "gate", {"actual_expiry_scheduler_waiting_before_payment": True})
            pending = pool.submit(burst, settings, path, token, [({}, pay_key) for _ in range(concurrency)])
            wait("expiry and payment queued", lambda: int(settings.sql(
                "SELECT COUNT(*) FROM performance_schema.data_lock_waits;")) >= 2, seconds=15)
            gate.execute("COMMIT")
            rows = pending.result(timeout=30)
        else:
            gate.execute("LOCK TABLES simulated_checkout_receipt WRITE")
            pending = pool.submit(burst, settings, path, token, [({}, pay_key)])
            wait("reserved payment", lambda: settings.sql(
                f"SELECT COUNT(*) FROM commerce_db.checkout_payment_attempt WHERE draft_id='{draft}';") == "1", seconds=15)
            # The lab scheduler initial delay leaves time to reserve and expire the target.
            before_count = int(settings.sql("START TRANSACTION; SELECT reconcile_count FROM commerce_db.checkout_payment_attempt "
                f"WHERE draft_id='{draft}' FOR UPDATE; UPDATE commerce_db.checkout_draft "
                f"SET expires_at=created_at+INTERVAL 1 MICROSECOND WHERE draft_id='{draft}'; COMMIT;"))
            assert before_count == 0, "scheduler claimed before expiry fixture; intended window not reached"
            wait("scheduler reached original attempt", lambda: int(settings.sql(
                f"SELECT reconcile_count FROM commerce_db.checkout_payment_attempt WHERE draft_id='{draft}';")) > 0, seconds=15)
            before = json.loads(settings.sql(f"SELECT JSON_OBJECT('status',status,'expired',expires_at<UTC_TIMESTAMP(6)) FROM commerce_db.checkout_draft WHERE draft_id='{draft}';"))
            assert before == {"status": "PAYMENT_PENDING", "expired": 1}
            save(folder, "gate", {**before, "actual_scheduler_claimed_original_attempt": True,
                                  "reconcile_count_before_expiry": before_count})
            # Establish the reservation/expiry window before filling the JDBC pool with
            # intentionally paused provider calls. Together these are C payment requests.
            rest = pool.submit(burst, settings, path, token, [({}, pay_key) for _ in range(concurrency - 1)])
            wait("remaining payment actor reached provider", lambda: actor_pending(
                settings, "INSERT INTO simulated_checkout_receipt") >= 2, seconds=10)
            gate.execute("UNLOCK TABLES")
            rows = pending.result(timeout=30) + [{**r, "index": r["index"] + 1} for r in rest.result(timeout=30)]
    save(folder, "requests", rows)
    state = expiry_state(settings, draft)
    if order == "expiry-first":
        validate_expired(state, rows)
        counts = state
    else:
        payment = api(settings, "GET", path, token)["payment"]
        counts = payment_counts(settings, draft)
        validate_payment(rows, payment["attempt_id"], counts, 2)
        assert state["status"] == "PAID" and state["close_reason"] is None
    result = {"scenario": "T08", "order": order, "concurrency": concurrency, "status": "PASSED",
              "draft_id": draft, "final_state": state, "counts": counts,
              "http_200": sum(r["status"] == 200 for r in rows), "http_409": sum(r["status"] == 409 for r in rows)}
    save(folder, "result", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--probe-id", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--only", choices=("both", "catalog", "expiry"), default="both")
    parser.add_argument("--expiry-order", choices=("both", "expiry-first", "reserve-first"), default="both")
    parser.add_argument("--catalog-factor", choices=("all", "price", "variant", "unlisted"), default="all")
    parser.add_argument("--concurrency", type=int, choices=(10, 30))
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", args.probe_id):
        raise ValueError("invalid probe identifier")
    settings = Settings(args.run_id)
    with settings.operation_lock():
        settings.freeze()
        output = settings.report / "trade-boundaries" / args.probe_id
        output.mkdir(parents=True, exist_ok=args.resume)
        originals = {str(p.relative_to(output)): sha256(p) for p in output.rglob("*.json")}
        if args.resume and not originals:
            raise ValueError("resume requires original records")
        save(output, "resume-inputs" if args.resume else "inputs", originals)
        save(output, "sources-resumed" if args.resume else "sources", {str(p.relative_to(settings.root)): sha256(p) for p in
                                 (Path(__file__), Path(__file__).with_name("backend_trade_faults.py"))})
        with (output / ("runner-resumed.py" if args.resume else "runner-at-execution.py")).open("xb") as file:
            file.write(Path(__file__).read_bytes())
        buyer = login(settings, "demo-buyer", "demo-pass-4001")
        merchant = login(settings, "demo-admin", "demo-pass-1100")
        rows = []
        concurrencies = (args.concurrency,) if args.concurrency else (10, 30)
        factors = ("price", "variant", "unlisted") if args.catalog_factor == "all" else (args.catalog_factor,)
        try:
            for factor in (() if args.only == "expiry" else factors):
                for order in ("checkout-first", "update-first"):
                    for concurrency in concurrencies:
                        folder = output / f"T03-{factor}-{order}-c{concurrency}"
                        folder.mkdir(exist_ok=args.resume)
                        if (folder / "result.json").exists():
                            rows.append(json.loads((folder / "result.json").read_text()))
                        elif (folder / "requests.json").exists():
                            # The only supported interrupted validation is the observed unlisted-404 contract.
                            assert args.resume and factor == "unlisted" and order == "update-first"
                            prepared = json.loads((folder / "prepared.json").read_text())
                            responses = json.loads((folder / "requests.json").read_text())
                            key = prepared["draft_key"]
                            count = int(settings.sql(f"SELECT COUNT(*) FROM commerce_db.checkout_draft WHERE idempotency_key='{key}';"))
                            validate_catalog_rejection(responses, factor, count)
                            result = {"scenario": "T03", "order": order, "factor": factor, "concurrency": concurrency,
                                      "status": "PASSED", "original_key_drafts": count, "http_404": len(responses),
                                      "http_200": 0, "http_409": 0, "resumed_read_only_validation": True}
                            save(folder, "result", result)
                            rows.append(result)
                        else:
                            if (folder / "prepared.json").exists():
                                raise ValueError("incomplete burst requires manual original-key inspection; no resend")
                            rows.append(catalog_round(settings, buyer, merchant, factor, order, concurrency, folder))
                        print(folder.name + " passed", flush=True)
            expiry_orders = ("expiry-first", "reserve-first") if args.expiry_order == "both" else (args.expiry_order,)
            for order in (() if args.only == "catalog" else expiry_orders):
                for concurrency in concurrencies:
                    folder = output / f"T08-{order}-c{concurrency}"
                    folder.mkdir(exist_ok=args.resume)
                    if (folder / "result.json").exists():
                        rows.append(json.loads((folder / "result.json").read_text()))
                    else:
                        if (folder / "prepared.json").exists():
                            raise ValueError("incomplete expiry burst requires inspection; no resend")
                        rows.append(expiry_round(settings, buyer, order, concurrency, folder))
                    print(folder.name + " passed", flush=True)
        finally:
            for relative, digest in originals.items():
                assert sha256(output / relative) == digest, relative
            save(output, "summary-resumed" if args.resume else "summary", {"run_id": settings.identity, "phase": "development, not formal matrix",
                                    "completed_rounds": len(rows), "planned_rounds": (0 if args.only == "expiry" else len(factors) * 2 * len(concurrencies))
                                    + (0 if args.only == "catalog" else len(expiry_orders) * len(concurrencies)), "rows": rows})


if __name__ == "__main__":
    main()
