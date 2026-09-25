"""The resident worker that delivers the callback outbox (C06.3b).

C06.1b-2 built the delivery client and C06.1c wired the Java side to receive it, but nothing called
``CallbackDelivery.deliver_due``: an outbox row written by a run stayed PENDING until a human drained it.

Why a thread inside the Agent process rather than a separate worker process:

* **The delivery is synchronous.** ``post_delivery`` uses ``urllib`` and the store uses psycopg — both
  blocking. As an ``asyncio`` task it would either block the event loop (stalling every HTTP request,
  including the health check) or need ``asyncio.to_thread`` on each tick, which is a thread with extra
  steps and no clean cancellation.
* **The Agent is already a resident process.** C06.3 in the task ledger calls for the loop to be resident;
  it does not call for a second deployment. ``docs/core-scope.md`` puts the core at three Java processes
  plus the Agent, and a coordinator only exists once there is more than one worker to coordinate — which
  ``docs/agent-spec.md:46`` ("worker 领取用 PG 租约/fence") describes for the *run* worker, not for this.

What that bound costs is stated rather than hidden: two Agent replicas would both deliver the same due
rows. The outbox is at-least-once and ``callback_id`` is the idempotency key on the Java side
(``docs/domain-model.md:69``), so the second delivery is answered DUPLICATE — but "safe" is not "free",
and a single replica is the deployment this bounds.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from typing import Protocol

from resolveflow.runtime.delivery import DeliveryOutcome

LOG = logging.getLogger(__name__)


class DueDelivery(Protocol):
    """What the loop needs from a delivery: the due rows, attempted, with their outcomes returned.

    A Protocol rather than :class:`CallbackDelivery` itself, because the loop genuinely uses one method and
    the app supplies a wrapper that resolves the store on the first tick (``_DeferredCallbackDelivery`` in
    :mod:`resolveflow.api.app`) so an unreachable database is a logged retry rather than a startup failure.
    Typing the parameter as the concrete class would have forced that wrapper to subclass it for no reason
    other than to satisfy the annotation.
    """

    def deliver_due(self, *, now: dt.datetime | None = None, limit: int = 50) -> list[DeliveryOutcome]: ...

#: How long one tick waits before looking for work again. Short, because a tick with nothing due is one
#: indexed read and the alternative is delaying a callback that is ready now.
DEFAULT_INTERVAL_SECONDS = 1.0

#: How many due rows one tick will attempt. Bounded so an unreachable case service cannot make one tick
#: unbounded: a failed callback is rescheduled into the future, so a smaller limit drains over several ticks
#: rather than hammering.
DEFAULT_BATCH_SIZE = 50


class CallbackDeliveryLoop:
    """Drains the callback outbox until it is stopped.

    ``start``/``close`` are separate from construction so the object can be built and inspected (including by
    a test that never starts it) without a thread existing.
    """

    def __init__(
        self,
        delivery: DueDelivery,
        *,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if interval_seconds <= 0:
            # A zero interval would spin the CPU looking for work; a negative one is a typo, not a policy.
            raise ValueError("the delivery interval must be positive")
        if batch_size < 1:
            raise ValueError("the delivery batch size must be at least 1")
        self._delivery = delivery
        self._interval = interval_seconds
        self._batch_size = batch_size
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        """Whether a tick loop is alive. False before ``start`` and after ``close``."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Begin ticking. Starting twice is refused rather than silently ignored."""
        if self._thread is not None:
            raise RuntimeError("the callback delivery loop is already started")
        self._thread = threading.Thread(target=self._run, name="callback-delivery", daemon=True)
        self._thread.start()

    def close(self, *, timeout: float = 5.0) -> None:
        """Ask the loop to stop and wait for the tick in flight to finish.

        The wait matters at shutdown: a tick in the middle of ``deliver_one`` is writing to the outbox, and
        killing the process around it would leave a callback whose attempt was never recorded. Nothing here
        can un-send an HTTP request already in flight, and that is the same bound the run cancellation states
        (``docs/core-contracts.md:41``).
        """
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)

    def run_once(self) -> int:
        """One tick, callable directly (tests, and a manual drain of the outbox).

        Returns how many attempts were made, which is what a caller can assert on without reading a log. A
        tick never raises: the thread it runs on has nobody to catch an exception, and a loop that dies on
        its first database blip stops delivering everything behind it.
        """
        try:
            outcomes = self._delivery.deliver_due(limit=self._batch_size)
        except Exception:  # noqa: BLE001 - a worker thread must survive its own tick
            LOG.warning("a callback delivery pass failed; the next tick will try again", exc_info=True)
            return 0
        for outcome in outcomes:
            if outcome.status == "DELIVERED":
                LOG.info(
                    "callback %s delivered (%s)%s",
                    outcome.callback_id,
                    outcome.disposition,
                    "" if outcome.case_version is None else f" at case version {outcome.case_version}",
                )
            else:
                LOG.warning(
                    "callback %s is %s: %s",
                    outcome.callback_id,
                    outcome.status,
                    outcome.error,
                )
        return len(outcomes)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            # wait() rather than sleep() so close() takes effect immediately instead of after a full interval.
            self._stop.wait(self._interval)