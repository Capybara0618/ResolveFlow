"""New frozen small cohort reusing the measured v2 driver; no historical manifest replacement."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from scripts import customer_agent_eval_v2 as driver

DIRECTORY = ROOT / "evals/customer-agent-action-smoke-v1"
PLAN = DIRECTORY / "manifest.json"
SELECTION = [("S01", "D01", 1), ("S02", "D02", 1), ("S03", "D13", 4)]


def load_cases():
    source = {c["id"]: c for c in driver.load_cases()}
    cases = driver.read_json(DIRECTORY / "cases.json")["cases"]
    if len(cases) != 3:
        raise ValueError("expected three smoke conversations")
    for case, (name, original, count) in zip(cases, SELECTION, strict=True):
        prior = source[original]
        if (case["id"] != name or case["source_case"] != original
                or case["turns"] != prior["turns"][:count] or case["snapshot_id"] != prior["snapshot_id"]):
            raise ValueError("smoke must retain selected original inputs and conditions")
        case["snapshot"] = deepcopy(prior["snapshot"])
    return cases


def freeze(path=PLAN):
    load_cases()
    original = driver.read_json(ROOT / "evals/customer-agent-eval-v2/manifest.json")
    files = set(original["files"])
    files.update([
        "evals/customer-agent-eval-v2/manifest.json", "evals/customer-agent-action-smoke-v1/cases.json",
        "scripts/customer_agent_action_smoke_v1.py", "docs/customer-agent-action-repair-v1.md",
        "agent/tests/unit/test_customer_agent_action_smoke_v1.py", "agent/tests/unit/test_support_guidance.py",
        "reports/customer-agent-eval-v2/runtime-results.json",
    ])
    driver.write_new(path, {"version": "customer-agent-action-smoke-v1", "groups": ["agent", "fixed"],
                            "conversations_per_group": 3, "turns_per_group": 6,
                            "synthetic": True, "not_independent_holdout": True,
                            "selection": SELECTION, "files": {p: driver.digest(ROOT / p) for p in sorted(files)},
                            "embedding_files": original["embedding_files"]})


def load_plan(path=PLAN):
    plan = driver.read_json(path)
    for name, fingerprint in plan["files"].items():
        if driver.digest(ROOT / name) != fingerprint:
            raise ValueError("frozen source changed: " + name)
    for name, fingerprint in plan["embedding_files"].items():
        if driver.digest(Path(driver.MODEL_PATH) / name) != fingerprint:
            raise ValueError("frozen embedding changed: " + name)
    return plan, load_cases()


def execute(output, usage_path):
    # The old file remains byte-for-byte frozen. Only this process's loader and plan pointer are adapted.
    with patch.object(driver, "PLAN", PLAN), patch.object(driver, "load_plan", load_plan):
        driver.evaluate(output, usage_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--database", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--live-usage", type=Path, default=ROOT / "tmp/evaluation-live-budget.json")
    args = parser.parse_args()
    if args.freeze:
        freeze()
    elif args.check:
        plan, cases = load_plan()
        result = {"version": plan["version"], "conversations_per_group": len(cases),
                  "turns_per_group": sum(len(c["turns"]) for c in cases), "new_models": 0}
        if args.database:
            result["database"] = driver.previous.check_database(cases, driver.DSN)
        if args.output:
            driver.write_new(args.output, result)
        print(json.dumps({k: v for k, v in result.items() if k != "database"}))
    elif args.output is None:
        parser.error("--output required")
    else:
        execute(args.output, args.live_usage)


if __name__ == "__main__":
    main()
