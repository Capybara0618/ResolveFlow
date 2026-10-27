"""R01-R06: once-only 120 owned two-Commerce cache rebuild rounds; no money execution."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from contextvars import ContextVar

import aiohttp

from evaluation.backend_d5_faults import check_inputs, freeze_inputs
from evaluation.backend_d5_http import digest, fixture_token, percentile, session
from evaluation.backend_d5_normal import ensure_relay, relay_control
from evaluation.backend_d5_rebuild_audit import assess
from evaluation.backend_d5_rebuild_support import (
    Paused,
    durable_probe,
    fixture,
    rebuild_peak,
    redis,
    service_token,
)
from evaluation.backend_d5_runtime import probe, start, stop_role
from evaluation.backend_lab import Settings, sha256
from evaluation.trade_request_journal import durable

NODES = ("commerce", "commerce2")
JOURNAL = ContextVar("d5_rebuild_request_journal", default=None)


def journal(stage, row):
    path = JOURNAL.get()
    if path is not None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps({"stage": stage, **row}, separators=(",", ":")) + "\n"
            )


def plan():
    return [
        {
            "id": f"{scenario}-r{repeat}-{condition}",
            "scenario": scenario,
            "repeat": repeat,
            "condition": condition,
            "concurrency": 10 if repeat < 5 else 30,
            "ttl": scenario == "R01" and repeat >= 5,
            "redis_fault": ("drop" if repeat < 5 else "stall")
            if scenario == "R06"
            else None,
        }
        for scenario in ("R01", "R02", "R03", "R04", "R05", "R06")
        for repeat in range(10)
        for condition in (("B", "C") if repeat % 2 == 0 else ("C", "B"))
    ]


def namespace(settings):
    return "rf:d5:" + settings.identity + ":rebuild-v1"


def configure(settings, condition):
    for role in NODES:
        stop_role(settings, role)
    ensure_relay(settings)
    state = settings.load()
    for role in NODES:
        start(
            settings,
            role,
            "B",
            cache=True,
            locking=condition == "C",
            namespace=namespace(settings),
            redis_port=state["d5_service_ports"]["redis_proxy"],
        )
    if "case" not in settings.load()["pids"]:
        start(
            settings,
            "case",
            "B",
            commerce_port=state["d5_service_ports"]["relay"],
            redis_port=state["d5_service_ports"]["redis_proxy"],
        )
    if "gateway" not in settings.load()["pids"]:
        start(settings, "gateway")


def base(settings, node):
    state = settings.load()
    port = (
        state["ports"][node] if node != "commerce2" else state["d5_service_ports"][node]
    )
    return f"http://127.0.0.1:{port}"


async def request(client, settings, node, product, index, limit=10):
    started = time.perf_counter()
    row = {
        "index": index,
        "node": node,
        "product": product,
        "started_ns": time.time_ns(),
        "status": 0,
    }
    row["request_id"] = node + "-" + str(time.perf_counter_ns())
    journal("start", row)
    try:
        async with client.get(
            base(settings, node)
            + f"/internal/v1/shop/products/{product}/reviews?limit={limit}",
            headers={"Authorization": "Bearer " + service_token()},
        ) as response:
            row["status"] = response.status
            body = await response.read()
        row["body"] = json.loads(body)
        row["body_sha256"] = digest(row["body"])
    except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as error:
        row["error"] = type(error).__name__
    row.update(
        elapsed_ms=(time.perf_counter() - started) * 1000, ended_ns=time.time_ns()
    )
    journal("end", row)
    return row


async def entered(settings, node, label, seconds=3):
    path = settings.folder / (node + "-" + label + ".entered")
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        if path.exists():
            return {
                "node": node,
                "gate": label,
                "at_ns": time.time_ns(),
                "call": path.read_text(encoding="utf-8"),
            }
        await asyncio.sleep(0.005)
    raise ValueError("INVALID_SETUP gate not reached: " + node + " " + label)


async def legal_reply(client, settings, target, label):
    path = (
        base(settings, "gateway")
        + f"/api/v1/merchant/reviews/{target['review_id']}/reply"
    )
    expected = "D5 legal reply " + label
    async with client.post(
        path,
        headers={"Authorization": "Bearer " + fixture_token("d5-merchant-0")},
        json={"body": expected, "expected_version": 1},
    ) as response:
        body = await response.json()
        if (
            response.status != 200
            or body.get("reply") != expected
            or body.get("version") != 2
        ):
            raise ValueError("legal reply refused: " + str(response.status))
    return {"response": body, "at_ns": time.time_ns()}


def load_events(settings, offsets):
    events = []
    for node in NODES:
        path = settings.folder / (node + "-events.jsonl")
        if path.exists():
            with path.open("rb") as handle:
                handle.seek(offsets[node])
                for line in handle:
                    events.append(json.loads(line))
    return events


async def exercise(settings, item, folder, products):
    JOURNAL.set(folder / "requests.jsonl")
    label, scenario, condition, count = (
        item["id"],
        item["scenario"],
        item["condition"],
        item["concurrency"],
    )
    hot, warm_a, warm_b = products[:3]
    product = hot["product"]
    key = namespace(settings) + ":" + product + ":1"
    lock_key = key + ":rebuild"
    gate_label = label.replace("smoke-", "s-")
    facts, requests, controls, paused, terminal, new_projection = (
        {},
        [],
        [],
        None,
        None,
        None,
    )
    recovery_anchor = None
    offsets = {
        node: (settings.folder / (node + "-events.jsonl")).stat().st_size
        if (settings.folder / (node + "-events.jsonl")).exists()
        else 0
        for node in NODES
    }
    durable(folder / "event-offsets.json", offsets)
    async with session(count + 8) as client:
        expected = await request(client, settings, "commerce", product, "reference", 11)
        assert expected["status"] == 200 and expected["body"]["summary"]["count"] == 1
        for node, warm in zip(NODES, (warm_a, warm_b), strict=True):
            row = await request(client, settings, node, warm["product"], "client-warm")
            if row["status"] != 200:
                raise ValueError("INVALID_SETUP client warm failed")
        if item["ttl"]:
            prime = await request(client, settings, "commerce", product, "prime")
            assert prime["status"] == 200
            ttl = redis(settings, "PTTL", key)
            assert 0 < ttl <= 30000
            at = time.perf_counter()
            await asyncio.sleep((ttl + 80) / 1000)
            assert redis(settings, "EXISTS", key) == 0
            facts["ttl"] = {
                "observed_ms": ttl,
                "actual_wait_ms": (time.perf_counter() - at) * 1000,
                "exists_after": 0,
            }
        for node in NODES:
            probe(settings, node, "begin", {})
            probe(settings, node, "events/on", {})
        before = {node: probe(settings, node) for node in NODES}
        gate_nodes = (
            NODES if scenario in ("R01", "R04", "R05", "R06") else ("commerce",)
        )
        for node in gate_nodes:
            probe(
                settings,
                node,
                "gate",
                {
                    "id": gate_label,
                    "product": product,
                    "mode": "fail" if scenario == "R02" else "hold",
                },
            )
        jobs = []
        try:
            first = asyncio.create_task(
                request(client, settings, "commerce", product, 0)
            )
            jobs.append(first)
            facts["owner_gate"] = await entered(settings, "commerce", gate_label)
            if condition == "C":
                facts["owner_lock"] = {
                    "pttl": redis(settings, "PTTL", lock_key),
                    "value": redis(settings, "HGETALL", lock_key),
                }
                assert facts["owner_lock"]["pttl"] > 0
            if scenario == "R02":
                recovery_anchor = time.perf_counter()
                facts["recovery_started_ns"] = time.time_ns()
                probe(settings, "commerce", "release", {})
                failed = await first
                facts["first_failure"] = failed
                if failed["status"] != 500:
                    raise ValueError("INVALID_SETUP first test failure not reached")
            if scenario == "R04":
                paused = Paused(settings, "commerce")
                facts["suspended"] = {"pid": paused.pid, "at_ns": paused.suspended_ns}
            jobs += [
                asyncio.create_task(
                    request(client, settings, NODES[index % 2], product, index)
                )
                for index in range(1, count)
            ]
            if scenario == "R01":
                controls = await asyncio.gather(
                    *(
                        request(
                            client,
                            settings,
                            NODES[i],
                            products[3 + i]["product"],
                            "independent",
                        )
                        for i in range(2)
                    )
                )
                assert (
                    all(row["status"] == 200 for row in controls) and not first.done()
                )
                await asyncio.sleep(0.05)
            elif scenario == "R03":
                await asyncio.sleep(0.05)
                facts["last_owner_probe"] = probe(settings, "commerce")
                stop_role(settings, "commerce")
                terminal = {
                    "node": "commerce",
                    "at_ns": time.time_ns(),
                    "pid": facts["last_owner_probe"]["pid"],
                }
                facts["killed"] = terminal
            elif scenario == "R04":
                await asyncio.sleep(2.2)
                survivor = asyncio.create_task(
                    request(client, settings, "commerce2", product, "new-owner")
                )
                facts["survivor_gate"] = await entered(
                    settings, "commerce2", gate_label
                )
                if condition == "C":
                    facts["new_lock_before_resume"] = redis(
                        settings, "HGETALL", lock_key
                    )
                    assert (
                        facts["new_lock_before_resume"]
                        and facts["new_lock_before_resume"]
                        != facts["owner_lock"]["value"]
                    )
                recovery_anchor = time.perf_counter()
                facts["recovery_started_ns"] = time.time_ns()
                facts["resumed_ns"] = paused.resume()
                probe(settings, "commerce", "release", {})
                await asyncio.sleep(0.05)
                if condition == "C":
                    facts["new_lock_after_old_release"] = redis(
                        settings, "HGETALL", lock_key
                    )
                    assert (
                        facts["new_lock_after_old_release"]
                        == facts["new_lock_before_resume"]
                    )
                probe(settings, "commerce2", "release", {})
                facts["survivor_response"] = await survivor
            elif scenario == "R05":
                facts["legal_reply"] = await legal_reply(client, settings, hot, label)
                recovery_anchor = time.perf_counter()
                facts["recovery_started_ns"] = time.time_ns()
                for node in gate_nodes:
                    probe(settings, node, "release", {})
                new_projection = await request(
                    client, settings, "commerce2", product, "new-reference", 11
                )
            elif scenario == "R06":
                facts["redis_injected"] = relay_control(settings, item["redis_fault"])
            if scenario != "R03":
                if recovery_anchor is None:
                    recovery_anchor = time.perf_counter()
                    facts["recovery_started_ns"] = time.time_ns()
                for node in gate_nodes:
                    probe(settings, node, "release", {})
            requests = await asyncio.gather(*jobs)
            recovered_from = recovery_anchor or time.perf_counter()
            if scenario == "R06":
                recovered_from = time.perf_counter()
                facts["recovery_started_ns"] = time.time_ns()
                facts["redis_restored"] = relay_control(settings, "normal")
            if scenario == "R03":
                recovered_from = terminal["at_ns"] / 1e9
                facts["recovery_started_ns"] = terminal["at_ns"]
            observations, first_success = [], None
            while (
                time.time() - recovered_from
                if scenario == "R03"
                else time.perf_counter() - recovered_from
            ) < 5:
                row = await request(client, settings, "commerce2", product, "observe")
                observations.append(row)
                if row["status"] == 200 and redis(
                    settings,
                    "GET",
                    key
                    if scenario != "R05"
                    else namespace(settings) + ":" + product + ":2",
                ):
                    first_success = (
                        time.time() - recovered_from
                        if scenario == "R03"
                        else time.perf_counter() - recovered_from
                    )
                    facts["cache_confirmed_ns"] = time.time_ns()
                    break
                await asyncio.sleep(0.05)
            follow = [
                await request(
                    client,
                    settings,
                    NODES[i % 2] if scenario != "R03" else "commerce2",
                    product,
                    "follow-" + str(i),
                )
                for i in range(10)
            ]
            facts.update(recovery_seconds=first_success, observations=observations)
        finally:
            if paused:
                paused.close()
            relay_control(settings, "normal")
            for node in gate_nodes:
                if node in settings.load()["pids"]:
                    probe(settings, node, "release", {})
            for job in jobs:
                if not job.done():
                    job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
            for node in NODES:
                if node in settings.load()["pids"]:
                    probe(settings, node, "events/off", {})
        after = {
            node: probe(settings, node)
            for node in NODES
            if node in settings.load()["pids"]
        }
    events = load_events(settings, offsets)
    # Events and SQL write-ahead records survive owner termination; no absent counter is filled with zero.
    with (folder / "events.jsonl").open("x", encoding="utf-8") as handle:
        for row in events:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    peak = rebuild_peak(events, product, terminal)
    waits = [r["wait_ns"] / 1e6 for r in events if r["stage"] == "lock_tryLock"]
    loads = sum(
        r["stage"] == "load_start" and r.get("product") == product for r in events
    )
    result = {
        "round": item,
        "products": products,
        "before": before,
        "after": after,
        "facts": facts,
        "initial": requests,
        "independent": controls,
        "followup": follow,
        "reference": expected,
        "new_reference": new_projection,
        "events_sha256": sha256(folder / "events.jsonl"),
        "sql_execute_events": sum(r["stage"] == "sql_execute" for r in events),
        "rebuild_loads": loads,
        "rebuild_peak": peak,
        "lock_wait_p95_ms": percentile(waits, 0.95),
        "terminal": terminal,
    }

    result["assessment"] = assess(result, events)
    result["passed"] = result["assessment"]["passed"]
    return result


def prepare_data(settings, folder, smoke=False):
    folder.mkdir(parents=True, exist_ok=False)
    durable(
        folder / "started.json", {"at_ns": time.time_ns(), "run_id": settings.identity}
    )
    windows = (
        [{**r, "id": "smoke-" + r["id"]} for r in plan() if r["repeat"] == 0]
        if smoke
        else plan()
    )
    rows = {}
    for item in windows:
        labels = ["hot", "warm-a", "warm-b"] + (
            ["independent-a", "independent-b"] if item["scenario"] == "R01" else []
        )
        rows[item["id"]] = [
            fixture(settings, folder, item["id"] + "-" + name) for name in labels
        ]
        print("PREPARED " + item["id"], flush=True)
    durable(
        folder / "manifest.json",
        {
            "run_id": settings.identity,
            "rounds": rows,
            "files": {
                p.relative_to(folder).as_posix(): sha256(p)
                for p in folder.glob("*.sql")
            },
            "boundary": "additional isolated synthetic paid read models; no payment/refund provider execution",
        },
    )


def execute(settings, folder, data_folder, smoke=False):
    if not smoke:
        check_inputs(settings, folder, plan())
    windows = (
        [{**r, "id": "smoke-" + r["id"]} for r in plan() if r["repeat"] == 0]
        if smoke
        else plan()
    )
    dataset = json.loads((data_folder / "manifest.json").read_text(encoding="utf-8"))
    assert dataset["run_id"] == settings.identity
    for name, wanted in dataset["files"].items():
        assert sha256(data_folder / name) == wanted
    for item in windows:
        target = folder / item["id"]
        if target.exists():
            if smoke or not (target / "complete.json").exists():
                raise ValueError("started round retained; do not rerun " + item["id"])
            continue
        if not smoke:
            check_inputs(settings, folder, plan())
        target.mkdir()
        durable(target / "started.json", {**item, "at_ns": time.time_ns()})
        print("START " + item["id"], flush=True)
        configure(settings, item["condition"])
        products = dataset["rounds"][item["id"]]
        try:
            result = asyncio.run(exercise(settings, item, target, products))
        except (
            ValueError,
            AssertionError,
            OSError,
            TimeoutError,
            RuntimeError,
            aiohttp.ClientError,
        ) as error:
            offsets_file = target / "event-offsets.json"
            if offsets_file.exists() and not (target / "events.jsonl").exists():
                offsets = json.loads(offsets_file.read_text(encoding="utf-8"))
                with (target / "events.jsonl").open("x", encoding="utf-8") as handle:
                    for row in load_events(settings, offsets):
                        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
            result = {
                "round": item,
                "products": products,
                "passed": False,
                "status": "INVALID_SETUP"
                if "INVALID_SETUP" in str(error)
                else "FAILED",
                "error": type(error).__name__,
                "message": str(error)[:500],
                "rebuild_loads": None,
                "rebuild_peak": None,
                "sql_execute_events": None,
            }
            if smoke:
                durable(target / "complete.json", result)
                raise
        durable(target / "complete.json", result)
        print(
            "DONE "
            + item["id"]
            + " "
            + json.dumps(
                {
                    key: result[key]
                    for key in (
                        "passed",
                        "rebuild_loads",
                        "rebuild_peak",
                        "sql_execute_events",
                    )
                }
            ),
            flush=True,
        )
        if not result["passed"]:
            print(
                "FAILED retained; next planned round uses a fresh product", flush=True
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "prepare-probe",
            "prepare-data",
            "prepare-smoke-data",
            "freeze",
            "smoke",
            "run",
        ),
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--cohort", required=True)
    parser.add_argument("--data-cohort")
    args = parser.parse_args()
    if not args.cohort.replace("-", "").isalnum():
        raise ValueError("explicit simple cohort")
    settings = Settings(args.run_id)
    folder = settings.folder / args.cohort
    with settings.operation_lock():
        normal = settings.folder / "normal-v1/audit.json"
        if (
            not normal.exists()
            or json.loads(normal.read_text(encoding="utf-8"))["window_count"] != 48
        ):
            raise ValueError(
                "finish and audit normal-v1 before probe selection or new rebuild fixtures"
            )
        if args.action == "prepare-probe":
            print(durable_probe(settings, args.cohort))
        elif args.action in ("prepare-data", "prepare-smoke-data"):
            prepare_data(settings, folder, smoke=args.action == "prepare-smoke-data")
        elif args.action == "freeze":
            if not args.data_cohort or not args.data_cohort.replace("-", "").isalnum():
                raise ValueError("explicit prepared data cohort required")
            data_folder = settings.folder / args.data_cohort
            probe_folder = settings.folder / settings.load()["d5_probe_group"]
            freeze_inputs(
                settings,
                folder,
                plan(),
                [
                    "scripts/evaluation/backend_d5_faults.py",
                    "scripts/evaluation/backend_d5_rebuild.py",
                    "scripts/evaluation/backend_d5_rebuild_support.py",
                    "scripts/evaluation/backend_d5_rebuild_audit.py",
                ]
                + [
                    p.relative_to(settings.root).as_posix()
                    for p in data_folder.iterdir()
                    if p.is_file()
                ]
                + [
                    p.relative_to(settings.root).as_posix()
                    for p in probe_folder.rglob("*.java")
                ],
                extra={"data_cohort": args.data_cohort},
            )
        else:
            if not args.data_cohort or not args.data_cohort.replace("-", "").isalnum():
                raise ValueError("explicit prepared data cohort required")
            if args.action != "smoke":
                manifest = check_inputs(settings, folder, plan())
                assert manifest["data_cohort"] == args.data_cohort
            try:
                execute(
                    settings,
                    folder,
                    settings.folder / args.data_cohort,
                    smoke=args.action == "smoke",
                )
            finally:
                for role in ("case", "commerce", "commerce2", "gateway", "relay"):
                    stop_role(settings, role)


if __name__ == "__main__":
    main()
