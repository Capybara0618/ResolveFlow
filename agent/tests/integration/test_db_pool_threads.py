"""C06.3b: opening the connection pool from two threads at once.

This is a regression test for a defect the C06.3b worker exposed rather than introduced. ``Database`` opens
its pool lazily on first use, which was safe while every caller was a request handler on one event loop. The
callback delivery worker is a second thread, so "first use" became a race: two threads both found the pool
unopened and both called ``ConnectionPool.open()``, whose second caller trips an internal
``assert not self._pool_full_event`` and raises ``AssertionError``. The first symptom was a *worker* tick
failing with a traceback out of psycopg_pool while a test thread was reading the same tables — a library
assertion wearing the costume of a delivery bug.

The test does not assert "no exception" alone; it asserts the property the fix promises — **the pool is
opened once** and every thread that asked gets a usable connection.
"""

from __future__ import annotations

import threading
from typing import Any

from resolveflow.runtime.db import Database


def test_two_threads_opening_the_pool_at_once_both_get_a_connection(agent_db: Database) -> None:
    # A fresh Database over the same schema, so this test's pool is the one being opened and the fixture's
    # already-open pool is not.
    database = Database(agent_db.dsn, schema=agent_db.schema)

    start = threading.Barrier(4)
    results: list[Any] = []
    lock = threading.Lock()

    def use_once() -> None:
        start.wait(timeout=5)
        try:
            with database.connection() as connection:
                row = connection.execute("SELECT 1 AS one").fetchone()
            outcome: Any = row["one"]
        except Exception as error:  # noqa: BLE001 - the point is to report whatever came out
            outcome = error
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=use_once) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    try:
        assert results == [1, 1, 1, 1], f"a thread did not get a connection: {results}"
    finally:
        database.close()


def test_opening_twice_is_harmless(agent_db: Database) -> None:
    database = Database(agent_db.dsn, schema=agent_db.schema)
    try:
        database.open()
        database.open()
        with database.connection() as connection:
            assert connection.execute("SELECT 1 AS one").fetchone()["one"] == 1
    finally:
        database.close()