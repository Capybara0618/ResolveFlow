"""Shared fixtures for the Agent test suite.

Two of the suite's dependencies are outside the process and are therefore arranged here rather than in
each test module: a real PostgreSQL for ``agent_db`` (C06.1) and the temporary schema that keeps one test's
tables out of another's. Nothing here is a fake: a test that needs the database either gets the real one or
is skipped with a stated reason, and the project's verification entry point refuses to pass on a skipped
suite (scripts/verify.ps1).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest

from resolveflow.runtime.db import DEFAULT_DSN, Database, create_schema, drop_schema


def _dsn() -> str:
    """The database the suite uses: the same environment variable the service reads, or the compose default."""
    return os.environ.get("RESOLVEFLOW_AGENT_DB") or DEFAULT_DSN


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    """The DSN the suite will use, or a skip that names exactly what is missing."""
    dsn = _dsn()
    try:
        with psycopg.connect(dsn, connect_timeout=5) as connection:
            connection.execute("SELECT 1")
    except psycopg.Error as error:  # pragma: no cover - depends on the machine, not on the code
        pytest.skip(f"agent_db is not reachable at {dsn}: {error}")
    return dsn


@pytest.fixture()
def agent_db(postgres_dsn: str) -> Iterator[Database]:
    """A migrated ``agent_db`` view in a schema of this test's own.

    A unique schema rather than ``public``: the suite must be runnable against the same server the service
    uses without leaving rows behind or reading someone else's. The schema is dropped on the way out, so a
    failing test leaves the database as it found it.
    """
    schema = f"t_{uuid.uuid4().hex[:16]}"
    create_schema(postgres_dsn, schema)
    database = Database(postgres_dsn, schema=schema)
    try:
        database.migrations()
        yield database
    finally:
        database.close()
        drop_schema(postgres_dsn, schema)