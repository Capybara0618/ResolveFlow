"""Audit one finished live report without rerunning models or changing automatic scores."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.evaluation.dataset import ALIGNED_DATA, digest, read  # noqa: E402


def audit(report):
    if (report.get("mode") != "live" or report.get("synthetic") is not True
            or report.get("state") != "FINISHED"
            or report.get("manifest_hash") != digest(ALIGNED_DATA / "manifest.json")):
        raise ValueError("Expected finished live report on aligned-v2")
    cases = {c["id"]: c for c in read("agent/cases.json", ALIGNED_DATA)}
    entries = report["results"]
    ids = [e["id"] for e in entries]
    if not entries or len(set(ids)) != len(ids) or set(ids) - set(cases):
        raise ValueError("Live report case denominator invalid")
    rows = []
    for entry in entries:
        requests = entry.get("requests", [])
        if entry["model_calls"] != len(requests):
            raise ValueError("Recorded request count differs")
        usage = {"provider_input_tokens": 0, "provider_output_tokens": 0,
                 "provider_usage_requests": 0, "estimated_usage_requests": 0, "missing_usage_requests": 0}
        searches, inputs, ratios = [], [], []
        for turn, request in enumerate(requests, 1):
            value = request.get("usage")
            if value is None:
                usage["missing_usage_requests"] += 1
            elif value.get("estimated") is False:
                usage["provider_usage_requests"] += 1
                usage["provider_input_tokens"] += value["input_tokens"]
                usage["provider_output_tokens"] += value["output_tokens"]
            else:
                usage["estimated_usage_requests"] += 1
            measurement = request.get("context_measurement")
            if measurement:
                inputs.append(measurement["input_estimate"])
                if value and value.get("estimated") is False and value["input_tokens"] > 0:
                    ratios.append(measurement["input_estimate"] / value["input_tokens"])
            decision = request.get("decision") or {}
            if decision.get("kind") == "SEARCH_POLICY":
                searches.append({"turn": turn, "query": decision.get("query"),
                                 "top_k": decision.get("arguments", {}).get("top_k")})
        notices = entry.get("notices", [])
        diagnostics = entry.get("context_diagnostics", [])
        rows.append({"id": entry["id"], "family": cases[entry["id"]]["family"], "split": entry["split"],
            "pair_id": entry["pair_id"], "status": entry["status"], "completed": entry.get("completed", False),
            "action": entry.get("action"), "action_correct": entry.get("action_correct", False),
            "joint_correct": entry.get("joint_correct", False),
            "forbidden_action": entry.get("forbidden_action", False),
            "reason_code": entry.get("reason_code"), "error": entry.get("error"), "model_calls": len(requests),
            "usage": usage, "max_sent_input_estimate_bytes": max(inputs) if inputs else None,
            "mean_utf8_estimate_to_provider_token_ratio": round(sum(ratios) / len(ratios), 4) if ratios else None,
            "search_decisions": searches,
            "refusal_notices": [n for n in notices if n.startswith("REFUSED ")],
            "overflow_diagnostics": [d for d in diagnostics if d.get("mandatory_tokens", 0) > d.get("cap", 0)],
            "automatic_support_gaps": {k: entry.get(k, []) for k in (
                "missing_tools", "missing_cited_tools", "missing_rules", "citation_errors", "missing_support")},
            "trajectory": entry.get("trajectory", [])})
    return {"n": len(rows), "automatic_action_correct": sum(r["action_correct"] for r in rows),
        "automatic_joint_correct": sum(r["joint_correct"] for r in rows),
        "forbidden_final_actions": sum(r["forbidden_action"] for r in rows),
        "completed": sum(r["completed"] for r in rows), "incomplete": sum(not r["completed"] for r in rows),
        "reason_counts": dict(Counter(r["reason_code"] or r["status"] for r in rows)),
        "request_count": sum(r["model_calls"] for r in rows),
        "refusal_notice_count": sum(len(r["refusal_notices"]) for r in rows),
        "queries": sum(len(r["search_decisions"]) for r in rows),
        "usage": {k: sum(r["usage"][k] for r in rows) for k in rows[0]["usage"]},
        "independent_semantic_review": "PENDING", "results": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Existing audit is immutable; choose a new path")
    report = json.loads(args.input_report.read_text(encoding="utf-8"))
    value = audit(report)
    value.update(source_report_sha256=digest(args.input_report), script_sha256=digest(Path(__file__)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in value.items() if k != "results"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
