from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

DATASET = Path(__file__).resolve().parents[3] / "evals" / "datasets"
sys.path.insert(0, str(DATASET))
from h1_pairs import GOLD, INPUT, export_case, validate  # noqa: E402


def _fixtures() -> tuple[dict, dict]:
    return json.loads(INPUT.read_text(encoding="utf-8")), json.loads(GOLD.read_text(encoding="utf-8"))


def test_pairs_are_complete_and_export_does_not_expose_gold() -> None:
    inputs, gold = _fixtures()
    validate(inputs, gold)
    exported = export_case(inputs, "H1-01-A")
    encoded = json.dumps(exported)
    assert "allowed_terminal_actions" not in encoded
    assert "must_cite" not in encoded
    assert "review_status" not in encoded
    assert exported["case"]["facts"]["shipment"] == "LOST"


def test_rejects_gold_leak_and_changed_pair_scope() -> None:
    inputs, gold = _fixtures()
    leaked = deepcopy(inputs)
    leaked["cases"][0]["allowed_terminal_actions"] = ["REFUND"]
    with pytest.raises(ValueError, match="Gold-only"):
        validate(leaked, gold)
    altered = deepcopy(inputs)
    altered["cases"][1]["scope"]["line_id"] = "other-line"
    with pytest.raises(ValueError, match="scope differs"):
        validate(altered, gold)


def test_rejects_missing_or_nondiscriminating_gold() -> None:
    inputs, gold = _fixtures()
    missing = deepcopy(gold)
    missing["gold"].pop()
    with pytest.raises(ValueError, match="twelve Gold"):
        validate(inputs, missing)
    weak = deepcopy(gold)
    weak["gold"][1]["forbidden_terminal_actions"] = []
    with pytest.raises(ValueError, match="divergent refund authority"):
        validate(inputs, weak)
