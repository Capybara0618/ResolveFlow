"""One new browser consultation, automatic editable refund summary, no Case creation."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import subprocess
import time

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

OUT = ROOT / "reports/customer-answer-fact-fields-v1/live-v1"
PRIVATE = ROOT / "tmp/customer-answer-fact-fields-live-v1"
TURNS = [
    "耳机还没送到。我想核对一下承运商的记录，并准备一份退款原因；先让我查看和修改，再决定是否提交。"
]
FILES = [
    "scripts/accept_customer_fact_fields_v1.py",
    "scripts/check_customer_fact_fields_v1.cjs",
    "scripts/accept_chat_refund_live_v1.py",
]
PROTECTED = [
    "docs/engineering.md",
    "scripts/verify.ps1",
    "scripts/verify.sh",
    "java/commerce-service/src/test/java/com/resolveflow/commerce/refund/RefundAcceptanceApiTest.java",
    "evals/customer-agent-publication-v2/manifest.json",
    "reports/chat-refund-stream-s3/provider-probe.json",
    "reports/customer-policy-focus-live-v1/runtime-results.json",
    "reports/chat-refund-handoff-v1/live-v2/runtime-results.json",
    "scripts/accept_chat_refund_handoff_v2.py",
    "scripts/check_chat_refund_handoff_v2.cjs",
]


def hashes(paths):
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}


def prepare():
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
        new_general_run_limit=0,
        files=hashes(FILES),
        protected=hashes(PROTECTED),
        model_bound="one support turn under original budget; no retry, Case creation, merchant approval or refund",
    )
    persist(OUT / "plan.json", plan)
    print(
        {
            "prepared": True,
            "new_synthetic_order": plan["order_id"],
            "provider_requests": 0,
        }
    )


def collect(settings, db, before, plan):
    old_support = {str(r["run_id"]) for r in before["support_runs"]}
    old_general = {str(r["run_id"]) for r in before["business"]["runs"]}
    end = time.monotonic() + 190
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
        if not pending or time.monotonic() >= end:
            break
        time.sleep(1)
    with db.connection() as c:
        all_support = c.execute(
            "SELECT * FROM support_agent_run ORDER BY run_id"
        ).fetchall()
        support = [dict(r) for r in all_support if str(r["run_id"]) not in old_support]
        general = [
            r
            for r in c.execute("SELECT * FROM agent_run ORDER BY created_at").fetchall()
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
        indexes = c.execute(
            "SELECT * FROM policy_index_generation ORDER BY generation_id"
        ).fetchall()
    sm = [call for r in support for call in r["calls"] if call["kind"] == "model"]
    gm = [a for r in general for a in r["attempts"]]
    usages = [(m.get("response_json") or {}).get("usage") for m in sm] + [
        (m.get("response") or {}).get("usage") for m in gm
    ]
    known = [u for u in usages if u]
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
    preserved["support_runs"] = {
        "unchanged": normalize(
            [r for r in all_support if str(r["run_id"]) in old_support]
        )
        == before["support_runs"]
    }
    preserved["policy_indexes"] = {"unchanged": normalize(indexes) == before["indexes"]}
    preserved["protected_files"] = {"unchanged": hashes(PROTECTED) == plan["protected"]}
    order = demo._sql_text(plan["order_id"])
    line = demo._sql_text(plan["line_id"])
    return {
        "support_runs": support,
        "general_runs": general,
        "model_attempts": len(sm) + len(gm),
        "provider_known_usage_count": len(known),
        "unknown_usage": len(usages) - len(known),
        "input_tokens": sum(u["input_tokens"] for u in known),
        "output_tokens": sum(u["output_tokens"] for u in known),
        "estimated": any(u.get("estimated", True) for u in known),
        "pending_at_accounting": pending,
        "preservation": preserved,
        "payment_ledger": demo.mysql_rows(
            "SELECT paid_amount,refunded_amount,reserved_refund_amount "
            "FROM commerce_db.payment_ledger WHERE order_id=" + order,
            settings,
        ),
        "refund_operations": demo.mysql_rows(
            "SELECT operation_id,state FROM commerce_db.refund_operation "
            "WHERE line_id=" + line,
            settings,
        ),
    }


def execute():
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    assert hashes(FILES) == plan["files"] and hashes(PROTECTED) == plan["protected"]
    with (PRIVATE / "execution-started.json").open("x", encoding="utf-8") as f:
        json.dump({"started": True}, f)
    settings, db = connect()
    before = json.loads((PRIVATE / "before.json").read_text(encoding="utf-8"))
    report = {
        "scope": "real Vue/Java/Python/DeepSeek on one synthetic new order",
        "success": False,
    }
    try:
        with live_guard(LEDGER):
            usage = allowance(LEDGER)
            report["ledger_before"] = usage["used"]
            try:
                runtime = (
                    ROOT.home()
                    / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
                )
                process = subprocess.run(
                    [
                        str(runtime / "bin/node.exe"),
                        "scripts/check_customer_fact_fields_v1.cjs",
                    ],
                    cwd=ROOT,
                    env={**os.environ, "NODE_PATH": str(runtime / "node_modules")},
                    timeout=180,
                    check=False,
                )
                report["browser_exit_code"] = process.returncode
            finally:
                report.update(collect(settings, db, before, plan))
                usage["used"] += report["model_attempts"]
                usage["save"]()
                report["ledger_after"] = usage["used"]
                report["success"] = (
                    report.get("browser_exit_code") == 0
                    and len(report["support_runs"]) == 1
                    and report["support_runs"][0]["status"] == "SUCCEEDED"
                    and not report["general_runs"]
                    and all(p["unchanged"] for p in report["preservation"].values())
                    and report["payment_ledger"]
                    == [[str(plan["amount_minor"]), "0", "0"]]
                    and not report["refund_operations"]
                    and not report["unknown_usage"]
                    and not report["pending_at_accounting"]
                )
                persist(OUT / "runtime-results.json", report)
    finally:
        db.close()
    print(
        {
            k: report[k]
            for k in ["success", "model_attempts", "ledger_before", "ledger_after"]
        }
    )
    if not report["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "execute"])
    args = parser.parse_args()
    (prepare if args.action == "prepare" else execute)()
