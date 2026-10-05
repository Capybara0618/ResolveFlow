"""Persist cooldown without sleeping in a lease or extending the investigation deadline."""

import json

import pytest
from resolveflow.harness.live_model import HttpResponse, ModelUnavailableError
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.runtime.durable import DurableRun
from resolveflow.runtime.journal import RunJournal
from resolveflow.runtime.recovery_store import StaleFenceError
from resolveflow.runtime.worker import RunWorker

from tests.integration.test_recovery_model_result import _reserved
from tests.integration.test_run_store import RUN_ID
from tests.integration.test_run_worker import queued
from tests.unit.test_harness_loop import StubTools, propose
from tests.unit.test_live_model_client import Recorder, client, ok


def worker(database, model):
    def investigate(facts):
        return AgentScopeRunner(model=model, tools=StubTools(), facts=facts,
                               durability=DurableRun(database, facts)).run()
    return RunWorker(database, investigate, recoverable=True)


def end_cooldown(database):
    with database.connection() as connection:
        connection.execute("UPDATE agent_run SET model_retry_after=clock_timestamp()-interval '1 second'")


def test_429_wait_survives_new_worker_and_retry_reuses_exact_request(agent_db):
    queued(agent_db)
    live = client(Recorder(HttpResponse(429, b"busy", headers={"Retry-After": "30"}),
                           ok(json.dumps(propose("MANUAL_REVIEW")), {"prompt_tokens": 20, "completion_tokens": 8})))
    assert worker(agent_db, live).run_once().status == "RUNNING"
    with agent_db.connection() as connection:
        row = connection.execute("SELECT model_retry_after,active_deadline_at FROM agent_run").fetchone()
        assert row["model_retry_after"] <= row["active_deadline_at"]
        attempt = connection.execute("SELECT failure_code FROM agent_model_attempt").fetchone()
        assert attempt["failure_code"] == "MODEL_RATE_LIMITED"
    assert worker(agent_db, live).run_once() is None and live.calls == 1
    end_cooldown(agent_db)
    result = worker(agent_db, live).run_once()
    assert result.callback_kind == "PROPOSAL" and result.result.completed
    assert live.calls == result.result.spend.model_calls == 2
    assert live.requests[0]["body_hash"] == live.requests[1]["body_hash"]


def test_repeated_429_exhausts_only_one_retry_without_a_third_request(agent_db):
    queued(agent_db)
    live = client(Recorder(HttpResponse(429, b""), HttpResponse(429, b"")))
    assert worker(agent_db, live).run_once().status == "RUNNING"
    end_cooldown(agent_db)
    assert worker(agent_db, live).run_once().status == "RUNNING"
    outcome = worker(agent_db, live).run_once()
    assert outcome.result.reason_code == "MODEL_RETRY_EXHAUSTED"
    assert live.calls == outcome.result.spend.model_calls == 2


def test_expired_deadline_finishes_even_during_long_provider_cooldown(agent_db):
    queued(agent_db)
    live = client(Recorder(HttpResponse(429, b"", headers={"Retry-After": "3600"})))
    worker(agent_db, live).run_once()
    with agent_db.connection() as connection:
        connection.execute("UPDATE agent_run SET active_deadline_at=clock_timestamp()-interval '1 second'")
    result = worker(agent_db, live).run_once()
    assert result.result.reason_code == "BUDGET_DEADLINE" and live.calls == 1


def test_cooling_run_does_not_block_another_queued_case(agent_db):
    queued(agent_db)
    live = client(Recorder(HttpResponse(429, b""), ok(json.dumps(propose("MANUAL_REVIEW")))))
    worker(agent_db, live).run_once()
    other = "11111111-2222-4333-8444-555555555556"
    queued(agent_db, run_id=other, case_id="9c858901-8a57-4791-81fe-4c455b099bca")
    outcome = worker(agent_db, live).run_once()
    assert outcome.run_id == other and outcome.callback_kind == "PROPOSAL" and live.calls == 2


def test_stale_fence_cannot_set_retry_cooldown(agent_db):
    _reserved(agent_db)
    with agent_db.connection() as connection:
        connection.execute("UPDATE agent_run SET fence=2 WHERE run_id=%s", (RUN_ID,))
    with pytest.raises(StaleFenceError):
        RunJournal(agent_db).defer_model_retry(RUN_ID, fence=1, owner="test-worker", call_id="step-0", seconds=5)
    with agent_db.connection() as connection:
        assert connection.execute("SELECT model_retry_after FROM agent_run").fetchone()["model_retry_after"] is None


def test_direct_reservation_cannot_bypass_persisted_cooldown_or_charge_again(agent_db):
    store = _reserved(agent_db)
    RunJournal(agent_db).defer_model_retry(RUN_ID, fence=1, owner="test-worker", call_id="step-0", seconds=30)
    with pytest.raises(ModelUnavailableError, match="cooldown"):
        store.reserve_retry(RUN_ID, fence=1, owner="test-worker", call_id="step-0",
                            request_hash="a" * 64, expected_attempt=0)
    with agent_db.connection() as connection:
        row = connection.execute("SELECT budget_spent FROM agent_run").fetchone()
        assert row["budget_spent"]["model_calls"] == 1
        assert connection.execute("SELECT count(*) AS n FROM agent_model_attempt").fetchone()["n"] == 1
