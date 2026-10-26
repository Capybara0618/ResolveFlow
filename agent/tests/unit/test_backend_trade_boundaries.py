"""Check every snapshot field and both expiry outcomes."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.backend_trade_boundaries import validate_catalog_rejection, validate_expired, validate_snapshot


def test_snapshot_rejects_mixed_old_new_price_or_variant():
    expected = [{"sku_id": "a", "quantity": 1, "unit_amount": 200, "line_amount": 200,
                 "variant": "old", "sku_version": 1}]
    validate_snapshot(expected, expected, 200)
    for field, value in (("unit_amount", 300), ("variant", "new"), ("sku_version", 2)):
        with pytest.raises(AssertionError):
            validate_snapshot([{**expected[0], field: value}], expected, 200)


def test_expired_order_must_have_no_reserved_attempt_receipt_or_order():
    state = {"status": "CANCELLED", "close_reason": "EXPIRED", "attempts": 0, "receipts": 0, "orders": 0}
    validate_expired(state, [{"status": 409}])
    for field in ("attempts", "receipts", "orders"):
        with pytest.raises(AssertionError):
            validate_expired({**state, field: 1}, [{"status": 409}])
    with pytest.raises(AssertionError):
        validate_expired(state, [{"status": 503}])


def test_unlisted_404_is_specific_and_does_not_accept_other_failures():
    rows = [{"status": 404, "body": {"code": "NOT_FOUND"}}]
    validate_catalog_rejection(rows, "unlisted", 0)
    with pytest.raises(AssertionError):
        validate_catalog_rejection(rows, "price", 0)
    with pytest.raises(AssertionError):
        validate_catalog_rejection(rows, "unlisted", 1)
    with pytest.raises(AssertionError):
        validate_catalog_rejection([{"status": 500, "body": {"code": "NOT_FOUND"}}], "unlisted", 0)
