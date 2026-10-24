"""Continue the original sample through its manual button, without retrying Agent messages."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from accept_chat_refund_handoff_v2 import (
    LEDGER,
    OUT,
    PRIVATE,
    ROOT,
    allowance,
    baseline_state,
    connect,
    demo,
    fingerprint,
    live_guard,
    normalize,
    persist,
)

TARGET = OUT / "manual-continuation"
SCRIPT = "scripts/check_chat_refund_handoff_manual_v2.cjs"


def main():
    settings, db = connect()
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    with (PRIVATE / "manual-execution-started.json").open("x") as marker:
        marker.write("one manual entry; no support-message retry\n")
    TARGET.mkdir(parents=True, exist_ok=True)
    before = baseline_state(settings, db)
    old = json.loads((PRIVATE / "before.json").read_text(encoding="utf-8"))
    with db.connection() as c:
        support_before = normalize(
            c.execute("SELECT * FROM support_agent_run ORDER BY run_id").fetchall()
        )
    old_support_ids = {r["run_id"] for r in support_before}
    old_general_ids = {r["run_id"] for r in before["runs"]}
    persist(
        TARGET / "plan.json",
        {
            "entry": "manual button on original sample; automatic summary result remains failed",
            "order_id": plan["order_id"],
            "line_id": plan["line_id"],
            "conversation_id": plan["conversation_id"],
            "new_support_messages": 0,
            "new_general_runs": 2,
            "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "browser_sha256": hashlib.sha256((ROOT / SCRIPT).read_bytes()).hexdigest(),
        },
    )
    result = {"success": False, "automatic_summary_retested": False}
    try:
        with live_guard(LEDGER):
            ledger = allowance(LEDGER)
            result["ledger_before"] = ledger["used"]
            try:
                node = (
                    Path.home()
                    / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
                )
                process = subprocess.run(
                    [str(node / "bin/node.exe"), SCRIPT],
                    cwd=ROOT,
                    env={**os.environ, "NODE_PATH": str(node / "node_modules")},
                    timeout=330,
                    check=False,
                )
                result["browser_exit_code"] = process.returncode
            finally:
                deadline = time.monotonic() + 190
                while True:
                    with db.connection() as c:
                        runs = [
                            r
                            for r in c.execute(
                                "SELECT * FROM agent_run ORDER BY run_id"
                            ).fetchall()
                            if str(r["run_id"]) not in old_general_ids
                        ]
                    pending = [r for r in runs if r["status"] in {"QUEUED", "RUNNING"}]
                    if not pending or time.monotonic() >= deadline:
                        break
                    time.sleep(1)
                with db.connection() as c:
                    attempts = [
                        a
                        for r in runs
                        for a in c.execute(
                            "SELECT * FROM agent_model_attempt WHERE run_id=%s ORDER BY created_at",
                            (r["run_id"],),
                        ).fetchall()
                    ]
                    support_after = normalize(
                        c.execute(
                            "SELECT * FROM support_agent_run ORDER BY run_id"
                        ).fetchall()
                    )
                    extra = [
                        r for r in support_after if r["run_id"] not in old_support_ids
                    ]
                    support_calls = [
                        a
                        for r in extra
                        for a in c.execute(
                            "SELECT * FROM support_agent_call WHERE run_id=%s AND kind='model' ORDER BY created_at",
                            (r["run_id"],),
                        ).fetchall()
                    ]
                model_usage = [
                    (a.get("response") or {}).get("usage") for a in attempts
                ] + [(a.get("response_json") or {}).get("usage") for a in support_calls]
                known = [u for u in model_usage if u]
                ledger["used"] += len(model_usage)
                ledger["save"]()
                current = normalize(baseline_state(settings, db))
                preserved = {}
                for table, rows in old["business"].items():

                    def key(r, current_table=table):
                        return str(r["run_id"]) if current_table == "runs" else r[0]

                    ids = {key(r) for r in rows}
                    actual = [r for r in current[table] if key(r) in ids]
                    preserved[table] = {
                        "unchanged": rows == actual,
                        "sha256_before": fingerprint(rows),
                        "sha256_after": fingerprint(actual),
                    }
                preserved["support_runs_including_original_failure"] = {
                    "unchanged": support_before
                    == [r for r in support_after if r["run_id"] in old_support_ids]
                }
                order, line = (
                    demo._sql_text(plan["order_id"]),
                    demo._sql_text(plan["line_id"]),
                )
                payment = demo.mysql_rows(
                    "SELECT paid_amount,refunded_amount,reserved_refund_amount "
                    "FROM commerce_db.payment_ledger WHERE order_id=" + order,
                    settings,
                )
                operations = demo.mysql_rows(
                    "SELECT operation_id,state,amount_minor FROM "
                    "commerce_db.refund_operation WHERE line_id=" + line,
                    settings,
                )
                result.update(
                    general_runs=runs,
                    model_attempt_records=attempts,
                    new_support_runs=extra,
                    support_model_calls=support_calls,
                    model_attempts=len(model_usage),
                    ledger_after=ledger["used"],
                    input_tokens=sum(u["input_tokens"] for u in known),
                    output_tokens=sum(u["output_tokens"] for u in known),
                    unknown_usage=len(model_usage) - len(known),
                    estimated=any(u.get("estimated", True) for u in known),
                    pending_at_accounting=[str(r["run_id"]) for r in pending],
                    preservation=preserved,
                    payment_ledger=payment,
                    refund_operations=operations,
                )
                result["success"] = (
                    result.get("browser_exit_code") == 0
                    and len(runs) == 2
                    and not extra
                    and not pending
                    and all(p["unchanged"] for p in preserved.values())
                    and not result["unknown_usage"]
                    and payment
                    == [[str(plan["amount_minor"]), str(plan["amount_minor"]), "0"]]
                    and len(operations) == 1
                    and operations[0][1] == "SUCCEEDED"
                )
                persist(TARGET / "runtime-results.json", result)
    finally:
        db.close()
    print(
        json.dumps(
            {
                k: result[k]
                for k in ["success", "model_attempts", "ledger_before", "ledger_after"]
            }
        )
    )
    if not result["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
