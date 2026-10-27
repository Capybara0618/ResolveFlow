"""Freeze, run once, and audit the 48 D5 normal HTTP windows on an explicit owned run."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import urllib.request

from evaluation.backend_d5_http import fetch, fixture_token, score, session, window
from evaluation.backend_d5_runtime import (
    free_ports,
    probe,
    start,
    stop_role,
    verify_files,
)
from evaluation.backend_lab import (
    ROOT,
    Settings,
    child_env,
    freeze_file,
    run,
    sha256,
    wait,
)
from evaluation.trade_request_journal import durable

FILES = [
    "scripts/evaluation/" + name
    for name in (
        "backend_d5_normal.py",
        "backend_d5_http.py",
        "backend_d5_relay.py",
        "backend_d5_runtime.py",
        "backend_d5_seed.py",
        "backend_lab.py",
        "trade_request_journal.py",
        "D5Probe.java",
    )
]


def plan():
    result = []
    for profile in ("P1", "P2", "P3"):
        for repeat in range(3):
            conditions = (
                (["A", "B"] if repeat != 1 else ["B", "A"])
                if profile == "P2"
                else ["A", "B", "C"][repeat:] + ["A", "B", "C"][:repeat]
            )
            for concurrency in (10, 30):
                for condition in conditions:
                    result.append(
                        {
                            "id": f"{profile}-r{repeat}-c{concurrency}-{condition}",
                            "profile": profile,
                            "repeat": repeat,
                            "concurrency": concurrency,
                            "condition": condition,
                            "warmup": 30,
                            "seconds": 60,
                        }
                    )
    return result


def relay_control(settings, mode=None):
    state = settings.load()
    path = "/__d5/snapshot" if mode is None else "/__d5/mode"
    request = urllib.request.Request(
        f"http://127.0.0.1:{state['d5_service_ports']['relay']}{path}",
        headers={"X-D5-Run": settings.identity, "Content-Type": "application/json"},
        data=None if mode is None else json.dumps({"mode": mode}).encode(),
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


def ensure_relay(settings):
    state = settings.load()
    if "d5_service_ports" not in state:
        values = free_ports(
            3, set(state["ports"].values()) | set(state["d5_probes"].values())
        )
        state["d5_service_ports"] = dict(
            zip(("commerce2", "relay", "redis_proxy"), values, strict=True)
        )
        settings.save(state)
    if "relay" not in state["pids"]:
        ports = state["d5_service_ports"]
        args = [
            sys.executable,
            "-u",
            "-m",
            "evaluation.backend_d5_relay",
            "--run-id=" + settings.identity,
            "--http-listen",
            str(ports["relay"]),
            "--redis-listen",
            str(ports["redis_proxy"]),
            "--redis-target",
            str(state["ports"]["redis"]),
            "--targets",
            str(state["ports"]["commerce"]),
            str(ports["commerce2"]),
        ]
        env = child_env()
        env["PYTHONPATH"] = str(ROOT / "scripts")
        settings.start_child("relay", args, env, state)
        wait("D5 relay", lambda: relay_control(settings)["mode"] == "normal")
    else:
        relay_control(settings, "normal")


def configure(settings, profile, condition, namespace):
    for role in ("case", "commerce", "commerce2"):
        stop_role(settings, role)
    ensure_relay(settings)
    state = settings.load()
    proxy = state["d5_service_ports"]["redis_proxy"]
    artifact = "A" if profile == "P2" and condition == "A" else "B"
    review_cache = profile == "P3" and condition != "A"
    for role in ("commerce", "commerce2") if profile == "P3" else ("commerce",):
        start(
            settings,
            role,
            artifact,
            cache=review_cache,
            locking=profile == "P3" and condition == "C",
            namespace=namespace,
            redis_port=proxy,
        )
    start(
        settings,
        "case",
        "A" if profile == "P1" and condition == "A" else "B",
        cache=profile == "P1" and condition == "C",
        namespace=namespace,
        redis_port=proxy,
        commerce_port=state["d5_service_ports"]["relay"]
        if profile == "P3"
        else state["ports"]["commerce"],
    )
    if "gateway" not in settings.load()["pids"]:
        start(settings, "gateway")
    return ["case", "commerce"] + (["commerce2"] if profile == "P3" else [])


def verify_manifest(settings, folder):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest["run_id"] != settings.identity or manifest["windows"] != plan():
        raise ValueError("cohort identity/plan changed")
    state = settings.load()
    if manifest["probe_group"] != state["d5_probe_group"] or manifest["ports"] != {
        key: state[key] for key in ("ports", "d5_probes", "d5_service_ports")
    }:
        raise ValueError("frozen runtime configuration changed")
    for path, wanted in manifest["files"].items():
        if sha256(ROOT / path) != wanted:
            raise ValueError("frozen input changed: " + path)
    verify_files(settings)
    return manifest


def freeze(settings, folder):
    verify_files(settings)
    folder.mkdir(parents=True, exist_ok=False)
    baseline = json.loads(
        (settings.folder / "http-oracle-baseline-check-01.json").read_text(
            encoding="utf-8"
        )
    )
    oracle = settings.folder / "http-oracle-development-01.json"
    assert baseline["identical_variants"] == 183 and baseline[
        "reference_sha256"
    ] == sha256(oracle)
    freeze_file(oracle, folder / "cohort.json")
    paths = [ROOT / path for path in FILES]
    paths += [
        folder / "cohort.json",
        settings.folder / "dataset-checked.json",
        settings.folder / "dataset.sql",
        settings.folder / "dataset-oracle.json",
        settings.folder / "d5-builds.json",
    ]
    paths += list(
        (settings.folder / settings.load()["d5_probe_group"]).rglob("*.class")
    )
    manifest = {
        "run_id": settings.identity,
        "phase": "formal normal HTTP, no faults",
        "created_ns": time.time_ns(),
        "git_sha": run(["git", "rev-parse", "HEAD"]),
        "windows": plan(),
        "files": {p.relative_to(ROOT).as_posix(): sha256(p) for p in paths},
        "hardware": run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Compress",
            ]
        ),
        "jvm": "Java21, ActiveProcessorCount=2, heap128-512m per node; Hikari maximum10/minimum2",
        "p1_ab": "same existing SQL/index, no new index; A/B Case JAR hash in d5-builds",
        "model_requests": 0,
        "probe_group": settings.load()["d5_probe_group"],
        "ports": {
            key: settings.load()[key]
            for key in ("ports", "d5_probes", "d5_service_ports")
        },
        "request_timeout_seconds": 3,
        "retry": 0,
        "boundary": "local synthetic read models, Gateway HTTP, P3 two Commerce nodes through round robin; SQL includes auth/epoch, no payments/refunds/models",
    }
    durable(folder / "manifest.json", manifest)
    print("Frozen 48-window normal cohort " + str(folder), flush=True)


async def cold_reads(base, cohort, profile):
    key = cohort["profiles"][profile][0]
    spec = cohort["specs"][key]
    tokens = {spec["actor"]: fixture_token(spec["actor"])} if spec.get("actor") else {}
    async with session(1) as client:
        return [(await fetch(client, base, spec, tokens))[0] for _ in range(3)]


def execute(settings, folder, smoke=False):
    if not smoke:
        verify_manifest(settings, folder)
    cohort = json.loads((folder / "cohort.json").read_text(encoding="utf-8"))
    base = f"http://127.0.0.1:{settings.load()['ports']['gateway']}"
    chosen = (
        [
            {**r, "id": "smoke-" + r["id"], "warmup": 1, "seconds": 2}
            for r in plan()
            if r["repeat"] == 0 and r["concurrency"] == 10
        ]
        if smoke
        else plan()
    )
    for item in chosen:
        target = folder / item["id"]
        if target.exists():
            if smoke or not (target / "complete.json").exists():
                raise ValueError(
                    "started window retained; explicit audit required: " + target.name
                )
            continue
        if not smoke:
            verify_manifest(settings, folder)
        target.mkdir()
        durable(target / "started.json", {**item, "at_ns": time.time_ns()})
        print("START " + item["id"], flush=True)
        roles = configure(
            settings,
            item["profile"],
            item["condition"],
            "rf:d5:" + settings.identity + ":" + item["id"],
        )
        cold = asyncio.run(cold_reads(base, cohort, item["profile"]))
        durable(target / "cold.json", cold)
        if any(row.get("error") == "PROJECTION_MISMATCH" for row in cold):
            raise ValueError("cold projection mismatch; window retained")
        warm = asyncio.run(
            window(
                base,
                cohort,
                item["profile"],
                item["concurrency"],
                item["warmup"],
                target / "warmup.jsonl.gz",
            )
        )
        warm_score = score(target / "warmup.jsonl.gz", cohort, item["profile"], warm)
        durable(target / "warmup.json", {"metadata": warm, "score": warm_score})
        if warm_score["errors"].get("PROJECTION_MISMATCH"):
            raise ValueError("warmup projection mismatch; window retained")
        for role in roles:
            probe(settings, role, "begin", {})
        before = {role: probe(settings, role) for role in roles}
        route_before = relay_control(settings)
        measured = asyncio.run(
            window(
                base,
                cohort,
                item["profile"],
                item["concurrency"],
                item["seconds"],
                target / "requests.jsonl.gz",
            )
        )
        after = {role: probe(settings, role) for role in roles}
        route_after = relay_control(settings)
        result = score(target / "requests.jsonl.gz", cohort, item["profile"], measured)
        sql = sum(after[r]["sql"] - before[r]["sql"] for r in roles)
        result.update(
            sql=sql,
            sql_per_success=sql / result["success"] if result["success"] else None,
            sql_per_request=sql / result["total"] if result["total"] else None,
        )
        durable(
            target / "complete.json",
            {
                "window": item,
                "metadata": measured,
                "score": result,
                "before": before,
                "after": after,
                "route_before": route_before,
                "route_after": route_after,
                "requests_sha256": sha256(target / "requests.jsonl.gz"),
                "at_ns": time.time_ns(),
            },
        )
        print("DONE " + item["id"] + " " + json.dumps(result), flush=True)
        if any(after[r]["sql_inflight"] for r in roles) or result["errors"].get(
            "PROJECTION_MISMATCH"
        ):
            raise ValueError(
                "candidate correctness/inflight failure; original window retained"
            )


def audit(settings, folder):
    manifest = verify_manifest(settings, folder)
    cohort = json.loads((folder / "cohort.json").read_text(encoding="utf-8"))
    rows = []
    for item in manifest["windows"]:
        target = folder / item["id"]
        data = json.loads((target / "complete.json").read_text(encoding="utf-8"))
        assert data["window"] == item and data["requests_sha256"] == sha256(
            target / "requests.jsonl.gz"
        )
        result = score(
            target / "requests.jsonl.gz", cohort, item["profile"], data["metadata"]
        )
        assert all(data["score"][key] == value for key, value in result.items())
        assert data["metadata"]["target_seconds"] == item["seconds"]
        assert not any(r["sql_inflight"] for r in data["after"].values())
        sql = sum(
            data["after"][r]["sql"] - data["before"][r]["sql"] for r in data["after"]
        )
        assert sql == data["score"]["sql"]
        rows.append({**item, **data["score"]})
    groups = {}
    for profile in ("P1", "P2", "P3"):
        for concurrency in (10, 30):
            for condition in ("A", "B") if profile == "P2" else ("A", "B", "C"):
                selected = [
                    r
                    for r in rows
                    if (r["profile"], r["concurrency"], r["condition"])
                    == (profile, concurrency, condition)
                ]
                assert len(selected) == 3
                groups[f"{profile}-c{concurrency}-{condition}"] = {
                    key: statistics.median(r[key] for r in selected)
                    for key in (
                        "success_p95_ms",
                        "success_rps",
                        "sql_per_success",
                        "sql_per_request",
                    )
                }
    summary = {
        "windows": rows,
        "median_groups": groups,
        "window_count": len(rows),
        "requests": sum(r["total"] for r in rows),
        "failures": sum(r["failed"] for r in rows),
    }
    durable(folder / "audit.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "windows"}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "smoke", "run", "audit"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--cohort", required=True)
    args = parser.parse_args()
    if not args.cohort.replace("-", "").isalnum():
        raise ValueError("explicit simple cohort name required")
    settings = Settings(args.run_id)
    folder = settings.folder / args.cohort
    with settings.operation_lock():
        if args.action == "freeze":
            freeze(settings, folder)
        elif args.action == "audit":
            audit(settings, folder)
        else:
            try:
                execute(settings, folder, smoke=args.action == "smoke")
            finally:
                for role in ("case", "commerce", "commerce2", "gateway", "relay"):
                    stop_role(settings, role)


if __name__ == "__main__":
    main()
