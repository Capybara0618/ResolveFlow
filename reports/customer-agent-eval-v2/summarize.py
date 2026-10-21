"""Recompute this failed cohort's accounting; successful answers require separate semantic review."""

import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values, p):
    values = sorted(values)
    position = (len(values) - 1) * p
    lower = int(position)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (position - lower)


def summarize(root):
    directory = root / "reports/customer-agent-eval-v2"
    runtime = directory / "runtime-results.json"
    data = json.loads(runtime.read_text(encoding="utf-8"))
    cases = json.loads((root / "evals/customer-agent-eval-v2/scenarios.json").read_text(encoding="utf-8"))["cases"]
    by_id = {c["id"]: c for c in cases}
    rows = data["rows"]
    assert data["state"] == "FINISHED" and len(rows) == 88
    assert data["plan_sha256"] == digest(root / "evals/customer-agent-eval-v2/manifest.json")
    assert all(r["state"] == "FINISHED" and r["http_status"] == 200 for r in rows)
    assert len({(r["id"], r["variant"], r["turn"]) for r in rows}) == 88
    if any(r["result"]["status"] != "FAILED" or r["result"]["answer"] is not None for r in rows):
        raise ValueError("this postprocessor only scores failed runs; actual answers require source review")
    groups = {}
    review = []
    for variant in ["agent", "fixed"]:
        selected = [r for r in rows if r["variant"] == variant]
        models = [m for r in selected for m in r["models"]]
        usage = [m["usage"] for m in models if m.get("usage")]
        latency = [r["elapsed_ms"] for r in selected]
        assert len(selected) == 44 and len({r["id"] for r in selected}) == 14
        groups[variant] = {
            "conversations": 14, "conversation_complete": 0, "conversation_failed": 14,
            "turns": 44, "turn_complete": 0, "turn_partial": 0, "turn_failed": 44,
            "reasons": dict(Counter(r["result"]["reason"] for r in selected)),
            "provider_requests": len(models), "provider_errors": sum(m["state"] != "COMPLETE" for m in models),
            "input_tokens": sum(u["input_tokens"] for u in usage),
            "output_tokens": sum(u["output_tokens"] for u in usage),
            "all_usage_provider_reported": len(usage) == len(models) and not any(u["estimated"] for u in usage),
            "failure_stop_latency_ms": {"p50": statistics.median(latency), "p95": percentile(latency, .95),
                                        "min": min(latency), "max": max(latency)},
            "actual_business_tool_executions": sum(len(r["tools"]) for r in selected),
            "actual_searches": sum(t["name"] == "search_policy" for r in selected for t in r["tools"]),
        }
        for row in selected:
            criteria = by_id[row["id"]]["turns"][row["turn"] - 1]["criteria"]
            review.append({"id": row["id"], "variant": variant, "turn": row["turn"], "grade": "FAILED",
                           "reason": row["result"]["reason"], "basis": "RUN_FAILED_WITH_NO_PUBLISHED_ANSWER",
                           "conditions": [{"text": c, "state": "NOT_SCORED_NO_ANSWER"} for c in criteria]})
    models = [m for r in rows for m in r["models"]]
    missing = [m for m in models if isinstance(m.get("decision"), dict) and "kind" not in m["decision"]]
    result = {"version": "customer-agent-eval-v2-summary", "runtime_sha256": digest(runtime), "groups": groups,
              "source_review": "FAILED_OUTCOME_AUDIT_NOT_INDEPENDENT_SEMANTIC_GOLD",
              "requests_missing_kind": len(missing), "all_requests": len(models),
              "served_models": sorted({m.get("served_model", "UNKNOWN") for m in models}),
              "max_provider_output_tokens": max(m["usage"]["output_tokens"] for m in models),
              "output_ceiling": sorted({m["body"]["max_tokens"] for m in models}),
              "warmup": data["warmup"], "usage_before": data["usage_before"], "usage_after": data["usage_after"],
              "preservation_equal": data["public_before"] == data["public_after"],
              "isolated_schema_dropped": data["isolated_schema_dropped"],
              "published_answer_latency_available": False, "live_rag_quality_exercised": False,
              "relative_agent_benefit_estimable": False, "acceptance_target_met": False}
    assert result["usage_after"] - result["usage_before"] == len(models)
    for name, value in [("summary.json", result), ("failed-outcome-review.json", review)]:
        with (directory / name).open("x", encoding="utf-8", newline="\n") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    summarize(Path(__file__).resolve().parents[2])
