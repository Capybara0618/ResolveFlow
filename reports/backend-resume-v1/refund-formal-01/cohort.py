"""Load the original plan and unstarted-ID continuation without replacing its failed round."""

import hashlib
import json


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(raw):
    batches = [raw / f"refund-formal-{i:02d}" for i in range(1, 5)]
    manifest = read(batches[0] / "manifest.json")
    assert manifest["profile"] == "formal" and len(manifest["plan"]) == 70
    complete, failures, pending = {}, {}, manifest["plan"]
    hashes = {}
    for index, folder in enumerate(batches):
        version, summary = read(folder / "manifest.json"), read(folder / "summary.json")
        assert version["profile"] == "formal" and version["plan"] == pending
        assert version["jars"] == manifest["jars"] and version["run_id"] == manifest["run_id"]
        assert summary["manifest_sha256"] == sha(folder / "manifest.json")
        hashes[folder.name] = sha(folder / "manifest.json")
        assert summary["planned"] == len(pending)
        assert summary["completed"] == summary["passed"] == len(summary["rows"])
        for name, digest in version["sources"].items():
            assert sha(folder / "execution-sources" / name) == digest
        if index:
            parent = batches[index - 1]
            assert version["lineage"]["parent"] == parent.name
            assert version["lineage"]["original_plan"] == read(parent / "manifest.json")["plan"]
            for name, digest in version["lineage"]["preserved_files"].items():
                assert sha(parent / name.replace("\\", "/")) == digest
        for row in summary["rows"]:
            assert row["id"] not in complete and row["id"] not in failures
            assert row["status"] == "PASSED"
            complete[row["id"]] = (row, folder / "rounds" / row["id"])
        remaining = []
        for spec in pending:
            directory = folder / "rounds" / spec["id"]
            if (directory / "failure.json").exists():
                error = read(directory / "failure.json")
                assert error["status"] == "FAILED" and spec["id"] not in complete
                assert spec["id"] not in failures
                failures[spec["id"]] = directory
            elif spec["id"] not in complete:
                assert not directory.exists(), "unknown partial round"
                remaining.append(spec)
        pending = remaining
    assert not pending and set(failures) == {"F05-r02", "F07-r06"}
    records = []
    for spec in manifest["plan"]:
        failed = spec["id"] in failures
        if failed:
            directory = failures[spec["id"]]
            status = "FAULT_NOT_REACHED" if spec["id"] == "F05-r02" else "OBSERVATION_TIMEOUT"
            row = {**spec, "status": status, "entities": read(directory / "entities.json")}
        else:
            row, directory = complete[spec["id"]]
            assert row["scenario"] == spec["scenario"]
        records.append((spec, row, directory, failed))
    assert len(complete) == 68 and len(records) == 70
    return manifest, records, {"planned_attempts": 70, "fault_rounds_passed": 68,
        "not_reached": ["F05-r02"], "observation_timeout": ["F07-r06"],
        "startup_failures_before_rounds": ["refund-formal-03"], "manifest_hashes": hashes}
