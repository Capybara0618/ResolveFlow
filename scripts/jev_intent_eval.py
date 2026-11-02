"""One frozen thirty-utterance comparison of the existing purpose check and Jev Choice."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any

from jev_compare import Allowance, RecordedModel, write
from resolveflow.harness.context import canonical_json
from resolveflow.harness.sdk_adapter import raw_text_message
from resolveflow.support.jev import JevClient, JevConfig, load_local_env
from resolveflow.support.jev_intent import (
    IntentPolicy,
    build_intent_request,
    intent_decision,
    pending_tasks,
)
from resolveflow.support.orchestration_prompts import REQUEST_CHECK_SYSTEM
from resolveflow.support.request_check import RequestCheck

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "agent/tests/fixtures/jev-intent-v1.json"


class RecordedChoices(JevClient):
    def __init__(self, config: JevConfig, allowance: Allowance) -> None:
        super().__init__(config)
        self.allowance = allowance

    def evaluate_choices(self, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        path, record = self.allowance.reserve("jev", body)
        try:
            response = super().evaluate_choices(body, **kwargs)
        except Exception as error:
            record.update(status="ERROR", error=type(error).__name__)
            write(path, record)
            raise
        record.update(status="COMPLETE", result=response)
        write(path, record)
        return response


def classify_baseline(packet: dict[str, Any], key: str, budget: Allowance) -> dict[str, Any]:
    model = RecordedModel(key, budget, "intent-baseline")
    reply = model.decide(system="", messages=[raw_text_message(REQUEST_CHECK_SYSTEM, role="system"),
        raw_text_message(canonical_json(packet))], max_output_tokens=1024)
    decision = RequestCheck.model_validate(reply.decision)
    expected_ids = {t["task_id"] for t in pending_tasks(packet)}
    if (len(decision.assessments) != len(expected_ids) or {a.task_id for a in decision.assessments} != expected_ids
            or any(a.quote not in packet["current_request"] for a in decision.assessments)):
        raise ValueError("invalid task coverage or quote provenance")
    return {"decision": decision.model_dump(), "call": model.records[-1]}


def freeze(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    files = [FIXTURE, Path(__file__), ROOT / "scripts/jev_compare.py",
             ROOT / "agent/src/resolveflow/support/jev.py", ROOT / "agent/src/resolveflow/support/jev_intent.py",
             ROOT / "agent/src/resolveflow/support/request_check.py",
             ROOT / "agent/src/resolveflow/support/orchestration_prompts.py"]
    write(directory / "manifest.json", {"version": "jev-intent-v1", "minimum_confidence": .70,
        "fallback_on_unclear": True, "fallback_whole_batch": True, "maximum_calls": 60,
        "reserved_usd_limit": 1, "synthetic": True, "independent_holdout": False,
        "labels": "Codex-authored before inference, no independent human label claim",
        "files": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}})


def execute(directory: Path) -> None:
    manifest = json.loads((directory / "manifest.json").read_bytes())
    for name, sha in manifest["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != sha:
            raise ValueError("frozen source changed: " + name)
    if (directory / "results.json").exists() or list(directory.glob("attempt-*.json")):
        raise ValueError("paid cohort cannot be repeated or overwritten")
    load_local_env(ROOT / ".env")
    config, policy = JevConfig.from_environ(), IntentPolicy(enabled=True)
    key = os.environ.get("RESOLVEFLOW_MODEL_API_KEY", "")
    if not key or not config.api_key:
        raise ValueError("both provider credentials are required")
    cases = json.loads(FIXTURE.read_bytes())["cases"]
    if len(cases) != 30:
        raise ValueError("fixed thirty-case denominator required")
    budget = Allowance(directory)
    rows: list[dict[str, Any]] = []
    write(directory / "results.json", {"rows": rows})
    for index, case in enumerate(cases):
        row: dict[str, Any] = {"id": case["id"], "split": case["split"], "packet": case["packet"],
                               "expected": case["expected"]}
        for arm in (["baseline", "jev"] if index % 2 else ["jev", "baseline"]):
            try:
                if budget.calls >= 60:
                    raise ValueError("sixty-call cap exhausted")
                if arm == "baseline":
                    row[arm] = classify_baseline(case["packet"], key, budget)
                else:
                    result = RecordedChoices(config, budget).evaluate_choices(build_intent_request(config, case["packet"]))
                    row[arm] = {"result": result, "accepted": intent_decision(case["packet"], result, policy)}
            except Exception as error:  # noqa: BLE001 - record every failed arm once, without retries
                row[arm] = {"error": type(error).__name__}
        rows.append(row)
        write(directory / "results.json", {"version": "jev-intent-v1", "rows": rows,
            "attempts": budget.calls, "reserved_usd": budget.reserved_usd})
        print(json.dumps({"id": case["id"], "baseline": row["baseline"].get("decision", {}).get("assessments"),
                          "jev": {k: v["choice"] for k, v in row["jev"].get("result", {}).get("answers", {}).items()},
                          "fallback": row["jev"].get("accepted") is None,
                          "attempts": budget.calls}, ensure_ascii=False), flush=True)


def summarize(directory: Path) -> dict[str, Any]:
    raw = json.loads((directory / "results.json").read_bytes())
    report: dict[str, Any] = {"version": "jev-intent-v1", "minimum_confidence": .70,
        "results_sha256": hashlib.sha256((directory / "results.json").read_bytes()).hexdigest(),
        "manifest": json.loads((directory / "manifest.json").read_bytes()), "rows": [], "splits": {}}
    roles = {}
    for name in ("jev", "intent-baseline"):
        calls = [json.loads(p.read_bytes()) for p in directory.glob("attempt-*.json")]
        calls = [c for c in calls if c["role"] == name]
        usage = [c.get("result", {}).get("usage", c.get("usage", {})) for c in calls]
        inputs = sum(u.get("input_tokens", 0) for u in usage)
        outputs = sum(u.get("output_tokens", 0) for u in usage)
        times = [c.get("result", {}).get("elapsed_ms", c.get("elapsed_ms")) for c in calls]
        times = [t for t in times if t is not None]
        roles[name] = {"calls": len(calls), "input_tokens": inputs, "output_tokens": outputs,
                       "median_ms": statistics.median(times) if times else None,
                       "estimated_usd": inputs * (.042 if name == "jev" else .3) / 1_000_000
                            + (0 if name == "jev" else outputs * 1.2 / 1_000_000)}
    for row in raw["rows"]:
        expected = row["expected"]
        baseline = {a["task_id"]: a["purpose"] for a in row["baseline"].get("decision", {}).get("assessments", [])}
        tasks = pending_tasks(row["packet"])
        predictions = {t["task_id"]: row["jev"].get("result", {}).get("answers", {}).get(
            f"purpose_{i}", {}).get("choice") for i, t in enumerate(tasks)}
        accepted = row["jev"].get("accepted") is not None
        chosen = predictions if accepted else baseline
        scores = {"baseline": baseline == expected, "jev_raw": predictions == expected, "hybrid": chosen == expected}
        for split in ("all", row["split"]):
            bucket = report["splits"].setdefault(split, {"cases": 0, "tasks": 0, "baseline": 0, "jev_raw": 0,
                "hybrid": 0, "fallbacks": 0, "accepted_wrong": 0, "baseline_task_correct": 0,
                "jev_task_correct": 0, "hybrid_task_correct": 0})
            bucket["cases"] += 1
            bucket["tasks"] += len(expected)
            for k, v in scores.items():
                bucket[k] += v
            bucket["fallbacks"] += not accepted
            bucket["accepted_wrong"] += accepted and not scores["jev_raw"]
            for name, values in (("baseline", baseline), ("jev", predictions), ("hybrid", chosen)):
                bucket[name + "_task_correct"] += sum(values.get(k) == v for k, v in expected.items())
        report["rows"].append({"id": row["id"], "split": row["split"], "packet": row["packet"],
            "expected": expected, "baseline": baseline, "jev": predictions, "hybrid": chosen,
            "fallback": not accepted, "scores": scores, "jev_response": row["jev"].get("result")})
    report["roles"] = roles
    report["total_attempts"] = raw["attempts"]
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
            parser.error("summary needs a new --output path")
        write(args.output, summarize(args.directory))


if __name__ == "__main__":
    main()
