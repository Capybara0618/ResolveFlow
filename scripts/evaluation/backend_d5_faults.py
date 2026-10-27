"""D5 owned Redis fault windows, frozen separately from the normal HTTP cohort."""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from evaluation.backend_d5_http import fetch, fixture_token, score, session, window
from evaluation.backend_d5_normal import FILES, configure, relay_control
from evaluation.backend_d5_runtime import probe, stop_role, verify_files
from evaluation.backend_lab import ROOT, Settings, freeze_file, run, sha256
from evaluation.trade_request_journal import durable


def plan():
    return [
        {
            "id": f"{profile}-{fault}-r{repeat}",
            "profile": profile,
            "fault": fault,
            "repeat": repeat,
            "concurrency": 32,
            "warmup": 10,
            "seconds": 30,
        }
        for profile, faults in (
            ("P1", ("expiry", "drop", "stall", "recovery")),
            ("P3", ("stall",)),
        )
        for fault in faults
        for repeat in range(3)
    ]


def freeze_inputs(settings, folder, windows, sources, extra=None):
    verify_files(settings)
    folder.mkdir(parents=True, exist_ok=False)
    freeze_file(
        settings.folder / "http-oracle-development-01.json", folder / "cohort.json"
    )
    paths = [ROOT / name for name in sorted(set(FILES + sources))]
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
    state = settings.load()
    manifest = {
        "run_id": settings.identity,
        "git_sha": run(["git", "rev-parse", "HEAD"]),
        "created_ns": time.time_ns(),
        "windows": windows,
        "model_requests": 0,
        "probe_group": state["d5_probe_group"],
        "ports": {
            key: state[key] for key in ("ports", "d5_probes", "d5_service_ports")
        },
        "files": {p.relative_to(ROOT).as_posix(): sha256(p) for p in paths},
    }
    manifest.update(extra or {})
    durable(folder / "manifest.json", manifest)
    return manifest


def check_inputs(settings, folder, expected):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    state = settings.load()
    if manifest["run_id"] != settings.identity or manifest["windows"] != expected:
        raise ValueError("wrong owned cohort/plan")
    if manifest["probe_group"] != state["d5_probe_group"] or manifest["ports"] != {
        key: state[key] for key in ("ports", "d5_probes", "d5_service_ports")
    }:
        raise ValueError("frozen runtime changed")
    for path, wanted in manifest["files"].items():
        if sha256(ROOT / path) != wanted:
            raise ValueError("frozen input changed: " + path)
    verify_files(settings)
    return manifest


async def recovery(base, cohort, profile):
    spec = cohort["specs"][cohort["profiles"][profile][0]]
    tokens = {spec["actor"]: fixture_token(spec["actor"])} if spec.get("actor") else {}
    started = time.perf_counter()
    rows, first = [], None
    async with session(1) as client:
        while time.perf_counter() - started < 5 and first is None:
            row, _ = await fetch(client, base, spec, tokens)
            rows.append({"offset_seconds": time.perf_counter() - started, **row})
            if row["correct"]:
                first = time.perf_counter() - started
            else:
                await asyncio.sleep(0.05)
        follow = [(await fetch(client, base, spec, tokens))[0] for _ in range(10)]
    return {"observations": rows, "first_success_seconds": first, "followup": follow}


def execute(settings, folder, smoke=False):
    if not smoke:
        check_inputs(settings, folder, plan())
    cohort = json.loads((folder / "cohort.json").read_text(encoding="utf-8"))
    base = f"http://127.0.0.1:{settings.load()['ports']['gateway']}"
    windows = (
        [
            {**r, "id": "smoke-" + r["id"], "warmup": 1, "seconds": 2}
            for r in plan()
            if r["repeat"] == 0
        ]
        if smoke
        else plan()
    )
    for item in windows:
        target = folder / item["id"]
        if target.exists():
            if smoke or not (target / "complete.json").exists():
                raise ValueError("started window retained; do not rerun " + target.name)
            continue
        if not smoke:
            check_inputs(settings, folder, plan())
        target.mkdir()
        durable(target / "started.json", {**item, "at_ns": time.time_ns()})
        print("START " + item["id"], flush=True)
        roles = configure(
            settings,
            item["profile"],
            "C",
            "rf:d5:" + settings.identity + ":fault:" + item["id"],
        )
        if item["fault"] == "recovery":
            relay_control(settings, "drop")
        warm = asyncio.run(
            window(
                base,
                cohort,
                item["profile"],
                32,
                item["warmup"],
                target / "warmup.jsonl.gz",
            )
        )
        warm_score = score(target / "warmup.jsonl.gz", cohort, item["profile"], warm)
        durable(target / "warmup.json", {"metadata": warm, "score": warm_score})
        if warm_score["errors"].get("PROJECTION_MISMATCH"):
            raise ValueError("warmup correctness failure")
        mode = item["fault"] if item["fault"] in ("drop", "stall") else "normal"
        injected = relay_control(settings, mode)
        for role in roles:
            probe(settings, role, "begin", {})
        before = {role: probe(settings, role) for role in roles}
        measured = asyncio.run(
            window(
                base,
                cohort,
                item["profile"],
                32,
                item["seconds"],
                target / "requests.jsonl.gz",
            )
        )
        after = {role: probe(settings, role) for role in roles}
        restored = relay_control(settings, "normal")
        recovered = asyncio.run(recovery(base, cohort, item["profile"]))
        settled = {role: probe(settings, role) for role in roles}
        result = score(target / "requests.jsonl.gz", cohort, item["profile"], measured)
        sql = sum(after[r]["sql"] - before[r]["sql"] for r in roles)
        result.update(
            sql=sql,
            sql_per_success=sql / result["success"] if result["success"] else None,
            sql_per_request=sql / result["total"] if result["total"] else None,
        )
        passed = (
            not result["errors"].get("PROJECTION_MISMATCH")
            and recovered["first_success_seconds"] is not None
            and recovered["first_success_seconds"] <= 5
            and all(r["correct"] for r in recovered["followup"])
            and all(r["sql_inflight"] == 0 for r in settled.values())
        )
        durable(
            target / "complete.json",
            {
                "window": item,
                "metadata": measured,
                "score": result,
                "before": before,
                "after": after,
                "settled": settled,
                "injected": injected,
                "restored": restored,
                "recovery": recovered,
                "requests_sha256": sha256(target / "requests.jsonl.gz"),
                "passed": passed,
            },
        )
        print(
            "DONE " + item["id"] + " " + json.dumps({"passed": passed, **result}),
            flush=True,
        )
        if result["errors"].get("PROJECTION_MISMATCH"):
            raise ValueError("candidate correctness failure, original window retained")


def audit(settings, folder):
    check_inputs(settings, folder, plan())
    cohort = json.loads((folder / "cohort.json").read_text(encoding="utf-8"))
    rows = []
    for item in plan():
        target = folder / item["id"]
        data = json.loads((target / "complete.json").read_text(encoding="utf-8"))
        assert data["window"] == item and data["requests_sha256"] == sha256(
            target / "requests.jsonl.gz"
        )
        result = score(
            target / "requests.jsonl.gz", cohort, item["profile"], data["metadata"]
        )
        assert all(data["score"][k] == v for k, v in result.items())
        assert data["metadata"]["target_seconds"] == item["seconds"]
        assert data["score"]["sql"] == sum(
            data["after"][r]["sql"] - data["before"][r]["sql"] for r in data["after"]
        )
        rows.append(
            {
                **item,
                "passed": data["passed"],
                **data["score"],
                "recovery_seconds": data["recovery"]["first_success_seconds"],
            }
        )
    durable(
        folder / "audit.json",
        {"windows": rows, "passed": sum(r["passed"] for r in rows), "total": len(rows)},
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "smoke", "run", "audit"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--cohort", required=True)
    args = parser.parse_args()
    if not args.cohort.replace("-", "").isalnum():
        raise ValueError("explicit simple cohort name")
    settings = Settings(args.run_id)
    folder = settings.folder / args.cohort
    with settings.operation_lock():
        if args.action == "freeze":
            freeze_inputs(
                settings, folder, plan(), ["scripts/evaluation/backend_d5_faults.py"]
            )
        elif args.action == "audit":
            audit(settings, folder)
        else:
            try:
                execute(settings, folder, smoke=args.action == "smoke")
            finally:
                try:
                    if "relay" in settings.load()["pids"]:
                        relay_control(settings, "normal")
                finally:
                    for role in ("case", "commerce", "commerce2", "gateway", "relay"):
                        stop_role(settings, role)


if __name__ == "__main__":
    main()
