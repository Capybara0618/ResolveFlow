"""A baseline cannot silently combine different settings, omit failures or repeat cases."""

import json
from copy import deepcopy

import pytest
from scripts.evaluation.dataset import ROOT, digest, read
from scripts.evaluation.live_baseline import merge_reports


def reports(tmp_path):
    dataset = ROOT / "evals/calibrated-v3"
    cases = read("agent/cases.json", dataset)
    base = {"mode": "live", "synthetic": True, "state": "FINISHED", "code_commit": "frozen-code",
            "manifest_hash": digest(dataset / "manifest.json"), "evaluation_config": {"model_calls": 12},
            "provider": {"model": "test"}, "code_hashes": {"frozen": "same"}, "entry_hash": "same",
            "results": [{"id": c["id"], "split": c["split"], "pair_id": c["pair_id"],
                         "completed": c["id"] != "A03B", "joint_correct": c["id"] != "A03B",
                         "action_correct": c["id"] != "A03B", "status": "COMPLETED" if c["id"] != "A03B"
                         else "INCOMPLETE", "model_calls": 1, "requests": [{}]} for c in cases]}
    paths = [tmp_path / "one.json", tmp_path / "two.json"]
    for path, entries in zip(paths, [base["results"][:6], base["results"][6:]], strict=True):
        path.write_text(json.dumps({**base, "results": entries}), encoding="utf-8")
    return paths, dataset


def test_full_fixed_cohort_preserves_failure_and_source_hashes(tmp_path):
    paths, dataset = reports(tmp_path)
    value = merge_reports(paths, dataset)
    assert value["summary"]["n"] == 32 and value["summary"]["joint_correct"] == 31
    assert value["summary"]["incomplete"] == 1 and value["summary"]["model_calls"] == 32
    assert value["cohort_reports"][0]["sha256"] == digest(paths[0])
    assert next(e for e in value["results"] if e["id"] == "A03B")["completed"] is False


@pytest.mark.parametrize("change", ["budget", "code", "duplicate", "missing", "unfinished", "requests"])
def test_mismatched_or_incomplete_cohort_is_rejected(tmp_path, change):
    paths, dataset = reports(tmp_path)
    value = json.loads(paths[1].read_text())
    if change == "budget":
        value["evaluation_config"]["model_calls"] = 6
    elif change == "code":
        value["code_hashes"]["frozen"] = "changed"
    elif change == "duplicate":
        first = json.loads(paths[0].read_text())["results"][0]
        value["results"].append(deepcopy(first))
    elif change == "missing":
        value["results"].pop()
    elif change == "unfinished":
        value["state"] = "RUNNING"
    else:
        value["results"][0]["model_calls"] = 2
    paths[1].write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        merge_reports(paths, dataset)
