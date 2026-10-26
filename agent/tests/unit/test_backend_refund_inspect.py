"""The operation diagnostic must be read-only and reject SQL-shaped identifiers."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evaluation.backend_refund_inspect import inspect_operation


def test_invalid_operation_rejected_before_any_database_read():
    class NoRead:
        def sql(self, _):
            pytest.fail("invalid operation must not reach SQL")
    with pytest.raises(ValueError):
        inspect_operation(NoRead(), "'; DELETE FROM orders;--")


def test_missing_operation_does_not_turn_into_unscoped_scan():
    class Empty:
        calls = []
        def sql(self, statement):
            self.calls.append(statement)
            assert statement.lstrip().startswith("SELECT") and "WHERE operation_id=" in statement
            return ""
    settings = Empty()
    with pytest.raises(LookupError):
        inspect_operation(settings, "11111111-1111-4111-8111-111111111111")
    assert len(settings.calls) == 1
