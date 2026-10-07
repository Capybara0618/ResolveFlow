"""Recompute formal Agent measurements without changing source records or Gold."""

import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/resume-quantification-v1/agent"


def percentile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def main():
    raw = json.loads((OUT / "formal-v1.json").read_text(encoding="utf-8"))
    review_path = ROOT / "evals/resume-quantification-v1/agent-review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    assert raw["state"] == "COMPLETED" and len(raw["results"]) == 128
    for path, digest in review["hashes"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    judgments = {(r["id"], r["group"], r["repeat"]): r for r in review["results"]}
    assert len(judgments) == 128
    classifications = {r["id"]: r for r in raw["classifications"]}
    groups = {}
    for group in ("fixed", "dynamic"):
        rows = [r for r in raw["results"] if r["group"] == group]
        assert len(rows) == 64
        assert {(r["id"], r["repeat"]) for r in rows} == {
            (case, repeat) for case in classifications for repeat in (0, 1)
        }
        for row in rows:
            decision_hash = hashlib.sha256(
                json.dumps(row["decision"], ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()
            assert (
                judgments[(row["id"], group, row["repeat"])]["decision_sha256"]
                == decision_hash
            )

        def valid(row):
            return judgments[(row["id"], row["group"], row["repeat"])]["valid"]

        requests = [request for row in rows for request in row["requests"]]
        known = [
            q for q in requests if q.get("usage") and not q["usage"].get("estimated")
        ]
        assert len(requests) == sum(row["model_calls"] for row in rows)
        complex_rows = [row for row in rows if classifications[row["id"]]["complex"]]
        elapsed = [row["elapsed_ms"] for row in rows]
        groups[group] = {
            "investigations": 64,
            "completed": sum(row["completed"] for row in rows),
            "automatic_joint": sum(row["joint_correct"] for row in rows),
            "semantic_valid": sum(valid(row) for row in rows),
            "semantic_valid_rate": sum(valid(row) for row in rows) / 64,
            "complex_investigations": len(complex_rows),
            "complex_valid": sum(valid(row) for row in complex_rows),
            "complex_valid_rate": sum(valid(row) for row in complex_rows)
            / len(complex_rows),
            "model_requests": len(requests),
            "model_requests_mean": len(requests) / 64,
            "http_reads": sum(len(row["http_reads"]) for row in rows),
            "tool_attempts": sum(row["spend"]["tool_attempts"] for row in rows),
            "local_reads": sum(row["spend"]["local_reads"] for row in rows),
            "known_usage_requests": len(known),
            "unknown_or_estimated_usage_requests": len(requests) - len(known),
            "input_tokens": sum(q["usage"]["input_tokens"] for q in known),
            "output_tokens": sum(q["usage"]["output_tokens"] for q in known),
            "elapsed_mean_ms": statistics.mean(elapsed),
            "elapsed_p50_ms": percentile(elapsed, 0.5),
            "elapsed_p95_ms": percentile(elapsed, 0.95),
            "case_elapsed_sum_ms": sum(elapsed),
            "stops": dict(
                Counter(row["reason_code"] for row in rows if not row["completed"])
            ),
            "model_aliases": dict(Counter(q.get("model_alias") for q in requests)),
            "families": {
                family: {
                    "n": sum(row["family"] == family for row in rows),
                    "valid": sum(valid(row) for row in rows if row["family"] == family),
                }
                for family in sorted({row["family"] for row in rows})
            },
        }
    result = {
        "state": "COMPLETED",
        "scope": "32 frozen synthetic scenarios; 128 real LLM investigations; NONBLIND Codex source review",
        "groups": groups,
        "dynamic_minus_fixed_valid_pp": 100
        * (
            groups["dynamic"]["semantic_valid_rate"]
            - groups["fixed"]["semantic_valid_rate"]
        ),
        "dynamic_minus_fixed_complex_pp": 100
        * (
            groups["dynamic"]["complex_valid_rate"]
            - groups["fixed"]["complex_valid_rate"]
        ),
        "hashes": {
            str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in (OUT / "formal-v1.json", review_path, Path(__file__).resolve())
        },
    }
    (OUT / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    table = [
        "# Agent 128次来源复核（Codex，NONBLIND）\n",
        "WARN表示表达可改善但主建议仍可执行；FAIL或INCOMPLETE不计有效。原Gold及原始结果保持。\n",
        "| 场景 | 组 | 轮次 | 自动联合 | 语义有效 | 事实/政策/动作/责任 | 复核说明 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in review["results"]:
        table.append(
            f"| {row['id']} | {row['group']} | {row['repeat']} | {row['automatic_joint']} "
            f"| {row['valid']} | {'/'.join(row['dimensions'].values())} "
            f"| {'；'.join(row['notes']).replace('|', '／')} |"
        )
    (OUT / "cases.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    print(json.dumps(result["groups"], ensure_ascii=False))


if __name__ == "__main__":
    main()
