"""Aggregate complete paired conversations only after source review, not by publication keywords."""

from __future__ import annotations

from collections import Counter
from statistics import mean


def metric_rows(runtime, cases):
    rows = runtime["rows"]
    expected = {(case["id"], turn + 1) for case in cases for turn in range(len(case["turns"]))}
    actual = [(row["id"], row["turn"]) for row in rows]
    if len(actual) != len(set(actual)) or set(actual) != expected or runtime["state"] != "FINISHED":
        raise ValueError("incomplete/duplicate run matrix; cannot report a completed experiment")
    if any(row["state"] != "FINISHED" for row in rows):
        raise ValueError("unfinished turn")
    return {(row["id"], row["turn"]): row for row in rows}


def review_template(runtime, cases):
    rows = metric_rows(runtime, cases)
    return {"origin": "CODEX_SOURCE_REVIEW_NOT_INDEPENDENT_HUMAN_GOLD", "rows": [
        {"id": case["id"], "turn": turn + 1, "criteria": spec["criteria"],
         "required_sources": spec.get("required_sources", []), "artifact": spec.get("artifact"),
         "run_id": rows[case["id"], turn + 1]["input"]["run_id"], "pass": None, "evidence": ""}
        for case in cases for turn, spec in enumerate(case["turns"])]}


def summarize(runtime, cases, review):
    rows = metric_rows(runtime, cases)
    labels = {(r["id"], r["turn"]): r for r in review["rows"]}
    if len(labels) != len(review["rows"]) or labels.keys() != rows.keys():
        raise ValueError("review denominator differs")
    records = []
    for case in cases:
        selected = [rows[case["id"], index + 1] for index in range(len(case["turns"]))]
        decisions = []
        for row in selected:
            label = labels[row["id"], row["turn"]]
            if type(label["pass"]) is not bool or not label["evidence"].strip():
                raise ValueError("unreviewed semantic result; no success percentage emitted")
            if label["run_id"] != row["input"]["run_id"]:
                raise ValueError("review run identity differs")
            if label["pass"] and row["result"]["status"] != "SUCCEEDED":
                raise ValueError("failed publication cannot be a completed task")
            decisions.append(label["pass"])
        counts = Counter(t["name"] for row in selected for t in row["tools"])
        records.append({"id": case["id"], "source_case_id": case["source_case_id"], "variant": case["variant"],
            "repeat": case["repeat"], "complex": case["complex"], "pass": all(decisions),
            "customer_turns": len(selected), "tool_attempts": sum(counts.values()),
            "business_http": sum(counts[k] for k in ("get_order_context", "get_shipment_trace", "read_history")),
            "policy_reads": counts["search_policy"], "guide_reads": counts["get_support_guide"],
            "models": sum(len(row["models"]) for row in selected),
            "completion_ms": sum(row["elapsed_ms"] for row in selected)})
    groups = {}
    for variant in ("dynamic", "fixed"):
        group = [r for r in records if r["variant"] == variant]
        complex_cases = [r for r in group if r["complex"]]
        groups[variant] = {"runs": len(group), "completed": sum(r["pass"] for r in group),
            "complex_runs": len(complex_cases), "complex_completed": sum(r["pass"] for r in complex_cases),
            "complex_completion_rate": mean(r["pass"] for r in complex_cases),
            "mean_business_http_all_runs": mean(r["business_http"] for r in group),
            "business_http_per_customer_turn": sum(r["business_http"] for r in group) / sum(
                r["customer_turns"] for r in group), "mean_models_all_runs": mean(r["models"] for r in group)}
    fixed = groups["fixed"]["mean_business_http_all_runs"]
    paired = {(r["source_case_id"], r["repeat"]) for r in records if r["pass"] and r["variant"] == "dynamic"} & {
        (r["source_case_id"], r["repeat"]) for r in records if r["pass"] and r["variant"] == "fixed"}
    paired_efficiency = {v: mean(r["business_http"] for r in records if r["variant"] == v and (
        r["source_case_id"], r["repeat"]) in paired) for v in ("dynamic", "fixed")} if paired else None
    model_calls = [m for row in rows.values() for m in row["models"]]
    return {"groups": groups, "complex_improvement_percentage_points": 100 * (
        groups["dynamic"]["complex_completion_rate"] - groups["fixed"]["complex_completion_rate"]),
        "business_http_reduction_all_runs": 1 - groups["dynamic"]["mean_business_http_all_runs"] / fixed
            if fixed else None, "both_completed_pairs": len(paired), "paired_efficiency": paired_efficiency,
        "provider_attempts": len(model_calls),
        "known_input_tokens": sum(m.get("usage", {}).get("input_tokens", 0) for m in model_calls),
        "known_output_tokens": sum(m.get("usage", {}).get("output_tokens", 0) for m in model_calls),
        "unknown_usage_calls": sum(not m.get("usage") for m in model_calls),
        "estimated_usage_calls": sum(m.get("usage", {}).get("estimated", False) for m in model_calls),
        "records": records}
