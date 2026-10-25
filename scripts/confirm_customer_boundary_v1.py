"""One capped repair confirmation on the original eleven inputs and review criteria."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

from scripts import accept_customer_final_v1 as base
from scripts.customer_agent_eval_v2 import digest, read_json, write_new

ROOT = base.ROOT
VERSION = "customer-boundary-confirm-live-v1"
PLAN = ROOT / "evals" / VERSION / "manifest.json"
OUT = ROOT / "reports" / VERSION


def load_plan():
    with patch.object(base, "PLAN", PLAN):
        return base.load_plan()


def freeze():
    old = read_json(base.PLAN)
    names = set(old["files"]) | {"scripts/confirm_customer_boundary_v1.py",
        "scripts/diagnose_customer_closeout_v1.py", "docs/customer-boundary-closeout-v1.md",
        "agent/tests/unit/test_support_boundary_closeout.py",
        "agent/tests/integration/test_support_boundary_closeout_runtime.py"}
    write_new(PLAN, {"version": VERSION, "architecture": "orchestrated-v1", "conversations": 3, "turns": 11,
        "source_visible_regression": True, "independent_holdout": False,
        "original_scenarios_sha256": digest(base.SCENARIOS), "prior_manifest_sha256": digest(base.PLAN),
        "max_new_provider_attempts": base.MAX_ATTEMPTS, "usage_start": read_json(base.USAGE)["used"],
        "files": {name: digest(ROOT / name) for name in sorted(names)},
        "embedding_files": {name: digest(Path(base.current.MODEL_PATH) / name) for name in old["embedding_files"]}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["freeze", "check", "execute"])
    args = parser.parse_args()
    if args.mode == "freeze":
        freeze()
    elif args.mode == "check":
        _, cases = load_plan()
        write_new(OUT / "preflight.json", {"new_provider_requests": 0, "plan_sha256": digest(PLAN),
            "database": base.current.previous.check_database(cases, base.current.DSN)})
    else:
        plan, _ = load_plan()
        if read_json(base.USAGE)["used"] != plan["usage_start"]:
            raise ValueError("usage changed after preparation")
        with patch.multiple(base.current, VERSION=VERSION, PLAN=PLAN, load_plan=load_plan,
                            RecordedStreamingModel=base.capped_model_class(plan["usage_start"])):
            base.current.evaluate(OUT / "runtime-results.json", base.USAGE)


if __name__ == "__main__":
    main()
