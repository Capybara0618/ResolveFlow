import json
import os
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from resolveflow.harness.budget import RunBudget
from resolveflow.harness.model import MockModelClient
from resolveflow.runtime.db import Database
from resolveflow.runtime.durable import DurableRun
from resolveflow.runtime.factory import DeploymentConfig, build_investigation
from resolveflow.runtime.runs import RunStore
from resolveflow.runtime.worker import RunWorker
from tests.integration.test_run_worker import CASE_DISPATCHER, RUN_ID, a_run, queued
from tests.integration.test_sdk_durable_recovery import Crash
from tests.unit.test_harness_loop import StubTools, propose


@pytest.mark.parametrize("repeat", range(5))
@pytest.mark.parametrize("window", ["before_model_saved", "after_model_saved", "after_tool_saved"])
def test_cf6_fresh_process_reclaims_and_finishes(agent_db: Database, window: str, repeat: int) -> None:
    queued(agent_db)
    env = dict(os.environ, RESOLVEFLOW_AGENT_DB=agent_db.dsn)
    root = Path(__file__).resolve().parents[2]
    def child(stage):
        return subprocess.run(  # noqa: S603 - fixed test module and isolated schema
            [sys.executable, "-m", "tests.integration.recovery_process", agent_db.schema, stage],
                              cwd=root, env=env, capture_output=True, text=True, timeout=45, check=False)
    first = child(window)
    assert first.returncode == 73, first.stderr
    with agent_db.connection() as connection:
        before = connection.execute("SELECT active_deadline_at,budget_spent FROM agent_run").fetchone()
        connection.execute("UPDATE agent_run SET lease_until=now()-interval '1 second'")
    second = child("resume-tool" if window == "after_tool_saved" else "resume")
    assert second.returncode == 0, second.stderr
    result = json.loads(second.stdout.strip().splitlines()[-1])
    assert result["kind"] == "PROPOSAL"
    assert result["models"] == (2 if window == "before_model_saved" else 1)
    assert result["tools"] == (0 if window == "after_tool_saved" else 1)
    with agent_db.connection() as connection:
        after = connection.execute("SELECT active_deadline_at,budget_spent,fence FROM agent_run").fetchone()
        assert after["active_deadline_at"] == before["active_deadline_at"]
        assert after["fence"] == 2
        assert after["budget_spent"]["model_calls"] == (3 if window == "before_model_saved" else 2)
        assert connection.execute("SELECT count(*) AS n FROM agent_callback_outbox").fetchone()["n"] == 2
        calls = connection.execute(
            "SELECT call_id,state,current_attempt FROM agent_model_call ORDER BY call_id"
        ).fetchall()
        assert [row["call_id"] for row in calls] == ["model-0", "model-1"]
        assert all(row["state"] == "SAVED" for row in calls)
        assert calls[0]["current_attempt"] == (1 if window == "before_model_saved" else 0)


@pytest.mark.parametrize("invalidate", ["fence", "cancel", "revision"])
def test_late_worker_cannot_save_reply_or_callback(agent_db: Database, monkeypatch, invalidate: str) -> None:
    queued(agent_db)
    model = MockModelClient(script=[propose("MANUAL_REVIEW", summary="synthetic")])
    investigate = build_investigation(database=agent_db, config=DeploymentConfig(mode="mock"), model=model,
                                     tools=StubTools())
    def fault(stage):
        if stage != "before_model_saved":
            return
        if invalidate == "cancel":
            RunStore(agent_db).cancel(RUN_ID)
        elif invalidate == "revision":
            RunStore(agent_db).queue(a_run(run_id=str(uuid.uuid4()), input_revision=2), caller=CASE_DISPATCHER)
        else:
            with agent_db.connection() as connection:
                connection.execute("UPDATE agent_run SET fence=fence+1")
    monkeypatch.setattr("resolveflow.runtime.factory.DurableRun", lambda db, facts: DurableRun(db, facts, fault=fault))
    result = RunWorker(agent_db, investigate, recoverable=True).run_once()
    assert result.callback_kind is None
    assert model.calls == 1
    with agent_db.connection() as connection:
        assert connection.execute("SELECT state FROM agent_model_call").fetchone()["state"] == "UNKNOWN"
        row = connection.execute("SELECT count(*) AS n FROM agent_callback_outbox WHERE kind!='STARTED'").fetchone()
        assert row["n"] == 0


@pytest.mark.parametrize("change", ["budget", "state", "code", "model"])
def test_changed_manifest_fails_without_new_model_call(agent_db: Database, monkeypatch, change: str) -> None:
    queued(agent_db)
    model = MockModelClient(script=[propose("MANUAL_REVIEW", summary="synthetic")])
    investigate = build_investigation(database=agent_db, config=DeploymentConfig(mode="mock"), model=model,
                                     tools=StubTools())
    def crash(stage):
        if stage == "after_model_saved":
            raise Crash()
    monkeypatch.setattr("resolveflow.runtime.factory.DurableRun", lambda db, facts: DurableRun(db, facts, fault=crash))
    with pytest.raises(Crash):
        RunWorker(agent_db, investigate, recoverable=True).run_once()
    with agent_db.connection() as connection:
        connection.execute("UPDATE agent_run SET lease_until=now()-interval '1 second'")
    monkeypatch.setattr("resolveflow.runtime.factory.DurableRun", DurableRun)
    budget = RunBudget()
    if change == "budget":
        budget = replace(budget, tool_attempts=15)
    elif change == "state":
        monkeypatch.setattr("resolveflow.harness.manifest.STATE_SCHEMA_VERSION", 999)
    elif change == "code":
        monkeypatch.setenv("RESOLVEFLOW_CODE_REVISION", "incompatible-build")
    else:
        model.model_alias = "different-model"
    changed = build_investigation(database=agent_db, config=DeploymentConfig(mode="mock"), model=model,
                                 tools=StubTools(), budget=budget)
    result = RunWorker(agent_db, changed, recoverable=True).run_once()
    assert result.result.reason_code == "MIGRATION_REQUIRED"
    assert model.calls == 1


@pytest.mark.parametrize("succeeds", [True, False])
def test_provider_outage_is_retried_once_with_unknown_cost(agent_db: Database, succeeds: bool) -> None:
    from resolveflow.harness.live_model import HttpResponse, LiveModelClient
    from tests.unit.test_live_model_client import Recorder, ok

    queued(agent_db)
    replies = [HttpResponse(503, b"unavailable"),
               ok(json.dumps(propose("MANUAL_REVIEW", summary="synthetic")),
                  {"prompt_tokens": 100, "completion_tokens": 30}) if succeeds else HttpResponse(503, b"unavailable")]
    transport = Recorder(*replies)
    model = LiveModelClient(endpoint="http://provider.test.invalid", model_id="test-model", transport=transport)
    config = DeploymentConfig(mode="live", endpoint=model.endpoint, model_id=model.model_id)
    investigate = build_investigation(database=agent_db, config=config, model=model, tools=StubTools())
    worker = RunWorker(agent_db, investigate, recoverable=True)
    first = worker.run_once()
    assert first.status == "RUNNING" and first.callback_kind is None
    for _ in range(2 if not succeeds else 1):
        with agent_db.connection() as connection:
            connection.execute("UPDATE agent_run SET lease_until=now()-interval '1 second'")
        last = worker.run_once()
    assert last.callback_kind == ("PROPOSAL" if succeeds else "FAILED")
    if not succeeds:
        assert last.result.reason_code == "MODEL_RETRY_EXHAUSTED"
    assert model.calls == 2
    assert transport.calls[0]["body"] == transport.calls[1]["body"]
    with agent_db.connection() as connection:
        row = connection.execute("SELECT budget_spent FROM agent_run").fetchone()
        assert row["budget_spent"]["model_calls"] == 2
        assert row["budget_spent"]["output_tokens"] >= 1024


def test_model_timeout_is_bounded_by_original_deadline(agent_db: Database) -> None:
    from resolveflow.harness.live_model import LiveModelClient
    from tests.unit.test_live_model_client import Recorder, ok

    queued(agent_db)
    with agent_db.connection() as connection:
        connection.execute("UPDATE agent_run SET deadline_at=now()+interval '5 seconds'")
    transport = Recorder(ok(json.dumps(propose("MANUAL_REVIEW", summary="synthetic")),
                            {"prompt_tokens": 100, "completion_tokens": 30}))
    model = LiveModelClient(endpoint="http://provider.test.invalid", model_id="test-model", transport=transport)
    investigate = build_investigation(database=agent_db,
                                     config=DeploymentConfig(mode="live", endpoint=model.endpoint,
                                                             model_id=model.model_id), model=model, tools=StubTools())
    assert RunWorker(agent_db, investigate, recoverable=True).run_once().callback_kind == "PROPOSAL"
    assert 0 < transport.calls[0]["timeout"] <= 5
    assert model.timeout_seconds == 30
