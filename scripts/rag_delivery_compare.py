"""Bounded before/after and anonymous judgment report, with explicit unassessed denominators."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.policy_documents import digest


def metrics(report: dict) -> dict:
    rows = report["results"]
    requests = [q for r in rows for q in r.get("requests", [])]
    known = [q for q in requests if q.get("usage") and q["usage"].get("estimated") is False]
    return {
        **report["summary"], "completed": sum(r["completed"] for r in rows),
        "request_records": len(requests), "requests_with_provider_usage": len(known),
        "requests_without_provider_usage": len(requests) - len(known),
        "provider_input_tokens": sum(q["usage"]["input_tokens"] for q in known),
        "provider_output_tokens": sum(q["usage"]["output_tokens"] for q in known),
        "model_aliases": dict(Counter(q.get("model_alias", "UNSPECIFIED") for q in requests)),
        "failures": [{
            "id": r["id"], "status": r["status"], "completed": r["completed"], "action": r.get("action"),
            "reason_code": r.get("reason_code"), "missing_support": r.get("missing_support"),
            "missing_rules": r.get("missing_rules"), "notices": r.get("notices"),
        } for r in rows if not r["joint_correct"]],
    }


def semantic_metrics(review: dict) -> dict:
    result = {}
    dims = ("factual_support", "policy_application", "action_reason_alignment")
    for cohort in ("baseline", "candidate"):
        values, missing = [], []
        for row in review["results"]:
            if row["status"] != "VALIDATED_MODEL_JUDGMENT":
                missing.append({"id": row["id"], "reason": row["status"]})
                continue
            found = [j for j in row["judgment"]["evaluations"] if row["mapping"][j["candidate"]] == cohort]
            if not found:
                missing.append({"id": row["id"], "reason": "NOT_JUDGED_INCOMPLETE"})
                continue
            values.append({"id": row["id"], **found[0]})
        result[cohort] = {
            "total_cases": len(review["results"]), "validated_judgment_denominator": len(values),
            **{k: sum(v[k] for v in values) for k in dims},
            "all_three_passed": sum(all(v[k] for k in dims) for v in values),
            "uncertain_true": sum(v.get("uncertain") is True for v in values),
            "uncertainty_unspecified": sum(v.get("uncertain") is None for v in values),
            "unassessed": missing,
            "failed_dimensions": [v for v in values if not all(v[k] for k in dims)],
        }
    return result


def compare(before: dict, after: dict, review: dict) -> dict:
    if any(r.get("state") != "FINISHED" or r.get("mode") != "live" for r in (before, after)):
        raise ValueError("only finished real model reports can be compared")
    for key in ("manifest_hash", "evaluation_config", "provider", "entry_hash", "dependency_lock_hash"):
        if before[key] != after[key]:
            raise ValueError("controlled configuration differs: " + key)
    if {r["id"] for r in before["results"]} != {r["id"] for r in after["results"]}:
        raise ValueError("case denominator differs")
    if review.get("state") != "FINISHED" or len(review["results"]) != len(after["results"]):
        raise ValueError("anonymous assessment denominator is incomplete")
    changes = []
    old = {r["id"]: r for r in before["results"]}
    for r in after["results"]:
        previous = old[r["id"]]
        if any(previous.get(k) != r.get(k) for k in ("joint_correct", "completed", "action", "reason_code")):
            changes.append({"id": r["id"], **{
                k: {"baseline": previous.get(k), "candidate": r.get(k)}
                for k in ("joint_correct", "completed", "action", "reason_code")
            }})
    return {
        "controlled_configuration_matched": True, "baseline": metrics(before), "candidate": metrics(after),
        "changed_outcomes": changes, "anonymous_semantic": semantic_metrics(review),
        "semantic_model_requests": review["transmissions"], "semantic_protocol_errors": review["errors"],
        "human_review_count": 0, "official_human_accuracy": None,
        "limits": ["synthetic cases and HTTP/MCP sources; real LLM/SDK/BGE/PG",
                   "same-model semantic judging is correlated, not independent human Gold",
                   "one new cohort versus preserved baseline, no stochastic confidence interval",
                   "no overall quality/usage gain causally attributed to RAG from this single comparison",
                   "new temporary Windows PG differs from historical Docker runtime; no latency advantage claim"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("comparison reports are immutable")
    paths = (args.baseline, args.candidate, args.review)
    documents = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    if documents[2]["baseline_sha256"] != digest(paths[0].read_bytes()) or (
        documents[2]["candidate_sha256"] != digest(paths[1].read_bytes())
    ):
        raise ValueError("semantic assessment is not bound to these exact reports")
    report = compare(*documents)
    report.update(
        files={p.as_posix(): digest(p.read_bytes()) for p in paths}, runner_sha256=digest(Path(__file__).read_bytes())
    )
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: report[k]["joint_correct"] for k in ("baseline", "candidate")}))


if __name__ == "__main__":
    main()
