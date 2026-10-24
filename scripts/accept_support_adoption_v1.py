"""Bounded independent new-profile conversations and one user-confirmed synthetic Case."""

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
    normalize,
    persist,
)
from accept_support_orchestrated_v1 import PROTECTED as PREVIOUS_PROTECTED

OUT = ROOT / "reports/customer-agent-orchestration-acceptance-v1"
PRIVATE = ROOT / "tmp/customer-agent-orchestration-acceptance-v1"
FILES = ["scripts/accept_support_adoption_v1.py", "scripts/check_support_adoption_controls_v1.cjs",
         "scripts/check_support_adoption_primary_v1.cjs"]
PROTECTED = PREVIOUS_PROTECTED + ["reports/customer-agent-orchestration-v1/live-v1/runtime-results.json",
                                "reports/customer-agent-orchestration-v1/final-audit.json"]
SPECS = {
    "policy": ["先了解一般规则：如果快递有签收记录但本人没收到，通常要满足什么条件、准备什么材料？这只是政策咨询，不判断我的订单，也不要申请退款或转人工。"],
    "correction": ["我没收到耳机。家人可能帮我收了，我还没确认。请先查承运记录，暂时不要申请退款。",
                   "更正刚才的说法：家人已经确认没有代收，我也问过代收点，那里没有包裹。请接着核查，不要再让我重复问家人。"],
    "pause": ["耳机一直没收到，请先帮我整理退款申请原因，让我查看修改，暂时不提交。",
              "退款这件事先暂停，不要继续准备或提交申请。我现在只想了解：请商家核查时，政策有没有规定必须提供哪些材料？"],
    "human": ["我现在不打算退款，只想请商家人工帮忙核查耳机没收到的问题。我已经问过家人和代收点，都没有找到。请先给我一份可以确认后转交商家的摘要。"],
    "primary": ["耳机未收到。我想查看承运商记录，并准备整件退款的原因，先让我核对和编辑，再由我确认提交。"],
}


def prepare():
    assert not (OUT / "plan.json").exists()
    samples = []
    previous = prior.OUT, prior.PRIVATE, prior.TURNS, prior.FILES, prior.PROTECTED
    try:
        for key, turns in SPECS.items():
            prior.OUT, prior.PRIVATE, prior.TURNS = OUT / key, PRIVATE / key, turns
            prior.FILES, prior.PROTECTED = FILES, PROTECTED
            prior.prepare()
            path = OUT / key / "plan.json"
            sample = json.loads(path.read_text(encoding="utf-8"))
            sample.update(id=key, turns=turns, turn_limit=len(turns), architecture="orchestrated-v1",
                          new_general_run_limit=1 if key == "primary" else 0,
                          model_bound="original per-run budgets; fixed turns; no retry; " + (
                              "one confirmed Case and initial investigation, no approval/refund"
                              if key == "primary" else "no refund Case, approval or refund"))
            persist(path, sample)
            samples.append(sample)
    finally:
        prior.OUT, prior.PRIVATE, prior.TURNS, prior.FILES, prior.PROTECTED = previous
    plan = {"architecture": "orchestrated-v1", "synthetic_business": True, "automatic_retry": False,
            "groups": samples[:-1], "primary": samples[-1], "turn_limit": 7, "case_run_limit": 1,
            "files": prior.hashes(FILES), "protected": prior.hashes(PROTECTED),
            "source_files": prior.hashes(["agent/src/resolveflow/support/" + p.name
                for p in (ROOT / "agent/src/resolveflow/support").glob("*.py")]), "resume_metrics": False}
    persist(OUT / "plan.json", plan)


def mechanics(report, plan):
    checks = []
    for group in plan["groups"]:
        runs = sorted((r for r in report["support_runs"]
                       if r["input_json"]["conversation_id"] == group["conversation_id"]),
                      key=lambda r: r["input_json"]["input_version"])
        checks.append({"group": group["id"], "check": "all_expected_answers",
                       "passed": len(runs) == len(group["turns"]) and all(r["status"] == "SUCCEEDED" for r in runs)})
        if not runs or any(r["status"] != "SUCCEEDED" for r in runs):
            continue
        answer = runs[-1]["result_json"]["answer"]
        no_refund = not answer.get("refund_summary")
        if group["id"] == "policy":
            names = [c["request_json"]["name"] for c in runs[-1]["calls"] if c["kind"] == "tool"]
            checks.append({"group": "policy", "check": "only_needed_policy_source_no_operations",
                           "passed": "search_policy" in names and not set(names).intersection({
                               "get_order_context", "get_shipment_trace", "get_support_guide"})
                           and no_refund and not answer.get("handoff_summary")})
        elif group["id"] == "correction":
            entries = answer["customer_memory"]["entries"]
            prior_claims = [e for e in runs[0]["result_json"]["answer"]["customer_memory"]["entries"]
                            if "家人" in e["quote"]]
            ids = {e["id"] for e in prior_claims}
            corrected = any(e["id"] in ids and e["status"] in {"SUPERSEDED", "RETRACTED"} for e in entries)
            active = any(e["status"] == "ACTIVE" and "家人" in e["quote"] and "没有" in e["quote"] for e in entries)
            checks.append({"group": "correction", "check": "actual_old_claim_replaced_new_claim_active",
                           "passed": corrected and active and no_refund})
        elif group["id"] == "pause":
            initial = runs[0]["result_json"]["answer"]
            ids = {t["id"] for t in initial["task_state"]["tasks"] if t["intent"] == "APPLICATION"}
            paused = any(t["id"] in ids and t.get("lifecycle") in {"PAUSED", "CANCELLED"}
                         for t in answer["task_state"]["tasks"])
            checks.append({"group": "pause", "check": "refund_goal_paused_and_no_new_reason",
                           "passed": bool(initial.get("refund_summary")) and paused and no_refund})
        else:
            checks.append({"group": "human", "check": "independent_handoff_no_refund",
                           "passed": bool(answer.get("handoff_summary")) and no_refund})
    return checks


def execute(stage):
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    assert prior.hashes(FILES) == plan["files"] and prior.hashes(PROTECTED) == plan["protected"]
    assert prior.hashes(plan["source_files"]) == plan["source_files"]
    if stage == "primary":
        review = json.loads((OUT / "controls-review.json").read_text(encoding="utf-8"))
        assert review["passed"] and review["source_review_complete"]
    settings, db = connect()
    try:
        assert demo.agent_health(settings, architecture="orchestrated-v1")
        with (PRIVATE / (stage + "-started.json")).open("x", encoding="utf-8") as f:
            json.dump({"stage": stage, "automatic_retry": False}, f)
        before = json.loads((PRIVATE / "policy/before.json").read_text(encoding="utf-8"))
        report = {"stage": stage, "scope": "real browser/Java/Python/DeepSeek; synthetic commerce", "success": False}
        accounted = 0 if stage == "controls" else json.loads(
            (OUT / "controls-runtime.json").read_text(encoding="utf-8"))["model_attempts"]
        with live_guard(LEDGER):
            usage = allowance(LEDGER)
            report["ledger_before"] = usage["used"]
            try:
                node = ROOT.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
                process = subprocess.run([str(node / "bin/node.exe"), f"scripts/check_support_adoption_{stage}_v1.cjs"],
                    cwd=ROOT, env={**os.environ, "NODE_PATH": str(node / "node_modules")},
                    timeout=600 if stage == "controls" else 420, check=False)
                report["browser_exit_code"] = process.returncode
            finally:
                previous = prior.PROTECTED
                prior.PROTECTED = PROTECTED
                try:
                    report.update(prior.collect(settings, db, before, plan["primary"]))
                finally:
                    prior.PROTECTED = previous
                report["stage_model_attempts"] = report["model_attempts"] - accounted
                assert report["stage_model_attempts"] >= 0
                usage["used"] += report["stage_model_attempts"]
                usage["save"]()
                report["ledger_after"] = usage["used"]
                report["mechanical_checks"] = mechanics(report, plan)
                report["success"] = (report.get("browser_exit_code") == 0
                    and all(check["passed"] for check in report["mechanical_checks"])
                    and all(p["unchanged"] for p in report["preservation"].values())
                    and len(report["general_runs"]) == (1 if stage == "primary" else 0)
                    and not report["unknown_usage"] and not report["pending_at_accounting"]
                    and not report["refund_operations"])
                persist(OUT / (stage + "-runtime.json"), report)
    finally:
        db.close()
    print(normalize({k: report[k] for k in ["stage", "success", "model_attempts", "stage_model_attempts",
                                          "ledger_before", "ledger_after", "mechanical_checks"]}))
    if not report["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "controls", "primary"])
    action = parser.parse_args().action
    prepare() if action == "prepare" else execute(action)
