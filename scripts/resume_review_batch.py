"""Run formal HTTP windows after model/refund batches finish, then recompute medians."""

import gzip
import hashlib
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/resume-quantification-v1/review"


def summarize():
    rows = []
    for path in sorted((OUT / "normal-v1").glob("r*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as file:
            raw = json.load(file)
        run = raw["runs"][0]
        assert len(raw["runs"]) == 1
        rows.append(
            {
                "file": path.name,
                "mode": raw["mode"],
                **{
                    k: run[k]
                    for k in (
                        "concurrency",
                        "request_count",
                        "success_count",
                        "success_rps",
                        "error_rate",
                        "p95_ms",
                    )
                },
                "database_queries_per_success": run["metrics_delta"]["database_queries"]
                / run["success_count"],
                "cache_hit_rate": run["metrics_delta"]["cache_hit"]
                / max(
                    1,
                    run["metrics_delta"]["cache_hit"]
                    + run["metrics_delta"]["cache_miss"]
                    + run["metrics_delta"]["cache_error"],
                ),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    assert len(rows) == 18
    medians = []
    for concurrency in (10, 30):
        for mode in ("baseline", "indexed", "cache"):
            selected = [
                row
                for row in rows
                if row["concurrency"] == concurrency and row["mode"] == mode
            ]
            assert len(selected) == 3
            medians.append(
                {
                    "concurrency": concurrency,
                    "mode": mode,
                    **{
                        key: statistics.median(row[key] for row in selected)
                        for key in (
                            "success_rps",
                            "error_rate",
                            "p95_ms",
                            "database_queries_per_success",
                            "cache_hit_rate",
                        )
                    },
                }
            )
    result = {
        "state": "COMPLETED",
        "normal_runs": rows,
        "medians_of_three": medians,
        "faults": json.loads(
            (OUT / "fault-v1/summary.json").read_text(encoding="utf-8")
        ),
    }
    (OUT / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(medians), flush=True)


def main():
    for experiment in ("refund", "recovery"):
        marker = (
            ROOT
            / f"reports/resume-quantification-v1/{experiment}/formal-v1/results.json"
        )
        while True:
            try:
                if (
                    json.loads(marker.read_text(encoding="utf-8"))["state"]
                    == "COMPLETED"
                ):
                    break
            except (FileNotFoundError, json.JSONDecodeError, PermissionError):
                pass
            time.sleep(10)
    print("FORMAL_MODEL_AND_REFUND_BATCHES_FINISHED_STARTING_HTTP_WINDOWS", flush=True)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/resume_review_benchmark.py"),
            "--schema",
            "resume_review_20261007a",
            "--output",
            str(OUT / "normal-v1"),
            "--prepared",
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/resume_review_faults.py"),
            "--schema",
            "resume_review_20261007a",
            "--output",
            str(OUT / "fault-v1"),
        ],
        cwd=ROOT,
        check=True,
    )
    summarize()


if __name__ == "__main__":
    main()
