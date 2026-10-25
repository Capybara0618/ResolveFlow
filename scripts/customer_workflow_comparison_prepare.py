"""Offline business-level design audit/review/aggregation. No model, DB or Agent imports."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "evals/customer-workflow-comparison-v2/cases.json"
CHECKS = {"correctness", "completion", "context"}
VARIANTS = ("agent", "basic_workflow")
STATUSES = {"SUCCEEDED", "FAILED", "TIMEOUT", "BUDGET_EXHAUSTED", "NOT_RUN"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dataset():
    data = read(DATA)
    for field in ("source_cases", "snapshot_source"):
        source = data[field]
        if digest(ROOT / source["path"]) != source["sha256"]:
            raise ValueError("retained source changed: " + source["path"])
    old = read(ROOT / data["source_cases"]["path"])
    if len(data["cases"]) != 32 or data["repeats"] != 1 or data["variants"] != list(VARIANTS):
        raise ValueError("design denominator differs")
    if len({c["id"] for c in data["cases"]}) != 32:
        raise ValueError("duplicate case")
    if Counter(c["family"] for c in data["cases"]) != Counter(c["family"] for c in old["cases"]):
        raise ValueError("family selection differs")
    for case, source in zip(data["cases"], old["cases"], strict=True):
        for key in ("id", "family", "complex", "snapshot_id", "snapshot_override"):
            if case.get(key) != source.get(key):
                raise ValueError("input/snapshot selection differs")
        for turn, original in zip(case["turns"], source["turns"], strict=True):
            if set(turn) != {"text", "business_expectations", "expected_artifact"}:
                raise ValueError("business rubric contains internal requirements")
            if turn["text"] != original["text"] or turn["expected_artifact"] != original["artifact"]:
                raise ValueError("customer input or requested artifact differs")
            if not turn["business_expectations"] or not all(
                isinstance(s, str) and s.strip() for s in turn["business_expectations"]
            ):
                raise ValueError("missing business expectations")
    return data


def audit():
    data = load_dataset()
    return {"version": data["version"], "dataset_sha256": digest(DATA), "cases": len(data["cases"]),
        "complex_cases": sum(c["complex"] for c in data["cases"]),
        "customer_inputs": sum(len(c["turns"]) for c in data["cases"]),
        "planned_conversation_runs": len(data["cases"]) * 2, "planned_customer_turns": 100,
        "source_inputs_and_snapshots_unchanged": True,
        "scoring_scope": "customer-visible outcomes; no task/memory/Agent protocol requirements",
        "baseline_implemented": True, "live_executor_implemented": True,
        "new_provider_requests": 0, "new_model_inferences": 0, "quality_measured": False}


def runtime_rows(data, runtime, dataset_hash):
    if (runtime.get("version") != data["version"] or runtime.get("dataset_sha256") != dataset_hash
            or runtime.get("state") != "FINISHED"):
        raise ValueError("runtime identity/state differs")
    expected = {(c["id"], variant, i + 1) for c in data["cases"] for variant in VARIANTS
                for i in range(len(c["turns"]))}
    rows = runtime["rows"]
    actual = [(r["case_id"], r["variant"], r["turn"]) for r in rows]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("incomplete/duplicate result matrix")
    if len({r["run_id"] for r in rows}) != len(rows) or any(not r["run_id"] for r in rows):
        raise ValueError("duplicate/empty run identity")
    for row in rows:
        if row["status"] not in STATUSES:
            raise ValueError("unknown execution status")
        answer = row.get("answer")
        if row["status"] == "SUCCEEDED" and (not isinstance(answer, dict) or not any(
            isinstance(answer.get(k), str) and answer[k].strip()
            for k in ("text", "refund_summary", "handoff_summary")
        )):
            raise ValueError("published result lacks a customer-visible answer")
        if row.get("elapsed_ms") is not None and row["elapsed_ms"] < 0:
            raise ValueError("negative latency")
        first, elapsed = row.get("first_body_ms"), row.get("elapsed_ms")
        if first is not None and (row['status'] != 'SUCCEEDED' or elapsed is None
                or not isinstance(first, (int, float)) or not math.isfinite(first) or not 0 <= first <= elapsed):
            raise ValueError("invalid first body latency")
        if row['status'] == 'NOT_RUN' and (row['tools'] or row['models'] or elapsed is not None or first is not None):
            raise ValueError("unrun turn cannot contribute costs or fake latency")
        for tool in row["tools"]:
            if tool["category"] not in {"ORDER", "SHIPMENT", "POLICY", "GUIDE", "HISTORY"}:
                raise ValueError("unknown tool category")
    return dict(zip(actual, rows, strict=True))


def sent_models(rows):
    return [model for row in rows for model in row['models'] if model.get('provider_sent') is not False]


def distribution(values):
    values = sorted(v for v in values if v is not None)
    return {'n': len(values), 'method': 'NEAREST_RANK',
        **{key: values[max(0, math.ceil(p * len(values)) - 1)] if values else None
            for key, p in (('p50', .5), ('p95', .95))}}


def performance(rows):
    models = sent_models(rows)
    known, estimated = [], []
    for model in models:
        usage = model.get('usage')
        if isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] >= 0
                for k in ('input_tokens', 'output_tokens')):
            (estimated if usage.get('estimated', False) else known).append(usage)
    return {'provider_attempts': len(models), 'blocked_model_attempts': sum(
            model.get('provider_sent') is False for row in rows for model in row['models']),
        'known_input_tokens': sum(u['input_tokens'] for u in known),
        'known_output_tokens': sum(u['output_tokens'] for u in known),
        'estimated_input_tokens': sum(u['input_tokens'] for u in estimated),
        'estimated_output_tokens': sum(u['output_tokens'] for u in estimated),
        'unknown_usage_calls': len(models) - len(known) - len(estimated), 'estimated_usage_calls': len(estimated),
        'first_body_ms': distribution(r.get('first_body_ms') for r in rows if r['status'] == 'SUCCEEDED'),
        'completion_ms_successful_publications': distribution(r.get('elapsed_ms') for r in rows
            if r['status'] == 'SUCCEEDED'),
        'completion_ms_all_attempted': distribution(r.get('elapsed_ms') for r in rows if r['status'] != 'NOT_RUN'),
        'attempted_turns': sum(r['status'] != 'NOT_RUN' for r in rows),
        'unrun_turns': sum(r['status'] == 'NOT_RUN' for r in rows),
        'timing_scope': 'SERVER; retained decoded text, not progress/JSON bytes/browser rendering'}


def review_template(data, runtime, dataset_hash):
    rows = runtime_rows(data, runtime, dataset_hash)
    return {"version": data["version"], "origin": "CODEX_SOURCE_REVIEW_NOT_INDEPENDENT_HUMAN_GOLD",
        "rows": [{"case_id": case["id"], "variant": variant, "turn": i + 1,
            "run_id": rows[case["id"], variant, i + 1]["run_id"],
            "business_expectations": turn["business_expectations"],
            "expected_artifact": turn["expected_artifact"],
            "checks": {key: None for key in sorted(CHECKS)}, "evidence": ""}
            for case in data["cases"] for variant in VARIANTS for i, turn in enumerate(case["turns"])]}


def summarize(data, runtime, review, dataset_hash):
    rows = runtime_rows(data, runtime, dataset_hash)
    labels = {(r["case_id"], r["variant"], r["turn"]): r for r in review["rows"]}
    if len(labels) != len(review["rows"]) or set(labels) != set(rows):
        raise ValueError("review denominator differs")
    records = []
    for case in data["cases"]:
        for variant in VARIANTS:
            selected = [rows[case["id"], variant, i + 1] for i in range(len(case["turns"]))]
            passes = []
            for i, row in enumerate(selected):
                label = labels[case["id"], variant, i + 1]
                checks = label["checks"]
                if (set(checks) != CHECKS or any(type(v) is not bool for v in checks.values())
                        or not label["evidence"].strip()):
                    raise ValueError("unreviewed business outcome")
                if label["run_id"] != row["run_id"]:
                    raise ValueError("review run identity differs")
                passed = all(checks.values())
                answer = row.get("answer") or {}
                artifact = case["turns"][i]["expected_artifact"]
                has_refund, has_handoff = (isinstance(answer.get(k), str) and bool(answer[k].strip())
                    for k in ("refund_summary", "handoff_summary"))
                shape_ok = {"NONE": not has_refund and not has_handoff,
                    "REFUND": has_refund and not has_handoff,
                    "HANDOFF": has_handoff and not has_refund}[artifact]
                if passed and (row["status"] != "SUCCEEDED" or not shape_ok):
                    raise ValueError("failed publication or missing/wrong artifact marked successful")
                passes.append(passed)
            records.append({"case_id": case["id"], "variant": variant, "family": case["family"],
                "complex": case["complex"], "passed": all(passes), "passed_turns": sum(passes),
                "customer_turns": len(selected), "business_http": sum(t["category"] in {
                    "ORDER", "SHIPMENT", "HISTORY"} for row in selected for t in row["tools"]),
                "model_requests": len(sent_models(selected))})
    groups = {}
    for variant in VARIANTS:
        selected = [r for r in records if r["variant"] == variant]
        complex_cases = [r for r in selected if r["complex"]]
        ordinary = [r for r in selected if not r["complex"]]
        groups[variant] = {"conversations": len(selected), "completed": sum(r["passed"] for r in selected),
            "complex_cases": len(complex_cases), "complex_completed": sum(r["passed"] for r in complex_cases),
            "complex_completion_rate": mean(r["passed"] for r in complex_cases),
            "ordinary_cases": len(ordinary), "ordinary_completed": sum(r["passed"] for r in ordinary),
            "customer_turns": sum(r["customer_turns"] for r in selected),
            "passed_turns": sum(r["passed_turns"] for r in selected),
            "mean_business_http_all_conversations": mean(r["business_http"] for r in selected),
            "model_requests": sum(r["model_requests"] for r in selected),
            "performance": performance([r for r in rows.values() if r['variant'] == variant])}
    paired = {r['case_id'] for r in records if r['passed'] and r['variant'] == 'agent'} & {
        r['case_id'] for r in records if r['passed'] and r['variant'] == 'basic_workflow'}
    paired_efficiency = {variant: {
        'mean_business_http': mean(r['business_http'] for r in records if r['variant'] == variant
            and r['case_id'] in paired),
        'mean_model_requests': mean(r['model_requests'] for r in records if r['variant'] == variant
            and r['case_id'] in paired),
        'performance': performance([r for r in rows.values() if r['variant'] == variant and r['case_id'] in paired])}
        for variant in VARIANTS} if paired else None
    return {"version": data["version"], "groups": groups, "records": records,
        'both_completed_pairs': len(paired), 'paired_efficiency': paired_efficiency,
        "complex_improvement_percentage_points": 100 * (groups["agent"]["complex_completion_rate"]
            - groups["basic_workflow"]["complex_completion_rate"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["audit", "review-template", "summarize"])
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "audit":
        report = audit()
    else:
        if args.runtime is None:
            parser.error("--runtime required")
        runtime, data = read(args.runtime), load_dataset()
        if args.mode == "review-template":
            report = review_template(data, runtime, digest(DATA))
            report["runtime_sha256"] = digest(args.runtime)
        else:
            if args.review is None:
                parser.error("--review required")
            review = read(args.review)
            if review.get("runtime_sha256") != digest(args.runtime):
                raise ValueError("review does not bind actual runtime bytes")
            report = summarize(data, runtime, review, digest(DATA))
            report.update(runtime_sha256=digest(args.runtime), review_sha256=digest(args.review))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(report, out, ensure_ascii=False, indent=2)
        out.write("\n")
    print({"mode": args.mode, "output": str(args.output), "new_provider_requests": 0})


if __name__ == "__main__":
    main()
