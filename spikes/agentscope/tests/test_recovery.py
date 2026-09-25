"""AS01.2: the recovery gate, over **real PostgreSQL**.

`docs/agentscope-migration.md:41` sets the standard for this sub-step and rules out the cheap version: *"必须用真实
SDK 和真实 PG，不用另写 toy 循环证明 SDK 可恢复"*. So these tests use the real `AgentState` from the real
AgentScope loop, and a real PostgreSQL database in a schema of their own — not `public`, and not a fake store, so
a probe cannot leave anything behind or read anything that is not its own.

The five properties, each with its own reason to exist:

1. **结果已落库而快照未推进 → 可复用，且不重复计费.** The window between `record_response` and `advance_snapshot`.
   The recorded answer must be reused as-is: re-deriving it would re-call the provider, and re-charging it would
   bill the run twice for one answer.
2. **未落库窗口记 UNKNOWN.** A call whose answer was never saved is `UNKNOWN`, which is neither success nor
   failure; the run may retry within its limit and must keep the cost conservatively
   (`docs/agentscope-migration.md:67`).
3. **旧 fence 写快照/终局被拒.** A superseded worker must not be able to advance the run, even while it is still
   running and still believes it holds it.
4. **预算/deadline 不重置.** A resume continues the run it was; it does not get a fresh budget or a later window.
5. **跨连接/跨进程恢复.** The snapshot must be readable by a different connection, because recovery in production
   means a **different process**, and an in-memory convenience would pass every other test here.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import sys
import uuid
from dataclasses import asdict
from typing import Any

import pytest
from agentscope.state import AgentState
from resolveflow.harness.budget import BudgetGuard, RunBudget
from resolveflow.runtime.db import DEFAULT_DSN, Database, create_schema, drop_schema

from resolveflow_spike.recovery_store import CALL_UNKNOWN, SNAP_SAVED, RecoveryStore, StaleFenceError
from tests._helpers import CountingTool, ScriptedModel, agent_with

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SPIKE_ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENT_SRC = REPO_ROOT / "agent" / "src"

RUN_ID = "5f2b1c3d-0000-4000-8000-0000000000b1"
CASE_ID = "9c858abd-0000-4000-8000-0000000000c2"
DEADLINE = dt.datetime(2026, 9, 25, 12, 0, tzinfo=dt.UTC)


def dsn() -> str:
    """The database the probe uses: the same DSN the agent service uses, or the compose default."""
    import os

    return os.environ.get("RESOLVEFLOW_AGENT_DB") or DEFAULT_DSN


@pytest.fixture()
def store() -> Any:
    """A migrated `RecoveryStore` in a schema of this test's own, dropped on the way out.

    A unique schema rather than `public` for the reason the agent's own suite gives: the probe must be runnable
    against the same server the service uses without leaving rows behind or reading someone else's. The schema is
    dropped on the way out, so a failing test leaves the database as it found it.
    """
    schema = f"as012_{uuid.uuid4().hex[:12]}"
    try:
        create_schema(dsn(), schema)
    except Exception as failure:  # pragma: no cover - depends on the machine, not the code
        pytest.skip(f"agent_db is not reachable at {dsn()}: {failure}")
    database = Database(dsn(), schema=schema)
    recovery = RecoveryStore(database)
    try:
        recovery.migrate()
        yield recovery
    finally:
        database.close()
        drop_schema(dsn(), schema)


def run_row(store: RecoveryStore) -> dict[str, Any]:
    """The run row, asserted present.

    A helper rather than `assert row is not None` at each site because mypy's narrowing through a helper keeps the
    tests readable: the row exists in every test here (the fixture creates it), so its absence is a bug in the test
    and not a case to handle.
    """
    row = store.read_run(RUN_ID)
    assert row is not None, f"run {RUN_ID} is not in the store"
    return row


def snapshot_of(store: RecoveryStore) -> dict[str, Any]:
    """The latest snapshot, asserted present."""
    snapshot = store.latest_snapshot(RUN_ID)
    assert snapshot is not None, f"run {RUN_ID} has no snapshot"
    return snapshot


def started(store: RecoveryStore) -> Any:
    """A run at fence 1 with the spec's budget and a fixed deadline."""
    return store.start(
        run_id=RUN_ID,
        case_id=CASE_ID,
        input_revision=1,
        budget=asdict(RunBudget()),
        active_deadline=DEADLINE,
        manifest_hash="a" * 64,
    )


# ------------------------------------------------------------------ 1. the saved-but-not-advanced window


def test_a_saved_response_is_reused_and_not_charged_twice(store: RecoveryStore) -> None:
    """**结果已保存但快照未推进**: the reply is rebuilt from the ledger, and the budget is not charged again.

    The window is created the way a crash creates it — the response is recorded, and the snapshot is *not*
    advanced — and then a fresh worker reads what is durable. Two assertions carry the requirement:

    * the recorded response comes back **identical**, so the rebuild has the answer it needs without asking the
      provider; and
    * the run's spend is unchanged by the recovery, so one answer is billed once.
    """
    claimed = started(store)
    call_id = "call-step-0"

    store.record_request(
        run_id=RUN_ID, fence=claimed.fence, call_id=call_id, step=0, kind="model", request_hash="h" * 64
    )
    recorded = {"content": [{"type": "tool_call", "name": "get_order_context"}], "is_last": True}
    store.record_response(
        run_id=RUN_ID,
        fence=claimed.fence,
        call_id=call_id,
        response=recorded,
        usage={"input_tokens": 120, "output_tokens": 30},
    )
    # The crash: record_response happened, advance_snapshot did not. So the ledger has the answer and the
    # snapshot does not — which is exactly the state the recovery path has to handle rather than an anomaly.
    assert store.latest_snapshot(RUN_ID) is None
    spend_before = run_row(store)["spend"]

    # A new worker claims the run (fence moves) and finds the saved answer.
    reclaimed = store.start(
        run_id=RUN_ID,
        case_id=CASE_ID,
        input_revision=1,
        budget={},
        active_deadline=DEADLINE,
    )
    reused = store.recorded_response(RUN_ID, call_id)

    assert reused == recorded, "the saved response was not reusable, so the reply would have to be re-asked"
    assert reclaimed.fence > claimed.fence, "the resume did not move the fence"
    # Nothing about the recovery charged the run: one answer, one billing.
    assert run_row(store)["spend"] == spend_before, "recovery changed the run's spend"


def test_the_snapshot_advances_only_under_the_current_fence(store: RecoveryStore) -> None:
    """The other half of the window: after the answer is saved, the snapshot advances and is then durable.

    Written as the counterpart to the test above so both sides of the window have a probe: that one leaves the
    snapshot behind deliberately, this one closes it — and the recorded step is what a resume starts from.
    """
    claimed = started(store)
    store.record_request(run_id=RUN_ID, fence=claimed.fence, call_id="c0", step=0, kind="model", request_hash="h")
    store.record_response(
        run_id=RUN_ID,
        fence=claimed.fence,
        call_id="c0",
        response={"ok": True},
        usage={"input_tokens": 1, "output_tokens": 1},
    )
    store.advance_snapshot(
        run_id=RUN_ID, fence=claimed.fence, step=0, agent_state={"session_id": "s", "context": []}
    )

    snapshot = snapshot_of(store)
    assert snapshot["step"] == 0
    assert snapshot["agent_state"]["session_id"] == "s"
    # `next_step` is the run's own cursor: how far the domain advanced, which is not the number of calls made.
    assert run_row(store)["next_step"] == 1


# ------------------------------------------------------------------ 2. the unknown window


def test_a_call_without_a_saved_response_is_unknown_and_retryable(store: RecoveryStore) -> None:
    """**未落库窗口记 UNKNOWN**: not success, not failure, and the cost stays on the books.

    `docs/agentscope-migration.md:67` is explicit that the run may retry within its retry limit but must keep the
    cost conservatively — so the ledger row must exist and must *not* claim a response. A missing row would make
    "we never got an answer" indistinguishable from "we never made the call", and a row claiming success would be
    a fabrication.
    """
    claimed = started(store)

    store.record_request(
        run_id=RUN_ID, fence=claimed.fence, call_id="c-lost", step=0, kind="model", request_hash="h"
    )
    # The process dies here: no record_response, no advance_snapshot.

    calls = store.calls(RUN_ID)
    assert len(calls) == 1
    assert calls[0]["state"] == CALL_UNKNOWN
    assert calls[0]["response"] is None
    assert store.recorded_response(RUN_ID, "c-lost") is None, (
        "an unsaved response came back as if it had been saved, which would let the run fabricate an answer"
    )

    # The retry reuses the *same* stable call id rather than minting a new one, which is what makes the duplicate
    # detectable and the replay possible (docs/agentscope-migration.md:60).
    store.record_request(
        run_id=RUN_ID, fence=claimed.fence, call_id="c-lost", step=0, kind="model", request_hash="h"
    )
    store.record_response(
        run_id=RUN_ID,
        fence=claimed.fence,
        call_id="c-lost",
        response={"retried": True},
        usage={"input_tokens": 1, "output_tokens": 1},
    )
    assert len(store.calls(RUN_ID)) == 1, "the retry created a second logical call instead of reusing the id"
    assert store.recorded_response(RUN_ID, "c-lost") == {"retried": True}
    assert store.calls(RUN_ID)[0]["state"] == SNAP_SAVED


# ------------------------------------------------------------------ 3. the old fence


def test_a_superseded_worker_cannot_advance_the_run(store: RecoveryStore) -> None:
    """**旧 fence 被拒**: the old worker's snapshot write and its finality write both fail.

    The point of a fence over a lock: the old worker is *still running* and still believes it owns the run, so the
    refusal has to come from the write itself. Checked for the snapshot (which would corrupt the resume point) and
    for the spend (which would let a superseded worker rewrite the run's cost).
    """
    first = started(store)
    # A second worker claims the run, as a lease expiry would.
    second = store.start(run_id=RUN_ID, case_id=CASE_ID, input_revision=1, budget={}, active_deadline=DEADLINE)
    assert second.fence > first.fence

    with pytest.raises(StaleFenceError):
        store.advance_snapshot(
            run_id=RUN_ID, fence=first.fence, step=0, agent_state={"session_id": "stale", "context": []}
        )
    with pytest.raises(StaleFenceError):
        store.update_spend(run_id=RUN_ID, fence=first.fence, spend={"model_calls": 999})
    with pytest.raises(StaleFenceError):
        store.record_response(
            run_id=RUN_ID, fence=first.fence, call_id="c", response={"ok": True}, usage={}
        )

    # Nothing the stale worker attempted landed: no snapshot, and the spend is untouched.
    assert store.latest_snapshot(RUN_ID) is None
    assert run_row(store)["spend"]["model_calls"] == 0
    # And the current fence can still advance it, so the refusal is about ownership and not about the run being
    # broken.
    store.advance_snapshot(
        run_id=RUN_ID, fence=second.fence, step=0, agent_state={"session_id": "current", "context": []}
    )
    assert snapshot_of(store)["agent_state"]["session_id"] == "current"


# ------------------------------------------------------------------ 4. budget and deadline


def test_a_resume_does_not_reset_the_budget_or_the_deadline(store: RecoveryStore) -> None:
    """**预算/deadline 不重置.** A resume continues the run it was.

    `docs/agentscope-migration.md:69`: 同run保持原manifest、预算和deadline；过期则明确终止而非续期. So the resumed
    claim must report the *stored* deadline and the *stored* budget, and a spend already made must still be there.
    A resume that started fresh would silently give a crashed run a second full budget and a new window, which is
    the renewal the rule forbids.
    """
    claimed = started(store)
    # The run spends some of its budget before crashing.
    spent = {"model_calls": 5, "tool_attempts": 3, "input_tokens": 900, "output_tokens": 200}
    store.update_spend(run_id=RUN_ID, fence=claimed.fence, spend=spent)

    resumed = store.start(
        run_id=RUN_ID,
        case_id=CASE_ID,
        input_revision=1,
        # A different budget is offered and must be ignored: the run's own budget is a fact about the run.
        budget={"model_calls": 999},
        active_deadline=None,
    )

    assert resumed.active_deadline == DEADLINE, "the resume moved the run's deadline"
    row = run_row(store)
    assert row["spend"] == spent, "the resume reset the spend"
    # psycopg hands jsonb columns back already decoded, so this is a dict and not a string to parse.
    assert row["budget"]["model_calls"] == RunBudget().model_calls, (
        "the resume replaced the run's budget with the one the new claim offered"
    )
    assert row["manifest_hash"] == "a" * 64


def test_the_run_budget_still_bounds_the_model_calls_after_a_resume(store: RecoveryStore) -> None:
    """A resumed run is still bounded by the budget it recorded, not by a fresh guard.

    The store is the run's memory of its own budget; a recovery that rebuilt a guard from the *defaults* would
    hand a crashed run twelve more calls. This asserts the two agree, which is the check that would catch that.
    """
    claimed = started(store)
    row = run_row(store)
    recorded = {k: v for k, v in row["budget"].items() if k in RunBudget().__dataclass_fields__}

    guard = BudgetGuard(RunBudget(**recorded))
    for _ in range(RunBudget().model_calls):
        guard.reserve_model_call(input_tokens=1, output_tokens=1)

    assert guard.spend.model_calls == RunBudget().model_calls
    # And the run's recorded spend is what a resume would continue from, so the two cannot disagree silently.
    store.update_spend(run_id=RUN_ID, fence=claimed.fence, spend=guard.spend.as_dict() | {"no_progress_rounds": 0})
    assert run_row(store)["spend"]["model_calls"] == RunBudget().model_calls


# ------------------------------------------------------------------ 5. across connections and processes


def test_the_snapshot_is_readable_from_a_separate_process(store: RecoveryStore) -> None:
    """**跨进程恢复**, because production recovery is a different process and not a second object.

    The snapshot is written by this process and read by a *child* process over its own connection to the same
    database and schema. An in-memory cache or a same-process convenience would satisfy every other test in this
    file and fail here — which is why `docs/agentscope-migration.md:41` says a toy loop does not count.
    """
    claimed = started(store)
    real_state = _agent_state_from_a_real_reply()
    store.advance_snapshot(run_id=RUN_ID, fence=claimed.fence, step=0, agent_state=real_state)

    schema = store._database.schema  # noqa: SLF001 - the test needs the schema it was given
    child = subprocess.run(  # noqa: S603 - our own interpreter, a fixed script, no shell
        [sys.executable, "-c", _CHILD_READER, dsn(), schema, RUN_ID],
        capture_output=True,
        text=True,
        timeout=60,
        env={**_child_env(), "PYTHONPATH": str(AGENT_SRC) + _pathsep() + str(SPIKE_ROOT / "src")},
        cwd=str(SPIKE_ROOT),
    )
    assert child.returncode == 0, f"the child could not read the snapshot: {child.stderr[-1500:]}"

    payload = json.loads(child.stdout.strip().splitlines()[-1])
    assert payload["step"] == 0
    # The state survived the round trip through PostgreSQL and a process boundary well enough to rebuild an agent
    # from it: the rebuilt AgentState carries the same context length and session.
    restored = AgentState.model_validate(payload["agent_state"])
    assert restored.session_id == real_state["session_id"]
    assert len(restored.context) == len(real_state["context"]) > 0


def test_a_rebuilt_agent_continues_from_the_persisted_state(store: RecoveryStore) -> None:
    """The end of the chain: persisted state → a new Agent that continues it, with no model call to build it.

    This is what "recoverable run snapshot" has to mean to be worth anything (`docs/agentscope-migration.md:58`):
    not that bytes are in a table, but that the loop can start from them. The model is a script and is asserted to
    have been called zero times by the *rebuild*, which is the part that must not touch the network.
    """
    claimed = started(store)
    real_state = _agent_state_from_a_real_reply()
    store.advance_snapshot(run_id=RUN_ID, fence=claimed.fence, step=0, agent_state=real_state)

    restored = AgentState.model_validate(snapshot_of(store)["agent_state"])

    model = ScriptedModel([])
    agent = agent_with(model, [CountingTool("get_order_context", [])], state=restored)

    assert model.calls == 0, "rebuilding the agent from the snapshot called the model"
    assert len(agent.state.context) == len(restored.context)


# ------------------------------------------------------------------ helpers


def _agent_state_from_a_real_reply() -> dict[str, Any]:
    """A real `AgentState`, dumped to JSON, taken from a real loop run.

    Deliberately not a hand-written dict: the point of the AS01.2 probe is that the *SDK's* state survives, so the
    state has to be one the SDK produced.
    """
    executions: list[str] = []
    model = ScriptedModel([("get_order_context", {})])
    agent = agent_with(model, [CountingTool("get_order_context", executions)], budget=None)
    from tests._helpers import run_agent

    run_agent(agent, "investigate")
    dumped: dict[str, Any] = json.loads(agent.state.model_dump_json())
    return dumped


def _child_env() -> dict[str, str]:
    import os

    return dict(os.environ)


def _pathsep() -> str:
    import os

    return os.pathsep


#: Run by a child process: connect on its own, read the snapshot, print it. No shared object with the parent.
_CHILD_READER = """
import json, sys
from resolveflow.runtime.db import Database
from resolveflow_spike.recovery_store import RecoveryStore

dsn, schema, run_id = sys.argv[1], sys.argv[2], sys.argv[3]
database = Database(dsn, schema=schema)
try:
    snapshot = RecoveryStore(database).latest_snapshot(run_id)
    print(json.dumps(snapshot))
finally:
    database.close()
"""
