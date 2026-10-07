"""Compute paired post-interruption requests, real usage, and source hashes."""

import hashlib
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/resume-quantification-v1/recovery"


def main():
    directory = OUT / "formal-v1"
    raw = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    assert raw["state"] == "COMPLETED" and len(raw["pairs"]) == 15
    assert (
        raw["runner_sha256"]
        == hashlib.sha256(
            (ROOT / "scripts/resume_recovery_benchmark.py").read_bytes()
        ).hexdigest()
    )
    rows = []
    for pair in raw["pairs"]:
        for group, data in pair["groups"].items():
            prefix = json.loads(
                (directory / data["prefix_file"]).read_text(encoding="utf-8")
            )
            post = json.loads(
                (directory / data["continuation_file"]).read_text(encoding="utf-8")
            )
            assert (
                data["prefix_exit"] == 73 and prefix["fault_reached"] == pair["window"]
            )
            assert data["same_deadline"]
            assert (
                data["before"]["active_deadline_at"]
                == data["after"]["active_deadline_at"]
            )
            assert (
                data["after"]["budget_spent"]["model_calls"]
                >= data["before"]["budget_spent"]["model_calls"]
            )
            assert data["post_requests"] == len(post["requests"])
            row = {
                "window": pair["window"],
                "repeat": pair["repeat"],
                "group": group,
                "continuation_exit": data["continuation_exit"],
                "completed": post["completed"],
                "automatic_joint": post["automatic"]["joint_correct"],
                "same_deadline": True,
                "fence": data["after"]["fence"],
                "elapsed_seconds": post["elapsed_seconds"],
                "post_http_reads": len(post["http_reads"]),
                "prefix_http_reads": len(prefix["http_reads"]),
            }
            for label, record in (("prefix", prefix), ("post", post)):
                known = [
                    q
                    for q in record["requests"]
                    if q.get("usage") and not q["usage"].get("estimated")
                ]
                row[label + "_requests"] = len(record["requests"])
                row[label + "_unknown_usage"] = len(record["requests"]) - len(known)
                for key in ("input_tokens", "output_tokens"):
                    row[label + "_" + key] = sum(q["usage"][key] for q in known)
            rows.append(row)
    assert len(rows) == 30
    windows = {}
    names = ("before_model_saved", "after_model_saved", "after_tool_saved", "all")
    for window in names:
        selected = [r for r in rows if window == "all" or r["window"] == window]
        groups = {}
        for group in ("resume", "redo"):
            measured = [r for r in selected if r["group"] == group]
            assert len(measured) == (15 if window == "all" else 5)
            groups[group] = {
                "runs": len(measured),
                "completed": sum(r["completed"] for r in measured),
                "automatic_joint": sum(r["automatic_joint"] for r in measured),
                "post_elapsed_mean_seconds": statistics.mean(
                    r["elapsed_seconds"] for r in measured
                ),
                **{
                    key: sum(r[key] for r in measured)
                    for key in (
                        "post_requests",
                        "prefix_requests",
                        "post_unknown_usage",
                        "prefix_unknown_usage",
                        "post_input_tokens",
                        "post_output_tokens",
                        "prefix_input_tokens",
                        "prefix_output_tokens",
                        "post_http_reads",
                        "prefix_http_reads",
                    )
                },
            }
        baseline, restored = groups["redo"], groups["resume"]
        requests_saved = baseline["post_requests"] - restored["post_requests"]
        token_baseline = baseline["post_input_tokens"] + baseline["post_output_tokens"]
        token_restored = restored["post_input_tokens"] + restored["post_output_tokens"]
        windows[window] = {
            "groups": groups,
            "requests_saved": requests_saved,
            "requests_saved_mean_per_pair": requests_saved / baseline["runs"],
            "request_reduction": requests_saved / baseline["post_requests"],
            "total_token_reduction": (token_baseline - token_restored) / token_baseline,
            "input_token_reduction": (
                baseline["post_input_tokens"] - restored["post_input_tokens"]
            )
            / baseline["post_input_tokens"],
            "output_token_reduction": (
                baseline["post_output_tokens"] - restored["post_output_tokens"]
            )
            / baseline["post_output_tokens"],
        }
    paths = list(directory.glob("*.json")) + [
        ROOT / "scripts/resume_recovery_benchmark.py",
        Path(__file__).resolve(),
        OUT / "strict-v1.json",
        OUT / "replay-negative-tests-v2.xml",
        OUT / "mock-junit.xml",
    ]
    result = {
        "state": "COMPLETED",
        "pairs": 15,
        "actual_crashes": 30,
        "case": raw["case"],
        "business_scenarios": 1,
        "scope": raw["scope"],
        "policy_variant": raw["policy_variant"],
        "same_original_deadline": 30,
        "windows": windows,
        "runs": rows,
        "quality_review": "Codex NONBLIND: all 30 continuation summaries match paid32900/NOT_SHIPPED/no-reservation/R-UNSHIPPED-001; REFUND remains merchant advice, all valid.",
        "hashes": {
            str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in paths
        },
    }
    (OUT / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(windows))


if __name__ == "__main__":
    main()
