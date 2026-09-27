"""HTTP load probe for the isolated C11 review-queue dataset.

Run against a Case process bound to a dedicated migrated MySQL schema. The
launcher chooses baseline/index/cache; this client never changes server data.
"""

from __future__ import annotations

import argparse
import gzip
import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def fetch(base: str, path: str, token: str | None = None) -> tuple[int, dict[str, Any], float]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}, (time.perf_counter() - started) * 1000
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = {}
        return error.code, body, (time.perf_counter() - started) * 1000


def login(base: str, username: str, password: str) -> str:
    body = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(base + "/api/v1/auth/login", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as response:
        answer = json.loads(response.read())
        assert response.status == 200 and answer["access_token"]
        return str(answer["access_token"])


def metric(base: str, name: str, outcome: str | None = None) -> float:
    path = f"/actuator/metrics/{name}"
    if outcome:
        path += f"?tag=outcome:{outcome}"
    status, body, _ = fetch(base, path)
    if status == 404:
        return 0.0
    assert status == 200, (path, status, body)
    return float(next((measurement["value"] for measurement in body["measurements"]
                       if measurement["statistic"] == "COUNT"), 0.0))


def snapshot_metrics(base: str) -> dict[str, float]:
    return {
        "database_queries": metric(base, "resolveflow.review.database.queries"),
        "cache_hit": metric(base, "resolveflow.review.cache", "hit"),
        "cache_miss": metric(base, "resolveflow.review.cache", "miss"),
        "cache_error": metric(base, "resolveflow.review.cache", "error"),
        "fallback_rejected": metric(base, "resolveflow.review.fallback", "rejected"),
    }


@dataclass
class Probe:
    status: int
    elapsed_ms: float
    correct: bool
    error: str | None = None


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * pct))]


def validate(base: str) -> list[tuple[str, str, list[str]]]:
    first = login(base, "demo-reviewer", "demo-pass-1003")
    second = login(base, "demo-reviewer-m2", "demo-pass-2002")
    customer = login(base, "demo-customer", "demo-pass-1001")
    status, _, _ = fetch(base, "/api/v1/review/cases?limit=20", customer)
    assert status == 403, f"customer queue returned {status}"
    paths: list[tuple[str, str, list[str]]] = []
    for token, merchant in ((first, "M-1001"), (second, "M-1002")):
        status, page, _ = fetch(base, "/api/v1/review/cases?limit=20", token)
        assert status == 200 and len(page["items"]) == 20 and page["page"]["next_cursor"], page
        ids = [item["case_id"] for item in page["items"]]
        assert len(set(ids)) == 20
        tails = [int(case_id[-12:]) for case_id in ids]
        assert all((tail < 10000) == (merchant == "M-1001") for tail in tails), ids
        paths.append((token, "/api/v1/review/cases?limit=20", ids))
        if merchant == "M-1001":
            cursor = page["page"]["next_cursor"]
            status, following, _ = fetch(base, f"/api/v1/review/cases?limit=20&cursor={cursor}", token)
            next_ids = [item["case_id"] for item in following["items"]]
            assert status == 200 and len(next_ids) == 20 and not set(ids).intersection(next_ids)
            paths.append((token, f"/api/v1/review/cases?limit=20&cursor={cursor}", next_ids))
    return paths


def window(base: str, paths: list[tuple[str, str, list[str]]], concurrency: int,
           seconds: float, seed: int) -> list[Probe]:
    deadline = time.monotonic() + seconds
    lock = threading.Lock()
    sequence = 0

    def worker() -> list[Probe]:
        nonlocal sequence
        samples: list[Probe] = []
        while time.monotonic() < deadline:
            with lock:
                number = sequence
                sequence += 1
            # Stable synthetic hotspot: 80% M1 first, 10% M1 next, 10% M2 first.
            slot = (number * 7 + seed) % 10
            token, path, expected = paths[0 if slot < 8 else 1 if slot == 8 else 2]
            try:
                status, body, elapsed = fetch(base, path, token)
                correct = status == 200 and [row["case_id"] for row in body.get("items", [])] == expected
                samples.append(Probe(status, elapsed, correct,
                                     None if correct else f"unexpected response for {path}: {status}"))
            except Exception as error:  # measured request failure, never dropped from denominator
                samples.append(Probe(0, 3000.0, False, type(error).__name__))
        return samples

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return [sample for batch in pool.map(lambda _: worker(), range(concurrency)) for sample in batch]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18083")
    parser.add_argument("--mode", required=True, choices=["baseline", "indexed", "cache"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--warmup", type=float, default=30)
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[10, 30])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert args.duration > 0 and args.repeats > 0 and all(c > 0 for c in args.concurrency)
    paths = validate(args.base)
    result: dict[str, Any] = {"mode": args.mode, "seed": args.seed, "warmup_seconds": args.warmup,
                              "duration_seconds": args.duration, "paths": [path for _, path, _ in paths],
                              "runs": []}
    for concurrency in args.concurrency:
        for repeat in range(args.repeats):
            # The validation reads these same keys. Wait out their 2s TTL so
            # "cold" really measures a miss, without clearing shared Redis.
            if args.mode == "cache":
                time.sleep(2.5)
            cold = []
            for token, path, expected in paths:
                status, body, elapsed_ms = fetch(args.base, path, token)
                correct = status == 200 and [row["case_id"] for row in body.get("items", [])] == expected
                cold.append(Probe(status, elapsed_ms, correct))
            assert all(sample.correct for sample in cold), "cold response validation failed"
            warm = window(args.base, paths, concurrency, args.warmup, args.seed) if args.warmup else []
            before = snapshot_metrics(args.base)
            started = time.monotonic()
            samples = window(args.base, paths, concurrency, args.duration, args.seed)
            elapsed = time.monotonic() - started
            after = snapshot_metrics(args.base)
            successes = [s.elapsed_ms for s in samples if s.correct]
            assert samples and successes, "zero valid samples"
            result["runs"].append({
                "concurrency": concurrency, "repeat": repeat, "elapsed_seconds": elapsed,
                "cold": [asdict(s) for s in cold], "warmup_count": len(warm),
                "request_count": len(samples), "success_count": len(successes),
                "success_rps": len(successes) / elapsed, "error_count": len(samples) - len(successes),
                "error_rate": (len(samples) - len(successes)) / len(samples),
                "p50_ms": percentile(successes, .5), "p95_ms": percentile(successes, .95),
                "metrics_delta": {key: after[key] - before[key] for key in before},
                "samples": [asdict(s) for s in samples],
            })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
    if args.output.suffix == ".gz":
        with gzip.open(args.output, "wb", compresslevel=6) as output:
            output.write(serialized)
    else:
        args.output.write_bytes(serialized)
    print(args.output)


if __name__ == "__main__":
    main()
