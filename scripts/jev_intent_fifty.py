"""One pass over all fifty historical customer turns; at most 50 Jev + 50 primary calls."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from jev_compare import Allowance, RecordedModel, write
from jev_intent_eval import RecordedChoices
from jev_intent_eval import summarize as original_summary
from resolveflow.harness.context import canonical_json
from resolveflow.harness.sdk_adapter import raw_text_message
from resolveflow.support.jev import JevConfig, load_local_env
from resolveflow.support.jev_intent import (
    OPTIONS,
    IntentPolicy,
    build_intent_request,
    intent_decision,
    pending_tasks,
)
from resolveflow.support.orchestration_prompts import REQUEST_CHECK_SYSTEM
from resolveflow.support.request_check import RequestCheck

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "agent/tests/fixtures/jev-intent-fifty-v1.json"
VERSION = "jev-intent-fifty-v1"
OPERATIONS = {"PREPARE_REFUND", "MERCHANT_REVIEW"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_fixture() -> dict[str, Any]:
    fixture = json.loads(FIXTURE.read_bytes())
    for name, sha in fixture["sources"].items():
        if digest(ROOT / name) != sha:
            raise ValueError("historical source changed: " + name)
    source = json.loads((ROOT / "evals/customer-workflow-comparison-v2/cases.json").read_bytes())
    original = [(c["id"], i, t["text"]) for c in source["cases"] for i, t in enumerate(c["turns"], 1)]
    actual = [(c["source_case"], c["source_turn"], c["packet"]["current_request"]) for c in fixture["cases"]]
    if original != actual or len(actual) != 50:
        raise ValueError("all original fifty turns are required in original order")
    for case in fixture["cases"]:
        tasks = pending_tasks(case["packet"])
        if {t["task_id"] for t in tasks} != set(case["expected"]) or not set(case["expected"].values()) <= set(OPTIONS):
            raise ValueError("fixed task labels required")
    return fixture


class CappedAllowance(Allowance):
    def __init__(self, directory: Path) -> None:
        super().__init__(directory)
        self.by_role: Counter[str] = Counter()

    def reserve(self, role: str, body: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        if role not in {"jev", "intent-baseline"} or self.calls >= 100 or self.by_role[role] >= 50:
            raise ValueError("one-pass request cap reached")
        result = super().reserve(role, body)
        self.by_role[role] += 1
        return result


class MeteredModel(RecordedModel):
    """Capture vendor cache accounting as evidence, without changing the production prompt or transport."""
    def _send(self, payload: bytes, headers: dict[str, str]) -> Any:
        self.sent_at = dt.datetime.now(dt.UTC).isoformat()
        response = super()._send(payload, headers)
        try:
            raw = json.loads(response.body.decode("utf-8"))
            self.vendor_usage = raw.get("usage")
        except (ValueError, AttributeError):
            self.vendor_usage = None
        return response


def classify(packet: dict[str, Any], key: str, budget: CappedAllowance) -> dict[str, Any]:
    model = MeteredModel(key, budget, "intent-baseline")
    reply = model.decide(system="", messages=[raw_text_message(REQUEST_CHECK_SYSTEM, role="system"),
        raw_text_message(canonical_json(packet))], max_output_tokens=1024)
    record = model.records[-1]
    record.update(vendor_usage=model.vendor_usage, sent_at=model.sent_at)
    write(budget.directory / f"attempt-{budget.calls:03d}.json", record)
    decision = RequestCheck.model_validate(reply.decision)
    ids = {t["task_id"] for t in pending_tasks(packet)}
    if (len(decision.assessments) != len(ids) or {a.task_id for a in decision.assessments} != ids
            or any(a.quote not in packet["current_request"] for a in decision.assessments)):
        raise ValueError("invalid task coverage or quote provenance")
    return {"decision": decision.model_dump(), "call": record}


def freeze(directory: Path) -> None:
    fixture = load_fixture()
    files = [FIXTURE, Path(__file__), ROOT / "scripts/jev_intent_eval.py", ROOT / "scripts/jev_compare.py",
        ROOT / "agent/src/resolveflow/support/jev.py", ROOT / "agent/src/resolveflow/support/jev_intent.py",
        ROOT / "agent/src/resolveflow/support/request_check.py",
        ROOT / "agent/src/resolveflow/support/orchestration_prompts.py",
        ROOT / "agent/src/resolveflow/harness/live_model.py", ROOT / "agent/src/resolveflow/harness/sdk_adapter.py",
        ROOT / "agent/src/resolveflow/harness/context.py", ROOT / "agent/uv.lock",
        *[ROOT / p for p in fixture["sources"]]]
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {"version": VERSION, "cases": 50, "maximum_calls": 100, "maximum_calls_per_provider": 50,
        "repeats": 1, "automatic_retries": 0, "reserved_usd_limit": 1,
        "minimum_confidence": .70, "fallback_on_unclear": True, "fallback_whole_batch": True,
        "synthetic": True, "independent_holdout": False, "labels": fixture["labels"],
        "input_policy": fixture["input_policy"], "boundary_policy": fixture["boundary_policy"],
        "cost_policy": "USD estimates at uniform peak cache-miss .3 input/1.2 output per M for Flash; "
                       "Jev .042 input per M/output free. Not an invoice. Preserve vendor cache usage separately.",
        "pricing_sources": ["https://docs.typesafe.ai/models", "https://api-docs.deepseek.com/quick_start/pricing/"],
        "files": {p.relative_to(ROOT).as_posix(): digest(p) for p in files}}
    for name in manifest["files"]:
        target = directory / "frozen-source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    write(directory / "manifest.json", manifest)


def execute(directory: Path) -> None:
    manifest = json.loads((directory / "manifest.json").read_bytes())
    for name, sha in manifest["files"].items():
        if digest(ROOT / name) != sha:
            raise ValueError("frozen source changed: " + name)
    if (directory / "results.json").exists() or list(directory.glob("attempt-*.json")):
        raise ValueError("paid cohort cannot be repeated or overwritten")
    fixture = load_fixture()
    load_local_env(ROOT / ".env")
    config, key = JevConfig.from_environ(), os.environ.get("RESOLVEFLOW_MODEL_API_KEY", "")
    if not key or not config.api_key:
        raise ValueError("both provider credentials required")
    budget = CappedAllowance(directory)
    rows: list[dict[str, Any]] = []
    write(directory / "results.json", {"version": VERSION, "rows": rows})
    for index, case in enumerate(fixture["cases"]):
        row: dict[str, Any] = {k: case[k] for k in ("id", "split", "packet", "expected")}
        for arm in (["baseline", "jev"] if index % 2 else ["jev", "baseline"]):
            try:
                if arm == "baseline":
                    row[arm] = classify(case["packet"], key, budget)
                else:
                    result = RecordedChoices(config, budget).evaluate_choices(build_intent_request(config, case["packet"]))
                    row[arm] = {"result": result, "accepted": intent_decision(case["packet"], result, IntentPolicy())}
            except Exception as error:  # noqa: BLE001 - retain one failed attempt, never retry or leak credentials
                row[arm] = {"error": type(error).__name__}
        rows.append(row)
        write(directory / "results.json", {"version": VERSION, "rows": rows, "attempts": budget.calls,
                                             "reserved_usd": budget.reserved_usd})
        print(json.dumps({"id": case["id"], "attempts": budget.calls,
                          "errors": {a: row[a]["error"] for a in ("baseline", "jev") if "error" in row[a]}}), flush=True)


def score(expected: dict[str, str], values: dict[str, str]) -> dict[str, Any]:
    return {"correct": expected == values, "task_correct": sum(values.get(k) == v for k, v in expected.items()),
            "false_operation": sum(v not in OPERATIONS and values.get(k) in OPERATIONS for k, v in expected.items())}


def selected(row: dict[str, Any]) -> dict[str, str]:
    return row["baseline"] if row["fallback"] else row["jev"]


def estimated_cost(usage: dict[str, Any] | None, role: str) -> float | None:
    if usage is None:
        return None
    return (usage["input_tokens"] * (.042 if role == "jev" else .3)
            + usage["output_tokens"] * (0 if role == "jev" else 1.2)) / 1_000_000


def sum_known(values: list[float | None]) -> float | None:
    return None if any(v is None for v in values) else sum(v for v in values if v is not None)


def summary(directory: Path) -> dict[str, Any]:
    raw = json.loads((directory / "results.json").read_bytes())
    fixture = json.loads((directory / "frozen-source" / FIXTURE.relative_to(ROOT)).read_bytes())
    manifest = json.loads((directory / "manifest.json").read_bytes())
    for name, sha in manifest["files"].items():
        if digest(directory / "frozen-source" / name) != sha:
            raise ValueError("archived source changed: " + name)
    if len(raw["rows"]) != 50 or [r["id"] for r in raw["rows"]] != [c["id"] for c in fixture["cases"]]:
        raise ValueError("complete fifty-row cohort required")
    attempts = [json.loads(p.read_bytes()) for p in sorted(directory.glob("attempt-*.json"))]
    if len(attempts) != 100 or Counter(a["role"] for a in attempts) != {"jev": 50, "intent-baseline": 50}:
        raise ValueError("exactly fifty attempts per provider required")
    for row, case in zip(raw["rows"], fixture["cases"], strict=True):
        if row["packet"] != case["packet"] or row["expected"] != case["expected"]:
            raise ValueError("frozen input or gold changed")
    report = original_summary(directory)
    report["version"] = VERSION
    report["attempts_sha256"] = {p.name: digest(p) for p in sorted(directory.glob("attempt-*.json"))}
    report["metrics"] = {}
    for arm in ("baseline", "jev_raw", "hybrid"):
        predictions = [r["baseline"] if arm == "baseline" else r["jev"] if arm == "jev_raw" else selected(r)
                       for r in report["rows"]]
        scores = [score(r["expected"], p) for r, p in zip(report["rows"], predictions, strict=True)]
        report["metrics"][arm] = {"cases": 50, "correct": sum(s["correct"] for s in scores),
            "tasks": sum(len(r["expected"]) for r in report["rows"]),
            "task_correct": sum(s["task_correct"] for s in scores),
            "false_operation": sum(s["false_operation"] for s in scores),
            "sensitivity_without_Q23": {"cases": 49, "correct": sum(s["correct"] for r, s in
                zip(report["rows"], scores, strict=True) if r["id"] != "Q23-T1")}}
    fees: dict[str, list[float | None]] = {k: [] for k in ("baseline", "jev_raw", "hybrid")}
    for index, row in enumerate(report["rows"]):
        pair = {a["role"]: a for a in attempts[index * 2:index * 2 + 2]}
        b, j = pair["intent-baseline"], pair["jev"]
        bc = estimated_cost(b.get("usage"), "intent-baseline")
        jc = estimated_cost(j.get("result", {}).get("usage"), "jev")
        fees["baseline"].append(bc)
        fees["jev_raw"].append(jc)
        fees["hybrid"].append(sum_known([jc, bc]) if row["fallback"] else jc)
    report["cost_estimate_peak_cache_miss_usd"] = {k: sum_known(v) for k, v in fees.items()}
    report["cost_unknown_calls"] = {k: sum(x is None for x in v) for k, v in fees.items()}
    report["errors"] = {arm: [r["id"] for r in raw["rows"] if "error" in r[arm]] for arm in ("baseline", "jev")}
    report["label_counts"] = dict(Counter(v for c in fixture["cases"] for v in c["expected"].values()))
    report["cost_comparison_scope"] = "Purpose module only; hybrid reconstructed using paired baseline usage; " \
        "uniform peak cache-miss estimates, not actual billing or full Agent cost."
    return report


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["freeze", "execute", "summary"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        freeze(args.directory)
    elif args.mode == "execute":
        if not args.live:
            parser.error("execute requires --live")
        execute(args.directory)
    else:
        if args.output is None or args.output.exists():
            parser.error("summary requires new --output")
        write(args.output, summary(args.directory))


if __name__ == "__main__":
    main()
