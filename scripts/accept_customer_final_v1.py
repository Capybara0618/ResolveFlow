"""One fixed final acceptance cohort; reuse measured streaming and accepted-state continuation."""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from resolveflow.support.protocol import SupportFailure

from scripts import customer_current_eval as current
from scripts.customer_agent_eval_v2 import digest, read_json, write_new

ROOT = current.ROOT
VERSION = "customer-final-acceptance-v1"
SCENARIOS = ROOT / "evals" / VERSION / "scenarios.json"
PLAN = SCENARIOS.with_name("manifest.json")
OUT = ROOT / "reports" / VERSION
USAGE = ROOT / "tmp/evaluation-live-budget.json"
MAX_ATTEMPTS = 40


def cases():
    selected = read_json(SCENARIOS)["cases"]
    snapshots = {c["id"]: c for c in read_json(ROOT / "evals/customer-agent-live-v3/cases.json")["cases"]}
    if len(selected) != 3 or [len(c["turns"]) for c in selected] != [5, 3, 3]:
        raise ValueError("expected fixed three conversations and eleven turns")
    if len({c["id"] for c in selected}) != 3:
        raise ValueError("duplicate case identity")
    for case in selected:
        case["snapshot"] = deepcopy(snapshots[case["snapshot_id"]])
        if any(not t["text"].strip() or not t["criteria"] for t in case["turns"]):
            raise ValueError("missing fixed input or review criteria")
    return selected


def freeze():
    cases()
    inherited = read_json(ROOT / "evals/customer-latency-session-live-v1/manifest.json")
    names = set(inherited["files"]) | {
        "scripts/accept_customer_final_v1.py", "evals/customer-final-acceptance-v1/scenarios.json",
        "docs/customer-final-acceptance-v1.md", "agent/tests/unit/test_customer_final_driver.py",
        "agent/src/resolveflow/api/app.py", "agent/src/resolveflow/harness/token_counting.py",
        "infra/logging.agent.json",
    }
    write_new(PLAN, {"version": VERSION, "architecture": "orchestrated-v1", "conversations": 3, "turns": 11,
        "source_visible_regression": True, "independent_holdout": False,
        "max_new_provider_attempts": MAX_ATTEMPTS, "usage_start": read_json(USAGE)["used"],
        "files": {name: digest(ROOT / name) for name in sorted(names)},
        "embedding_files": {name: digest(Path(current.MODEL_PATH) / name) for name in inherited["embedding_files"]}})


def load_plan():
    plan = read_json(PLAN)
    if (plan["turns"], plan["max_new_provider_attempts"]) != (11, MAX_ATTEMPTS):
        raise ValueError("frozen scope mismatch")
    for name, expected in plan["files"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("frozen source changed: " + name)
    for name, expected in plan["embedding_files"].items():
        if digest(Path(current.MODEL_PATH) / name) != expected:
            raise ValueError("frozen embedding changed: " + name)
    return plan, cases()


def capped_model_class(start):
    class CappedModel(current.RecordedStreamingModel):
        def decide(self, **kwargs):
            if self.usage_ledger["used"] - start >= MAX_ATTEMPTS:
                raise SupportFailure("EVALUATION_ALLOWANCE_EXHAUSTED")
            return super().decide(**kwargs)
    return CappedModel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["freeze", "check", "execute"])
    args = parser.parse_args()
    if args.mode == "freeze":
        freeze()
    elif args.mode == "check":
        _, selected = load_plan()
        write_new(OUT / "preflight.json", {"new_provider_requests": 0,
            "plan_sha256": digest(PLAN), "database": current.previous.check_database(selected, current.DSN)})
    else:
        plan, _ = load_plan()
        if read_json(USAGE)["used"] != plan["usage_start"]:
            raise ValueError("usage changed after preparation")
        with patch.multiple(current, VERSION=VERSION, PLAN=PLAN, load_plan=load_plan,
                            RecordedStreamingModel=capped_model_class(plan["usage_start"])):
            current.evaluate(OUT / "runtime-results.json", USAGE)


if __name__ == "__main__":
    main()
