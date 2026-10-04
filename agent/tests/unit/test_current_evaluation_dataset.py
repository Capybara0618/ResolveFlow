"""Gold isolation and paired facts must be meaningful before any model is evaluated."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.evaluation.dataset import DATA, check_input, digest, export_case, read, validate  # noqa: E402


def test_current_dataset_is_complete_and_gold_is_separate():
    assert validate() == {"merchants": 3, "bundles": 6, "agent_cases": 32, "pairs": 16, "rag_queries": 60}
    exported = export_case("A01A")
    check_input(exported)
    assert "allowed_actions" not in json.dumps(exported)
    assert exported["backend"]["order"]["fulfillment_status"] == "NOT_SHIPPED"


@pytest.mark.parametrize("key", ["allowed_actions", "gold", "must_cite", "expected_action"])
def test_nested_gold_leak_is_rejected(key):
    with pytest.raises(ValueError, match="Gold-only"):
        check_input({"backend": {"materials": [{key: "REFUND"}]}})


def _copy(tmp_path):
    import shutil

    shutil.copytree(DATA, tmp_path / "data")
    return tmp_path / "data"


def _change(directory, file, value):
    (directory / file).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    manifest = read("manifest.json", directory)
    manifest["files"][file] = digest(directory / file)
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_pair_scope_and_no_difference_are_rejected(tmp_path):
    directory = _copy(tmp_path)
    cases = read("agent/cases.json", directory)
    broken = deepcopy(cases)
    broken[1]["scope"]["line_id"] = "other"
    broken[1]["backend"]["order"]["line_id"] = "other"
    _change(directory, "agent/cases.json", broken)
    with pytest.raises(ValueError, match="Pair scope"):
        validate(directory)
    broken = deepcopy(cases)
    broken[1]["backend"] = broken[0]["backend"]
    _change(directory, "agent/cases.json", broken)
    with pytest.raises(ValueError, match="Pair facts"):
        validate(directory)


def test_missing_and_nondiscriminating_gold_are_rejected(tmp_path):
    directory = _copy(tmp_path)
    gold = read("gold/agent.json", directory)
    missing = deepcopy(gold)
    missing.pop("A01A")
    _change(directory, "gold/agent.json", missing)
    with pytest.raises(ValueError, match="32 cases"):
        validate(directory)
    weak = deepcopy(gold)
    weak["A01B"]["forbidden_actions"] = []
    _change(directory, "gold/agent.json", weak)
    with pytest.raises(ValueError, match="discriminating"):
        validate(directory)


def test_frozen_hash_tampering_fails(tmp_path):
    directory = _copy(tmp_path)
    with (directory / "agent/cases.json").open("a", encoding="utf-8") as output:
        output.write(" ")
    with pytest.raises(ValueError, match="Frozen file"):
        validate(directory)
