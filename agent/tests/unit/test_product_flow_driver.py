"""The acceptance helper must never fall back to a historical or already consumed run."""
from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import product_flow_acceptance as flow  # noqa: E402

CASE = "aaaabbbb-0000-4000-8000-000000000001"


@pytest.mark.parametrize("status", ["CANCELLED", "CLOSED_SUCCESS", "CLOSED_REJECTED",
                                    "AUTHORIZED", "RECONCILING"])
def test_ended_or_consumed_case_never_reaches_run_or_model(status):
    with pytest.raises(flow.demo.DemoRefused, match="never investigated"):
        flow.investigate(None, None, {"case_id": CASE}, {"case": {"status": status}})


@pytest.mark.parametrize("orders", [[], [{"case_id": "aaaabbbb-0000-4000-8000-000000000002"}],
                                    [{"case_id": CASE}, {"case_id": CASE}]])
def test_unknown_or_ambiguous_case_is_refused(orders):
    with pytest.raises(flow.demo.DemoRefused, match="manifest-owned"):
        flow.select_target({"orders": orders}, CASE)


@pytest.mark.parametrize("row", [None, {"status": "RUNNING"}, {"status": "CALLBACK_PENDING"},
                                 {"status": "FAILED"}, {"status": "COMPLETED"}])
def test_only_exact_dispatched_queued_revision_can_be_claimed(row):
    class Connection:
        def execute(self, sql, params):
            assert "case_id=%s AND input_revision=%s" in sql
            assert params == (flow.demo.agent_run_id(CASE, 4), CASE, 4)
            return self

        def fetchone(self):
            return row

    class DB:
        @contextmanager
        def connection(self):
            yield Connection()

    with pytest.raises(flow.demo.DemoRefused, match="no reset"):
        flow.queued_run(DB(), {"case_id": CASE}, 4)


@pytest.mark.parametrize("purpose,status", [("cancel", "ANALYZING"),
                                           ("failed-manual-approve", "CLOSED_SUCCESS")])
def test_recovery_refuses_other_fixture_or_terminal_case(purpose, status):
    with pytest.raises(flow.demo.DemoRefused, match="dedicated failure"):
        flow.recover_failure(None, {"purpose": purpose}, {"case": {"status": status}})


@pytest.mark.parametrize("row", [None, {"status": "COMPLETED"},
    {"status": "RUNNING", "active_deadline_at": None},
    {"status": "RUNNING", "active_deadline_at": datetime.now(UTC) + timedelta(days=1)}])
def test_recovery_requires_exact_running_revision_and_real_expired_deadline(row):
    class Connection:
        def execute(self, sql, params):
            assert "case_id=%s AND input_revision=%s" in sql
            assert params == (flow.demo.agent_run_id(CASE, 2), CASE, 2)
            return self

        def fetchone(self):
            return row

    class DB:
        @contextmanager
        def connection(self):
            yield Connection()

    with pytest.raises(flow.demo.DemoRefused, match="never extend or reset"):
        flow.recover_failure(DB(), {"purpose": "failed-manual-approve", "case_id": CASE},
                             {"case": {"status": "ANALYZING"}, "input_revision": 2})
