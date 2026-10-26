"""Trade probes must measure actual effects and keep conflicts separate from failures."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.backend_trade import classify, validate_cart, validate_checkout, validate_payment


def test_unexpected_error_is_not_counted_as_expected_conflict():
    assert classify(200) == "success"
    assert classify(409) == "conflict"
    assert classify(500) == "unexpected"
    assert classify(0) == "unexpected"


def test_cart_needs_exactly_one_winner_and_saved_quantity_matches():
    rows = [{"status": 200, "quantity": 2}, {"status": 409, "quantity": 1}]
    validate_cart(rows, 3, 4, 2)
    with pytest.raises(AssertionError):
        validate_cart(rows, 3, 4, 1)
    with pytest.raises(AssertionError):
        validate_cart(rows + [{"status": 200, "quantity": 1}], 3, 4, 2)


def test_draft_replays_need_same_id_and_database_unique_row():
    rows = [{"status": 200, "body": {"draft_id": "a"}},
            {"status": 200, "body": {"draft_id": "a"}}, {"status": 409}]
    assert validate_checkout(rows, 1) == "a"
    with pytest.raises(AssertionError):
        validate_checkout(rows, 2)
    with pytest.raises(AssertionError):
        validate_checkout([*rows, {"status": 200, "body": {"draft_id": "b"}}], 1)


def test_payment_validates_attempt_and_amounts_not_just_success_responses():
    rows = [{"status": 200, "body": {"attempt_id": "a"}}, {"status": 409}]
    counts = {"attempts": 1, "receipts": 1, "orders": 1, "lines": 2, "slots": 2,
              "paid": 4000, "draft_total": 4000, "line_total": 4000, "receipt_total": 4000,
              "reserved": 0, "refunded": 0}
    validate_payment(rows, "a", counts, 2)
    for field in ("receipts", "orders", "line_total", "reserved"):
        with pytest.raises(AssertionError):
            validate_payment(rows, "a", {**counts, field: counts[field] + 1}, 2)
    with pytest.raises(AssertionError):
        validate_payment([{"status": 500}], "a", counts, 2)


def test_resume_saved_payment_responses_never_resends_burst(tmp_path, monkeypatch):
    import json

    from evaluation import backend_trade as probe

    prepared = {"round": {"scenario": "T04", "concurrency": 10, "draft_id": "draft-a", "path": "/payment"},
                "inputs": [[{}, "original-key"]]}
    (tmp_path / "prepared.json").write_text(json.dumps(prepared))
    responses = [{"status": 200, "classification": "success", "body": {"attempt_id": "a"}}]
    (tmp_path / "requests.json").write_text(json.dumps(responses))
    monkeypatch.setattr(probe, "burst", lambda *a: pytest.fail("must not repeat payment requests"))
    def read_only(_settings, method, *_args, **_kwargs):
        assert method == "GET"
        return {"payment": {"attempt_id": "a"}}
    monkeypatch.setattr(probe, "api", read_only)
    monkeypatch.setattr(probe, "payment_counts", lambda *a: {
        "attempts": 1, "receipts": 1, "orders": 1, "lines": 2, "slots": 2,
        "paid": 4000, "draft_total": 4000, "line_total": 4000, "receipt_total": 4000,
        "reserved": 0, "refunded": 0})
    assert probe.round_probe(object(), "token", "T04", 10, tmp_path)["status"] == "PASSED"
