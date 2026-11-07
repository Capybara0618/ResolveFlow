"""Real PostgreSQL: ownership migration refuses unknown/active runs and preserves archives."""
from pathlib import Path

import psycopg
import pytest

from resolveflow.runtime.runs import RunStore
from tests.integration.test_run_store import CASE_DISPATCHER, a_request


def test_identity_upgrade_requires_a_map_and_drained_runs_without_rewriting_requests(agent_db):
    request = a_request()
    RunStore(agent_db).queue(request, caller=CASE_DISPATCHER)
    migration = (
        Path(__file__).resolve().parents[2] / "src/resolveflow/runtime/migrations/015_unified_buyer_identity.sql"
    ).read_text(encoding="utf-8")
    archive = "SELECT request_hash,policy_manifest,budget_spent,deadline_at FROM agent_run"
    with agent_db.connection() as connection:
        original = connection.execute(archive).fetchone()
        connection.execute("ALTER TABLE agent_run RENAME COLUMN buyer_id TO customer_id")
        with pytest.raises(psycopg.Error, match="Unmapped agent run owner"):
            connection.execute(migration)
        connection.execute("INSERT INTO buyer_identity_legacy VALUES (%s,%s,%s)",
                           (request.merchant_id, request.buyer_id, "global-buyer"))
        with pytest.raises(psycopg.Error, match="Drain active runs"):
            connection.execute(migration)
        connection.execute("UPDATE agent_run SET status='COMPLETED'")
        connection.execute(migration)
        assert connection.execute("SELECT buyer_id FROM agent_run").fetchone()["buyer_id"] == "global-buyer"
        assert connection.execute(archive).fetchone() == original
        connection.execute(migration)  # startup is idempotent
