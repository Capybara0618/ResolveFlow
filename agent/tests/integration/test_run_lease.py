import datetime as dt
import uuid

from resolveflow.runtime.db import Database
from resolveflow.runtime.leases import RunLease
from resolveflow.runtime.runs import RunStore
from tests.integration.test_run_store import CASE_DISPATCHER, RUN_ID, a_request


def test_targeted_lease_never_claims_an_unrelated_older_run(agent_db: Database) -> None:
    store = RunStore(agent_db)
    store.queue(a_request(), caller=CASE_DISPATCHER)
    target = str(uuid.uuid4())
    store.queue(a_request(run_id=target, case_id=str(uuid.uuid4())), caller=CASE_DISPATCHER)
    lease = RunLease(agent_db, owner="targeted-check")
    with lease.acquire(run_id=target) as claimed:
        assert claimed is not None and claimed.facts.run_id == target
        with lease.acquire(run_id=target) as held:
            assert held is None
    with lease.acquire(run_id=str(uuid.uuid4())) as missing:
        assert missing is None
    with agent_db.connection() as connection:
        unrelated = connection.execute(
            "SELECT status,fence,active_deadline_at FROM agent_run WHERE run_id=%s", (RUN_ID,),
        ).fetchone()
        assert unrelated["status"] == "QUEUED"
        assert unrelated["fence"] is None and unrelated["active_deadline_at"] is None
        callbacks = connection.execute(
            "SELECT count(*) AS n FROM agent_callback_outbox WHERE run_id=%s", (RUN_ID,),
        ).fetchone()
        assert callbacks["n"] == 0
    with lease.acquire() as first:
        assert first is not None and first.facts.run_id == RUN_ID


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
