"""Three frozen real turns after policy-floor and independent-fact batching changes."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

from resolveflow.support.protocol import SupportFailure

from scripts import customer_current_eval as current
from scripts.customer_agent_eval_v2 import digest, read_json, write_new

VERSION = "customer-policy-batch-live-v1"
ROOT = current.ROOT
PLAN = ROOT / "evals" / VERSION / "manifest.json"
SCENARIOS = PLAN.with_name("scenarios.json")
OUT = ROOT / "reports" / VERSION
USAGE = ROOT / "tmp/evaluation-live-budget.json"
MAX_ATTEMPTS = 18


def cases():
    selected = read_json(SCENARIOS)["cases"]
    snapshots = {c["snapshot_id"]: c["snapshot"] for c in current.load_cases()}
    if len(selected) != 3 or any(len(c["turns"]) != 1 or not c["turns"][0]["criteria"] for c in selected):
        raise ValueError("expected three independent single-turn cases with criteria")
    for case in selected:
        case["snapshot"] = snapshots[case["snapshot_id"]]
    return selected


def freeze():
    cases()
    inherited = read_json(ROOT / "evals/customer-agent-summary-live-v1/manifest.json")
    names = set(inherited["files"]) | {
        "scripts/accept_support_policy_batch_live_v1.py", "evals/customer-policy-batch-live-v1/scenarios.json",
        "agent/tests/unit/test_support_policy_batch_live_driver.py", "docs/customer-policy-batch-live-v1.md",
        "docs/customer-refund-policy-readiness-v1.md", "docs/customer-agent-fact-batch-v1.md",
    }
    write_new(PLAN, {"version": VERSION, "architecture": "orchestrated-v1", "turns": 3,
        "source_visible_regression": True, "independent_holdout": False,
        "max_new_provider_attempts": MAX_ATTEMPTS, "usage_start": read_json(USAGE)["used"],
        "files": {n: digest(ROOT / n) for n in sorted(names)},
        "embedding_files": {n: digest(Path(current.MODEL_PATH) / n) for n in inherited["embedding_files"]}})


def load_plan():
    value = read_json(PLAN)
    if value["max_new_provider_attempts"] != MAX_ATTEMPTS:
        raise ValueError("unexpected cohort bound")
    for name, expected in value["files"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("frozen source changed: " + name)
    for name, expected in value["embedding_files"].items():
        if digest(Path(current.MODEL_PATH) / name) != expected:
            raise ValueError("frozen weights changed: " + name)
    return value, cases()


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
            raise ValueError("usage changed since preparation")
        with patch.multiple(current, VERSION=VERSION, PLAN=PLAN, load_plan=load_plan,
                            RecordedStreamingModel=capped_model_class(plan["usage_start"])):
            current.evaluate(OUT / "runtime-results.json", USAGE)


if __name__ == "__main__":
    main()
