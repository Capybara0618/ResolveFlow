"""Offline R-round semantic assessment and complete-cohort audit from preserved evidence."""

from __future__ import annotations

import argparse
import json
from collections import Counter

from evaluation.backend_d5_http import digest
from evaluation.backend_d5_rebuild_support import rebuild_peak
from evaluation.backend_lab import Settings, sha256
from evaluation.trade_request_journal import durable


def metric_delta(result, name, outcome):
    total = 0
    for node, after in result["after"].items():
        before = result["before"][node]
        for key, value in after["meters"].items():
            if (
                key.startswith(name + "[")
                and f"outcome={outcome}" in key
                and key.endswith(":COUNT")
            ):
                total += value - before["meters"].get(key, 0)
    return total


def assess(result, events):
    if result.get("status") in ("FAILED", "INVALID_SETUP"):
        return {
            "passed": False,
            "reasons": [result["status"] + ": " + result.get("message", "")],
        }
    reasons = []
    item, facts = result["round"], result["facts"]
    scenario, condition = item["scenario"], item["condition"]
    product = result["products"][0]["product"]

    def check(condition, reason):
        if not condition:
            reasons.append(reason)

    reference = result["reference"]
    body = reference.get("body", {})
    check(
        reference["status"] == 200 and reference.get("body_sha256") == digest(body),
        "invalid reference",
    )
    check(
        body.get("summary") == {"count": 1, "average": 3.0, "stars": [0, 0, 1, 0, 0]},
        "reference fixture summary",
    )
    check(
        len(body.get("items", [])) == 1
        and body["items"][0].get("product_id") == product
        and body["items"][0].get("version") == 1,
        "reference product/version",
    )
    allowed = {reference["body_sha256"]}
    follow_hash = reference["body_sha256"]
    if scenario == "R05":
        new = result.get("new_reference") or {}
        check(
            new.get("status") == 200
            and new.get("body_sha256") == digest(new.get("body")),
            "new epoch reference",
        )
        follow_hash = new.get("body_sha256")
        allowed.add(follow_hash)
        changed = new.get("body", {}).get("items", [])
        legal = facts.get("legal_reply", {}).get("response", {})
        check(
            len(changed) == 1
            and changed[0].get("version") == 2
            and changed[0].get("reply") == legal.get("reply")
            and legal.get("version") == 2,
            "legal reply/new version missing",
        )
    initial = result["initial"]
    check(
        len(initial) == item["concurrency"]
        and sorted(r["index"] for r in initial) == list(range(item["concurrency"])),
        "initial request denominator",
    )
    for row in initial:
        check(
            row["node"] == ("commerce" if row["index"] % 2 == 0 else "commerce2"),
            "node distribution changed",
        )
        okay_status = (
            row["status"]
            in ((200, 503, 0) if scenario in ("R03", "R04") else (200, 503))
            or scenario == "R02"
            and row["index"] == 0
            and row["status"] == 500
        )
        check(okay_status, "unexpected initial status")
        if row["status"] == 200:
            check(
                row.get("body_sha256") == digest(row.get("body"))
                and row.get("body_sha256") in allowed,
                "initial projection mismatch",
            )
    follow = result["followup"]
    check(
        len(follow) == 10
        and all(
            r["status"] == 200
            and r.get("body_sha256") == follow_hash
            and digest(r.get("body")) == follow_hash
            for r in follow
        ),
        "followup failed/stale",
    )
    seconds = facts.get("recovery_seconds")
    check(seconds is not None and 0 <= seconds <= 5, "recovery exceeded five seconds")
    check(
        all(row["sql_inflight"] == 0 for row in result["after"].values()),
        "SQL inflight not drained",
    )
    primary = [r for r in events if r.get("product") == product]
    peak = rebuild_peak(events, product, result.get("terminal"))
    check(peak == result["rebuild_peak"], "overlap score changed")
    loads = sum(r["stage"] == "load_start" for r in primary)
    check(loads == result["rebuild_loads"], "load denominator changed")
    sql = sum(r["stage"] == "sql_execute" for r in events)
    check(
        sql > 0 and sql == result["sql_execute_events"],
        "durable SQL execution evidence missing",
    )
    if scenario == "R01":
        check(
            len(result["independent"]) == 2
            and all(
                r["status"] == 200
                and r["body"]["items"][0]["product_id"] == r["product"]
                for r in result["independent"]
            ),
            "independent keys failed",
        )
        if item["ttl"]:
            ttl = facts.get("ttl", {})
            check(
                ttl.get("exists_after") == 0
                and ttl.get("actual_wait_ms", 0) >= ttl.get("observed_ms", 30001) > 0,
                "real TTL not reached",
            )
        if condition == "C":
            check(peak == 1 and loads == 1, "normal lease duplicated page load")
    elif scenario == "R02":
        check(
            facts.get("first_failure", {}).get("status") == 500,
            "test exception not reached",
        )
        if condition == "C":
            check(
                any(
                    r["stage"] == "lock_unlock" and product in r.get("key", "")
                    for r in events
                ),
                "exception did not release lock",
            )
    elif scenario == "R03":
        terminal = result.get("terminal") or {}
        check(
            terminal.get("pid") == facts.get("last_owner_probe", {}).get("pid")
            and terminal.get("node") == "commerce"
            and "commerce" not in result["after"],
            "actual owner termination missing",
        )
    elif scenario == "R04":
        check(
            facts.get("resumed_ns", 0) - facts.get("suspended", {}).get("at_ns", 0)
            >= 2_000_000_000
            and peak >= 2,
            "process pause/lease overlap missing",
        )
        if condition == "C":
            value = facts.get("new_lock_before_resume")
            check(
                value
                and value != facts.get("owner_lock", {}).get("value")
                and value == facts.get("new_lock_after_old_release"),
                "old owner changed new owner lock",
            )
            check(
                metric_delta(
                    result, "resolveflow.product_reviews.cache.write", "lease_lost"
                )
                >= 1,
                "old owner did not skip fill",
            )
    elif scenario == "R06":
        check(
            facts.get("redis_injected", {}).get("mode") == item["redis_fault"]
            and facts.get("redis_restored", {}).get("mode") == "normal",
            "proxy fault boundary missing",
        )
        errors = sum(
            metric_delta(result, name, outcome)
            for name, outcome in (
                ("resolveflow.product_reviews.cache", "error"),
                ("resolveflow.product_reviews.cache.write", "error"),
                ("resolveflow.product_reviews.rebuild.lock", "unavailable"),
                ("resolveflow.product_reviews.rebuild.lock", "unlock_unavailable"),
            )
        )
        check(errors > 0, "Redis fault not observed by application")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "sql_execute_events": sql,
        "rebuild_loads": loads,
        "rebuild_peak": peak,
        "initial_statuses": dict(Counter(str(r["status"]) for r in initial)),
    }


def journal_audit(path):
    starts, ends = {}, {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        group = starts if row.pop("stage") == "start" else ends
        if row["request_id"] in group:
            raise ValueError("duplicate request journal event")
        group[row["request_id"]] = row
    if set(starts) != set(ends):
        raise ValueError("unresolved/missing request journal event")
    for key, row in ends.items():
        if row["elapsed_ms"] < 0 or row["started_ns"] != starts[key]["started_ns"]:
            raise ValueError("request timing mismatch")
        if "body" in row and digest(row["body"]) != row["body_sha256"]:
            raise ValueError("request body hash mismatch")
    return ends


def audit(settings, folder):
    from evaluation.backend_d5_faults import check_inputs
    from evaluation.backend_d5_rebuild import plan

    check_inputs(settings, folder, plan())
    rows = []
    for item in plan():
        target = folder / item["id"]
        result = json.loads((target / "complete.json").read_text(encoding="utf-8"))
        assert result["round"] == item
        if result.get("status") in ("FAILED", "INVALID_SETUP"):
            rows.append(
                {
                    **item,
                    "passed": False,
                    "status": result["status"],
                    "error": result.get("message"),
                }
            )
            continue
        assert sha256(target / "events.jsonl") == result["events_sha256"]
        events = [
            json.loads(line)
            for line in (target / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        checked = assess(result, events)
        assert checked == result["assessment"] and checked["passed"] == result["passed"]
        ends = journal_audit(target / "requests.jsonl")
        for row in (
            result["initial"] + result["followup"] + result["facts"]["observations"]
        ):
            assert ends[row["request_id"]] == row
        rows.append(
            {**item, **checked, "recovery_seconds": result["facts"]["recovery_seconds"]}
        )
    summary = {
        "rounds": rows,
        "total": len(rows),
        "passed": sum(r["passed"] for r in rows),
        "invalid_setup": sum(r.get("status") == "INVALID_SETUP" for r in rows),
    }
    durable(folder / "audit.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "rounds"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--cohort", required=True)
    args = parser.parse_args()
    if not args.cohort.replace("-", "").isalnum():
        raise ValueError("explicit simple cohort")
    settings = Settings(args.run_id)
    with settings.operation_lock():
        audit(settings, settings.folder / args.cohort)


if __name__ == "__main__":
    main()
