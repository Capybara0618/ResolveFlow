"""Finite paired candidate comparison; same current foundations, actual independent result prefixes."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from scripts import customer_agent_experience_v3 as base

prior = base.prior
DIRECTORY = ROOT / "evals/customer-agent-staged-live-v1"
PLAN = DIRECTORY / "manifest.json"
VERSION = "customer-agent-staged-live-v1"


def load_cases():
    result = []
    for index, original in enumerate(base.load_cases()):
        order = ["single", "staged-v1"] if index % 2 == 0 else ["staged-v1", "single"]
        for architecture in order:
            result.append({**deepcopy(original), "id": original["id"] + ":" + architecture,
                           "source_id": original["id"], "architecture": architecture})
    return result


def prepare_turn(case, turn_index, completed):
    return prior.baseline.prepare_turn(
        {**case, "id": VERSION + ":" + case["id"]}, turn_index, completed, "agent",
    )


def freeze(path=PLAN):
    cases = load_cases()
    old = prior.read_json(base.PLAN)
    files = set(old["files"]) | {
        "evals/customer-agent-experience-v3/manifest.json", "scripts/customer_agent_experience_v3.py",
        "scripts/customer_agent_staged_live_v1.py", "docs/customer-agent-staged-live-v1.md",
        "docs/customer-agent-staged-v1.md", "reports/customer-agent-experience-v3/runtime-results.json",
        "agent/tests/unit/test_customer_agent_staged_live_v1.py",
        "agent/tests/integration/test_customer_agent_staged_live_v1.py",
        "agent/tests/unit/test_support_staged.py", "agent/tests/integration/test_support_staged_api.py",
        "agent/tests/unit/test_support_issue_retention.py", "agent/tests/unit/test_support_action_interface.py",
    }
    files.update(str(p.relative_to(ROOT)).replace("\\", "/")
                 for p in (ROOT / "agent/src/resolveflow/support").glob("*.py"))
    prior.write_new(path, {"version": VERSION, "conversations": 6, "turns": 12,
        "not_resume_metrics": True, "synthetic_facts": True, "not_holdout": True,
        "not_pure_decomposition_ablation": True,
        "order": [{"id": c["id"], "architecture": c["architecture"], "turns": len(c["turns"])} for c in cases],
        "files": {p: prior.digest(ROOT / p) for p in sorted(files)}, "embedding_files": old["embedding_files"]})


def load_plan(path=None):
    plan = prior.read_json(path or PLAN)
    if plan["version"] != VERSION:
        raise ValueError("wrong comparison version")
    for name, digest in plan["files"].items():
        if prior.digest(ROOT / name) != digest:
            raise ValueError("frozen source changed: " + name)
    for name, digest in plan["embedding_files"].items():
        if prior.digest(Path(prior.MODEL_PATH) / name) != digest:
            raise ValueError("embedding changed: " + name)
    return plan, load_cases()


def evaluate(output, usage_path):
    from resolveflow.support import service

    original_runtime = service.SupportRuntime
    profiles = {}

    def prepare(case, turn_index, completed):
        req, archive = prepare_turn(case, turn_index, completed)
        profiles[req.run_id] = case["architecture"]
        return req, archive

    class RoutedRuntime(original_runtime):
        def run(self, request, token):
            self.architecture = profiles[request.run_id]  # Controller-owned, never a model/customer argument.
            return super().run(request, token)

    with patch.object(prior, "PLAN", PLAN), patch.object(prior, "load_plan", load_plan), \
            patch.object(prior, "prepare_turn", prepare), patch.object(service, "SupportRuntime", RoutedRuntime):
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
                  "turns": sum(len(c["turns"]) for c in cases), "new_models": 0}
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
