import datetime as dt

from resolveflow.runtime.db import Database
from resolveflow.runtime.leases import RunLease
from resolveflow.runtime.runs import RunStore
from tests.integration.test_run_store import CASE_DISPATCHER, RUN_ID, a_request


def test_session_lock_blocks_takeover_and_reclaim_preserves_deadline(agent_db: Database) -> None:
    RunStore(agent_db).queue(a_request(), caller=CASE_DISPATCHER)
    first = RunLease(agent_db, owner="first")
    second = RunLease(agent_db, owner="second")
    with first.acquire() as claimed:
        assert claimed is not None and claimed.facts.fence == 1
        original = claimed.facts.active_deadline_at
        with agent_db.connection() as connection:
            connection.execute("UPDATE agent_run SET lease_until=now()-interval '1 second' WHERE run_id=%s", (RUN_ID,))
        with second.acquire() as blocked:
            assert blocked is None
    with second.acquire() as recovered:
        assert recovered is not None and recovered.facts.fence == 2
        assert recovered.facts.active_deadline_at == original
    with agent_db.connection() as connection:
        assert connection.execute("SELECT count(*) AS n FROM agent_callback_outbox").fetchone()["n"] == 1


def test_lease_renewal_does_not_extend_activity_window(agent_db: Database) -> None:
    RunStore(agent_db).queue(a_request(), caller=CASE_DISPATCHER)
    lease = RunLease(agent_db, owner="first")
    with lease.acquire() as claimed:
        assert lease.renew(claimed.facts.run_id, claimed.facts.fence)
        with agent_db.connection() as connection:
            row = connection.execute("SELECT active_deadline_at,lease_until FROM agent_run").fetchone()
            assert row["active_deadline_at"].isoformat() == claimed.facts.active_deadline_at
            assert row["lease_until"] < dt.datetime.now(dt.UTC) + dt.timedelta(seconds=31)
