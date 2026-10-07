"""18 rotated real HTTP windows on 20,000 synthetic cases in a new schema."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluation.resume_lab import create_database, mysql, start_java, stop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--prepared", action="store_true")
    args = parser.parse_args()
    if not args.prepared:
        create_database(args.schema, "case_svc")
        process = start_java("case", args.schema, 18083, f"{args.schema}-migrate")
        stop(process)
        seed = (ROOT / "scripts/c11_review_queue_seed.sql").read_text(encoding="utf-8")
        seed = "\n".join(
            line for line in seed.splitlines() if not line.startswith("CREATE ")
        )
        seed = seed.replace("c11_review_bench", args.schema).replace("M-2002", "M-1002")
        mysql(seed)
        counts = mysql(
            f"SELECT count(*),sum(status='PENDING_REVIEW'),count(distinct merchant_id) FROM {args.schema}.aftersale_case;"
        )
        assert counts == "20000\t4000\t2", counts
        print(f"PREPARED {args.schema}: {counts}", flush=True)
        if args.prepare_only:
            return
    args.output.mkdir(parents=True, exist_ok=False)
    process = None
    windows = []
    try:
        for repeat in range(3):
            modes = ["baseline", "indexed", "cache"]
            modes = modes[repeat:] + modes[:repeat]
            for concurrency in (10, 30):
                for mode in modes:
                    present = (
                        mysql(
                            f"SELECT count(*) FROM information_schema.statistics WHERE table_schema='{args.schema}' AND table_name='aftersale_case' AND index_name='idx_case_review_queue';"
                        )
                        != "0"
                    )
                    if mode == "baseline" and present:
                        mysql(
                            f"ALTER TABLE {args.schema}.aftersale_case DROP INDEX idx_case_review_queue;"
                        )
                    elif mode != "baseline" and not present:
                        mysql(
                            f"ALTER TABLE {args.schema}.aftersale_case ADD INDEX idx_case_review_queue (merchant_id,status,updated_at DESC,case_id DESC);"
                        )
                    label = f"r{repeat}-{mode}-c{concurrency}"
                    process = start_java(
                        "case",
                        args.schema,
                        18083,
                        label,
                        env_extra={
                            "REDIS_HOST": "127.0.0.1",
                            "REDIS_PORT": "56379",
                            "REVIEW_CACHE_ENABLED": str(mode == "cache").lower(),
                            "RESOLVEFLOW_REVIEW_CACHE_NAMESPACE": f"rf:resume:{args.schema}:{label}",
                        },
                    )
                    raw = args.output / f"{label}.json.gz"
                    subprocess.run(
                        [
                            sys.executable,
                            str(ROOT / "scripts/c11_review_load.py"),
                            "--mode",
                            mode,
                            "--seed",
                            "42",
                            "--warmup",
                            "30",
                            "--duration",
                            "60",
                            "--repeats",
                            "1",
                            "--concurrency",
                            str(concurrency),
                            "--output",
                            str(raw),
                        ],
                        check=True,
                        cwd=ROOT,
                    )
                    stop(process)
                    process = None
                    windows.append(
                        {
                            "repeat": repeat,
                            "mode": mode,
                            "concurrency": concurrency,
                            "file": raw.name,
                            "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                        }
                    )
                    (args.output / "progress.json").write_text(
                        json.dumps(windows, indent=2), encoding="utf-8"
                    )
                    print(f"COMPLETED {len(windows)}/18 {label}", flush=True)
    finally:
        stop(process)
    assert len(windows) == 18
    files = [
        "scripts/resume_review_benchmark.py",
        "scripts/c11_review_load.py",
        "scripts/evaluation/resume_lab.py",
        "scripts/c11_review_queue_seed.sql",
        "java/case-service/target/case-service-0.1.0-SNAPSHOT.jar",
    ]
    (args.output / "metadata.json").write_text(
        json.dumps(
            {
                "state": "COMPLETED",
                "schema": args.schema,
                "rows": 20000,
                "pending": 4000,
                "warmup_seconds": 30,
                "measurement_seconds": 60,
                "repeats": 3,
                "jvm": "Java21 -Xms256m -Xmx768m",
                "seed": 42,
                "windows": windows,
                "sha256": {
                    path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                    for path in files
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
