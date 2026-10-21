"""Frozen same-input regression after support Harness changes; delegates the existing measured API driver."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from scripts import customer_rag_live_v2 as driver  # noqa: E402

PLAN = ROOT / "evals/customer-agent-live-v3/cases.json"


def verify_plan():
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    binding = plan["baseline"]
    source = ROOT / binding["plan_path"]
    if driver.digest(source) != binding["plan_sha256"]:
        raise ValueError("frozen baseline plan changed")
    baseline = json.loads(source.read_text(encoding="utf-8"))
    for old, new in zip(baseline["cases"], plan["cases"], strict=True):
        expected, actual = deepcopy(old), deepcopy(new)
        for case in [expected, actual]:
            case["input_without_deadline"].pop("run_id")
            case["input_without_deadline"].pop("conversation_id")
        if expected != actual:
            raise ValueError("regression must retain exact business inputs, facts, pins and criteria")
        if old["input_without_deadline"]["run_id"] == new["input_without_deadline"]["run_id"]:
            raise ValueError("new implementation cannot resume an old run")
    for relative, fingerprint in binding["reports"].items():
        if driver.digest(ROOT / relative) != fingerprint:
            raise ValueError("baseline result changed")
    if driver.digest(Path(__file__)) != plan["runner_sha256"]:
        raise ValueError("frozen regression runner changed")
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live-usage", type=Path, default=ROOT / "tmp/evaluation-live-budget.json")
    args = parser.parse_args()
    if not args.execute:
        parser.error("explicit --execute required")
    verify_plan()
    driver.PLAN = PLAN
    driver.evaluate(args.output, args.live_usage)


if __name__ == "__main__":
    main()
