"""``agent_db`` access and its append-only schema (C06.1).

The Agent owns one PostgreSQL database (docs/architecture.md:12, docs/engineering.md:60). Two rules from
the project decide how this module is shaped:

**Migrations are append-only.** Every file in ``migrations/`` runs on every start, in name order, and each
one is written so that running it again is a no-op (``CREATE TABLE IF NOT EXISTS``). Nothing already run is
ever edited, because a file that changes after it has run would make two databases of the same version
disagree. This is the same discipline as the Java services' Flyway files (docs/engineering.md:77), kept
here with the standard library instead of adding a migration tool to the Agent for one table.

**A schema is a parameter, not a constant.** Production uses ``public``. A test asks for a schema of its
own, and every connection this module hands out resolves unqualified table names into that schema, so two
tests running against the same server cannot see each other's rows. The database name itself is not
parameterised: the Agent account may only reach ``agent_db`` (docs/engineering.md:60), so creating one
database per test would need privileges the service deliberately does not have.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from typing import Any, cast

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

#: The default store: the compose ``postgres`` service of infra/compose.yaml. The host port is 55432
#: rather than 5432 on purpose — this machine runs another project's PostgreSQL on the default port
#: (infra/compose.yaml:24), and silently claiming it would break that stack.
DEFAULT_DSN = "postgresql://agent:agent@127.0.0.1:55432/agent_db"

#: Environment override, used by a deployment and by any run that points somewhere else.
DSN_ENV = "RESOLVEFLOW_AGENT_DB"

DEFAULT_SCHEMA = "public"

#: A schema identifier reaches DDL as an identifier, but it is still restricted to the shape PostgreSQL
#: accepts unquoted. A caller-supplied string is never interpolated into SQL as text.
_SCHEMA_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

MIGRATIONS_PACKAGE = "resolveflow.runtime.migrations"


class SchemaError(ValueError):
    """A schema name that is not a safe PostgreSQL identifier."""


def default_dsn(environ: dict[str, str] | None = None) -> str:
    """The DSN this process should use: the environment's, or the compose default."""
    source = os.environ if environ is None else environ
    return source.get(DSN_ENV) or DEFAULT_DSN


def require_schema(schema: str) -> str:
    if not _SCHEMA_PATTERN.match(schema):
        raise SchemaError(f"{schema!r} is not a schema this service will address")
    return schema


def migration_files() -> list[tuple[str, str]]:
    """Every append-only migration, as ``(name, sql)`` in the order it must run.

    Read through :mod:`importlib.resources` so a wheel and a source checkout behave the same.
    """
    root = resources.files(MIGRATIONS_PACKAGE)
    files: list[tuple[str, str]] = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if entry.name.endswith(".sql"):
            files.append((entry.name, entry.read_text(encoding="utf-8")))
    if not files:
        # A package that lost its migrations would otherwise report a healthy start over an empty schema.
        raise SchemaError(f"no migrations found in {MIGRATIONS_PACKAGE}")
    return files


def apply_migrations(connection: psycopg.Connection[dict[str, Any]], schema: str) -> list[str]:
    """Run every migration against ``schema``. Idempotent, and safe to call on every start."""
    require_schema(schema)
    applied: list[str] = []
    for name, statement in migration_files():
        # The schema name is an identifier and the file body is verbatim: the DDL is never string-formatted
        # into a larger statement.
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        connection.execute(statement)
        applied.append(name)
    return applied


class Database:
    """A pooled, schema-scoped view of ``agent_db``.

    The pool is opened lazily (``open=False``) and started on the first use, so constructing the service
    app does not open a connection and a liveness probe never touches the database
    (contracts/core/openapi-agent.yaml:40).

    The first use can now come from **two threads at once** (C06.3b): the callback delivery worker and
    whatever request arrived. ``psycopg_pool.ConnectionPool.open()`` is not safe to call concurrently — its
    second caller trips an internal ``assert not self._pool_full_event`` and raises ``AssertionError`` from
    inside the pool — so the open is guarded by a lock. The pool is still opened lazily and only once; what
    changed is that "only once" is now enforced rather than assumed. Without this, a worker thread that
    happened to start during a request got an AssertionError out of a library rather than a connection.
    """

    def __init__(self, dsn: str | None = None, *, schema: str = DEFAULT_SCHEMA, min_size: int = 1, max_size: int = 4):
        self.dsn = dsn or default_dsn()
        self.schema = require_schema(schema)
        self._open_lock = threading.Lock()
        self._opened = False
        self._pool = ConnectionPool(
            self.dsn,
            min_size=min_size,
            max_size=max_size,
            open=False,
            # Rows come back as mappings, so a query names its columns and a reader cannot get them out of
            # order. Autocommit keeps one statement one transaction; the few places that need two writes to
            # be one fact say so explicitly with `connection.transaction()`. `prepare_threshold=None` keeps
            # psycopg3 from preparing and caching a statement across checkouts, which is what a pool that
            # serves a schema per caller needs.
            kwargs={
                "options": f"-c search_path={self.schema}",
                "autocommit": True,
                "row_factory": dict_row,
                "prepare_threshold": None,
            },
        )

    def close(self) -> None:
        self._pool.close()

    def open(self) -> None:
        """Start the pool if it is not running yet. Idempotent, and safe from several threads at once.

        An explicit flag rather than ``pool.closed``: that property is also true for a pool that has never
        been opened, so it cannot tell "not started" from "shut down", and a chained ``if`` on it would be
        right only by accident. The flag is set **after** ``open()`` returns, so an open that raised is
        attempted again by the next caller instead of being remembered as done.

        Two threads arriving together both intend to open one pool, and the loser must not call ``open()`` a
        second time — that is the call that raises ``AssertionError`` from inside psycopg_pool (see
        ``test_db_pool_threads.py``). So the loser does not decide anything: it waits for the winner's lock and
        returns, because whatever the winner found is what this caller would have found.

        Written with ``acquire(blocking=False)`` rather than a ``with`` block plus a second ``self._opened``
        check. The second check is the obvious form and is what this started as, but mypy strict reads the
        early return above as having already established ``self._opened``, so the re-check lands as
        unreachable code — and the honest fix for that is a shape where the lock is what decides, not a type
        ignore that would have silenced a rule which is right in general.
        """
        if self._opened:
            return
        if not self._open_lock.acquire(blocking=False):
            # Another thread is opening it. It waits for that one to finish, then re-reads the flag rather
            # than assuming success: an open that raised leaves the flag false for the next caller to retry.
            with self._open_lock:
                pass
            return
        try:
            self._pool.open(wait=True)
            self._opened = True
        finally:
            self._open_lock.release()

    def migrations(self) -> list[str]:
        """Apply the append-only migrations, opening the pool if it is not running yet."""
        with self.connection() as connection:
            return apply_migrations(connection, self.schema)

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        """One connection from the pool, returned even when the caller raises."""
        self.open()
        with self._pool.connection() as raw:
            # The pool is generic over its row factory and reports Connection[tuple[Any, ...]] here because
            # that parameter cannot be inferred from the kwargs above, while the connection really yields
            # dict rows (row_factory=dict_row). Stating it keeps every caller's `row["column"]` typed.
            yield cast("psycopg.Connection[dict[str, Any]]", raw)


def create_schema(dsn: str, schema: str, *, drop_first: bool = False) -> None:
    """Create an empty schema for a caller that wants the same tables to itself.

    Only the test suite calls this. It is here rather than in the tests so that the DDL that makes an
    isolated schema stays in one place with the DDL that fills it.
    """
    require_schema(schema)
    with psycopg.connect(dsn, autocommit=True) as connection:
        if drop_first:
            connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        connection.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))


def drop_schema(dsn: str, schema: str) -> None:
    """Remove a schema this service created. Never called against ``public``."""
    require_schema(schema)
    if schema == DEFAULT_SCHEMA:
        raise SchemaError("refusing to drop the service's own schema")
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))