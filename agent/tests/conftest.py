"""Shared fixtures for the Agent test suite.

Two of the suite's dependencies are outside the process and are therefore arranged here rather than in
each test module: a real PostgreSQL for ``agent_db`` (C06.1) and the temporary schema that keeps one test's
tables out of another's. Nothing here is a fake: a test that needs the database either gets the real one or
is skipped with a stated reason, and the project's verification entry point refuses to pass on a skipped
suite (scripts/verify.ps1).
"""

from __future__ import annotations

import json
import math
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import psycopg
import pytest

from resolveflow.runtime.db import DEFAULT_DSN, Database, create_schema, drop_schema


def _dsn() -> str:
    """The database the suite uses: the same environment variable the service reads, or the compose default.

    ``client_encoding`` is set explicitly because the server's default here is ``SQL_ASCII``: without it the
    Chinese policy fixtures come back as mojibake, and a test comparing rule text would fail in a way that looks
    like a chunking bug.
    """
    return os.environ.get("RESOLVEFLOW_AGENT_DB") or DEFAULT_DSN


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    """The DSN the suite will use, or a skip that names exactly what is missing."""
    dsn = _dsn()
    try:
        with psycopg.connect(dsn, connect_timeout=5, client_encoding="UTF8") as connection:
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


@dataclass(frozen=True, slots=True)
class StubEmbedder:
    """A deterministic stand-in for the dense stack (C07.1).

    Unit tests of the index's behaviour — the READY gate, the hard filters, the citation round trip — must not
    need 811 MB of torch and 192 MB of weights, so they take an embedder that satisfies the same Protocol. What
    that deliberately does **not** establish is that retrieval quality is good: the real model's numbers come
    from an actual embedding run, and one is recorded in ``reports/c071-policy-index/``. A stub that is only
    ever used to prove *plumbing* is honest; a stub whose scores were reported as results would not be.
    """

    dimension: int = 8
    model: str = "stub-embedder"
    revision: str = "stub-revision-1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Character-ngram features, normalised. Same text ⇒ same vector, different text ⇒ different vector."""
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimension
            for position, character in enumerate(text):
                bucket = (ord(character) * 31 + position) % self.dimension
                vector[bucket] += 1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors


@pytest.fixture()
def stub_embedder() -> StubEmbedder:
    return StubEmbedder()


def input_text_of(client: object, turn: int = -1) -> str:
    """Everything a scripted model was handed on one turn, from **either** loop input shape.

    Two shapes reach the model while they coexist (C08.1): the C06.4 evidence packet, which travels as one JSON
    message, and the P0–P4 context packet, which travels as several rendered turns. A loop test's claim — "the
    observation reached the next model call" — is about neither shape, so it asks this instead of reaching into one.

    Both are returned as text, which is what makes it a *reading* rather than an assertion about a shape: a test
    that needs the rendered layers looks for ``P2·fact``, and one that needs a field looks for ``key=value`` (both
    appear in either shape, since the facts are rendered as ``key=value``). The first version assumed
    ``conversations[turn]`` was a single message; it is a **list** of them, and the resulting
    ``AttributeError`` is why two tests failed while this was being written.
    """
    packets = getattr(client, "packets", [])
    if packets:
        # The C06.4 shape: the whole input is the JSON mapping the mock parsed out of the last message.
        return json.dumps(packets[turn], ensure_ascii=False, default=str)
    conversations = getattr(client, "conversations", [])
    if not conversations:
        return ""
    return "\n".join(
        block.text
        for message in conversations[turn]
        for block in message.get_content_blocks()
        if hasattr(block, "text")
    )


def packet_of(client: object, turn: int = -1) -> dict[str, object]:
    """The structured packet the C06.4 loop hands the model, or an empty mapping for the context-builder shape.

    The context builder does not hand over a mapping (it renders prose, which is the point), so a test that needs the
    *structure* asks :func:`input_text_of` and looks at the rendered layers. Kept as a separate name so a caller is
    explicit about which it wants.
    """
    packets = getattr(client, "packets", [])
    return {} if not packets else dict(packets[turn])