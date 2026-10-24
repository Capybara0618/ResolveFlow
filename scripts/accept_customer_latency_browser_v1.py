"""Prepare one synthetic UI turn; account it independently of the CUA process."""

from __future__ import annotations

import argparse
import json
import subprocess
import time

import accept_customer_fact_fields_v1 as prior
from accept_chat_refund_live_v1 import (
    LEDGER,
    ROOT,
    allowance,
    connect,
    live_guard,
    normalize,
    persist,
)

OUT = ROOT / "reports/customer-latency-browser-v1"
PRIVATE = ROOT / "tmp/customer-latency-browser-v1"
FILES = [
    "scripts/accept_customer_latency_browser_v1.py",
    "scripts/accept_customer_fact_fields_v1.py",
    "scripts/accept_chat_refund_live_v1.py",
    "agent/src/resolveflow/support/engine.py",
    "agent/src/resolveflow/support/orchestration.py",
    "agent/src/resolveflow/support/orchestration_prompts.py",
    "agent/src/resolveflow/harness/streaming_model.py",
    "web/src/ui/SupportWorkspace.vue",
    "web/src/ui/SupportRefundCard.vue",
]
TURN = "这件耳机我还没有收到，请查当前物流并帮我准备退款原因草稿，先让我核对编辑，不要提交。"


def prepare():
    prior.OUT, prior.PRIVATE, prior.TURNS, prior.FILES = OUT, PRIVATE, [TURN], FILES
    prior.prepare()
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    plan.update(
        scope="CUA actual DOM: old saved draft reload, one new streamed turn, edit/save/reload; no confirm",
        max_model_attempts=12,
        ledger_start=allowance(LEDGER)["used"],
        required_observations=[
            "old saved reason and pending confirmation survive reload without a message",
            "immediate processing feedback and two different intermediate visible body texts",
            "final answer retains observed streamed text; facts and quotes separate",
            "new refund reason editable, saved and restored after reload",
            "one support run; no Case, handoff, authorization or refund",
        ],
    )
    persist(OUT / "plan.json", plan)


def watch():
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    assert prior.hashes(FILES) == plan["files"]
    assert prior.hashes(prior.PROTECTED) == plan["protected"]
    assert subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True) == ""
    settings, db = connect()
    before = json.loads((PRIVATE / "before.json").read_text(encoding="utf-8"))
    (PRIVATE / "execution-started.json").open("x", encoding="utf-8").close()
    report = {"scope": plan["scope"], "synthetic_business": True, "success": False}
    try:
        with live_guard(LEDGER):
            usage = allowance(LEDGER)
            assert usage["used"] == plan["ledger_start"]
            report["ledger_before"] = usage["used"]
            persist(PRIVATE / "ready.json", {"ready": True, "max_model_attempts": 12})
            print("Accounting guard ready; one CUA message allowed", flush=True)
            try:
                deadline = time.monotonic() + 1200
                while not (PRIVATE / "finish.json").exists():
                    if time.monotonic() >= deadline:
                        report["ui_timeout"] = True
                        break
                    time.sleep(0.5)
            finally:
                report.update(normalize(prior.collect(settings, db, before, plan)))
                # Serialize UUIDs before advancing the ledger; do not double-account on export failure.
                persist(PRIVATE / "accounting-before-ledger.json", report)
                usage["used"] += report["model_attempts"]
                usage["save"]()
                report["ledger_after"] = usage["used"]
                report["backend_checks_passed"] = (
                    len(report["support_runs"]) == 1
                    and report["support_runs"][0]["status"] == "SUCCEEDED"
                    and not report["general_runs"]
                    and all(p["unchanged"] for p in report["preservation"].values())
                    and report["payment_ledger"] == [[str(plan["amount_minor"]), "0", "0"]]
                    and not report["refund_operations"]
                    and not report["unknown_usage"]
                    and not report["estimated"]
                    and not report["pending_at_accounting"]
                    and 0 < report["model_attempts"] <= plan["max_model_attempts"]
                )
                persist(OUT / "runtime-results.json", report)
    finally:
        db.close()
    print({k: report[k] for k in ("backend_checks_passed", "model_attempts", "ledger_before", "ledger_after")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "watch"])
    args = parser.parse_args()
    (prepare if args.action == "prepare" else watch)()
