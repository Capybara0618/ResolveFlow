"""Recompute the user-selected complete P1/P2 windows; no app, DB or network access."""

import hashlib
import json
import statistics
import sys
import uuid
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluation.backend_d5_http import score
from evaluation.backend_d5_normal import plan


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = json.loads((HERE / "archive-manifest.json").read_text(encoding="utf-8"))
    source = json.loads((HERE / "original-manifest.json").read_text(encoding="utf-8"))
    for path, wanted in source["files"].items():
        if path.startswith("scripts/"):
            assert sha(ROOT / path) == wanted, (
                "frozen scorer dependency changed: " + path
            )
    output = ROOT / "tmp" / ("backend-d5-focused-audit-" + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    for profile in ("P1", "P2"):
        path = HERE / (profile + ".zip")
        assert sha(path) == manifest["archives"][path.name]
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                relative = PurePosixPath(item.filename)
                assert not relative.is_absolute() and ".." not in relative.parts
                target = (output / Path(*relative.parts)).resolve()
                assert target.is_relative_to(output.resolve())
                target.parent.mkdir(parents=True, exist_ok=True)
                content = archive.read(item)
                assert (
                    hashlib.sha256(content).hexdigest()
                    == manifest["files"][item.filename]
                )
                with target.open("xb") as handle:
                    handle.write(content)
    cohort = json.loads((HERE / "cohort.json").read_text(encoding="utf-8"))
    summary = json.loads((HERE / "summary.json").read_text(encoding="utf-8"))
    rows = []
    for item in plan():
        if item["profile"] not in ("P1", "P2"):
            continue
        folder = output / item["id"]
        data = json.loads((folder / "complete.json").read_text(encoding="utf-8"))
        assert data["window"] == item and data["metadata"]["target_seconds"] == 60
        assert sha(folder / "requests.jsonl.gz") == data["requests_sha256"]
        result = score(
            folder / "requests.jsonl.gz", cohort, item["profile"], data["metadata"]
        )
        assert all(data["score"][k] == v for k, v in result.items())
        warm = json.loads((folder / "warmup.json").read_text(encoding="utf-8"))
        assert warm["metadata"]["target_seconds"] == 30
        assert (
            score(folder / "warmup.jsonl.gz", cohort, item["profile"], warm["metadata"])
            == warm["score"]
        )
        assert data["score"]["sql"] == sum(
            data["after"][r]["sql"] - data["before"][r]["sql"] for r in data["after"]
        )
        assert all(row["sql_inflight"] == 0 for row in data["after"].values())
        rows.append(
            {
                **item,
                **data["score"],
                "failure_rate": result["failed"] / result["total"],
            }
        )
    assert rows == summary["rows"] and len(rows) == 30
    for key, expected in summary["median_groups"].items():
        profile, concurrency, condition = key.split("-")
        selected = [
            r
            for r in rows
            if (r["profile"], r["concurrency"], r["condition"])
            == (profile, int(concurrency), condition)
        ]
        assert len(selected) == 3
        assert {
            field: statistics.median(r[field] for r in selected) for field in expected
        } == expected
    assert sum(r["total"] for r in rows) == summary["requests"] == 404177
    print(
        json.dumps(
            {
                "windows": len(rows),
                "requests": summary["requests"],
                "recomputed": True,
                "scope": "P1/P2 complete profiles after explicit user reduction; not original full48/fault/R120",
                "jar_verification": "original runtime checked hashes; binaries excluded from this raw-metric archive",
            }
        )
    )


if __name__ == "__main__":
    main()
