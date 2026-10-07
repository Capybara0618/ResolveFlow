"""Real Redis network faults through a dedicated loopback TCP proxy; shared Redis stays up."""

import argparse
import gzip
import hashlib
import json
import select
import socket
import socketserver
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.c11_review_load import (
    Probe,
    fetch,
    percentile,
    snapshot_metrics,
    validate,
)
from scripts.evaluation.resume_lab import start_java, stop


def window(base, paths, concurrency, seconds, seed):
    """Keep the existing traffic mix while measuring actual transport failure latency."""
    deadline = time.monotonic() + seconds
    lock, sequence = threading.Lock(), 0

    def worker():
        nonlocal sequence
        samples = []
        while time.monotonic() < deadline:
            with lock:
                number = sequence
                sequence += 1
            slot = (number * 7 + seed) % 10
            token, path, expected = paths[0 if slot < 8 else 1 if slot == 8 else 2]
            started = time.perf_counter()
            try:
                status, body, elapsed = fetch(base, path, token)
                correct = (
                    status == 200
                    and [row["case_id"] for row in body.get("items", [])] == expected
                )
                samples.append(
                    Probe(
                        status,
                        elapsed,
                        correct,
                        None if correct else f"unexpected status {status}",
                    )
                )
            except Exception as error:  # noqa: BLE001 - measured failures remain in the denominator
                samples.append(
                    Probe(
                        0,
                        (time.perf_counter() - started) * 1000,
                        False,
                        type(error).__name__,
                    )
                )
        return samples

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return [
            sample
            for batch in pool.map(lambda _: worker(), range(concurrency))
            for sample in batch
        ]


class RedisProxy:
    def __init__(self):
        self.mode = "normal"
        self.sockets = set()
        self.lock = threading.Lock()
        owner = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                client = self.request
                if owner.mode == "disconnect":
                    return
                try:
                    upstream = socket.create_connection(("127.0.0.1", 56379), timeout=1)
                    with upstream:
                        with owner.lock:
                            owner.sockets.update((client, upstream))
                        while True:
                            if owner.mode == "disconnect":
                                return
                            if owner.mode == "timeout":
                                time.sleep(0.02)
                                continue
                            ready, _, _ = select.select(
                                [client, upstream], [], [], 0.05
                            )
                            for source in ready:
                                data = source.recv(65536)
                                if not data:
                                    return
                                (upstream if source is client else client).sendall(data)
                except (OSError, ValueError):
                    pass
                finally:
                    with owner.lock:
                        owner.sockets.discard(client)
                        if "upstream" in locals():
                            owner.sockets.discard(upstream)

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server(("127.0.0.1", 56380), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def set_mode(self, mode):
        self.mode = mode
        with self.lock:
            for connection in list(self.sockets):
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                    connection.close()
                except OSError:
                    pass
            self.sockets.clear()

    def close(self):
        self.set_mode("disconnect")
        self.server.shutdown()
        self.server.server_close()


def gauges(base):
    values = {}
    for name in ("inflight", "peak"):
        status, body, _ = fetch(
            base, f"/actuator/metrics/resolveflow.review.database.{name}"
        )
        assert status == 200
        values[name] = next(
            m["value"] for m in body["measurements"] if m["statistic"] == "VALUE"
        )
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source_paths = [
        Path(__file__).resolve(),
        ROOT / "scripts/c11_review_load.py",
        ROOT / "scripts/evaluation/resume_lab.py",
        ROOT / "java/case-service/target/case-service-0.1.0-SNAPSHOT.jar",
    ]
    frozen = {
        str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
            p.read_bytes()
        ).hexdigest()
        for p in source_paths
    }
    (args.output / "metadata.json").write_text(
        json.dumps(
            {
                "source_sha256": frozen,
                "schema": args.schema,
                "redis": "dedicated TCP proxy 56380 -> existing Redis56379",
                "permits": 8,
                "permit_wait_ms": 100,
                "concurrency": 32,
                "measurement_seconds": 30,
                "warmup_seconds": 10,
                "repeats": 3,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    proxy, process = RedisProxy(), None
    records = []
    try:
        for repeat in range(3):
            for fault in ("expired", "disconnect", "timeout", "restored"):
                label = f"fault-r{repeat}-{fault}"
                proxy.set_mode("normal")
                process = start_java(
                    "case",
                    args.schema,
                    18083,
                    label,
                    env_extra={
                        "REDIS_HOST": "127.0.0.1",
                        "REDIS_PORT": "56380",
                        "REVIEW_CACHE_ENABLED": "true",
                        "RESOLVEFLOW_REVIEW_CACHE_NAMESPACE": f"rf:resume:{args.schema}:{label}",
                    },
                )
                base = "http://127.0.0.1:18083"
                paths = validate(base)
                if fault in ("disconnect", "timeout", "restored"):
                    proxy.set_mode("disconnect" if fault == "restored" else fault)
                warm = window(base, paths, 32, 10, 42)
                if fault == "expired":
                    time.sleep(2.5)
                elif fault == "restored":
                    proxy.set_mode("normal")
                before, peak_before = snapshot_metrics(base), gauges(base)
                started = time.monotonic()
                samples = window(base, paths, 32, 30, 42)
                seconds = time.monotonic() - started
                after, peak_after = snapshot_metrics(base), gauges(base)
                successful = [sample.elapsed_ms for sample in samples if sample.correct]
                failures = [
                    sample.elapsed_ms for sample in samples if not sample.correct
                ]
                record = {
                    "repeat": repeat,
                    "fault": fault,
                    "concurrency": 32,
                    "warmup_seconds": 10,
                    "measurement_seconds": 30,
                    "warmup_requests": len(warm),
                    "warmup_errors": sum(not x.correct for x in warm),
                    "elapsed_seconds": seconds,
                    "requests": len(samples),
                    "successes": len(successful),
                    "success_rps": len(successful) / seconds,
                    "error_rate": len(failures) / len(samples),
                    "p95_success_ms": percentile(successful, 0.95),
                    "p95_failure_ms": percentile(failures, 0.95),
                    "metrics_delta": {key: after[key] - before[key] for key in before},
                    "peak_before": peak_before,
                    "peak_after": peak_after,
                    "peak_scope": "actual maximum Mapper concurrency since this process start, includes validation/warmup/measurement",
                    "samples": [asdict(sample) for sample in samples],
                }
                file = args.output / f"{label}.json.gz"
                with gzip.open(file, "wb") as output:
                    output.write(
                        json.dumps(
                            record, ensure_ascii=False, separators=(",", ":")
                        ).encode()
                    )
                records.append({k: v for k, v in record.items() if k != "samples"})
                (args.output / "summary.json").write_text(
                    json.dumps({"state": "RUNNING", "runs": records}, indent=2),
                    encoding="utf-8",
                )
                print(
                    json.dumps(
                        {
                            "fault": fault,
                            "repeat": repeat,
                            "peak": peak_after,
                            "errors": len(failures),
                        }
                    ),
                    flush=True,
                )
                stop(process)
                process = None
    finally:
        stop(process)
        proxy.close()
    assert len(records) == 12
    assert all(
        hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h
        for p, h in frozen.items()
    )
    (args.output / "summary.json").write_text(
        json.dumps({"state": "COMPLETED", "runs": records}, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
