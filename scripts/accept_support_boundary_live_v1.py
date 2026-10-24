"""Six frozen real-model checks using the existing streaming evaluator and isolated PG journal."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

from scripts import customer_current_eval as current
from scripts.customer_agent_eval_v2 import digest, read_json, write_new

from resolveflow.support.protocol import SupportFailure

ROOT = Path(__file__).resolve().parents[1]
VERSION = "customer-agent-boundary-live-v1"
PLAN = ROOT / "evals" / VERSION / "manifest.json"
SCENARIOS = PLAN.with_name("scenarios.json")
DIRECTORY = ROOT / "reports" / VERSION
USAGE = ROOT / "tmp/evaluation-live-budget.json"
MAX_ATTEMPTS = 24


def cases():
    selected = read_json(SCENARIOS)["cases"]
    snapshots = {c["snapshot_id"]: c["snapshot"] for c in current.load_cases()}
    if len(selected) != 6 or len({c["id"] for c in selected}) != 6:
        raise ValueError("expected six distinct cases")
    for case in selected:
        if len(case["turns"]) != 1 or not case["turns"][0]["criteria"]:
            raise ValueError("each case requires one scored turn")
        case["snapshot"] = snapshots[case["snapshot_id"]]
    return selected


def freeze():
    cases()
    inherited = read_json(ROOT / "evals/customer-current-evaluation-v1/manifest.json")
    names = set(inherited["files"]) | {
        "scripts/accept_support_boundary_live_v1.py",
        "evals/customer-agent-boundary-live-v1/scenarios.json",
        "docs/customer-agent-boundary-live-v1.md",
        "agent/tests/unit/test_support_boundary_live_driver.py",
    }
    write_new(PLAN, {"version": VERSION, "architecture": "orchestrated-v1", "conversations": 6, "turns": 6,
        "source_visible_regression": True, "independent_holdout": False,
        "max_new_provider_attempts": MAX_ATTEMPTS, "usage_start": read_json(USAGE)["used"],
        "files": {n: digest(ROOT / n) for n in sorted(names)},
        "embedding_files": {n: digest(Path(current.MODEL_PATH) / n) for n in inherited["embedding_files"]}})


def load_plan():
    value = read_json(PLAN)
    if value["max_new_provider_attempts"] != MAX_ATTEMPTS:
        raise ValueError("unexpected batch budget")
    for name, expected in value["files"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("frozen source changed: " + name)
    for name, expected in value["embedding_files"].items():
        if digest(Path(current.MODEL_PATH) / name) != expected:
            raise ValueError("frozen embedding changed: " + name)
    return value, cases()


def capped_model_class(start):
    class CappedModel(current.RecordedStreamingModel):
        def decide(self, **kwargs):
            if self.usage_ledger["used"] - start >= MAX_ATTEMPTS:
                raise SupportFailure("EVALUATION_ALLOWANCE_EXHAUSTED")
            return super().decide(**kwargs)

    return CappedModel


def execute(output):
    plan, _ = load_plan()
    if read_json(USAGE)["used"] != plan["usage_start"]:
        raise ValueError("usage changed since preparation; do not silently expand the batch")
    with patch.multiple(current, VERSION=VERSION, PLAN=PLAN, load_plan=load_plan,
                        RecordedStreamingModel=capped_model_class(plan["usage_start"])):
        current.evaluate(output, USAGE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["freeze", "check", "execute"])
    args = parser.parse_args()
    if args.mode == "freeze":
        freeze()
    elif args.mode == "check":
        plan, selected = load_plan()
        result = {"version": VERSION, "cases": len(selected), "new_provider_requests": 0,
                  "plan_sha256": digest(PLAN), "database": current.previous.check_database(selected, current.DSN)}
        write_new(DIRECTORY / "preflight.json", result)
    else:
        execute(DIRECTORY / "runtime-results.json")


if __name__ == "__main__":
    main()
