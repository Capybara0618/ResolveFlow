"""One frozen five-turn summary acceptance using the existing live streaming evaluator."""

from __future__ import annotations

import argparse
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from resolveflow.harness.model import ModelReply
from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import SupportFailure, SupportInput

from scripts import customer_current_eval as current
from scripts.customer_agent_eval_v2 import digest, read_json, write_new
from scripts.customer_rag_live_v2 import persist
from scripts.diagnose_support_boundary_v1 import SavedSources

ROOT = Path(__file__).resolve().parents[1]
VERSION = "customer-agent-summary-live-v1"
PLAN = ROOT / "evals" / VERSION / "manifest.json"
SCENARIOS = PLAN.with_name("scenarios.json")
DIRECTORY = ROOT / "reports" / VERSION
USAGE = ROOT / "tmp/evaluation-live-budget.json"
MAX_ATTEMPTS = 24
GOAL_ATTEMPTS = 6


def cases():
    selected = read_json(SCENARIOS)["cases"]
    snapshots = {c["snapshot_id"]: c["snapshot"] for c in current.load_cases()}
    if len(selected) != 2 or sum(len(c["turns"]) for c in selected) != 5:
        raise ValueError("expected two conversations and five turns")
    for case in selected:
        if not all(t["criteria"] for t in case["turns"]):
            raise ValueError("missing criteria")
        case["snapshot"] = snapshots[case["snapshot_id"]]
    return selected


def freeze():
    cases()
    inherited = read_json(ROOT / "evals/customer-current-evaluation-v1/manifest.json")
    names = set(inherited["files"]) | {
        "scripts/accept_support_summary_live_v1.py", "evals/customer-agent-summary-live-v1/scenarios.json",
        "docs/customer-agent-summary-live-v1.md", "agent/tests/unit/test_support_summary_live_driver.py",
        "docs/customer-agent-summary-grounding-v1.md", "scripts/diagnose_support_boundary_v1.py",
        "reports/customer-agent-close-v1/runtime-results.json",
        "reports/customer-agent-summary-live-v1/browser/plan.json",
        "scripts/accept_customer_fact_fields_v1.py", "scripts/accept_chat_refund_live_v1.py",
        "scripts/product_flow_acceptance.py", "scripts/reviewer_demo.py", "scripts/logistics_simulator.py",
    }
    write_new(PLAN, {"version": VERSION, "architecture": "orchestrated-v1", "conversations": 2, "turns": 5,
        "source_visible_regression": True, "independent_holdout": False,
        "max_new_provider_attempts": MAX_ATTEMPTS, "usage_start": read_json(USAGE)["used"],
        "separate_goal_max_provider_attempts": GOAL_ATTEMPTS, "browser_max_provider_attempts": 12,
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
        raise ValueError("usage changed since preparation")
    with patch.multiple(current, VERSION=VERSION, PLAN=PLAN, load_plan=load_plan,
                        RecordedStreamingModel=capped_model_class(plan["usage_start"])):
        current.evaluate(output, USAGE)


def injected_model_class(start, prefix):
    class InjectedModel(current.RecordedStreamingModel):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.prefix = deepcopy(prefix)
            self.prefix_records = []

        def decide(self, **kwargs):
            if self.prefix:
                decision = self.prefix.pop(0)
                self.prefix_records.append({"mode": "mock", "origin": "EXPLICIT_INJECTED_PREFIX",
                    "decision": deepcopy(decision), "provider_requests": 0,
                    "body": self.prepare_request(system=kwargs["system"], messages=kwargs["messages"],
                                                 max_output_tokens=kwargs["max_output_tokens"])})
                return ModelReply(decision=decision, mode="mock", model_alias="recorded-prefix-not-provider")
            if self.usage_ledger["used"] - start >= GOAL_ATTEMPTS:
                raise SupportFailure("EVALUATION_ALLOWANCE_EXHAUSTED")
            return super().decide(**kwargs)

    return InjectedModel


def goal():
    load_plan()
    previous = read_json(DIRECTORY / "runtime-results.json")
    if previous["state"] != "FINISHED" or read_json(USAGE)["used"] != previous["usage_after"]:
        raise ValueError("cohort must finish and usage must match")
    source = read_json(ROOT / "reports/customer-agent-close-v1/runtime-results.json")
    row = next(r for r in source["rows"] if (r["id"], r["turn"]) == ("M02", 2))
    prefix = deepcopy([m["decision"] for m in row["models"][:3]])
    prefix[-1]["handoff_reason"] = {"customer_quotes": ["新发现耳机外壳有损坏"]}
    req = SupportInput.model_validate({**row["input"], "deadline_at": datetime.now(UTC) + timedelta(seconds=120)})
    output = DIRECTORY / "goal-continuation.json"
    report = {"natural_conversation": False, "explicit_mock_prefix": prefix,
              "max_real_provider_requests": GOAL_ATTEMPTS, "real_models": [], "state": "STARTED"}
    write_new(output, report)
    sources = SavedSources(row["calls"])
    with current.live_guard(USAGE):
        usage = current.allowance(USAGE)
        report["usage_before"] = usage["used"]

        def save(records):
            report["real_models"] = records
            persist(output, report)

        model = injected_model_class(usage["used"], prefix)(usage=usage, save=save, provider="deepseek",
            model_id="deepseek-flash", endpoint="https://api.deepseek.com/chat/completions",
            api_key=os.environ["Deepseek_API_KEY"], timeout_seconds=30, parameters={"thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"}, "temperature": 0})
        agent = SupportAgent(req, model, sources, architecture="orchestrated-v1", provider_capacity=32768)
        try:
            report["result"] = agent.run()
            report["state"] = "FINISHED"
        finally:
            report.update(usage_after=usage["used"], prefix_records=model.prefix_records,
                          source_reads=sources.calls, goal_reviews=agent.orchestration.goal_reviews,
                          repairs=agent.repairs)
            persist(output, report)
    print({"diagnostic": "injected-prefix-real-continuation", "status": report["result"]["status"],
           "real_calls": len(report["real_models"]), "reviews": len(report["goal_reviews"])})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["freeze", "check", "execute", "goal"])
    args = parser.parse_args()
    if args.mode == "freeze":
        freeze()
    elif args.mode == "check":
        _, selected = load_plan()
        write_new(DIRECTORY / "preflight.json", {"new_provider_requests": 0,
            "plan_sha256": digest(PLAN), "database": current.previous.check_database(selected, current.DSN)})
    elif args.mode == "goal":
        goal()
    else:
        execute(DIRECTORY / "runtime-results.json")


if __name__ == "__main__":
    main()
