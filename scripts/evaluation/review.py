"""Human review is explicit, pending by default, and bound to one immutable run."""

from __future__ import annotations

from scripts.evaluation.dataset import digest

CRITERIA = ("decision_supported", "no_unsupported_claims", "question_relevant")


def make_review(report, source_path):
    if report["mode"] not in {"mock", "live"}:
        raise ValueError("Semantic review accepts only Agent reports")
    return {
        "schema_version": 1,
        "report_sha256": digest(source_path),
        "manifest_hash": report["manifest_hash"],
        "reviewer": "",
        "reviewer_kind": "HUMAN",
        "reviewed_at": "",
        "rubric": {
            "decision_supported": "动作是否符合原始事实和适用政策；材料不足不得退款/直接拒绝。",
            "no_unsupported_claims": "说明中的事实、来源、核验和条款是否真实存在；无编造或用户陈述变事实。",
            "question_relevant": "ASK_CUSTOMER问题是否针对缺口、客户能回答、没有重复已答内容；其他动作留null。",
        },
        "results": [
            {
                "id": entry["id"],
                "decision_supported": None,
                "no_unsupported_claims": None,
                "question_relevant": None,
                "notes": "",
            }
            for entry in report["results"]
        ],
    }


def score_review(report, source_path, review):
    if review["report_sha256"] != digest(source_path) or review["manifest_hash"] != report["manifest_hash"]:
        raise ValueError("Human review does not belong to this report/data")
    entries = {entry["id"]: entry for entry in report["results"]}
    rows = review["results"]
    if len({row["id"] for row in rows}) != len(rows) or {row["id"] for row in rows} != set(entries):
        raise ValueError("Review ids/denominator differ")
    for row in rows:
        if any(row.get(key) is not None and type(row[key]) is not bool for key in CRITERIA):
            raise ValueError("Review criteria must be boolean or null; no coercion")
    judged = []
    for row in rows:
        entry = entries[row["id"]]
        required = list(CRITERIA[:2])
        if (entry.get("decision") or {}).get("kind") == "ASK_CUSTOMER":
            required.append("question_relevant")
        complete = all(row.get(key) is not None for key in required)
        if complete:
            if (
                review.get("reviewer_kind") != "HUMAN"
                or not review.get("reviewer", "").strip()
                or not review.get("reviewed_at", "").strip()
            ):
                raise ValueError("Completed human judgments need a named reviewer and date")
            judged.append(
                {
                    "id": row["id"],
                    "semantic_pass": all(row[key] for key in required),
                    "combined_pass": bool(entry.get("joint_correct")) and all(row[key] for key in required),
                }
            )
    return {
        "n": len(entries),
        "reviewed_n": len(judged),
        "pending_n": len(entries) - len(judged),
        "reviewer": review.get("reviewer"),
        "reviewed_at": review.get("reviewed_at"),
        "semantic_pass": sum(e["semantic_pass"] for e in judged),
        "combined_pass": sum(e["combined_pass"] for e in judged),
        "results": judged,
        "report_sha256": review["report_sha256"],
        "status": "COMPLETE" if len(judged) == len(entries) else "PENDING",
    }
