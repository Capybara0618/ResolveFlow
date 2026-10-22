"""Frozen finite post-refactor comparison, inheriting accepted state even when an answer failed."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from scripts import customer_agent_staged_live_v1 as base

prior = base.prior
VERSION = "customer-agent-state-live-v1"
PLAN = ROOT / "evals/customer-agent-state-live-v1/manifest.json"


def load_cases():
    cases = base.load_cases()
    template = next(c for c in cases if c["source_id"] == "U02")
    for mode in ["single", "staged-v1"]:
        case = deepcopy(template)
        case.update(id="U06:" + mode, source_id="U06", architecture=mode,
                    scenario="核实订单实付与付款状态", partition="development-visible-extension")
        case["turns"] = [{"text": "先不看退款资格，帮我核对这笔台灯订单的实付金额和付款状态。不要替我提交申请。",
                          "criteria": ["实付129.00CNY及PAID由本轮订单来源核实，不混作物流LOST",
                                       "回答当前金额及付款状态，不虚构提交申请或转交"]}]
        cases.append(case)
    return cases


def prepare_turn(case, turn_index, completed):
    req, archive = prior.baseline.prepare_turn(
        {**case, "id": VERSION + ":" + case["id"]}, turn_index, completed, "agent")
    req.context.pop("previous_tasks", None)
    req.context.pop("previous_customer_memory", None)
    for result in reversed(completed):
        update = result.get("conversation_update")
        if update is not None:
            if update.get("version") != "support-state-v1" or any(
                update.get(key) != (result[key] if key in {"run_id", "input_version"} else getattr(req, key))
                for key in ("run_id", "conversation_id", "input_version", "merchant_id", "customer_id", "line_id")
            ):
                raise ValueError("accepted update scope mismatch")
            state = update
        elif result["status"] == "SUCCEEDED":
            state = result["answer"]
        else:
            continue
        tasks = state.get("task_state", {}).get("tasks")
        if tasks:
            req.context["previous_tasks"] = {"origin": "MODEL_PREVIOUS_TURN",
                "input_version": result["input_version"], "tasks": deepcopy(tasks)}
        memory = state.get("customer_memory")
        if memory is not None:
            if memory.get("input_version") != result["input_version"] or any(
                memory.get(key) != getattr(req, key)
                for key in ("conversation_id", "merchant_id", "customer_id", "line_id")
            ):
                raise ValueError("customer memory scope mismatch")
            req.context["previous_customer_memory"] = deepcopy(memory)
        break
    return req, archive


def freeze(path=PLAN):
    cases = load_cases()
    old = prior.read_json(base.PLAN)
    files = set(old["files"]) | {
        "evals/customer-agent-staged-live-v1/manifest.json", "scripts/customer_agent_staged_live_v1.py",
        "scripts/customer_agent_state_live_v1.py", "docs/customer-agent-state-live-v1.md",
        "docs/customer-agent-state-refactor-v1.md", "reports/customer-agent-staged-live-v1/runtime-results.json",
        "agent/tests/unit/test_customer_agent_state_live_v1.py",
        "agent/tests/integration/test_customer_agent_state_live_v1.py",
        "agent/tests/unit/test_support_customer_claims.py", "agent/tests/unit/test_support_refine_needs.py",
        "agent/tests/unit/test_support_grounding.py", "agent/tests/unit/test_support_state_feedback.py",
        "agent/tests/integration/test_support_conversation_update.py",
        "contracts/core/openapi-agent.yaml", "contracts/core/fixtures/support-agent.json",
        "java/case-service/src/main/java/com/resolveflow/caseservice/support/SupportAgentTurns.java",
    }
    files.update(str(p.relative_to(ROOT)).replace("\\", "/")
                 for p in (ROOT / "agent/src/resolveflow/support").glob("*.py"))
    prior.write_new(path, {"version": VERSION, "conversations": 8, "turns": 14,
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

    original = service.SupportRuntime
    profiles = {}

    def prepare(case, index, completed):
        req, archive = prepare_turn(case, index, completed)
        profiles[req.run_id] = case["architecture"]
        return req, archive

    class ProfileRuntime(original):
        def run(self, request, token):
            self.architecture = profiles[request.run_id]
            return super().run(request, token)

    with patch.object(prior, "PLAN", PLAN), patch.object(prior, "load_plan", load_plan), \
            patch.object(prior, "prepare_turn", prepare), patch.object(service, "SupportRuntime", ProfileRuntime):
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
        result = {"version": plan["version"], "conversations": len(cases), "turns": 14, "new_models": 0}
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
