"""Integration-test helpers shared by more than one module."""

from __future__ import annotations

import datetime as dt


def future_deadline(*, hours: int = 6) -> str:
    """A run deadline that is still in the future when the test runs.

    It used to be the literal ``2026-09-28T05:00:00Z``, copied into five modules. That instant
    stopped being the future on 2026-09-28, after which every test that queued a run with it
    failed with ``BUDGET_DEADLINE`` - a run that is refused before its first model call, which
    reads as a broken worker rather than as an expired fixture. A deadline is a duration here,
    so it is computed from now.
    """
    return (dt.datetime.now(dt.UTC) + dt.timedelta(hours=hours)).isoformat()


def future_deadline_offset(*, seconds: int) -> str:
    """The same, for a test that needs a deadline just far enough ahead to act within."""
    return (dt.datetime.now(dt.UTC) + dt.timedelta(seconds=seconds)).isoformat()
