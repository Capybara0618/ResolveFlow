"""One new real-model sample covering confirmed reason, merchant verification and refund."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import subprocess
import time
from pathlib import Path

import accept_chat_refund_live_v1 as original
from accept_chat_refund_live_v1 import (
    LEDGER,
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

OUT = ROOT / "reports/chat-refund-handoff-v1/live-v2"
PRIVATE = ROOT / "tmp/chat-refund-handoff-live-v2"
TURNS = [
    "这件商品一直没收到，请查看当前物流，并帮我整理整件退款申请的原因，供我核对后确认提交。"
]


def prepare():
    # Reuse only the existing purchase/shipment/scenario setup; original frozen evidence is untouched.
    previous = original.OUT, original.PRIVATE, original.TURNS
    original.OUT, original.PRIVATE, original.TURNS = OUT, PRIVATE, TURNS
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            original.prepare()
    finally:
        original.OUT, original.PRIVATE, original.TURNS = previous
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    plan.update(
        turn_limit=1,
        new_general_run_limit=2,
        model_bound="one support turn; Case revision1 manual review then merchant verification and revision2 refund; original budgets",
        files={
            p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
            for p in [
                "scripts/accept_chat_refund_handoff_v2.py",
                "scripts/check_chat_refund_handoff_v2.cjs",
                "scripts/accept_chat_refund_live_v1.py",
            ]
        },
    )
    persist(OUT / "plan.json", plan)
    print(
        "V2 prepared: one new synthetic order, one support turn and at most two Case investigations; provider requests: 0"
    )


def execute():
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    for path, expected in plan["files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
    with (PRIVATE / "execution-started.json").open("x", encoding="utf-8") as f:
        json.dump({"started": True}, f)
    settings, db = connect()
    before = json.loads((PRIVATE / "before.json").read_text(encoding="utf-8"))
    report = {
        "scope": "real browser + Java/Python/DeepSeek, synthetic transaction",
        "success": False,
    }
    try:
        with live_guard(LEDGER):
            usage = allowance(LEDGER)
            report["ledger_before"] = usage["used"]
            try:
                runtime = (
                    Path.home()
                    / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
                )
                result = subprocess.run(
                    [
                        str(runtime / "bin/node.exe"),
                        "scripts/check_chat_refund_handoff_v2.cjs",
                    ],
                    cwd=ROOT,
                    env={**os.environ, "NODE_PATH": str(runtime / "node_modules")},
                    timeout=600,
                    check=False,
                )
                report["browser_exit_code"] = result.returncode
            finally:
                old_support = {str(r["run_id"]) for r in before["support_runs"]}
                old_general = {str(r["run_id"]) for r in before["business"]["runs"]}
                # A browser failure must not hide model requests still completing server-side.
                deadline = time.monotonic() + 190
                while True:
                    with db.connection() as c:
                        pending = [
                            r
                            for r in c.execute(
                                "SELECT run_id FROM support_agent_run WHERE status='RUNNING'"
                            ).fetchall()
                            if str(r["run_id"]) not in old_support
                        ] + [
                            r
                            for r in c.execute(
                                "SELECT run_id FROM agent_run WHERE status IN ('QUEUED','RUNNING')"
                            ).fetchall()
                            if str(r["run_id"]) not in old_general
                        ]
                    if not pending or time.monotonic() >= deadline:
                        report["pending_at_accounting"] = normalize(pending)
                        break
                    time.sleep(1)
                with db.connection() as c:
                    support = [
                        r
                        for r in c.execute(
                            "SELECT * FROM support_agent_run ORDER BY created_at"
                        ).fetchall()
                        if str(r["run_id"]) not in old_support
                    ]
                    general = [
                        r
                        for r in c.execute(
                            "SELECT * FROM agent_run ORDER BY created_at"
                        ).fetchall()
                        if str(r["run_id"]) not in old_general
                    ]
                    for r in support:
                        r["calls"] = c.execute(
                            "SELECT * FROM support_agent_call WHERE run_id=%s ORDER BY created_at,kind,position",
                            (r["run_id"],),
                        ).fetchall()
                    for r in general:
                        r["attempts"] = c.execute(
                            "SELECT * FROM agent_model_attempt WHERE run_id=%s ORDER BY created_at",
                            (r["run_id"],),
                        ).fetchall()
                    current_support = c.execute(
                        "SELECT * FROM support_agent_run ORDER BY run_id"
                    ).fetchall()
                    current_indexes = c.execute(
                        "SELECT * FROM policy_index_generation ORDER BY generation_id"
                    ).fetchall()
                sm = [
                    call
                    for r in support
                    for call in r["calls"]
                    if call["kind"] == "model"
                ]
                gm = [a for r in general for a in r["attempts"]]
                usages = [(m.get("response_json") or {}).get("usage") for m in sm] + [
                    (m.get("response") or {}).get("usage") for m in gm
                ]
                known = [u for u in usages if u]
                count = len(sm) + len(gm)
                usage["used"] += count
                usage["save"]()
                current = normalize(baseline_state(settings, db))
                preserved = {}
                for name, old in before["business"].items():
                    ids = {str(r["run_id"]) if name == "runs" else r[0] for r in old}
                    actual = [
                        r
                        for r in current[name]
                        if (str(r["run_id"]) if name == "runs" else r[0]) in ids
                    ]
                    preserved[name] = {
                        "unchanged": actual == old,
                        "count": len(old),
                        "sha256_before": fingerprint(old),
                        "sha256_after": fingerprint(actual),
                    }
                old_current = [
                    r for r in current_support if str(r["run_id"]) in old_support
                ]
                # Calls are attached only to new rows above; old rows remain byte-equivalent after normalization.
                preserved["support_runs"] = {
                    "unchanged": normalize(old_current) == before["support_runs"]
                }
                preserved["policy_indexes"] = {
                    "unchanged": normalize(current_indexes) == before["indexes"]
                }
                report.update(
                    support_runs=support,
                    general_runs=general,
                    model_attempts=count,
                    provider_known_usage_count=len(known),
                    unknown_usage=count - len(known),
                    input_tokens=sum(u["input_tokens"] for u in known),
                    output_tokens=sum(u["output_tokens"] for u in known),
                    estimated=any(u.get("estimated", True) for u in known),
                    ledger_after=usage["used"],
                    preservation=preserved,
                )
                order = demo._sql_text(plan["order_id"])
                line = demo._sql_text(plan["line_id"])
                report["payment_ledger"] = demo.mysql_rows(
                    "SELECT paid_amount,refunded_amount,reserved_refund_amount FROM commerce_db.payment_ledger WHERE order_id="
                    + order,
                    settings,
                )
                report["refund_operations"] = demo.mysql_rows(
                    "SELECT operation_id,state,amount_minor FROM commerce_db.refund_operation WHERE line_id="
                    + line,
                    settings,
                )
                report["success"] = (
                    report.get("browser_exit_code") == 0
                    and len(support) == 1
                    and len(general) == 2
                    and all(r["status"] == "SUCCEEDED" for r in support)
                    and all(p["unchanged"] for p in preserved.values())
                    and report["payment_ledger"]
                    == [[str(plan["amount_minor"]), str(plan["amount_minor"]), "0"]]
                    and len(report["refund_operations"]) == 1
                    and report["refund_operations"][0][1] == "SUCCEEDED"
                    and not report["unknown_usage"]
                    and not report["pending_at_accounting"]
                )
                persist(OUT / "runtime-results.json", report)
    finally:
        db.close()
    print(
        json.dumps(
            {
                k: report[k]
                for k in ["success", "model_attempts", "ledger_before", "ledger_after"]
            }
        )
    )
    if not report["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "execute"])
    prepare() if parser.parse_args().command == "prepare" else execute()
