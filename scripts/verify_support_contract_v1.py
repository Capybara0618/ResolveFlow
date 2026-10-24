"""One fixed different-wording contract confirmation, then the unexecuted original refund chain."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from copy import deepcopy

import accept_support_adoption_v1 as base
from accept_chat_refund_live_v1 import (
    LEDGER,
    ROOT,
    allowance,
    baseline_state,
    connect,
    live_guard,
    normalize,
    persist,
)

OUT = base.OUT / "recheck-v1"
PRIVATE = base.PRIVATE / "recheck-v1"
FILES = ["scripts/verify_support_contract_v1.py", "scripts/check_support_contract_recheck_v1.cjs",
         "scripts/check_support_contract_primary_v1.cjs"]
PROTECTED = base.PROTECTED + base.FILES + [
    "reports/customer-agent-orchestration-acceptance-v1/controls-runtime.json",
    "reports/customer-agent-orchestration-acceptance-v1/controls-review.json",
    "reports/customer-agent-orchestration-acceptance-v1/plan.json"]
TEXT = "请把我没收到耳机、已经问过家人和代收点仍未找到的情况，单独整理成要交给商家的核查摘要，先让我编辑确认；这次不申请退款。"


def prepare():
    assert not (OUT / "plan.json").exists()
    old = json.loads((base.OUT / "plan.json").read_text(encoding="utf-8"))
    group = deepcopy(next(g for g in old["groups"] if g["id"] == "human"))
    group["turns"] = [TEXT]
    primary = deepcopy(old["primary"])
    settings, db = connect()
    try:
        with db.connection() as c:
            assert not c.execute("SELECT run_id FROM support_agent_run WHERE status='RUNNING'").fetchall()
            assert not c.execute("SELECT run_id FROM agent_run WHERE status IN ('QUEUED','RUNNING')").fetchall()
            before = {"business": baseline_state(settings, db),
                      "support_runs": c.execute("SELECT * FROM support_agent_run ORDER BY run_id").fetchall(),
                      "indexes": c.execute("SELECT * FROM policy_index_generation ORDER BY generation_id").fetchall()}
        persist(PRIVATE / "before.json", normalize(before))
    finally:
        db.close()
    plan = {"groups": [group], "primary": primary, "original_successful_groups_repeated": False,
            "original_failed_run": "b52c3378-6f7c-4c05-8d1e-00d6581b4cdf", "automatic_retry": False,
            "remaining_customer_turns": 2, "new_case_run_limit": 1, "architecture": "orchestrated-v1",
            "files": base.prior.hashes(FILES), "protected": base.prior.hashes(PROTECTED),
            "source_files": base.prior.hashes(["agent/src/resolveflow/support/" + p.name
                for p in (ROOT / "agent/src/resolveflow/support").glob("*.py")])}
    persist(OUT / "plan.json", plan)
    persist(OUT / "primary/plan.json", {**primary, "source_files": plan["source_files"]})
    print({"prepared": True, "new_orders": 0, "model_calls": 0})


def execute(stage):
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    assert base.prior.hashes(FILES) == plan["files"] and base.prior.hashes(PROTECTED) == plan["protected"]
    assert base.prior.hashes(plan["source_files"]) == plan["source_files"]
    if stage == "primary":
        review = json.loads((OUT / "controls-review.json").read_text(encoding="utf-8"))
        assert review["passed"] and review["source_review_complete"]
    settings, db = connect()
    try:
        assert base.demo.agent_health(settings, architecture="orchestrated-v1")
        with (PRIVATE / (stage + "-started.json")).open("x", encoding="utf-8") as f:
            json.dump({"stage": stage, "automatic_retry": False}, f)
        before = json.loads((PRIVATE / "before.json").read_text(encoding="utf-8"))
        accounted = 0 if stage == "controls" else json.loads(
            (OUT / "controls-runtime.json").read_text(encoding="utf-8"))["model_attempts"]
        report = {"stage": stage, "scope": "real new contract confirmation; original failure preserved", "success": False}
        with live_guard(LEDGER):
            usage = allowance(LEDGER)
            report["ledger_before"] = usage["used"]
            try:
                node = ROOT.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
                name = "recheck" if stage == "controls" else "primary"
                process = subprocess.run([str(node / "bin/node.exe"), f"scripts/check_support_contract_{name}_v1.cjs"],
                    cwd=ROOT, env={**os.environ, "NODE_PATH": str(node / "node_modules")}, timeout=420, check=False)
                report["browser_exit_code"] = process.returncode
            finally:
                previous = base.prior.PROTECTED
                base.prior.PROTECTED = PROTECTED
                try:
                    report.update(base.prior.collect(settings, db, before,
                                                       {**plan["primary"], "protected": plan["protected"]}))
                finally:
                    base.prior.PROTECTED = previous
                report["stage_model_attempts"] = report["model_attempts"] - accounted
                usage["used"] += report["stage_model_attempts"]
                usage["save"]()
                report["ledger_after"] = usage["used"]
                report["mechanical_checks"] = base.mechanics(report, plan)
                report["success"] = (report.get("browser_exit_code") == 0
                    and all(c["passed"] for c in report["mechanical_checks"])
                    and all(p["unchanged"] for p in report["preservation"].values())
                    and len(report["general_runs"]) == (1 if stage == "primary" else 0)
                    and not report["unknown_usage"] and not report["pending_at_accounting"]
                    and not report["refund_operations"])
                persist(OUT / (stage + "-runtime.json"), report)
    finally:
        db.close()
    print({k: report[k] for k in ["stage", "success", "stage_model_attempts", "ledger_before", "ledger_after"]})
    if not report["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "controls", "primary"])
    action = parser.parse_args().action
    prepare() if action == "prepare" else execute(action)
