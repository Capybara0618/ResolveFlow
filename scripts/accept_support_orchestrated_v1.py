"""One explicit new-profile browser confirmation; preserve original budgets and all frozen failures."""

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
    demo,
    live_guard,
    persist,
)

OUT = ROOT / "reports/customer-agent-orchestration-v1/live-v1"
PRIVATE = ROOT / "tmp/customer-agent-orchestration-v1/live-v1"
FILES = ["scripts/accept_support_orchestrated_v1.py", "scripts/check_support_orchestrated_v1.cjs",
         "scripts/accept_customer_fact_fields_v1.py", "scripts/accept_chat_refund_live_v1.py"]
PROTECTED = prior.PROTECTED + [
    "reports/customer-agent-acceptance-gate-v1/primary/runtime-results.json",
    "reports/customer-answer-fact-fields-v1/live-v1/runtime-results.json",
    "reports/customer-agent-acceptance-gate-v1/diagnostic.json",
]


def prepare():
    previous = prior.OUT, prior.PRIVATE, prior.FILES, prior.PROTECTED
    prior.OUT, prior.PRIVATE, prior.FILES, prior.PROTECTED = OUT, PRIVATE, FILES, PROTECTED
    try:
        prior.prepare()
    finally:
        prior.OUT, prior.PRIVATE, prior.FILES, prior.PROTECTED = previous
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    plan.update(architecture="orchestrated-v1", source_files=prior.hashes([
        "agent/src/resolveflow/support/" + p.name for p in (ROOT / "agent/src/resolveflow/support").glob("*.py")]),
        intended_checks=["actual new protocol", "current order and shipment", "program-owned guide",
                         "automatic editable reason", "real streamed COMPOSE text", "reload draft recovery"],
        automatic_retry=False, switch_daily_default=False)
    persist(OUT / "plan.json", plan)


def execute():
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    assert prior.hashes(FILES) == plan["files"] and prior.hashes(PROTECTED) == plan["protected"]
    assert prior.hashes(plan["source_files"]) == plan["source_files"]
    settings, db = connect()
    report = {"scope": "real Vue/Java/Python/DeepSeek; one synthetic order; explicit orchestrated-v1",
              "success": False}
    try:
        assert demo.agent_health(settings, architecture="orchestrated-v1")
        with (PRIVATE / "execution-started.json").open("x", encoding="utf-8") as f:
            json.dump({"started": True, "automatic_retry": False}, f)
        before = json.loads((PRIVATE / "before.json").read_text(encoding="utf-8"))
        with live_guard(LEDGER):
            usage = allowance(LEDGER)
            report["ledger_before"] = usage["used"]
            try:
                node = ROOT.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
                process = subprocess.run([str(node / "bin/node.exe"), "scripts/check_support_orchestrated_v1.cjs"],
                    cwd=ROOT, env={**os.environ, "NODE_PATH": str(node / "node_modules")}, timeout=180, check=False)
                report["browser_exit_code"] = process.returncode
            finally:
                previous = prior.PROTECTED
                prior.PROTECTED = PROTECTED
                try:
                    report.update(prior.collect(settings, db, before, plan))
                finally:
                    prior.PROTECTED = previous
                usage["used"] += report["model_attempts"]
                usage["save"]()
                report["ledger_after"] = usage["used"]
                report["success"] = (report.get("browser_exit_code") == 0
                    and len(report["support_runs"]) == 1 and report["support_runs"][0]["status"] == "SUCCEEDED"
                    and report["support_runs"][0]["manifest_json"]["architecture"] == "orchestrated-v1"
                    and not report["general_runs"] and all(p["unchanged"] for p in report["preservation"].values())
                    and report["payment_ledger"] == [[str(plan["amount_minor"]), "0", "0"]]
                    and not report["refund_operations"] and not report["unknown_usage"]
                    and not report["pending_at_accounting"])
                persist(OUT / "runtime-results.json", report)
    finally:
        db.close()
    print({key: report[key] for key in ["success", "model_attempts", "ledger_before", "ledger_after"]})
    if not report["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "execute"])
    (prepare if parser.parse_args().action == "prepare" else execute)()
