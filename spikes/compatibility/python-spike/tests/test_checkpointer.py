"""T00 gate: LangGraph's Postgres checkpointer saves and restores against real PG 16 + pgvector.

This is the capability T22 (checkpoint/lease/recovery) builds on, so it is verified
against a real server rather than an in-memory saver.

Needs the spike stack up:
    docker compose -f spikes/compatibility/infra/spike-compose.yaml up -d postgres
"""

from __future__ import annotations

import os
from typing import TypedDict

import pytest
import psycopg

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

CONN_STRING = os.environ.get(
    "SPIKE_PG_DSN",
    "postgresql://agent:agent@127.0.0.1:15432/agent_db",
)


class GraphState(TypedDict):
    observation: str
    steps: int


def _build_graph(checkpointer: PostgresSaver):
    def investigate(state: GraphState) -> GraphState:
        # Stands in for one Harness step: a model call plus a recorded observation.
        return {"observation": state["observation"] + f"|step{state['steps'] + 1}", "steps": state["steps"] + 1}

    builder = StateGraph(GraphState)
    builder.add_node("investigate", investigate)
    builder.add_edge(START, "investigate")
    builder.add_edge("investigate", END)
    return builder.compile(checkpointer=checkpointer)


@pytest.fixture(scope="module")
def saver():
    with PostgresSaver.from_conn_string(CONN_STRING) as s:
        s.setup()  # idempotent: creates the checkpoint tables if absent
        yield s


def test_postgres_and_pgvector_available():
    with psycopg.connect(CONN_STRING) as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW server_version")
            version = cur.fetchone()[0]
            assert version.startswith("16."), f"expected PostgreSQL 16, got {version}"

            # The project stores policy embeddings in this same database.
            cur.execute("SELECT name FROM pg_available_extensions WHERE name = 'vector'")
            assert cur.fetchone() is not None, "pgvector must be installable in this image"

            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ext_version = cur.fetchone()[0]
            assert ext_version, "pgvector extension must be creatable"

            # Prove a vector column and exact-search ordering actually work.
            cur.execute("DROP TABLE IF EXISTS spike_vec")
            cur.execute("CREATE TABLE spike_vec (id text primary key, embedding vector(3))")
            cur.execute(
                "INSERT INTO spike_vec VALUES ('a', '[1,0,0]'), ('b', '[0,1,0]'), ('c', '[0,0,1]')"
            )
            cur.execute(
                "SELECT id FROM spike_vec ORDER BY embedding <-> '[0.9,0.1,0]' LIMIT 1"
            )
            assert cur.fetchone()[0] == "a"
        conn.rollback()


def test_checkpoint_persists_and_survives_a_new_connection(saver):
    app = _build_graph(saver)
    config = {"configurable": {"thread_id": "t00-thread-persist"}}

    first = app.invoke({"observation": "start", "steps": 0}, config)
    assert first["steps"] == 1

    # A brand-new saver == a restarted worker process. It must see the same state,
    # which is what makes crash recovery possible at all.
    with PostgresSaver.from_conn_string(CONN_STRING) as reopened:
        reopened.setup()
        checkpoint = reopened.get_tuple({"configurable": {"thread_id": "t00-thread-persist"}})
        assert checkpoint is not None, "state must survive a new connection"
        assert checkpoint.checkpoint["channel_values"]["observation"] == "start|step1"
        assert checkpoint.checkpoint["channel_values"]["steps"] == 1


def test_threads_are_isolated(saver):
    app = _build_graph(saver)

    app.invoke({"observation": "alpha", "steps": 0}, {"configurable": {"thread_id": "t00-thread-a"}})
    app.invoke({"observation": "beta", "steps": 0}, {"configurable": {"thread_id": "t00-thread-b"}})

    a = saver.get_tuple({"configurable": {"thread_id": "t00-thread-a"}})
    b = saver.get_tuple({"configurable": {"thread_id": "t00-thread-b"}})

    assert a.checkpoint["channel_values"]["observation"] == "alpha|step1"
    assert b.checkpoint["channel_values"]["observation"] == "beta|step1"
    assert a.checkpoint["id"] != b.checkpoint["id"]


def test_checkpoint_history_is_append_only(saver):
    app = _build_graph(saver)
    config = {"configurable": {"thread_id": "t00-thread-history"}}

    app.invoke({"observation": "one", "steps": 0}, config)
    app.invoke({"observation": "two", "steps": 1}, config)

    history = list(saver.list({"configurable": {"thread_id": "t00-thread-history"}}))
    assert len(history) >= 2, "each step must append a checkpoint, not overwrite history"


def test_unknown_thread_has_no_checkpoint(saver):
    assert saver.get_tuple({"configurable": {"thread_id": "t00-thread-never-created"}}) is None