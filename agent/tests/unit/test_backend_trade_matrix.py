"""Formal rounds, valid alternate payloads and measured concurrency have fixed denominators."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.backend_trade import bound_payload
from evaluation.backend_trade_matrix import inventory_check, plan, score_intervals


def test_formal_plan_has_exact_160_rounds_and_both_boundary_orders():
    rows = plan("formal")
    assert len(rows) == 160 and len({r["id"] for r in rows}) == 160
    for scenario in (f"T{i:02d}" for i in range(1, 9)):
        for concurrency in (10, 30):
            group = [r for r in rows if r["scenario"] == scenario and r["concurrency"] == concurrency]
            assert len(group) == 10
            if scenario in ("T03", "T08"):
                assert len({r["order"] for r in group}) == 2
                assert all(sum(g["order"] == order for g in group) == 5 for order in {g["order"] for g in group})


def test_either_valid_payload_can_bind_key_but_other_body_must_conflict():
    full, subset = {"lines": ["a", "b"]}, {"lines": ["a"]}
    inputs = [(full, "same"), (subset, "same")]
    rows = [{"index": 0, "status": 409}, {"index": 1, "status": 200, "body": {"draft_id": "one"}}]
    assert bound_payload(rows, inputs) == (subset, full)
    with pytest.raises(AssertionError):
        bound_payload([{**rows[0], "status": 200}, rows[1]], inputs)


def test_requested_30_is_not_accepted_when_actual_peak_is_one():
    rows = [{"request_id": str(i), "started_ns": i * 2 + 1, "finished_ns": i * 2 + 2} for i in range(30)]
    with pytest.raises(AssertionError):
        score_intervals(rows, 30)
    for row in rows:
        row.update(started_ns=1, finished_ns=3)
    assert score_intervals(rows, 30) == 30


def test_global_inventory_detects_orders_outside_expected_attempt_mapping():
    before = {"orders": ["old"], "receipts": [], "attempts": []}
    after = {"orders": ["old", "new", "orphan"], "receipts": ["a"], "attempts": ["a"]}
    with pytest.raises(AssertionError):
        inventory_check(before, after, 1)
    assert inventory_check(before, {**after, "orders": ["old", "new"]}, 1)["orders"] == ["new"]
