"""Freeze/check/run the paired current Agent benchmark; live execution requires explicit new allowance."""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from resolveflow.support.service import SupportRuntime

from scripts import accept_customer_final_v1 as base
from scripts.customer_agent_eval_v2 import digest, read_json, write_new
from scripts.evaluation.customer_quantification_data import (
    DATA,
    ROOT,
    agent_cases,
    audit,
)
from scripts.evaluation.support_fixed_current import FixedCurrentRuntime

VERSION = "customer-quantification-v1"
PLAN = DATA / "agent-manifest.json"
OUT = ROOT / "reports/customer-quantification-v1"


def runs():
    selected = []
    for repeat in (1, 2):
        for index, case in enumerate(agent_cases()):
            order = ("dynamic", "fixed") if (index + repeat) % 2 else ("fixed", "dynamic")
            for variant in order:
                run = deepcopy(case)
                run.update(id=f"{case['id']}-{variant}-r{repeat}", source_case_id=case["id"],
                           variant=variant, repeat=repeat, scenario=case["family"])
                selected.append(run)
    return selected


def freeze():
    audit()
    inherited = read_json(ROOT / "evals/customer-phase-closeout-live-v1/manifest.json")
    names = set(inherited["files"]) | {
        "scripts/customer_quantification_agent.py", "scripts/evaluation/support_fixed_current.py",
        "scripts/evaluation/customer_quantification_data.py", "docs/customer-quantification-v1.md",
        "scripts/evaluation/customer_quantification_metrics.py", "scripts/customer_quantification_prepare.py",
        "evals/customer-quantification-v1/agent-cases.json", "evals/customer-quantification-v1/rag-queries.json",
        "agent/tests/unit/test_support_fixed_current.py", "agent/tests/unit/test_customer_quantification_data.py",
        "agent/tests/unit/test_customer_quantification_metrics.py", "agent/tests/unit/test_customer_quantification_rag.py",
        "agent/tests/integration/test_customer_quantification_runtime.py"}
    write_new(PLAN, {"version": VERSION, "architecture": "orchestrated-v1", "conversations": 128,
        "turns": sum(len(c["turns"]) for c in runs()), "source_visible_regression": True,
        "independent_holdout": False, "provider_allowance": "required explicitly at execution; none authorized in prep",
        "files": {name: digest(ROOT / name) for name in sorted(names)},
        "embedding_files": {name: digest(Path(base.current.MODEL_PATH) / name)
                            for name in inherited["embedding_files"]}})


def load_plan():
    plan = read_json(PLAN)
    for name, expected in plan["files"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("frozen source changed: " + name)
    for name, expected in plan["embedding_files"].items():
        if digest(Path(base.current.MODEL_PATH) / name) != expected:
            raise ValueError("frozen embedding changed: " + name)
    return plan, runs()


def execute(output, limit):
    load_plan()
    start = read_json(base.USAGE)["used"]
    registry = {}

    def prepare(case, turn_index, completed):
        request, archive = original_prepare(case, turn_index, completed)
        registry[request.run_id] = case["variant"]
        return request, archive

    class DispatchRuntime(SupportRuntime):
        def run(self, request, token, *, progress_token=None):
            if registry[request.run_id] == "fixed":
                fixed = FixedCurrentRuntime(self.database, self.config, model_factory=self.model_factory,
                    sources_factory=self.sources_factory, embeddings=self.embeddings, architecture=self.architecture)
                return fixed.run(request, token, progress_token=progress_token)
            return super().run(request, token, progress_token=progress_token)

    original_prepare = base.current.prepare_turn
    with (patch.object(base, "MAX_ATTEMPTS", limit),
          patch("resolveflow.support.service.SupportRuntime", DispatchRuntime),
          patch.multiple(base.current, VERSION=VERSION, PLAN=PLAN, load_plan=load_plan, prepare_turn=prepare,
                         RecordedStreamingModel=base.capped_model_class(start))):
        base.current.evaluate(output, base.USAGE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["freeze", "check", "execute"])
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-provider-requests", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        freeze()
    elif args.mode == "check":
        _, selected = load_plan()
        report = {"dataset": audit(), "database": base.current.previous.check_database(selected, base.current.DSN),
                  "new_provider_requests": 0, "measured_effect": None}
        if args.output:
            write_new(args.output, report)
        print({key: value for key, value in report.items() if key != "database"})
    else:
        if not args.live or not args.max_provider_requests or args.max_provider_requests <= 0 or not args.output:
            parser.error("execute requires --live, a positive --max-provider-requests and new --output")
        execute(args.output, args.max_provider_requests)


if __name__ == "__main__":
    main()
