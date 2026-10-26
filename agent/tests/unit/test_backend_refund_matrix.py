"""Reject false refund claims even when every HTTP response looked successful."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.backend_refund_matrix import validate_final, validate_ledger, validate_unknown


def test_ledger_checks_nonnegative_and_refunded_plus_reserved():
    validate_ledger({"paid": 100, "refunded": 0, "reserved": 100})
    for wrong in ({"paid": 100, "refunded": 1, "reserved": 100},
                  {"paid": 100, "refunded": -1, "reserved": 0}):
        with pytest.raises(AssertionError):
            validate_ledger(wrong)


def test_unknown_requires_original_reservation_and_no_settlement():
    good = {"paid": 100, "refunded": 0, "reserved": 100,
            "operations": [{"state": "UNKNOWN", "provider_key": "a", "operation_id": "a"}]}
    validate_unknown(good, 100)
    with pytest.raises(AssertionError):
        validate_unknown({**good, "reserved": 0}, 100)
    with pytest.raises(AssertionError):
        validate_unknown({**good, "operations": [{**good["operations"][0], "provider_key": "new"}]}, 100)


def test_final_requires_one_success_per_line_and_one_case_close():
    good = {"paid": 100, "refunded": 100, "reserved": 0, "operation_count": 1,
            "provider_successes": [1], "provider_attempts": [1], "closed_events": [1],
            "operation_states": ["SUCCEEDED"], "line_states": ["CONSUMED"], "case_states": ["CLOSED_SUCCESS"]}
    validate_final(good, 1, 100)
    for field, value in (("provider_successes", [2]), ("closed_events", [2]), ("operation_count", 2),
                         ("provider_attempts", [2]), ("line_states", ["FREE"])):
        with pytest.raises(AssertionError):
            validate_final({**good, field: value}, 1, 100)
