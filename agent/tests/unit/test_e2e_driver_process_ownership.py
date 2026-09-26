"""E2E drivers may only stop processes they started, even when a demo port is occupied."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import e2e_harness_java_tools as tools_driver  # noqa: E402
import e2e_refund_chain as refund_driver  # noqa: E402


class Report:
    def __init__(self) -> None:
        self.notes: list[str] = []

    def note(self, message: str) -> None:
        self.notes.append(message)


@pytest.mark.parametrize("driver", [refund_driver, tools_driver])
def test_occupied_java_port_is_refused_without_killing_its_owner(
    driver: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = Report()
    monkeypatch.setattr(driver.base, "pids_on_port", lambda port: ["4242"] if port == driver.CASE_PORT else [])
    monkeypatch.setattr(driver.base, "kill_port", lambda port: pytest.fail(f"killed port {port}"))
    assert driver.java_ports_available(report) is False
    assert any("4242" in note for note in report.notes)


@pytest.mark.parametrize("driver", [refund_driver, tools_driver])
def test_cleanup_does_not_kill_an_unowned_process_on_the_same_port(
    driver: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(driver.base, "pids_on_port", lambda port: ["4242"])
    monkeypatch.setattr(driver.base, "kill_port", lambda port: pytest.fail(f"killed port {port}"))
    driver.stop(None, driver.CASE_PORT)
