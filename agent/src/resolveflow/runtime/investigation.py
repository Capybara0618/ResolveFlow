"""One resident investigation thread; run claiming and the SDK loop stay in their existing owners.

Shutdown waits for the current investigation rather than cancelling a consumed action. A crash stops this
thread and leaves the run RUNNING for C09 recovery; it must not be disguised as a model decision or retried.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable

LOG = logging.getLogger(__name__)


class InvestigationLoop:
    def __init__(self, run_once: Callable[[], object], *, interval_seconds: float = 1.0) -> None:
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("the investigation interval must be finite and positive")
        self._run_once = run_once
        self._interval = interval_seconds
        self._stop = threading.Event()
        self.stopped = threading.Event()
        self.failed = False
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("the investigation loop is already started")
        self._thread = threading.Thread(target=self._run, name="run-investigation", daemon=True)
        self._thread.start()

    def close(self, *, timeout: float = 135.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise TimeoutError("investigation still running; do not close its database pool")

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._run_once()
                self._stop.wait(self._interval)
        except Exception:  # noqa: BLE001 - surface a thread failure without fabricating a FAILED decision
            self.failed = True
            LOG.error("investigation worker stopped unexpectedly; RUNNING runs require recovery")
        finally:
            self.stopped.set()
