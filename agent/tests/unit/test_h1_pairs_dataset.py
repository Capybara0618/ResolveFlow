from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.evaluation.dataset import check_input, export_case, read, validate  # noqa: E402


def test_pairs_are_complete_and_export_does_not_expose_gold() -> None:
    assert validate()["pairs"] == 16
    exported = export_case("A05A")
    encoded = json.dumps(exported)
    assert "allowed_terminal_actions" not in encoded
    assert "must_cite" not in encoded
    assert "review_status" not in encoded
    assert exported["backend"]["shipment"]["status"] == "LOST"


def test_rejects_gold_leak_and_changed_pair_scope() -> None:
    with pytest.raises(ValueError, match="Gold-only"):
        check_input({"allowed_terminal_actions": ["REFUND"]})
    cases = read("agent/cases.json")
    for pair in {case["pair_id"] for case in cases}:
        first, second = [case for case in cases if case["pair_id"] == pair]
        assert first["scope"] == second["scope"]
        assert first["description"] == second["description"]
        assert first["backend"] != second["backend"]


def test_rejects_missing_or_nondiscriminating_gold() -> None:
    cases, gold = read("agent/cases.json"), read("gold/agent.json")
    assert len(gold) == 32
    assert set(gold) == {case["id"] for case in cases}
    for pair in {case["pair_id"] for case in cases}:
        first, second = [gold[case["id"]] for case in cases if case["pair_id"] == pair]
        assert set(first["allowed_actions"]) & set(second["forbidden_actions"])
