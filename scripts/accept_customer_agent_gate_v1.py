"""One real automatic summary/confirmation chain; controls run only after primary passes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess

import accept_customer_fact_fields_v1 as prior
from accept_chat_refund_live_v1 import (
    LEDGER,
    ROOT,
    allowance,
    connect,
    live_guard,
    persist,
)

OUT = ROOT / "reports/customer-agent-acceptance-gate-v1/primary"
PRIVATE = ROOT / "tmp/customer-agent-acceptance-gate-v1/primary"
FILES = [
    "scripts/accept_customer_agent_gate_v1.py",
    "scripts/check_customer_agent_gate_v1.cjs",
    "scripts/accept_customer_fact_fields_v1.py",
    "scripts/accept_chat_refund_live_v1.py",
]
PROTECTED = prior.PROTECTED + [
    "reports/customer-answer-fact-fields-v1/live-v1/runtime-results.json",
    "reports/customer-answer-fact-fields-v1/source-feedback-review.json",
    "reports/customer-answer-fact-fields-v1/final-audit.json",
]


def prepare():
    previous = prior.OUT, prior.PRIVATE, prior.FILES, prior.PROTECTED
    prior.OUT, prior.PRIVATE, prior.FILES, prior.PROTECTED = (
        OUT,
        PRIVATE,
        FILES,
        PROTECTED,
    )
    try:
        prior.prepare()
    finally:
        prior.OUT, prior.PRIVATE, prior.FILES, prior.PROTECTED = previous
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    plan.update(
        new_general_run_limit=1,
        model_bound="one support turn plus one automatic initial Case investigation; original budgets; no retry/approval/refund",
        source_files=prior.hashes(
            [
                "agent/src/resolveflow/support/" + p.name
                for p in (ROOT / "agent/src/resolveflow/support").glob("*.py")
            ]
        ),
        semantic_checks=[
            "observed order/shipment/guide",
            "published editable model summary",
            "same confirmed Case",
            "initial unverified statement",
            "validated manual review, no refund authorization",
        ],
        controls_after_primary_only=True,
    )
    persist(OUT / "plan.json", plan)


def collect(settings, db, before, plan):
    previous = prior.PROTECTED
    prior.PROTECTED = PROTECTED
    try:
        return prior.collect(settings, db, before, plan)
    finally:
        prior.PROTECTED = previous


def execute():
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    assert prior.hashes(FILES) == plan["files"]
    assert prior.hashes(PROTECTED) == plan["protected"]
    assert prior.hashes(plan["source_files"]) == plan["source_files"]
    with (PRIVATE / "execution-started.json").open("x", encoding="utf-8") as f:
        json.dump({"started": True}, f)
    settings, db = connect()
    before = json.loads((PRIVATE / "before.json").read_text(encoding="utf-8"))
    report = {
        "scope": "real Vue/Java/Python/DeepSeek; synthetic commerce; primary acceptance",
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
                result = subprocess.run(
                    [
                        str(runtime / "bin/node.exe"),
                        "scripts/check_customer_agent_gate_v1.cjs",
                    ],
                    cwd=ROOT,
                    env={**os.environ, "NODE_PATH": str(runtime / "node_modules")},
                    timeout=420,
                    check=False,
                )
                report["browser_exit_code"] = result.returncode
            finally:
                report.update(collect(settings, db, before, plan))
                usage["used"] += report["model_attempts"]
                usage["save"]()
                report["ledger_after"] = usage["used"]
                report["success"] = (
                    report.get("browser_exit_code") == 0
                    and len(report["support_runs"]) == 1
                    and report["support_runs"][0]["status"] == "SUCCEEDED"
                    and len(report["general_runs"]) == 1
                    and report["general_runs"][0]["status"] == "COMPLETED"
                    and all(p["unchanged"] for p in report["preservation"].values())
                    and report["payment_ledger"]
                    == [[str(plan["amount_minor"]), "0", "0"]]
                    and not report["refund_operations"]
                    and not report["unknown_usage"]
                    and not report["pending_at_accounting"]
                )
                report["controls"] = (
                    "READY_FOR_PREPARATION"
                    if report["success"]
                    else "NOT_RUN_PRIMARY_FAILED"
                )
                persist(OUT / "runtime-results.json", report)
    finally:
        db.close()
    print(
        {
            k: report[k]
            for k in [
                "success",
                "model_attempts",
                "ledger_before",
                "ledger_after",
                "controls",
            ]
        }
    )
    if not report["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "execute"])
    args = parser.parse_args()
    (prepare if args.action == "prepare" else execute)()
