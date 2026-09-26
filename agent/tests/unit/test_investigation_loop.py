from __future__ import annotations

import threading

import pytest

from resolveflow.runtime.investigation import InvestigationLoop


def test_empty_queue_waits_and_shutdown_wakes_it() -> None:
    ticked = threading.Event()
    calls: list[int] = []

    def tick() -> None:
        calls.append(1)
        ticked.set()

    loop = InvestigationLoop(tick, interval_seconds=60)
    assert not loop.running
    loop.start()
    assert ticked.wait(2)
    loop.close(timeout=2)
    assert not loop.running
    assert calls == [1]
    assert not loop.failed


def test_shutdown_does_not_claim_again_after_inflight_work() -> None:
    entered, release = threading.Event(), threading.Event()
    calls: list[int] = []

    def tick() -> None:
        calls.append(1)
        entered.set()
        assert release.wait(2)

    loop = InvestigationLoop(tick, interval_seconds=0.01)
    loop.start()
    try:
        assert entered.wait(2)
        with pytest.raises(TimeoutError):
            loop.close(timeout=0)
        assert loop.running, "a timed-out join must not claim that the worker stopped"
    finally:
        release.set()
        loop.close(timeout=2)
    assert calls == [1]
    assert not loop.running


def test_unexpected_investigation_failure_stops_instead_of_retrying_the_run() -> None:
    def tick() -> None:
        raise RuntimeError("investigation crashed")

    loop = InvestigationLoop(tick)
    loop.start()
    assert loop.stopped.wait(2)
    assert loop.failed
    loop.close(timeout=2)
    assert not loop.running


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf")])
def test_invalid_interval_is_refused(interval: float) -> None:
    with pytest.raises(ValueError):
        InvestigationLoop(lambda: None, interval_seconds=interval)
