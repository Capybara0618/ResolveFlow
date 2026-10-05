"""Aggregate disjoint finished live cohorts with identical execution provenance, without model calls."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from scripts.evaluation.dataset import ROOT, digest, read


def merge_reports(paths, dataset):
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if len(reports) < 2:
        raise ValueError("Expected at least two disjoint cohorts")
    identity = ("manifest_hash", "dataset_version", "mode", "synthetic", "code_commit", "entry_hash",
                "code_hashes", "dependency_lock_hash", "dependencies", "provider", "evaluation_config",
                "embedding", "backend_profile", "business_end_to_end", "scoring_scope", "gold_review")
    rows = []
    for report in reports:
        if (report.get("state") != "FINISHED" or report.get("mode") != "live"
                or report.get("synthetic") is not True
                or report.get("manifest_hash") != digest(dataset / "manifest.json")):
            raise ValueError("Expected finished live cohorts on this dataset")
        if any(report.get(key) != reports[0].get(key) for key in identity):
            raise ValueError("Cohort execution provenance/settings differ")
        for entry in report["results"]:
            if entry["status"] not in {"COMPLETED", "INCOMPLETE", "ERROR"}:
                raise ValueError("Unfinished case cannot enter baseline")
            if entry["model_calls"] != len(entry.get("requests", [])):
                raise ValueError("Recorded request count differs")
            rows.append(entry)
    cases = read("agent/cases.json", dataset)
    by_id = {entry["id"]: entry for entry in rows}
    if len(by_id) != len(rows) or set(by_id) != {case["id"] for case in cases}:
        raise ValueError("Baseline must cover every frozen case exactly once")
    if any(by_id[case["id"]]["split"] != case["split"]
           or by_id[case["id"]]["pair_id"] != case["pair_id"] for case in cases):
        raise ValueError("Case grouping differs")
    result = deepcopy(reports[0])
    result["results"] = [by_id[case["id"]] for case in cases]
    result["aggregation"] = "disjoint-fixed-config-no-reruns-v1"
    result["aggregation_script_sha256"] = digest(Path(__file__))
    result["cohort_reports"] = [{"path": path.as_posix(), "sha256": digest(path), "time": report.get("time"),
                                 "ids": [entry["id"] for entry in report["results"]]}
                                for path, report in zip(paths, reports, strict=True)]
    result["live_usage"] = reports[-1].get("live_usage")
    result["summary"] = {
        "n": len(rows), "joint_correct": sum(bool(e.get("joint_correct")) for e in rows),
        "action_correct": sum(bool(e.get("action_correct")) for e in rows),
        "forbidden_actions": sum(bool(e.get("forbidden_action")) for e in rows),
        "errors": sum("error" in e for e in rows), "incomplete": sum(not e.get("completed", False) for e in rows),
        "model_calls": sum(e["model_calls"] for e in rows),
    }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-report", type=Path, action="append", required=True)
    parser.add_argument("--dataset", type=Path, default=ROOT / "evals/calibrated-v3")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Existing baseline is immutable; choose a new path")
    result = merge_reports(args.input_report, args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
