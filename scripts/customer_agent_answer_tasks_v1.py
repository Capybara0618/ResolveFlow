"""Two seen autonomous inputs under a new immutable source manifest after the answer-task repair."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from scripts import customer_agent_annotation_check_v1 as prior

DIRECTORY = ROOT / "evals/customer-agent-answer-tasks-v1"
PLAN = DIRECTORY / "manifest.json"
driver = prior.driver
original_cases = prior.load_cases


def load_cases():
    with patch.object(prior, "DIRECTORY", DIRECTORY):
        cases = original_cases()
    old = original_cases()
    for case, previous in zip(cases, old, strict=True):
        for key in ["run_id", "conversation_id"]:
            if case["input_without_deadline"][key] == previous["input_without_deadline"][key]:
                raise ValueError("fresh run and conversation identities required")
        if any(case[k] != previous[k] for k in ["facts", "http_status", "pinned_generations", "criteria"]):
            raise ValueError("old conditions changed")
        new_input, old_input = case["input_without_deadline"], previous["input_without_deadline"]
        if {k: v for k, v in new_input.items() if k not in {"run_id", "conversation_id"}} != {
            k: v for k, v in old_input.items() if k not in {"run_id", "conversation_id"}
        }:
            raise ValueError("original request changed")
    return cases


def freeze(path=PLAN):
    load_cases()
    old = prior.preparation.read_json(prior.PLAN)
    files = set(old["files"]) | {
        "evals/customer-agent-annotation-check-v1/manifest.json",
        "reports/customer-agent-annotation-check-v1/runtime-results.json",
        "evals/customer-agent-answer-tasks-v1/cases.json", "scripts/customer_agent_answer_tasks_v1.py",
        "agent/tests/unit/test_customer_agent_answer_tasks_v1.py", "agent/tests/unit/test_support_answer_tasks.py",
        "docs/customer-agent-answer-tasks-v1.md",
    }
    prior.preparation.write_new(path, {
        "version": "customer-agent-answer-tasks-v1", "autonomous_turns": 2,
        "factual_scope": "Two seen synthetic HTTP snapshots; actual model/ASGI/AgentScope/PG, no Java/browser",
        "files": {p: prior.preparation.digest(ROOT / p) for p in sorted(files)},
        "embedding_files": old["embedding_files"],
    })


def load_plan(path=PLAN):
    with patch.object(prior, "load_cases", load_cases):
        return prior.load_plan(path)


def execute(output, usage):
    with patch.object(driver, "PLAN", PLAN), patch.object(driver, "load_plan", load_plan):
        driver.evaluate(output, usage)


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
            scoped = [{"id": c["id"], "snapshot": c, "turns": [{
                "text": c["input_without_deadline"]["context"]["current_request"], "criteria": c["criteria"]
            }]} for c in plan["cases"]]
            result["database"] = prior.preparation.previous.check_database(scoped, driver.DSN)
        if args.output:
            prior.preparation.write_new(args.output, result)
        print(json.dumps({k: v for k, v in result.items() if k != "database"}))
    elif args.output is None:
        parser.error("--output required")
    else:
        execute(args.output, args.live_usage)


if __name__ == "__main__":
    main()
