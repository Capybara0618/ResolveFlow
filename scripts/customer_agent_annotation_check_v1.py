"""Two bounded autonomous checks after the metadata repair, using the existing single-turn API driver."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from scripts import customer_agent_action_smoke_v1 as prior
from scripts import customer_agent_eval_v2 as preparation
from scripts import customer_rag_live_v2 as driver

DIRECTORY = ROOT / "evals/customer-agent-annotation-check-v1"
PLAN = DIRECTORY / "manifest.json"


def load_cases():
    cases = preparation.read_json(DIRECTORY / "cases.json")["cases"]
    originals = {c["id"]: c for c in preparation.load_cases()}
    if len(cases) != 2:
        raise ValueError("expected exactly two autonomous checks")
    for c, source in zip(cases, ["D01", "D02"], strict=True):
        old = originals[source]
        if (c["source_case"] != source or c["criteria"] != old["turns"][0]["criteria"]
                or c["input_without_deadline"]["context"]["current_request"] != old["turns"][0]["text"]):
            raise ValueError("original input/criteria changed")
        for key in ["facts", "http_status", "pinned_generations"]:
            if c[key] != old["snapshot"][key]:
                raise ValueError("original facts/pins changed")
    return cases


def freeze(path=PLAN):
    load_cases()
    old = preparation.read_json(prior.PLAN)
    files = set(old["files"])
    files.update([
        "evals/customer-agent-action-smoke-v1/manifest.json", "evals/customer-agent-annotation-check-v1/cases.json",
        "reports/customer-agent-action-smoke-v1/runtime-results.json", "scripts/customer_agent_annotation_check_v1.py",
        "agent/tests/unit/test_customer_agent_annotation_check_v1.py",
        "agent/tests/unit/test_support_annotation_repair.py", "docs/customer-agent-annotation-repair-v1.md",
    ])
    preparation.write_new(path, {"version": "customer-agent-annotation-check-v1", "autonomous_turns": 2,
                                 "factual_scope": "Two seen synthetic HTTP snapshots, actual model/API/SDK/PG; no Java/browser",
                                 "files": {p: preparation.digest(ROOT / p) for p in sorted(files)},
                                 "embedding_files": old["embedding_files"]})


def load_plan(path=PLAN):
    plan = preparation.read_json(path)
    for name, fingerprint in plan["files"].items():
        if preparation.digest(ROOT / name) != fingerprint:
            raise ValueError("frozen source changed: " + name)
    for name, fingerprint in plan["embedding_files"].items():
        if preparation.digest(Path(driver.MODEL_PATH) / name) != fingerprint:
            raise ValueError("embedding changed: " + name)
    return {**plan, "cases": load_cases()}


def execute(output, usage_path):
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
        plan = load_plan()
        result = {"version": plan["version"], "autonomous_turns": len(plan["cases"]), "new_models": 0}
        if args.database:
            scoped = [{"id": c["id"], "snapshot": deepcopy(c), "turns": [{
                "text": c["input_without_deadline"]["context"]["current_request"], "criteria": c["criteria"]
            }]} for c in plan["cases"]]
            result["database"] = preparation.previous.check_database(scoped, driver.DSN)
        if args.output:
            preparation.write_new(args.output, result)
        print(json.dumps({k: v for k, v in result.items() if k != "database"}))
    elif args.output is None:
        parser.error("--output required")
    else:
        execute(args.output, args.live_usage)


if __name__ == "__main__":
    main()
