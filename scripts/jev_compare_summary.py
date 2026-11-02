"""Offline summary of one immutable Jev study and explicit source-reviewed labels; no model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(directory: Path, review_path: Path) -> dict[str, Any]:
    results_path = directory / "results.json"
    results = json.loads(results_path.read_bytes())
    review = json.loads(review_path.read_bytes())
    if review["results_sha256"] != digest(results_path):
        raise ValueError("review does not match the frozen results")
    rows = results["rows"]
    labels = {x["id"]: x for x in review["rows"]}
    if len(labels) != len(rows) or set(labels) != {x["id"] for x in rows} or len(rows) != 19:
        raise ValueError("review must cover all nineteen cases exactly once")
    attempts = [json.loads(p.read_bytes()) for p in sorted(directory.glob("attempt-*.json"))]
    if len(attempts) != results["provider_attempts"]:
        raise ValueError("attempt ledger count differs")
    roles = {}
    for role in ("baseline", "jev", "jev-repair", "self-check"):
        group = [a for a in attempts if a["role"] == role]
        usage = [a.get("usage", a.get("result", {}).get("usage", {})) for a in group]
        inputs = sum(u.get("input_tokens", 0) for u in usage)
        outputs = sum(u.get("output_tokens", 0) for u in usage)
        times = [a.get("elapsed_ms", a.get("result", {}).get("elapsed_ms")) for a in group]
        times = [t for t in times if t is not None]
        roles[role] = {"attempts": len(group), "statuses": dict(Counter(a["status"] for a in group)),
                       "input_tokens": inputs, "output_tokens": outputs,
                       "median_provider_ms": statistics.median(times) if times else None,
                       "total_provider_ms": sum(times),
                       "estimated_peak_no_cache_usd": inputs * (.042 if role == "jev" else .3) / 1_000_000
                           + (0 if role == "jev" else outputs * 1.2 / 1_000_000)}
    arms: dict[str, Any] = {}
    details = []
    for row in rows:
        label = labels[row["id"]]
        check = row.get("jev_check") or {}
        baseline = row["baseline"]["answer"]
        candidates = {"baseline": baseline}
        for arm, repair in (("jev-gated", "jev-repair"), ("self-check", "self-check")):
            candidate = row["repairs"].get(repair)
            candidates[arm] = candidate["answer"] if candidate and candidate["status"] == "SUCCEEDED" else baseline
        for arm, answer in candidates.items():
            expected_hash = hashlib.sha256(json.dumps(answer, ensure_ascii=False, sort_keys=True,
                                                     separators=(",", ":")).encode()).hexdigest()
            if label["answers_sha256"][arm] != expected_hash:
                raise ValueError("reviewed answer changed: " + row["id"] + "/" + arm)
            scores = label["scores"][arm]
            if any(type(scores[k]) is not bool for k in ("grounded", "task_complete")):
                raise ValueError("explicit binary review labels required")
            bucket = arms.setdefault(arm, {"grounded": 0, "task_complete": 0, "changed_text": 0})
            bucket["grounded"] += scores["grounded"]
            bucket["task_complete"] += scores["task_complete"]
            bucket["changed_text"] += answer["text"] != baseline["text"]
        details.append({"id": row["id"], "jev_status": check.get("status"),
                        "jev_verdict": check.get("verdict"), "jev_reason": check.get("reason"),
                        "scores": label["scores"], "notes": label["notes"],
                        "baseline_text": baseline["text"],
                        "jev_text": candidates["jev-gated"]["text"],
                        "self_check_text": candidates["self-check"]["text"]})
    checked = [r for r in rows if (r.get("jev_check") or {}).get("status") == "COMPLETE"]
    triggered = [r for r in checked if r["jev_check"]["verdict"] != "supported"]
    for role in ("jev-gated", "self-check"):
        repair_role = "jev-repair" if role == "jev-gated" else "self-check"
        included = ["baseline", repair_role] + (["jev"] if role == "jev-gated" else [])
        arms[role]["total_estimated_peak_no_cache_usd"] = sum(roles[k]["estimated_peak_no_cache_usd"] for k in included)
        extra = roles[repair_role]["total_provider_ms"] + (roles["jev"]["total_provider_ms"] if role == "jev-gated" else 0)
        arms[role]["mean_added_provider_ms_per_case"] = extra / len(rows)
    arms["baseline"]["total_estimated_peak_no_cache_usd"] = roles["baseline"]["estimated_peak_no_cache_usd"]
    return {"version": "jev-comparison-v1", "reviewer": review["reviewer"],
            "scope": "19 source-visible synthetic single-turn cases; current Agent; frozen facts/policy adapter",
            "results_sha256": digest(results_path), "review_sha256": digest(review_path),
            "manifest_sha256": digest(directory / "manifest.json"),
            "total_cases": len(rows), "arms": arms, "roles": roles,
            "jev_coverage": {"completed": len(checked),
                             "statuses": dict(Counter((r.get("jev_check") or {}).get("status", "MISSING") for r in rows)),
                             "skipped": sum((r.get("jev_check") or {}).get("status") == "SKIPPED" for r in rows),
                             "repair_triggers": len(triggered),
                             "triggers_on_grounded_answers": sum(labels[r["id"]]["scores"]["baseline"]["grounded"]
                                                                 for r in triggered)},
            "total_attempts": len(attempts),
            "total_estimated_peak_no_cache_usd": sum(v["estimated_peak_no_cache_usd"] for v in roles.values()),
            "conservative_reserved_usd": results["conservative_reserved_usd"], "rows": details}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.directory, args.review)
    with args.output.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
