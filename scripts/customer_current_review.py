"""Recompute counts/latencies from saved observations and explicit source-review judgments; zero network."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from scripts.customer_agent_eval_v2 import digest, read_json, write_new
from scripts.customer_current_eval import DIRECTORY, PLAN, load_plan
from scripts.customer_rag_benchmark import percentile


def distribution(values):
    return {"n": len(values), "p50_ms": percentile(values, .5) if values else None,
            "p95_ms": percentile(values, .95) if values else None,
            "max_ms": max(values) if values else None}


def stable_projection(row):
    """A surviving attempt alone is insufficient: final navigation rendering may replace its text."""
    events = row["events"]
    reset = max((i for i, event in enumerate(events) if event["kind"] == "answer.reset"), default=-1)
    parts, first = defaultdict(str), {}
    for event in events[reset + 1:]:
        if event["kind"] == "answer.delta" and event["payload"].get("text"):
            key = event["payload"]["part_id"]
            parts[key] += event["payload"]["text"]
            first.setdefault(key, event["elapsed_ms"])
    answer = row["result"].get("answer")
    if answer is None:
        return {"published_body_ms": None, "stream_identity_parts": [], "replaced_parts": [],
                "first_stable_observation": "NO_PUBLISHED_ANSWER"}
    retained = [key for key, text in parts.items() if text in answer["text"]]
    replaced = [key for key in parts if key not in retained]
    return {"published_body_ms": min(first[key] for key in retained) if retained else row["elapsed_ms"],
            "stream_identity_parts": retained, "replaced_parts": replaced,
            "first_stable_observation": "STREAM_RECEIVER" if retained else "FINAL_RESULT_RETURN"}


def evaluate():
    _, cases = load_plan()
    source = DIRECTORY / "agent-runtime.json"
    runtime, reviews = read_json(source), read_json(DIRECTORY / "source-review.json")
    if runtime["state"] != "FINISHED" or runtime["plan_sha256"] != digest(PLAN):
        raise ValueError("incomplete or different runtime")
    if reviews["runtime_sha256"] != digest(source):
        raise ValueError("review belongs to different runtime")
    labels = {(r["id"], r["turn"]): r for r in reviews["rows"]}
    expected = [(c["id"], n) for c in cases for n in range(1, len(c["turns"]) + 1)]
    if len(labels) != len(reviews["rows"]) or set(labels) != set(expected) or len(expected) != 44:
        raise ValueError("every frozen turn requires exactly one review")
    if [(r["id"], r["turn"]) for r in runtime["rows"]] != expected:
        raise ValueError("runtime is not the frozen ordered cohort")
    by_case = {case["id"]: case for case in cases}
    rows, conversations = [], defaultdict(list)
    for row in runtime["rows"]:
        review = labels[(row["id"], row["turn"])]
        criteria = by_case[row["id"]]["turns"][row["turn"] - 1]["criteria"]
        if len(review["criteria_pass"]) != len(criteria) or not review["note"].strip():
            raise ValueError("missing explicit criterion review")
        published = row["result"]["status"] == "SUCCEEDED"
        passed = published and all(review["criteria_pass"]) and not review["material_issues"]
        if not published and any(review["criteria_pass"]):
            raise ValueError("unpublished candidate cannot satisfy a delivered-answer criterion")
        item = {"id": row["id"], "turn": row["turn"], "run_id": row["input"]["run_id"],
                "published": published, "passed": passed, "criteria": criteria, **review,
                "projection": stable_projection(row)}
        rows.append(item)
        conversations[row["id"]].append(passed)
    models = [m for row in runtime["rows"] for m in row["models"]]
    if runtime["usage_after"] - runtime["usage_before"] != len(models):
        raise ValueError("usage ledger count mismatch")
    report = {"version": "current-source-review-metrics-v1", "runtime_sha256": digest(source),
        "review_sha256": digest(DIRECTORY / "source-review.json"), "new_model_calls": 0,
        "reviewer": reviews["reviewer"], "independent_holdout": False,
        "turns": 44, "published": sum(r["published"] for r in rows), "semantic_complete": sum(r["passed"] for r in rows),
        "conversations": len(conversations), "complete_conversations": sum(all(v) for v in conversations.values()),
        "conversation_scores": {key: {"passed": sum(value), "n": len(value)} for key, value in conversations.items()},
        "completion_all": distribution([r["elapsed_ms"] for r in runtime["rows"]]),
        "completion_published": distribution([r["elapsed_ms"] for r in runtime["rows"]
                                               if r["result"]["status"] == "SUCCEEDED"]),
        "completion_failed": distribution([r["elapsed_ms"] for r in runtime["rows"]
                                            if r["result"]["status"] == "FAILED"]),
        "first_provisional": distribution([r["stream_times"]["first_provisional_ms"] for r in runtime["rows"]
                                            if r["stream_times"]["first_provisional_ms"] is not None]),
        "published_stable_body": distribution([r["projection"]["published_body_ms"] for r in rows if r["published"]]),
        "stable_body_observation_modes": dict(Counter(r["projection"]["first_stable_observation"] for r in rows)),
        "published_with_replaced_stream_parts": sum(bool(r["projection"]["replaced_parts"]) for r in rows),
        "model_requests": len(models), "model_states": dict(Counter(m["state"] for m in models)),
        "model_elapsed": distribution([m["elapsed_ms"] for m in models]),
        "input_tokens": sum(m.get("usage", {}).get("input_tokens", 0) for m in models),
        "output_tokens": sum(m.get("usage", {}).get("output_tokens", 0) for m in models),
        "unknown_usage_requests": sum("usage" not in m for m in models),
        "estimated_usage_requests": sum(m.get("usage", {}).get("estimated", False) for m in models),
        "tools": dict(Counter(t["name"] for r in runtime["rows"] for t in r["tools"])),
        "agent_rag_elapsed": distribution([t["elapsed_ms"] for r in runtime["rows"] for t in r["tools"]
                                            if t["name"] == "search_policy"]),
        "public_unchanged": runtime["public_before"] == runtime["public_after"],
        "isolated_schema_dropped": runtime["isolated_schema_dropped"], "rows": rows}
    if not report["public_unchanged"] or not report["isolated_schema_dropped"]:
        raise ValueError("missing preservation")
    write_new(DIRECTORY / "agent-metrics.json", report)
    document = ["# 44轮客服逐轮源审", "", ("同版本固定合成回归；Codex源审，非独立盲审。"
                "未发布候选不计交付，部分满足不计完整通过。保留全部用户输入、最终回答、结构化摘要及原判据。"), ""]
    for raw, reviewed in zip(runtime["rows"], rows, strict=True):
        document += [f"## {raw['id']} / 第{raw['turn']}轮", "", "用户：" + raw["input"]["context"]["current_request"], "",
                     "结果：" + raw["result"]["status"] + "；源审：" + ("通过" if reviewed["passed"] else "未完整通过"), "",
                     "助手：", "", (raw["result"].get("answer") or {}).get("text", "（未发布回答）"), ""]
        for key, label in [("refund_summary", "退款原因草稿"), ("handoff_summary", "待共享核查摘要")]:
            if (raw["result"].get("answer") or {}).get(key):
                document += [label + "：" + raw["result"]["answer"][key], ""]
        document += ["判据：", ""]
        document += [("- 通过：" if passed else "- 未满足：") + criterion
                     for passed, criterion in zip(reviewed["criteria_pass"], reviewed["criteria"], strict=True)]
        document += ["", "审阅：" + reviewed["note"], "", "实际工具：" + ", ".join(t["name"] for t in raw["tools"]), ""]
    path = DIRECTORY / "conversations.md"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(document))
    print(json.dumps({k: report[k] for k in ["turns", "published", "semantic_complete", "complete_conversations",
        "completion_all", "published_stable_body", "stable_body_observation_modes", "published_with_replaced_stream_parts",
        "model_requests", "input_tokens", "output_tokens", "agent_rag_elapsed"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    evaluate()
