"""D1 development probes for T01/T02/T04/T05 over the owned real HTTP chain.

This is not the formal eight-scenario matrix. Every probe directory is append-only.
"""

import argparse
import hashlib
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.backend_lab import Settings, sha256
from evaluation.backend_smoke import api, login


def classify(status):
    return "success" if status == 200 else "conflict" if status == 409 else "unexpected"


def validate_cart(rows, before, after, quantity):
    winners = [r for r in rows if r["status"] == 200]
    assert len(winners) == 1 and all(r["status"] in (200, 409) for r in rows)
    assert after == before + 1 and quantity == winners[0]["quantity"]


def validate_checkout(rows, database_count):
    winners = [r["body"]["draft_id"] for r in rows if r["status"] == 200]
    assert winners and len(set(winners)) == 1
    assert all(r["status"] in (200, 409) for r in rows) and database_count == 1
    return winners[0]


def bound_payload(rows, inputs):
    winner = next(r for r in rows if r["status"] == 200)
    winning = inputs[winner["index"]][0]
    losing = next(body for body, _ in inputs if body != winning)
    assert all(r["status"] == (200 if inputs[r["index"]][0] == winning else 409) for r in rows)
    return winning, losing


def validate_payment(rows, attempt, counts, expected_lines):
    assert any(r["status"] == 200 for r in rows)
    assert all(r["status"] in (200, 409) for r in rows)
    assert all(r["body"]["attempt_id"] == attempt for r in rows if r["status"] == 200)
    assert counts["attempts"] == counts["receipts"] == counts["orders"] == 1
    assert counts["lines"] == counts["slots"] == expected_lines
    assert counts["paid"] == counts["draft_total"] == counts["line_total"] == counts["receipt_total"] > 0
    assert counts["reserved"] == counts["refunded"] == 0


def burst(settings, path, token, inputs):
    port = settings.load()["ports"]["gateway"]
    gate = threading.Barrier(len(inputs))
    journal = getattr(settings, "request_journal", None)
    tickets = journal.prepare(path, journal.actor(token), inputs) if journal else None

    def one(index, payload):
        body, key = payload
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "Idempotency-Key": key})
        gate.wait(timeout=10)
        started = time.monotonic()
        if journal:
            journal.start(tickets[index])
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status, value = response.status, json.load(response)
        except urllib.error.HTTPError as response:
            status, value = response.code, json.loads(response.read())
        except OSError as error:
            status, value = 0, {"transport_error": type(error).__name__}
        row = {"index": index, "status": status, "classification": classify(status), "body": value,
                "quantity": body.get("quantity"), "elapsed_ms": (time.monotonic() - started) * 1000,
                "started_monotonic": started, "request_sha256": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()}
        return journal.finish(tickets[index], row) if journal else row

    factory = getattr(settings, "burst_gate", None)
    with (factory(path) if factory else nullcontext(None)) as release, ThreadPoolExecutor(max_workers=len(inputs)) as pool:
        futures = [pool.submit(one, i, payload) for i, payload in enumerate(inputs)]
        if release:
            journal.wait_active(path, len(inputs))
            release()
        return [future.result(timeout=40) for future in futures]


def cart_group(settings, token):
    return next(g for g in api(settings, "GET", "/api/v1/shop/cart", token)["stores"] if g["store_id"] == "M-1001")


def setup_cart(settings, token):
    group = cart_group(settings, token)
    for sku in ("SKU-1001-BLACK", "SKU-1002-WHITE"):
        api(settings, "POST", "/api/v1/shop/cart/M-1001/items", token,
            {"sku_id": sku, "quantity": 1, "expected_revision": group["revision"], "expected_sku_version": 1},
            {"Idempotency-Key": uuid.uuid4().hex})
        group = cart_group(settings, token)
    return {"expected_revision": group["revision"], "lines": [
        {"sku_id": sku, "quantity": 1, "expected_sku_version": 1} for sku in ("SKU-1001-BLACK", "SKU-1002-WHITE")]}


def payment_counts(settings, draft):
    attempts = f"SELECT attempt_id FROM commerce_db.checkout_payment_attempt WHERE draft_id='{draft}'"
    orders = f"SELECT order_id FROM commerce_db.checkout_payment_attempt WHERE draft_id='{draft}'"
    return json.loads(settings.sql(f"""SELECT JSON_OBJECT(
      'attempts',(SELECT COUNT(*) FROM commerce_db.checkout_payment_attempt WHERE draft_id='{draft}'),
      'receipts',(SELECT COUNT(*) FROM commerce_db.simulated_checkout_receipt WHERE attempt_id IN ({attempts})),
      'orders',(SELECT COUNT(*) FROM commerce_db.orders WHERE order_id IN ({orders})),
      'lines',(SELECT COUNT(*) FROM commerce_db.order_line WHERE order_id IN ({orders})),
      'slots',(SELECT COUNT(*) FROM commerce_db.line_refund r JOIN commerce_db.order_line l ON l.line_id=r.line_id WHERE l.order_id IN ({orders})),
      'paid',(SELECT SUM(paid_amount) FROM commerce_db.payment_ledger WHERE order_id IN ({orders})),
      'draft_total',(SELECT total_amount FROM commerce_db.checkout_draft WHERE draft_id='{draft}'),
      'line_total',(SELECT SUM(line_paid_amount) FROM commerce_db.order_line WHERE order_id IN ({orders})),
      'receipt_total',(SELECT SUM(total_amount) FROM commerce_db.simulated_checkout_receipt WHERE attempt_id IN ({attempts})),
      'reserved',(SELECT SUM(reserved_refund_amount) FROM commerce_db.payment_ledger WHERE order_id IN ({orders})),
      'refunded',(SELECT SUM(refunded_amount) FROM commerce_db.payment_ledger WHERE order_id IN ({orders})))"""))


def prepare_round(settings, token, scenario, concurrency, folder):
    inputs = []
    key = uuid.uuid4().hex
    row = {"scenario": scenario, "concurrency": concurrency, "phase": "D1 development probe", "status": "STARTED"}
    if scenario == "T01":
        group = cart_group(settings, token)
        path = "/api/v1/shop/cart/M-1001/items"
        inputs = [({"sku_id": "SKU-1001-BLACK", "quantity": i % 5 + 1,
                    "expected_revision": group["revision"], "expected_sku_version": 1}, uuid.uuid4().hex)
                  for i in range(concurrency)]
        row["before_revision"] = group["revision"]
    else:
        body = setup_cart(settings, token)
        if scenario == "T02":
            path = "/api/v1/shop/cart/M-1001/drafts"
            # Both payloads are valid against the same original cart. Quantity changes
            # would otherwise be rejected independently of idempotency binding.
            changed = {**body, "lines": body["lines"][:1]}
            inputs = [(body if i < concurrency // 2 else changed, key) for i in range(concurrency)]
        else:
            purchase = api(settings, "POST", "/api/v1/shop/cart/M-1001/drafts", token, body, {"Idempotency-Key": key})
            row["draft_id"] = purchase["draft_id"]
            path = f"/api/v1/shop/drafts/{purchase['draft_id']}/payment"
            pay_key = uuid.uuid4().hex
            inputs = [({}, pay_key if scenario == "T04" else uuid.uuid4().hex) for _ in range(concurrency)]
    row.update(path=path, input_sha256=hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest())
    (folder / "prepared.json").write_bytes((json.dumps({"round": row, "inputs": inputs}, indent=2) + "\n").encode())
    return row, inputs


def round_probe(settings, token, scenario, concurrency, folder):
    if (folder / "prepared.json").exists():
        saved = json.loads((folder / "prepared.json").read_text())
        row, inputs = saved["round"], saved["inputs"]
    else:
        row, inputs = prepare_round(settings, token, scenario, concurrency, folder)
    assert row["scenario"] == scenario and row["concurrency"] == concurrency
    if (folder / "requests.json").exists():
        rows = json.loads((folder / "requests.json").read_text())
    else:
        marker = folder / "burst-started.json"
        if marker.exists():
            raise ValueError("unknown partial burst: inspect original keys; never resend blindly")
        marker.write_bytes(b'{"started":true}\n')
        rows = burst(settings, row["path"], token, inputs)
        (folder / "requests.json").write_bytes((json.dumps(rows, indent=2) + "\n").encode())
    try:
        if scenario == "T01":
            group = cart_group(settings, token)
            quantity = next(i["quantity"] for i in group["items"] if i["sku_id"] == "SKU-1001-BLACK")
            row.update(after_revision=group["revision"], saved_quantity=quantity)
            validate_cart(rows, row["before_revision"], group["revision"], quantity)
        elif scenario == "T02":
            key = inputs[0][1]
            count = int(settings.sql(f"SELECT COUNT(*) FROM commerce_db.checkout_draft WHERE idempotency_key='{key}';"))
            row["draft_id"] = validate_checkout(rows, count)
            row["drafts_for_key"] = count
            winning, losing = bound_payload(rows, inputs)
            actual = settings.sql("SELECT CONCAT(sku_id,':',quantity) FROM commerce_db.checkout_draft_line "
                                  f"WHERE draft_id='{row['draft_id']}' ORDER BY sku_id;").splitlines()
            assert actual == sorted(f"{line['sku_id']}:{line['quantity']}" for line in winning["lines"])
            row["bound_body"] = winning
            replay = api(settings, "POST", "/api/v1/shop/cart/M-1001/drafts", token, winning, {"Idempotency-Key": key})
            assert replay["draft_id"] == row["draft_id"]
            api(settings, "POST", "/api/v1/shop/cart/M-1001/drafts", token, losing,
                {"Idempotency-Key": key}, expected=409)
        else:
            draft = row["draft_id"]
            payment = api(settings, "GET", f"/api/v1/shop/drafts/{draft}/payment", token)["payment"]
            counts = payment_counts(settings, draft)
            row.update(attempt_id=payment["attempt_id"], counts=counts)
            validate_payment(rows, payment["attempt_id"], counts, 2)
        row["status"] = "PASSED"
    except (AssertionError, KeyError, StopIteration, RuntimeError) as error:
        row.update(status="FAILED", failure=type(error).__name__ + ": " + str(error))
    row["http_counts"] = {kind: sum(r["classification"] == kind for r in rows) for kind in ("success", "conflict", "unexpected")}
    row["requests_sha256"] = sha256(folder / "requests.json")
    row["prepared_sha256"] = sha256(folder / "prepared.json")
    target = folder / ("result-resumed.json" if (folder / "result.json").exists() else "result.json")
    if target.exists():
        raise FileExistsError(target)
    target.write_bytes((json.dumps(row, indent=2) + "\n").encode())
    if row["status"] != "PASSED":
        raise AssertionError(row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--probe-id", required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", args.probe_id):
        raise ValueError("invalid probe identifier")
    settings = Settings(args.run_id)
    with settings.operation_lock():
        settings.freeze()
        output = settings.report / "trade-probes" / args.probe_id
        output.mkdir(parents=True, exist_ok=args.resume)
        original_hashes = {str(p.relative_to(output)): sha256(p) for p in output.rglob("*.json")}
        if args.resume:
            if not original_hashes:
                raise ValueError("resume needs existing probe records")
            (output / "resume-inputs.json").write_bytes((json.dumps(original_hashes, indent=2) + "\n").encode())
        token = login(settings, "demo-buyer", "demo-pass-4001")
        rows = []
        try:
            for scenario in ("T01", "T02", "T04", "T05"):
                for concurrency in (10, 30):
                    folder = output / f"{scenario}-c{concurrency}"
                    folder.mkdir(exist_ok=args.resume)
                    result = folder / "result.json"
                    if args.resume and result.exists() and json.loads(result.read_text())["status"] == "PASSED":
                        rows.append(json.loads(result.read_text()))
                    else:
                        rows.append(round_probe(settings, token, scenario, concurrency, folder))
                    print(f"{scenario} c{concurrency} passed", flush=True)
        finally:
            summary = {"phase": "development probes, not formal 160-round matrix", "run_id": settings.identity,
                       "completed_rounds": len(rows), "planned_rounds": 8, "rows": rows,
                       "source_sha256": sha256(__file__), "original_hashes": original_hashes}
            for relative, digest in original_hashes.items():
                assert sha256(output / relative) == digest, relative
            target = output / ("summary-resumed.json" if args.resume else "summary.json")
            if target.exists():
                raise FileExistsError(target)
            target.write_bytes((json.dumps(summary, indent=2) + "\n").encode())


if __name__ == "__main__":
    main()
