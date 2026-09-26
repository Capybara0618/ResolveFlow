import pytest

from resolveflow.harness.budget import RunBudget
from resolveflow.runtime.db import Database
from resolveflow.runtime.journal import RunJournal
from resolveflow.runtime.recovery_store import RecoveryConflictError, StaleFenceError
from tests.integration.test_recovery_budget_store import _store
from tests.integration.test_run_store import RUN_ID


def test_journal_binds_manifest_and_tool_result_under_fence(agent_db: Database) -> None:
    _store(agent_db)
    journal = RunJournal(agent_db)
    journal.bind(RUN_ID, fence=1, owner="test-worker", manifest={"manifest_id": "m", "version": 1}, budget=RunBudget())
    after = journal.reserve_tool(RUN_ID, fence=1, owner="test-worker", call_id="tool-0",
                                 request_hash="a"*64, local=True)
    assert after["tool_attempts"] == 1 and after["local_reads"] == 1
    journal.save_tool(RUN_ID, fence=1, owner="test-worker", call_id="tool-0", observation={"synthetic": True})
    assert journal.reserve_tool(RUN_ID, fence=1, owner="test-worker", call_id="tool-0",
                                request_hash="a"*64, local=True) == after
    with pytest.raises(RecoveryConflictError):
        journal.bind(RUN_ID, fence=1, owner="test-worker", manifest={"manifest_id": "m", "version": 2},
                     budget=RunBudget())
    with pytest.raises(StaleFenceError):
        journal.save_tool(RUN_ID, fence=0, owner="test-worker", call_id="tool-0", observation={"synthetic": False})
