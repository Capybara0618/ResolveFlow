"""Fault evidence must prove the window, not merely a successful retry."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.backend_trade_faults import MysqlSession, validate_crash_window, validate_loss


def test_crash_requires_committed_receipt_without_published_order():
    state = {"attempt_id": "original", "planned_order_id": "planned", "attempts": 1,
             "receipts": 1, "orders": 0, "draft_status": "PAYMENT_PENDING", "attempt_status": "UNKNOWN"}
    validate_crash_window(state)
    for field, bad in (("receipts", 0), ("orders", 1), ("attempts", 2),
                       ("draft_status", "CANCELLED"), ("attempt_status", "SUCCEEDED")):
        with pytest.raises(AssertionError):
            validate_crash_window({**state, field: bad})


def test_lost_response_requires_upstream_success_and_client_eof():
    validate_loss({"upstream_status": 200, "client_status": 0, "discarded_bytes": 120,
                   "client_error": "RemoteDisconnected"})
    for field, bad in (("upstream_status", 500), ("client_status", 200), ("discarded_bytes", 0)):
        with pytest.raises(AssertionError):
            validate_loss({"upstream_status": 200, "client_status": 0, "discarded_bytes": 120,
                           "client_error": "RemoteDisconnected", field: bad})


def test_sql_session_checks_ownership_before_opening_process(monkeypatch):
    from evaluation import backend_trade_faults as faults

    class Foreign:
        def assert_owned(self, role):
            assert role == "mysql"
            raise ValueError("foreign container")

    monkeypatch.setattr(faults.subprocess, "Popen", lambda *a, **k: pytest.fail("must reject before connecting"))
    with pytest.raises(ValueError, match="foreign container"):
        MysqlSession(Foreign())
