"""Read-only offline verification. Usage: python audit.py RAW_DIRECTORY OUTPUT_JSON"""

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def audit(raw):
    manifest, summary = read(raw / "manifest.json"), read(raw / "summary.json")
    assert manifest["profile"] == "formal" and len(manifest["plan"]) == 160
    assert summary["planned"] == summary["finished"] == summary["passed"] == 160
    assert summary["manifest_sha256"] == sha(raw / "manifest.json")
    for name, value in manifest["sources"].items():
        assert sha(raw / "execution-sources" / name) == value
    selected, all_http, cohort = Counter(), Counter(), Counter()
    orders, receipts, attempts, overlaps = [], [], [], []
    recorded = 0
    per_scenario = {}
    for spec, expected in zip(manifest["plan"], summary["rounds"], strict=True):
        folder = raw / "rounds" / spec["id"]
        outcome = read(folder / "outcome.json")
        assert outcome == expected and outcome["status"] == "PASSED"
        for name, value in outcome["evidence"].items():
            assert sha(folder / name) == value
        target = "recovery-requests.json" if spec["scenario"] in ("T06", "T07") else "requests.json"
        rows = read(folder / target)
        assert len(rows) == spec["concurrency"] == outcome["actual_peak"]
        assert len({r["request_id"] for r in rows}) == len(rows)
        # Independent proof that all C intervals share a nonempty intersection.
        common = min(r["finished_ns"] for r in rows) - max(r["started_ns"] for r in rows)
        assert common > 0
        overlaps.append(common)
        selected.update(str(r["status"]) for r in rows)
        cohort[spec["concurrency"]] += 1
        per_scenario.setdefault(spec["scenario"], Counter()).update({"rounds": 1, "requests": len(rows)})
        clock = read(folder / "journal/journal.json")["clock_session"]
        complete = list((folder / "journal").glob("[0-9]" * 6 + "/completed.json"))
        intents = list((folder / "journal").glob("[0-9]" * 6 + "/intent.json"))
        assert len(complete) == len(intents) == outcome["all_recorded_requests"]
        recorded += len(complete)
        for response in complete:
            value = read(response)
            intent = read(response.with_name("intent.json"))
            assert value["request_id"] == response.parent.name == intent["request_id"]
            assert value["clock_session"] == intent["clock_session"] == clock
            assert value["intent_sha256"] == hashlib.sha256(
                json.dumps(intent, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            assert value["finished_ns"] > value["started_ns"]
            assert "Authorization" not in intent and "access_token" not in value
            all_http[str(value["status"])] += 1
        for row in rows:
            response = read(folder / "journal" / row["request_id"] / "completed.json")
            intent = read(folder / "journal" / row["request_id"] / "intent.json")
            assert intent["actor"] == "demo-buyer" and intent["method"] == "POST"
            assert response["status"] == row["status"] and response["body"] == row["body"]
        orders.extend(outcome["effects"]["orders"])
        receipts.extend(outcome["effects"]["receipts"])
        attempts.extend(outcome["effects"]["attempts"])
    assert len(orders) == len(set(orders)) == len(receipts) == len(set(receipts)) == len(attempts) == len(set(attempts)) == 90
    assert set(receipts) == set(attempts) and cohort == {10: 80, 30: 80}
    assert sum(selected.values()) == 3200
    database = read(raw / "database-audit.json")
    assert database["global_effects"]["orders"] == sorted(orders)
    assert database["global_effects"]["receipts"] == sorted(receipts)
    assert database["global_effects"]["attempts"] == sorted(attempts)
    assert len(database["payments"]) == 90
    for row in database["payments"]:
        assert row["attempt_id"] in attempts and row["order_id"] in orders
        assert row["status"] == "SUCCEEDED" and row["draft_status"] == "PAID"
        assert row["paid"] == row["line_total"] == row["receipt_amount"] == 52800
        assert row["lines"] == row["slots"] == 2 and row["receipts"] == 1
        assert row["reserved"] == row["refunded"] == 0 and row["customer"] == "C-B3001-M1001"
    return {"planned": 160, "passed": 160, "cohorts": dict(cohort), "per_scenario": per_scenario,
            "selected_requests": 3200, "selected_http": dict(selected), "all_recorded_requests": recorded,
            "all_recorded_http": dict(all_http), "successful_payment_groups": 90,
            "successful_receipts": 90, "orders": 90, "order_lines": 180, "refund_slots": 180,
            "minimum_common_overlap_ms": min(overlaps) / 1000000,
            "duplicate_orders": 0, "duplicate_simulated_receipts": 0, "unknown_requests": 0,
            "manifest_sha256": sha(raw / "manifest.json"), "model_requests": 0}


if __name__ == "__main__":
    result = audit(Path(sys.argv[1]))
    with Path(sys.argv[2]).open("xb") as output:
        output.write((json.dumps(result, indent=2) + "\n").encode())
    print(json.dumps(result))
