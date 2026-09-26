from resolveflow.runtime.db import Database
from resolveflow.runtime.leases import RunLease
from resolveflow.runtime.worker import RunWorker
from tests.integration.test_run_worker import RUN_ID, proposal_result, queued


def test_recoverable_worker_uses_fence(agent_db: Database) -> None:
    queued(agent_db)
    seen = []
    def investigate(facts):
        seen.append(facts)
        return proposal_result()
    outcome = RunWorker(agent_db, investigate, recoverable=True).run_once()
    assert outcome.callback_kind == "PROPOSAL"
    assert seen[0].fence == 1 and seen[0].lease_owner


def test_old_fence_cannot_finish(agent_db: Database) -> None:
    queued(agent_db)
    worker = RunWorker(agent_db, lambda _: proposal_result())
    with RunLease(agent_db).acquire() as claimed:
        with agent_db.connection() as connection:
            connection.execute("UPDATE agent_run SET fence=fence+1 WHERE run_id=%s", (RUN_ID,))
        assert worker.finish(claimed, proposal_result()).callback_kind is None
    with agent_db.connection() as connection:
        assert connection.execute("SELECT count(*) AS n FROM agent_callback_outbox").fetchone()["n"] == 1


def test_legacy_run_refuses_without_investigation(agent_db: Database) -> None:
    queued(agent_db)
    RunWorker(agent_db, lambda _: proposal_result()).claim_one()
    def forbidden(_):
        raise AssertionError("legacy run must not silently restart")
    outcome = RunWorker(agent_db, forbidden, recoverable=True).run_once()
    assert outcome.result.reason_code == "MIGRATION_REQUIRED"


def test_expired_deadline_is_not_extended(agent_db: Database) -> None:
    queued(agent_db)
    with agent_db.connection() as connection:
        connection.execute("UPDATE agent_run SET deadline_at=now()-interval '1 second'")
    def forbidden(_):
        raise AssertionError("expired run must not call model")
    outcome = RunWorker(agent_db, forbidden, recoverable=True).run_once()
    assert outcome.result.reason_code == "BUDGET_DEADLINE"


def test_waiting_for_terminal_lock_consumes_lease(agent_db: Database) -> None:
    import time
    from concurrent.futures import ThreadPoolExecutor

    queued(agent_db)
    worker = RunWorker(agent_db, lambda _: proposal_result())
    with RunLease(agent_db).acquire() as claimed, ThreadPoolExecutor(max_workers=1) as threads:
        with agent_db.connection() as connection:
            connection.execute("UPDATE agent_run SET lease_until=clock_timestamp()+interval '0.2 seconds'")
        with agent_db.connection() as connection, connection.transaction():
            connection.execute("SELECT run_id FROM agent_run FOR UPDATE")
            finishing = threads.submit(worker.finish, claimed, proposal_result())
            time.sleep(0.3)
        assert finishing.result(timeout=3).callback_kind is None
