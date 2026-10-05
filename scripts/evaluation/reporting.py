"""Read-only summaries and comparable paired runs; never rerun a model."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path


def load_report(path: Path):
    report = json.loads(path.read_text(encoding="utf-8"))
    if not report.get("results") or not report.get("manifest_hash"):
        raise ValueError("A report must contain identified data and nonzero results")
    return report


def identity(entry):
    return entry["id"], entry.get("path")


def compare_reports(before, after):
    if any(
        report.get("state") == "RUNNING"
        or any(entry.get("status") in {"RUNNING", "NOT_RUN"} for entry in report["results"])
        for report in (before, after)
    ):
        raise ValueError("Unfinished report cannot be an effect comparison")
    for key in ("manifest_hash", "mode", "provider", "embedding", "backend_profile"):
        if before.get(key) != after.get(key):
            raise ValueError("Incomparable reports: " + key)
    aliases = [
        {
            request.get("model_alias")
            for entry in report["results"]
            for request in entry.get("requests", [])
            if request.get("model_alias")
        }
        for report in (before, after)
    ]
    if aliases[0] != aliases[1]:
        raise ValueError("Observed model aliases differ")
    if before["mode"] not in {"mock", "live", "rag"}:
        raise ValueError("Only Agent/RAG effect reports can be compared")
    for name in ("scripts/evaluation/scoring.py", "scripts/evaluation/dataset.py"):
        left_hashes = before.get("scoring_hashes", before.get("code_hashes", {}))
        right_hashes = after.get("scoring_hashes", after.get("code_hashes", {}))
        if not left_hashes.get(name) or left_hashes[name] != right_hashes.get(name):
            raise ValueError("Scoring/data code changed; explicitly rescore both saved runs before comparison")
    left = {identity(e): e for e in before["results"]}
    right = {identity(e): e for e in after["results"]}
    if len(left) != len(before["results"]) or len(right) != len(after["results"]):
        raise ValueError("Duplicate result ids")
    if set(left) != set(right):
        raise ValueError("Selected cases differ; do not compare unequal denominators")
    if any(left[key]["split"] != right[key]["split"] for key in left):
        raise ValueError("Split labels differ")
    metric = "all_required_at_5" if before["mode"] == "rag" else "joint_correct"
    eligible = [key for key in left if before["mode"] != "rag" or left[key].get("positive", False)]
    return {
        "n": len(left),
        "scored_n": len(eligible),
        "metric": metric,
        "before": sum(bool(left[key].get(metric)) for key in eligible),
        "after": sum(bool(right[key].get(metric)) for key in eligible),
        "improved": [
            key[0] + ("/" + key[1] if key[1] else "")
            for key in eligible
            if not left[key].get(metric) and right[key].get(metric)
        ],
        "regressed": [
            key[0] + ("/" + key[1] if key[1] else "")
            for key in eligible
            if left[key].get(metric) and not right[key].get(metric)
        ],
        "changed_code": sorted(
            key
            for key, value in after.get("code_hashes", {}).items()
            if before.get("code_hashes", {}).get(key) != value
        ),
    }


def describe(report):
    mode, entries = report["mode"], report["results"]
    lines = [
        "# 评测记录",
        "",
        f"模式：{mode}；数据：{report['dataset_version']}；来源：合成；Gold未经独立人审。",
        "",
        f"代码：{report['code_commit']}；数据清单hash：{report['manifest_hash']}。",
        "",
    ]
    not_run = sum(e.get("status") == "NOT_RUN" for e in entries)
    if report.get("state") == "RUNNING" or not_run:
        lines += [f"执行未收口；计划样本{len(entries)}，尚未执行{not_run}，不能作完成对照。", ""]
    if mode in {"mock", "live"}:
        correct = sum(bool(e.get("joint_correct")) for e in entries)
        actions = sum(bool(e.get("action_correct")) for e in entries)
        failures = sum(not e.get("completed", False) for e in entries)
        calls = sum(e.get("model_calls", 0) for e in entries)
        usage = [r["usage"] for e in entries for r in e.get("requests", []) if "usage" in r]
        lines += [
            f"自动联合达标：{correct}/{len(entries)}；动作匹配：{actions}/{len(entries)}；未完成：{failures}；调用：{calls}。",
            "",
            "脚本模型只测试接线；自动评分不代替提问相关性、解释可信度的人审。",
            "",
        ]
        if mode == "live":
            exact = [u for u in usage if not u.get("estimated", True)]
            lines += [
                f"provider准确usage：{len(exact)}/{calls}次；"
                f"输入{sum(u['input_tokens'] for u in exact)}、"
                f"输出{sum(u['output_tokens'] for u in exact)} tokens。未知计费不计为零。",
                "",
            ]
        pairs = {}
        for entry in entries:
            pairs.setdefault(entry["pair_id"], []).append(entry)
        complete = [members for members in pairs.values() if len(members) == 2]
        lines += [
            f"完整配对：{len(complete)}；"
            f"两成员均达标：{sum(all(e.get('joint_correct', False) for e in pair) for pair in complete)}；"
            "单成员不计配对分。",
            "",
        ]
        reasons = Counter(e.get("reason_code") or e.get("error") or "completed" for e in entries)
        lines += [
            "终止原因：" + json.dumps(dict(reasons), ensure_ascii=False),
            "",
            "| 案例 | 分组 | 动作 | 联合达标 | 失败/缺口 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for e in entries:
            gap = (
                e.get("reason_code")
                if not e.get("completed", False)
                else ", ".join(
                    e.get("missing_tools", [])
                    + e.get("missing_cited_tools", [])
                    + e.get("missing_rules", [])
                    + e.get("citation_errors", [])
                )
            )
            lines.append(
                f"| {e['id']} | {e['split']} | {e.get('action') or '—'} | "
                f"{bool(e.get('joint_correct'))} | {gap or e.get('error', '—')} |"
            )
    elif mode == "rag":
        lines += [
            "| 路径/分组 | 样本 | 正例 | 覆盖@1 | 覆盖@2 | 覆盖@5 | 全依据@5 | 错主体/版本 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for key, s in report["summary"].items():
            lines.append(
                f"| {key} | {s['n']} | {s['positive_n']} | {s['coverage_at_1']} | "
                f"{s['coverage_at_2']} | {s['coverage_at_5']} | "
                f"{s['all_required_at_5']}/{s['positive_n']} | {s['filter_violations']} |"
            )
        lines += ["", "无适用政策的负例单独计候选，不混入正例召回分母；候选不等于业务适用。"]
    else:
        lines += ["结果：" + json.dumps(report["summary"], ensure_ascii=False)]
    latency = sorted(e["elapsed_ms"] for e in entries if "elapsed_ms" in e)
    if latency:
        lines += [
            "",
            f"案例耗时：median {statistics.median(latency):.2f} ms，"
            f"p95 {latency[max(0, (95 * len(latency) + 99) // 100 - 1)]:.2f} ms（含本机执行开销）。",
        ]
    lines += ["", "逐轮显式动作、工具Observation、原始请求和usage见对应JSON；不保存隐式思维链。", ""]
    return "\n".join(lines)
