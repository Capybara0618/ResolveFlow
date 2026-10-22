"""One finite confirmation of task-resolution changes, reusing the tested autonomous executor."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from scripts import customer_agent_experience_v1 as prior

DIRECTORY = ROOT / "evals/customer-agent-experience-v2"
PLAN = DIRECTORY / "manifest.json"
VERSION = "customer-agent-experience-v2"


def load_cases():
    original = prior.read_json(prior.DIRECTORY / "scenarios.json")["cases"]
    selected = prior.read_json(DIRECTORY / "scenarios.json")["cases"]
    if selected != original:
        raise ValueError("v2 must preserve original questions, facts and criteria")
    return deepcopy(prior.load_cases())


def prepare_turn(case, turn_index, completed):
    return prior.baseline.prepare_turn(
        {**case, "id": "experience-v2:" + case["id"]}, turn_index, completed, "agent",
    )


def freeze(path=PLAN):
    load_cases()
    old = prior.read_json(prior.PLAN)
    files = set(old["files"]) | {
        "scripts/customer_agent_experience_v1.py", "scripts/customer_agent_experience_v2.py",
        "evals/customer-agent-experience-v1/manifest.json", "evals/customer-agent-experience-v2/scenarios.json",
        "reports/customer-agent-experience-v1/runtime-results.json", "docs/customer-agent-experience-v2.md",
        "docs/customer-agent-task-resolution-v1.md", "agent/tests/unit/test_customer_agent_experience_v2.py",
        "agent/tests/integration/test_customer_agent_experience_v2.py",
        "agent/tests/unit/test_support_activity.py", "agent/tests/unit/test_support_completion.py",
    }
    files.update(str(p.relative_to(ROOT)).replace("\\", "/")
                 for p in (ROOT / "agent/src/resolveflow/support").glob("*.py"))
    prior.write_new(path, {"version": VERSION, "conversations": 5, "turns": 8, "not_resume_metrics": True,
                           "synthetic_facts": True, "not_holdout": True,
                           "files": {p: prior.digest(ROOT / p) for p in sorted(files)},
                           "embedding_files": old["embedding_files"]})


def load_plan(path=None):
    plan = prior.read_json(path or PLAN)
    if plan["version"] != VERSION:
        raise ValueError("wrong experience version")
    for name, digest in plan["files"].items():
        if prior.digest(ROOT / name) != digest:
            raise ValueError("frozen source changed: " + name)
    for name, digest in plan["embedding_files"].items():
        if prior.digest(Path(prior.MODEL_PATH) / name) != digest:
            raise ValueError("embedding changed: " + name)
    return plan, load_cases()


def evaluate(output, usage_path):
    # Single-process adapter only: no production loop, route or evaluator logic is changed.
    with patch.object(prior, "PLAN", PLAN), patch.object(prior, "load_plan", load_plan), \
            patch.object(prior, "prepare_turn", prepare_turn):
        prior.evaluate(output, usage_path)


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
        result = {"version": plan["version"], "conversations": len(cases),
                  "turns": sum(len(c["turns"]) for c in cases), "new_models": 0, "not_resume_metrics": True}
        if args.database:
            result["database"] = prior.baseline.previous.check_database(cases, prior.DSN)
        if args.output:
            prior.write_new(args.output, result)
        print({k: v for k, v in result.items() if k != "database"})
    elif args.output is None:
        parser.error("--output required")
    else:
        evaluate(args.output, args.live_usage)


if __name__ == "__main__":
    main()
