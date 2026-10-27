"""Capture full fixed projections after normal sampling; archive without credentials or JARs."""

from __future__ import annotations

import argparse
import asyncio
import json
import zipfile
from pathlib import Path

from evaluation.backend_d5_http import digest, fetch, fixture_token, score, session
from evaluation.backend_d5_normal import configure, plan, verify_manifest
from evaluation.backend_d5_runtime import stop_role
from evaluation.backend_lab import ROOT, Settings, freeze_file, sha256
from evaluation.trade_request_journal import durable


async def capture(base, cohort, folder):
    folder.mkdir(parents=True, exist_ok=False)
    tokens = {
        s["actor"]: fixture_token(s["actor"])
        for s in cohort["specs"].values()
        if s.get("actor")
    }
    result = {}
    async with session(1) as client:
        for key, spec in cohort["specs"].items():
            measured, body = await fetch(client, base, spec, tokens)
            # A changed projection is retained as a capture failure, never made the new expected hash.
            target = folder / (key + ".json")
            durable(
                target,
                {
                    "key": key,
                    "path": spec["path"],
                    "measurement": measured,
                    "body": body,
                },
            )
            if not measured["correct"]:
                raise ValueError("post-normal projection changed: " + key)
            assert digest(body) == spec["body_sha256"]
            result[key] = {"sha256": sha256(target), "body_sha256": digest(body)}
    durable(
        folder / "manifest.json",
        {
            "samples": result,
            "count": len(result),
            "boundary": "post-normal/pre-rebuild read-only capture; not performance samples",
        },
    )
    return result


def capture_owned(settings, cohort_folder, output):
    audit = json.loads((cohort_folder / "audit.json").read_text(encoding="utf-8"))
    if audit["window_count"] != 48:
        raise ValueError("finish and audit all normal windows first")
    verify_manifest(settings, cohort_folder)
    cohort = json.loads((cohort_folder / "cohort.json").read_text(encoding="utf-8"))
    roles = configure(settings, "P2", "B", "rf:d5:" + settings.identity + ":capture")
    assert roles == ["case", "commerce"]
    try:
        base = f"http://127.0.0.1:{settings.load()['ports']['gateway']}"
        return asyncio.run(capture(base, cohort, output))
    finally:
        for role in ("case", "commerce", "commerce2", "gateway", "relay"):
            stop_role(settings, role)


def check_normal(folder):
    """Raw metric recomputation; intentionally needs no running apps/JARs/DB."""
    cohort = json.loads((folder / "cohort.json").read_text(encoding="utf-8"))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["windows"] == plan()
    rows = []
    for item in plan():
        target = folder / item["id"]
        data = json.loads((target / "complete.json").read_text(encoding="utf-8"))
        assert item == data["window"] and data["metadata"]["target_seconds"] == 60
        assert data["requests_sha256"] == sha256(target / "requests.jsonl.gz")
        measured = score(
            target / "requests.jsonl.gz", cohort, item["profile"], data["metadata"]
        )
        assert all(measured[key] == data["score"][key] for key in measured)
        warm = json.loads((target / "warmup.json").read_text(encoding="utf-8"))
        assert warm["metadata"]["target_seconds"] == 30
        assert (
            score(target / "warmup.jsonl.gz", cohort, item["profile"], warm["metadata"])
            == warm["score"]
        )
        sql = sum(
            data["after"][r]["sql"] - data["before"][r]["sql"] for r in data["after"]
        )
        assert sql == data["score"]["sql"]
        assert all(r["sql_inflight"] == 0 for r in data["after"].values())
        cold = json.loads((target / "cold.json").read_text(encoding="utf-8"))
        expected_hash = cohort["specs"][cohort["profiles"][item["profile"]][0]][
            "body_sha256"
        ]
        assert len(cold) == 3
        for row in cold:
            assert row["elapsed_ms"] >= 0
            assert row["correct"] == (
                row["status"] == 200
                and row.get("error") is None
                and row.get("body_sha256") == expected_hash
            )
        if item["profile"] == "P3":
            delta = [
                b - a
                for a, b in zip(
                    data["route_before"]["requests"],
                    data["route_after"]["requests"],
                    strict=True,
                )
            ]
            assert (
                measured["success"] <= sum(delta) <= measured["total"]
                and abs(delta[0] - delta[1]) <= 1
            )
            assert set(data["after"]) == {"case", "commerce", "commerce2"}
        rows.append({**item, **data["score"]})
    return rows


def archive_normal(settings, folder, destination):
    """Three independent ZIPs keep requests and source evidence small enough for Git."""
    rows = check_normal(folder)
    destination.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    files = {}
    for profile in ("P1", "P2", "P3"):
        target = destination / (profile + ".zip")
        with zipfile.ZipFile(
            target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            for item in plan():
                if item["profile"] != profile:
                    continue
                expected = {
                    "started.json",
                    "cold.json",
                    "warmup.json",
                    "warmup.jsonl.gz",
                    "requests.jsonl.gz",
                    "complete.json",
                }
                if {p.name for p in (folder / item["id"]).iterdir()} != expected:
                    raise ValueError("unexpected window artifact; refuse blind archive")
                for name in sorted(expected):
                    source = folder / item["id"] / name
                    relative = source.relative_to(folder).as_posix()
                    archive.write(
                        source,
                        relative,
                        compress_type=zipfile.ZIP_STORED
                        if source.suffix == ".gz"
                        else zipfile.ZIP_DEFLATED,
                    )
                    files[relative] = sha256(source)
        if target.stat().st_size > 90_000_000:
            raise ValueError("archive too large; preserve local output, do not commit")
    for name in ("manifest.json", "cohort.json", "audit.json"):
        files[name] = freeze_file(folder / name, destination / name)
    for name in (
        "d5-builds.json",
        "dataset-checked.json",
        "http-oracle-baseline-check-01.json",
    ):
        relative = "setup/" + name
        files[relative] = freeze_file(settings.folder / name, destination / relative)
    for name, wanted in manifest["files"].items():
        if not name.startswith("scripts/"):
            continue
        if sha256(ROOT / name) != wanted:
            raise ValueError("frozen normal source changed: " + name)
        relative = "sources/" + name
        files[relative] = freeze_file(ROOT / name, destination / relative)
    relative = "sources/scripts/evaluation/backend_d5_evidence.py"
    files[relative] = freeze_file(Path(__file__), destination / relative)
    durable(
        destination / "archive-manifest.json",
        {
            "run_id": settings.identity,
            "files": files,
            "archives": {p.name: sha256(p) for p in destination.glob("*.zip")},
            "windows": len(rows),
            "requests": sum(r["total"] for r in rows),
            "boundary": "raw metric/source archive; application JARs and database volume remain owned local artifacts, not included",
        },
    )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "archive", "check-normal"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--cohort", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.cohort.replace("-", "").isalnum():
        raise ValueError("explicit simple cohort")
    settings = Settings(args.run_id)
    folder = settings.folder / args.cohort
    with settings.operation_lock():
        if args.action == "check-normal":
            print(len(check_normal(folder)))
        elif args.action == "capture":
            if args.output is None:
                raise ValueError("explicit capture output")
            print(len(capture_owned(settings, folder, args.output)))
        else:
            if args.output is None:
                raise ValueError("explicit archive output")
            print(len(archive_normal(settings, folder, args.output)))


if __name__ == "__main__":
    main()
