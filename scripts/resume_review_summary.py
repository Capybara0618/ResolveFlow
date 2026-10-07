"""Audit all thirty HTTP measurement windows and compute comparable medians."""

import gzip
import hashlib
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/resume-quantification-v1/review"


def read(path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as file:
            return json.load(file)
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    normal_meta = read(OUT / "normal-v1/metadata.json")
    assert normal_meta["state"] == "COMPLETED"
    assert len(normal_meta["windows"]) == 18
    fault_meta = read(OUT / "fault-v1/metadata.json")
    faults = read(OUT / "fault-v1/summary.json")
    assert faults["state"] == "COMPLETED" and len(faults["runs"]) == 12
    for frozen in (normal_meta["sha256"], fault_meta["source_sha256"]):
        for path, digest in frozen.items():
            assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    normal, fault_rows = [], []
    paths = [
        OUT / "normal-v1/metadata.json",
        OUT / "fault-v1/metadata.json",
        OUT / "fault-v1/summary.json",
    ]
    for window in normal_meta["windows"]:
        path = OUT / "normal-v1" / window["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == window["sha256"]
        paths.append(path)
        raw = read(path)
        assert (
            raw["seed"] == 42
            and raw["warmup_seconds"] == 30
            and raw["duration_seconds"] == 60
        )
        assert len(raw["runs"]) == 1
        run = raw["runs"][0]
        assert (
            raw["mode"] == window["mode"]
            and run["concurrency"] == window["concurrency"]
        )
        assert run["request_count"] == len(run["samples"])
        assert run["success_count"] == sum(
            sample["correct"] for sample in run["samples"]
        )
        assert run["request_count"] > 0 and run["success_count"] > 0
        assert run["elapsed_seconds"] >= 60 and len(run["cold"]) == 3
        normal.append(
            {
                **window,
                **{
                    key: run[key]
                    for key in (
                        "request_count",
                        "success_count",
                        "error_count",
                        "success_rps",
                        "error_rate",
                        "p95_ms",
                    )
                },
                "db_queries_per_success": run["metrics_delta"]["database_queries"]
                / run["success_count"],
                "cache_hit_rate": run["metrics_delta"]["cache_hit"]
                / max(
                    1,
                    sum(
                        run["metrics_delta"][key]
                        for key in ("cache_hit", "cache_miss", "cache_error")
                    ),
                ),
                "cold_ms": [sample["elapsed_ms"] for sample in run["cold"]],
            }
        )
    assert {(r["repeat"], r["mode"], r["concurrency"]) for r in normal} == {
        (repeat, mode, concurrency)
        for repeat in range(3)
        for mode in ("baseline", "indexed", "cache")
        for concurrency in (10, 30)
    }
    for row in faults["runs"]:
        path = OUT / "fault-v1" / f"fault-r{row['repeat']}-{row['fault']}.json.gz"
        paths.append(path)
        raw = read(path)
        assert len(raw["samples"]) == row["requests"] > 0
        assert sum(sample["correct"] for sample in raw["samples"]) == row["successes"]
        assert row["elapsed_seconds"] >= 30 and row["concurrency"] == 32
        assert row["peak_after"]["peak"] <= 8 and row["peak_after"]["inflight"] == 0
        assert all(sample["elapsed_ms"] >= 0 for sample in raw["samples"])
        failures = [sample for sample in raw["samples"] if not sample["correct"]]
        assert all(sample["status"] == 503 for sample in failures)
        assert len(failures) == row["metrics_delta"]["fallback_rejected"]
        fault_rows.append(
            {key: value for key, value in row.items() if key != "samples"}
        )
    assert {(row["repeat"], row["fault"]) for row in fault_rows} == {
        (repeat, fault)
        for repeat in range(3)
        for fault in ("expired", "disconnect", "timeout", "restored")
    }
    medians = {}
    for concurrency in (10, 30):
        groups = {}
        for mode in ("baseline", "indexed", "cache"):
            rows = [
                r
                for r in normal
                if r["concurrency"] == concurrency and r["mode"] == mode
            ]
            assert len(rows) == 3
            groups[mode] = {
                key: statistics.median(r[key] for r in rows)
                for key in (
                    "success_rps",
                    "p95_ms",
                    "error_rate",
                    "db_queries_per_success",
                    "cache_hit_rate",
                )
            }
        a, b, c = (groups[mode] for mode in ("baseline", "indexed", "cache"))
        medians[str(concurrency)] = {
            "groups": groups,
            "index_p95_reduction": (a["p95_ms"] - b["p95_ms"]) / a["p95_ms"],
            "cache_p95_reduction": (b["p95_ms"] - c["p95_ms"]) / b["p95_ms"],
            "combined_p95_reduction": (a["p95_ms"] - c["p95_ms"]) / a["p95_ms"],
            "cache_db_queries_per_success_reduction": (
                b["db_queries_per_success"] - c["db_queries_per_success"]
            )
            / b["db_queries_per_success"],
        }
    fault_medians = {}
    for fault in ("expired", "disconnect", "timeout", "restored"):
        rows = [r for r in fault_rows if r["fault"] == fault]
        failure_p95 = [
            r["p95_failure_ms"] for r in rows if r["p95_failure_ms"] is not None
        ]
        fault_medians[fault] = {
            "success_rps": statistics.median(r["success_rps"] for r in rows),
            "error_rate": statistics.median(r["error_rate"] for r in rows),
            "p95_success_ms": statistics.median(
                r["p95_success_ms"] for r in rows if r["p95_success_ms"] is not None
            ),
            "p95_failure_ms": statistics.median(failure_p95) if failure_p95 else None,
            "maximum_mapper_peak": max(r["peak_after"]["peak"] for r in rows),
            "fallback_rejected": sum(
                r["metrics_delta"]["fallback_rejected"] for r in rows
            ),
        }
    paths += [
        OUT / "environment.json",
        OUT / "proxy-smoke.json",
        OUT / "normal-v1/interruption.json",
        OUT / "normal-v1/launcher-before-interruption.py",
        Path(__file__).resolve(),
        ROOT / "scripts/resume_review_batch.py",
        ROOT / "java/case-service/src/main/resources/application.yml",
    ]
    result = {
        "state": "COMPLETED",
        "normal_windows": 18,
        "fault_windows": 12,
        "normal_requests": sum(r["request_count"] for r in normal),
        "normal_errors": sum(r["error_count"] for r in normal),
        "fault_requests": sum(r["requests"] for r in fault_rows),
        "fault_errors": sum(r["requests"] - r["successes"] for r in fault_rows),
        "medians_of_three": medians,
        "fault_medians": fault_medians,
        "normal_runs": normal,
        "fault_runs": fault_rows,
        "peak_scope": "actual maximum Mapper concurrency since each process start, includes validation/warmup/measurement",
        "hashes": {
            str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in paths
        },
    }
    (OUT / "audited-summary.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"normal": medians, "faults": fault_medians}))


if __name__ == "__main__":
    main()
