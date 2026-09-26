from resolveflow.runtime.db import Database
from resolveflow.runtime.leases import RunLease
from resolveflow.runtime.worker import RunWorker
from tests.integration.test_run_worker import proposal_result, queued


def test_pre_c09_claim_cannot_finish_after_fenced_takeover(agent_db: Database) -> None:
    queued(agent_db)
    old = RunWorker(agent_db, lambda _: proposal_result())
    claimed = old.claim_one()
    assert claimed.facts.fence is None
    with RunLease(agent_db).acquire() as recovery:
        assert recovery.legacy and recovery.facts.fence == 1
        assert old.finish(claimed, proposal_result()).callback_kind is None
