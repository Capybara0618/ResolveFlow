"""Small natural-cold dual-JVM comparison: three pairs, 30 requests each, no fault gates."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

from evaluation.backend_d5_http import digest, session
from evaluation.backend_d5_rebuild import load_events, request
from evaluation.backend_d5_rebuild_support import rebuild_peak, redis
from evaluation.backend_d5_runtime import probe, start, stop_role, verify_files
from evaluation.backend_lab import ROOT, Settings, sha256, wait
from evaluation.trade_request_journal import durable

NODES = ("commerce", "commerce2")
PRODUCT = "P-1001"
SOURCES = [
    "scripts/evaluation/" + name
    for name in (
        "backend_hot_rebuild.py",
        "backend_d5_http.py",
        "backend_d5_rebuild.py",
        "backend_d5_rebuild_audit.py",
        "backend_d5_rebuild_support.py",
        "backend_d5_faults.py",
        "backend_d5_normal.py",
        "backend_d5_runtime.py",
        "backend_lab.py",
        "trade_request_journal.py",
    )
]


def plan(smoke=False):
    return [
        {
            "id": f"r{repeat}-{condition}",
            "repeat": repeat,
            "condition": condition,
            "requests": 30,
            "product": PRODUCT,
        }
        for repeat in range(1 if smoke else 3)
        for condition in (("B", "C") if repeat % 2 == 0 else ("C", "B"))
    ]


def summarize(rows, events, page_calls, sql, expected):
    if len(rows) != 30 or sorted(r["index"] for r in rows) != list(range(30)):
        raise ValueError("request denominator changed")
    if any(r["node"] != NODES[r["index"] % 2] for r in rows):
        raise ValueError("node distribution changed")
    loads = sum(
        r["stage"] == "load_start" and r.get("product") == PRODUCT for r in events
    )
    if loads != page_calls:
        raise ValueError("page counter disagrees with load events")
    if any(r["status"] == 200 and r.get("body_sha256") != expected for r in rows):
        raise ValueError("projection mismatch")
    peak = rebuild_peak(events, PRODUCT)
    okay = sum(r["status"] == 200 for r in rows)
    rejected = sum(r["status"] == 503 for r in rows)
    return {
        "rebuilds": loads,
        "peak": peak,
        "sql": sql,
        "success": okay,
        "rejected": rejected,
        "errors": 30 - okay - rejected,
        "requests": 30,
    }


def page_calls(snapshot):
    return sum(
        value
        for key, value in snapshot["meters"].items()
        if key.startswith("resolveflow.product_reviews.database.calls[")
        and "operation=page" in key
        and key.endswith(":COUNT")
    )


def freeze(settings, folder):
    verify_files(settings)
    if settings.load()["pids"]:
        raise ValueError("stop owned apps before freezing")
    folder.mkdir(parents=True, exist_ok=False)
    state = settings.load()
    paths = [ROOT / path for path in SOURCES]
    paths += list((settings.folder / state["d5_probe_group"]).rglob("*.class"))
    paths += [
        settings.folder / "d5-builds.json",
        settings.folder / "dataset-checked.json",
        settings.folder / "http-oracle-development-01.json",
    ]
    durable(
        folder / "manifest.json",
        {
            "run_id": settings.identity,
            "plan": plan(),
            "created_ns": time.time_ns(),
            "files": {p.relative_to(ROOT).as_posix(): sha256(p) for p in paths},
            "probe_group": state["d5_probe_group"],
            "model_requests": 0,
            "method": "natural cold namespace; same D4 Commerce bytes, cache on, only lock switch differs; no artificial gate, no retry, fixed 3 pairs",
        },
    )


def check(settings, folder):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == settings.identity and manifest["plan"] == plan()
    assert manifest["probe_group"] == settings.load()["d5_probe_group"]
    for path, wanted in manifest["files"].items():
        if sha256(ROOT / path) != wanted:
            raise ValueError("frozen source changed: " + path)
    verify_files(settings)


async def burst(settings):
    async with session(30) as client:
        barrier = asyncio.Event()

        async def send(index):
            await barrier.wait()
            return await request(client, settings, NODES[index % 2], PRODUCT, index)

        jobs = [asyncio.create_task(send(i)) for i in range(30)]
        barrier.set()
        return await asyncio.gather(*jobs)


def execute(settings, folder, smoke=False):
    if smoke:
        folder.mkdir(parents=True, exist_ok=False)
    else:
        check(settings, folder)
    expected = json.loads(
        (settings.folder / "http-oracle-development-01.json").read_text(
            encoding="utf-8"
        )
    )["specs"]["review-P-1001"]["body_sha256"]
    settings.assert_owned("mysql")
    settings.assert_owned("redis")
    settings.compose("up", "-d")
    wait("owned MySQL", lambda: settings.sql("SELECT 1;") == "1")
    try:
        for item in plan(smoke):
            target = folder / item["id"]
            if target.exists():
                raise ValueError("round already started; never overwrite or rerun")
            if not smoke:
                check(settings, folder)
            target.mkdir()
            durable(target / "started.json", {**item, "at_ns": time.time_ns()})
            namespace = (
                "rf:hot:" + settings.identity + ":" + folder.name + ":" + item["id"]
            )
            for node in NODES:
                start(
                    settings,
                    node,
                    cache=True,
                    locking=item["condition"] == "C",
                    namespace=namespace,
                )

            # Establish both JDBC/Redis/Redisson clients on a different product, outside measurement.
            async def warm():
                async with session(1) as client:
                    rows = [
                        await request(client, settings, node, product, "warm")
                        for node, product in zip(
                            NODES, ("P-1002", "P-1003"), strict=True
                        )
                    ]
                    assert all(r["status"] == 200 for r in rows), "warmup failed"
                    return rows

            durable(target / "warm.json", asyncio.run(warm()))
            key = namespace + ":" + PRODUCT + ":1"
            if redis(settings, "EXISTS", key) != 0:
                raise ValueError("hot key was not cold before burst")
            durable(
                target / "cold.json", {"key": key, "exists": 0, "at_ns": time.time_ns()}
            )
            offsets = {
                node: (settings.folder / (node + "-events.jsonl")).stat().st_size
                if (settings.folder / (node + "-events.jsonl")).exists()
                else 0
                for node in NODES
            }
            for node in NODES:
                probe(settings, node, "begin", {})
                probe(settings, node, "events/on", {})
            before = {node: probe(settings, node) for node in NODES}
            rows = asyncio.run(burst(settings))
            after = {node: probe(settings, node) for node in NODES}
            for node in NODES:
                probe(settings, node, "events/off", {})
            events = load_events(settings, offsets)
            sql = sum(after[n]["sql"] - before[n]["sql"] for n in NODES)
            pages = sum(page_calls(after[n]) - page_calls(before[n]) for n in NODES)
            result = summarize(rows, events, pages, sql, expected)
            assert all(after[n]["sql_inflight"] == 0 for n in NODES)
            durable(
                target / "complete.json",
                {
                    "round": item,
                    "before": before,
                    "after": after,
                    "requests": rows,
                    "events": events,
                    "summary": result,
                    "expected": expected,
                    "namespace": namespace,
                    "at_ns": time.time_ns(),
                },
            )
            print(item["id"] + " " + json.dumps(result), flush=True)
            for node in NODES:
                stop_role(settings, node)
    finally:
        for node in NODES:
            stop_role(settings, node)
        settings.compose("stop", "--timeout", "30")


def audit(settings, folder):
    check(settings, folder)
    results = []
    for item in plan():
        data = json.loads(
            (folder / item["id"] / "complete.json").read_text(encoding="utf-8")
        )
        assert data["round"] == item
        assert all(
            r.get("body_sha256") == digest(r["body"])
            for r in data["requests"]
            if "body" in r
        )
        calls = sum(
            page_calls(data["after"][n]) - page_calls(data["before"][n]) for n in NODES
        )
        sql = sum(data["after"][n]["sql"] - data["before"][n]["sql"] for n in NODES)
        result = summarize(
            data["requests"], data["events"], calls, sql, data["expected"]
        )
        assert result == data["summary"]
        results.append({**item, **result})
    medians = {
        condition: statistics.median(
            r["rebuilds"] for r in results if r["condition"] == condition
        )
        for condition in ("B", "C")
    }
    output = {
        "rounds": results,
        "median_rebuilds": medians,
        "requests": 180,
        "success": sum(r["success"] for r in results),
        "rejected": sum(r["rejected"] for r in results),
        "errors": sum(r["errors"] for r in results),
        "boundary": "natural cold-cache burst; three pairs; direct internal HTTP to two real Commerce JVMs; not Gateway p95 or fault recovery",
    }
    durable(folder / "audit.json", output)
    print(json.dumps(output), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("smoke", "freeze", "run", "audit"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--cohort", required=True)
    args = parser.parse_args()
    if not args.cohort.replace("-", "").isalnum():
        raise ValueError("explicit simple cohort name")
    settings = Settings(args.run_id)
    with settings.operation_lock():
        folder = settings.folder / args.cohort
        if args.action == "freeze":
            freeze(settings, folder)
        elif args.action == "audit":
            audit(settings, folder)
        else:
            execute(settings, folder, smoke=args.action == "smoke")


if __name__ == "__main__":
    main()
