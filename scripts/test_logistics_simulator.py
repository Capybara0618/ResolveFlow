"""CLI behavior tests; DB atomicity and transport are covered by LogisticsSimulatorTest."""

from __future__ import annotations

import json
import sys
from unittest.mock import Mock

import logistics_simulator as sim
import pytest


@pytest.mark.parametrize(
    "arguments",
    [
        ("order;DELETE", "M-1001", 2, "LOST", "a", None),
        ("order", "M-1001", 1, "LOST", "a", None),
        ("order", "M-1001", 2, "REFUND", "a", None),
        ("order", "M-1001", 2, "LOST", "a", "2026-10-20T10:00:00"),
        ("order", "M-1001", 2, "UNAVAILABLE", "a", "2026-10-20T10:00:00Z"),
    ],
)
def test_invalid_inputs_rejected_before_any_database_call(arguments):
    with pytest.raises(ValueError):
        sim.call_sql(*arguments)


def test_equivalent_timezone_inputs_generate_same_request():
    assert sim.call_sql(
        "order", "M-1001", 2, "LOST", "a", "2026-10-20T10:00:00+08:00"
    ) == sim.call_sql("order", "M-1001", 2, "LOST", "a", "2026-10-20T02:00:00Z")


def test_inspection_reference_time_does_not_rewrite_or_reorder_facts():
    state = {
        "query_unavailable": 0,
        "lines": [
            {
                "line_id": "a",
                "events": [
                    {
                        "code": "IN_TRANSIT",
                        "source_version": 2,
                        "occurred_at": "2026-10-19T12:00:00Z",
                    },
                    {
                        "code": "SIMULATED_SHIPPED",
                        "source_version": 1,
                        "occurred_at": "2026-10-19T11:00:00Z",
                    },
                ],
            }
        ],
    }
    database = Mock()
    database.execute.return_value = [state]
    result = sim.inspect(database, "order", "M-1001", "2026-10-20T12:00:00Z")
    assert result["observation_time_is_service_clock"] is False
    assert result["lines"][0]["hours_since_last_event"] == 24
    assert [e["source_version"] for e in result["lines"][0]["events"]] == [1, 2]
    assert "START TRANSACTION READ ONLY" in database.execute.call_args.args[0]


def test_main_returns_nonzero_and_does_not_open_docker_for_bad_time(
    monkeypatch, capsys
):
    database = Mock(side_effect=AssertionError("must not open Docker"))
    monkeypatch.setattr(sim, "LocalMysql", database)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sim",
            "inspect",
            "--order-id",
            "order",
            "--merchant-id",
            "M-1001",
            "--observed-at",
            "2026-10-20T12:00:00",
        ],
    )
    assert sim.main() == 2
    database.assert_not_called()
    assert "timezone" in capsys.readouterr().err


def test_command_emits_original_receipt_and_separate_current_snapshot(
    monkeypatch, capsys
):
    database = Mock()
    database.execute.return_value = [{"fulfillment_version": 3}]
    monkeypatch.setattr(sim, "LocalMysql", lambda: database)
    monkeypatch.setattr(sim, "inspect", lambda *_args: {"fulfillment_version": 4})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sim",
            "advance",
            "--order-id",
            "order",
            "--merchant-id",
            "M-1001",
            "--expected-version",
            "2",
            "--scenario",
            "DELAYED",
            "--request-key",
            "a",
        ],
    )
    assert sim.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["receipt"]["fulfillment_version"] == 3
    assert result["current"]["fulfillment_version"] == 4
