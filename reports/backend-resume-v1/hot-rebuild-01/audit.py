"""Offline recomputation of the six archived natural cold-cache bursts; no network or DB."""

import hashlib
import json
import statistics
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluation.backend_d5_http import digest
from evaluation.backend_hot_rebuild import page_calls, plan, summarize


def main():
    archive = HERE / "rounds.zip"
    manifest = json.loads((HERE / "archive-manifest.json").read_text(encoding="utf-8"))
    assert (
        hashlib.sha256(archive.read_bytes()).hexdigest() == manifest["archive_sha256"]
    )
    frozen = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    for path, wanted in frozen["files"].items():
        if path.startswith("scripts/"):
            assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == wanted
    results = []
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == set(manifest["files"])
        for name, wanted in manifest["files"].items():
            assert hashlib.sha256(bundle.read(name)).hexdigest() == wanted
        for item in plan():
            data = json.loads(bundle.read(item["id"] + "/complete.json"))
            cold = json.loads(bundle.read(item["id"] + "/cold.json"))
            assert data["round"] == item and cold["exists"] == 0
            assert cold["key"] == data["namespace"] + ":P-1001:1"
            assert all(row["sql_inflight"] == 0 for row in data["after"].values())
            for row in data["requests"]:
                assert row.get("body_sha256") == digest(row["body"])
            calls = sum(
                page_calls(data["after"][n]) - page_calls(data["before"][n])
                for n in data["after"]
            )
            sql = sum(
                data["after"][n]["sql"] - data["before"][n]["sql"]
                for n in data["after"]
            )
            result = summarize(
                data["requests"], data["events"], calls, sql, data["expected"]
            )
            assert result == data["summary"]
            results.append({**item, **result})
    summary = json.loads((HERE / "summary.json").read_text(encoding="utf-8"))
    assert results == summary["rounds"]
    medians = {
        c: statistics.median(r["rebuilds"] for r in results if r["condition"] == c)
        for c in ("B", "C")
    }
    assert medians == summary["median_rebuilds"]
    assert sum(r["requests"] for r in results) == summary["requests"] == 180
    for key in ("success", "rejected", "errors"):
        assert sum(r[key] for r in results) == summary[key]
    print(
        json.dumps(
            {
                "pairs": 3,
                "requests": 180,
                "median_rebuilds": medians,
                "success": summary["success"],
                "rejected": summary["rejected"],
                "errors": summary["errors"],
                "recomputed": True,
            }
        )
    )


if __name__ == "__main__":
    main()
