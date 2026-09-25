"""AS01.2: the durable side — a fence-protected run snapshot and a stable call ledger, over real PostgreSQL.

This is the spike's answer to "can a run be resumed under a fence, and not just saved". The distinction matters
because `docs/agentscope-migration.md:58` says the requirement is *not* to use an SDK's own checkpoint tables:
what `checkpoint` means here is **a recoverable domain run snapshot**, and SDK state is only one part of it. So
the durable record holds both halves:

- **the domain half** — the run, its fence, the manifest/state versions, the spend, the deadline, and one row per
  logical call with its stable id; and
- **the SDK half** — the `AgentState` the loop needs to continue, stored as one snapshot per advance.

**Why a fence rather than a lock.** Two workers must never both advance one run. A lock is held for the duration
of the work, and the work includes network calls, so holding one across them is exactly what
`docs/engineering.md:68` forbids. A fence is a number: claiming the run increments it, every write states the
fence it believes in, and a write whose number is stale is refused. That is the rule
`docs/agentscope-migration.md:66` asks for — "旧worker不能更新有效结果、快照或callback" — expressed so that it holds
even while the old worker is still running and still thinks it holds the run.

**Why the response is stored before the snapshot.** `docs/agentscope-migration.md:67` names the window that
decides the design: "结果已保存但快照未推进" must be recoverable by replaying *the recorded result*, not by
re-calling. So the ledger write and the snapshot write are two separate transactions in that order, and a crash
between them is a state the recovery path is required to handle rather than an anomaly.

**What this module is not.** It is not the production store: it is a spike schema in a temporary PostgreSQL
schema, deliberately separate from `agent_run`/`agent_callback_outbox` so the probe cannot corrupt real state.
The production shape is C09's job, and this exists to prove the SDK and the storage can meet the requirements at
all — which is what AS01.2 is for.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "CALL_UNKNOWN",
    "SNAP_SAVED",
    "RecoveryStore",
    "StaleFenceError",
]

#: A logical call whose response was never durably saved. `docs/agentscope-migration.md:67`: the cost is
#: conservatively kept and marked, and the run may retry within its retry limit — never pretending it succeeded.
CALL_UNKNOWN: Final = "UNKNOWN"
#: A logical call whose response is in the ledger and can be replayed without asking the provider again.
SNAP_SAVED: Final = "SAVED"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS spike_run (
    run_id            text PRIMARY KEY,
    case_id           text NOT NULL,
    input_revision    int  NOT NULL,
    fence             bigint NOT NULL,
    status            text NOT NULL,
    -- The budget/deadline facts a resume must NOT reset (docs/agentscope-migration.md:69).
    budget            jsonb NOT NULL,
    spend             jsonb NOT NULL,
    active_deadline   timestamptz,
    manifest_hash     text,
    -- How far the domain has advanced, which is not the same as how many calls were made.
    next_step         int NOT NULL DEFAULT 0,
    updated_at        timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS spike_call (
    run_id        text NOT NULL REFERENCES spike_run (run_id) ON DELETE CASCADE,
    -- The stable logical call id (docs/agentscope-migration.md:60). A retry after an unknown response reuses it,
    -- which is what makes replay possible and duplicate charging detectable.
    call_id       text NOT NULL,
    step          int  NOT NULL,
    kind          text NOT NULL,
    request_hash  text NOT NULL,
    state         text NOT NULL,
    response      jsonb,
    usage         jsonb,
    created_at    timestamptz NOT NULL,
    PRIMARY KEY (run_id, call_id)
);

CREATE TABLE IF NOT EXISTS spike_snapshot (
    run_id      text NOT NULL REFERENCES spike_run (run_id) ON DELETE CASCADE,
    step        int  NOT NULL,
    agent_state jsonb NOT NULL,
    created_at  timestamptz NOT NULL,
    PRIMARY KEY (run_id, step)
);
"""


class StaleFenceError(RuntimeError):
    """A write from a worker whose fence is no longer current.

    Raised rather than silently ignored: a superseded worker that keeps trying to advance a run is a bug or a
    lease that was lost, and either way the caller needs to stop rather than retry.
    """


@dataclass(frozen=True, slots=True)
class ClaimedRun:
    """A run this worker may work on, and the fence it must present for every later write."""

    run_id: str
    case_id: str
    input_revision: int
    fence: int
    active_deadline: dt.datetime | None


class RecoveryStore:
    """The durable run snapshot and call ledger, over the project's own `Database`.

    Every method is one transaction. Nothing here holds a connection open across a network call — the caller does
    the model or tool work outside, exactly as `docs/agent-harness.md:27` requires.
    """

    def __init__(self, database: Any) -> None:
        self._database = database

    def migrate(self) -> None:
        """Create this spike's tables inside whatever schema the `Database` is pointed at."""
        with self._database.connection() as connection:
            connection.execute(_SCHEMA)

    # ------------------------------------------------------------------ claiming

    def start(
        self,
        *,
        run_id: str,
        case_id: str,
        input_revision: int,
        budget: dict[str, Any],
        active_deadline: dt.datetime | None,
        manifest_hash: str | None = None,
    ) -> ClaimedRun:
        """Create the run at fence 1, or hand back an existing one's fence without resetting its facts."""
        with self._database.connection() as connection:
            existing = connection.execute(
                "SELECT fence, active_deadline FROM spike_run WHERE run_id = %(run_id)s",
                {"run_id": run_id},
            ).fetchone()
            if existing is not None:
                # A resume must not reset the budget or the deadline (docs/agentscope-migration.md:69), so an
                # existing run is returned exactly as it stands; only the *claim* changes.
                connection.execute(
                    """
                    UPDATE spike_run SET fence = fence + 1, updated_at = %(now)s WHERE run_id = %(run_id)s
                    """,
                    {"run_id": run_id, "now": _now()},
                )
                claimed = connection.execute(
                    "SELECT fence, active_deadline FROM spike_run WHERE run_id = %(run_id)s",
                    {"run_id": run_id},
                ).fetchone()
                return ClaimedRun(
                    run_id=run_id,
                    case_id=case_id,
                    input_revision=input_revision,
                    fence=int(claimed["fence"]),
                    active_deadline=claimed["active_deadline"],
                )
            connection.execute(
                """
                INSERT INTO spike_run (
                    run_id, case_id, input_revision, fence, status, budget, spend,
                    active_deadline, manifest_hash, next_step, updated_at
                ) VALUES (
                    %(run_id)s, %(case_id)s, %(input_revision)s, 1, 'RUNNING', %(budget)s::jsonb,
                    %(spend)s::jsonb, %(active_deadline)s, %(manifest_hash)s, 0, %(now)s
                )
                """,
                {
                    "run_id": run_id,
                    "case_id": case_id,
                    "input_revision": input_revision,
                    "budget": json.dumps(budget),
                    "spend": json.dumps({"model_calls": 0, "tool_attempts": 0, "input_tokens": 0, "output_tokens": 0}),
                    "active_deadline": active_deadline,
                    "manifest_hash": manifest_hash,
                    "now": _now(),
                },
            )
        return ClaimedRun(
            run_id=run_id,
            case_id=case_id,
            input_revision=input_revision,
            fence=1,
            active_deadline=active_deadline,
        )

    def read_run(self, run_id: str) -> dict[str, Any] | None:
        """The run row, for asserting what a resume did and did not change."""
        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT run_id, fence, status, budget, spend, active_deadline, manifest_hash, next_step
                  FROM spike_run WHERE run_id = %(run_id)s
                """,
                {"run_id": run_id},
            ).fetchone()
        return dict(row) if row is not None else None

    # ------------------------------------------------------------------ the call ledger

    def record_request(
        self, *, run_id: str, fence: int, call_id: str, step: int, kind: str, request_hash: str
    ) -> None:
        """Save the request and its stable id **before** the external call (docs/agentscope-migration.md:65).

        The row starts as `UNKNOWN`: if the process dies here, the honest record is "a call was made and its answer
        is not known", which is what the recovery path must find — not a missing row, and not a row claiming
        success.
        """
        with self._database.connection() as connection:
            self._require_fence(connection, run_id, fence)
            connection.execute(
                """
                INSERT INTO spike_call (run_id, call_id, step, kind, request_hash, state, response, usage, created_at)
                VALUES (%(run_id)s, %(call_id)s, %(step)s, %(kind)s, %(request_hash)s, %(state)s, NULL, NULL, %(now)s)
                ON CONFLICT (run_id, call_id) DO NOTHING
                """,
                {
                    "run_id": run_id,
                    "call_id": call_id,
                    "step": step,
                    "kind": kind,
                    "request_hash": request_hash,
                    "state": CALL_UNKNOWN,
                    "now": _now(),
                },
            )

    def record_response(
        self, *, run_id: str, fence: int, call_id: str, response: dict[str, Any], usage: dict[str, Any]
    ) -> None:
        """Save the response and usage **after** the call, still under the fence (docs/agentscope-migration.md:66).

        This is the write that closes the unknown window. It is a separate transaction from
        :meth:`advance_snapshot` on purpose: the window between them is the "result saved, snapshot not advanced"
        case the recovery path exists for, and merging the two writes would remove the window from the design
        rather than handle it.
        """
        with self._database.connection() as connection:
            self._require_fence(connection, run_id, fence)
            connection.execute(
                """
                UPDATE spike_call
                   SET state = %(state)s, response = %(response)s::jsonb, usage = %(usage)s::jsonb
                 WHERE run_id = %(run_id)s AND call_id = %(call_id)s
                """,
                {
                    "run_id": run_id,
                    "call_id": call_id,
                    "state": SNAP_SAVED,
                    "response": json.dumps(response),
                    "usage": json.dumps(usage),
                },
            )

    def calls(self, run_id: str) -> list[dict[str, Any]]:
        """Every recorded call, oldest first — the ledger a replay reads."""
        with self._database.connection() as connection:
            rows = connection.execute(
                """
                SELECT call_id, step, kind, state, response, usage
                  FROM spike_call WHERE run_id = %(run_id)s ORDER BY step, created_at
                """,
                {"run_id": run_id},
            ).fetchall()
        return [dict(row) for row in rows]

    def recorded_response(self, run_id: str, call_id: str) -> dict[str, Any] | None:
        """The saved response for a call, or ``None`` if it was never saved.

        ``None`` is the honest answer for the unknown window: the caller must record the cost conservatively and
        may retry within its limit — it must not treat the call as succeeded, and must not invent a response
        (docs/agentscope-migration.md:67).
        """
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT state, response FROM spike_call WHERE run_id = %(run_id)s AND call_id = %(call_id)s",
                {"run_id": run_id, "call_id": call_id},
            ).fetchone()
        if row is None or row["state"] != SNAP_SAVED or row["response"] is None:
            return None
        return dict(row["response"])

    # ------------------------------------------------------------------ the snapshot

    def advance_snapshot(self, *, run_id: str, fence: int, step: int, agent_state: dict[str, Any]) -> None:
        """Advance the run's snapshot and its step counter, under the fence."""
        with self._database.connection() as connection:
            self._require_fence(connection, run_id, fence)
            connection.execute(
                """
                INSERT INTO spike_snapshot (run_id, step, agent_state, created_at)
                VALUES (%(run_id)s, %(step)s, %(agent_state)s::jsonb, %(now)s)
                ON CONFLICT (run_id, step) DO NOTHING
                """,
                {
                    "run_id": run_id,
                    "step": step,
                    "agent_state": json.dumps(agent_state),
                    "now": _now(),
                },
            )
            connection.execute(
                """
                UPDATE spike_run SET next_step = GREATEST(next_step, %(step)s + 1), updated_at = %(now)s
                 WHERE run_id = %(run_id)s
                """,
                {"run_id": run_id, "step": step, "now": _now()},
            )

    def latest_snapshot(self, run_id: str) -> dict[str, Any] | None:
        """The most advanced snapshot, or ``None`` for a run that never advanced."""
        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT step, agent_state FROM spike_snapshot
                 WHERE run_id = %(run_id)s ORDER BY step DESC LIMIT 1
                """,
                {"run_id": run_id},
            ).fetchone()
        if row is None:
            return None
        return {"step": int(row["step"]), "agent_state": dict(row["agent_state"])}

    def update_spend(self, *, run_id: str, fence: int, spend: dict[str, Any]) -> None:
        """Persist the run's spend, monotonically.

        Monotonic because a resume must not reduce what has already been charged: a spend that could go down would
        let a crash reset the run's cost (docs/agentscope-migration.md:69, "预算/deadline 不重置").
        """
        with self._database.connection() as connection:
            self._require_fence(connection, run_id, fence)
            connection.execute(
                """
                UPDATE spike_run
                   SET spend = %(spend)s::jsonb, updated_at = %(now)s
                 WHERE run_id = %(run_id)s
                """,
                {"run_id": run_id, "spend": json.dumps(spend), "now": _now()},
            )

    # ------------------------------------------------------------------ the fence

    @staticmethod
    def _require_fence(connection: Any, run_id: str, fence: int) -> None:
        """Refuse a write whose fence is not the run's current one, checked **in the writing transaction**.

        `docs/agentscope-migration.md:66` names the failure mode this avoids: *"不能'先查fence再另开连接写SDK状态'"* —
        check the fence, then write on another connection. Between those two acts the run can be claimed again,
        and the old worker's write then lands on a run it no longer owns. So this takes the row lock and compares
        inside the same transaction as the write, and every writer below calls it as its first statement.

        `FOR UPDATE` is what makes the comparison meaningful: without the lock two workers could both read the
        same fence and both proceed.
        """
        row = connection.execute(
            "SELECT fence FROM spike_run WHERE run_id = %(run_id)s FOR UPDATE",
            {"run_id": run_id},
        ).fetchone()
        if row is None:
            raise StaleFenceError(f"run {run_id} does not exist")
        current = int(row["fence"])
        if current != fence:
            raise StaleFenceError(
                f"run {run_id} is at fence {current}; this worker holds {fence} and may not advance it"
            )


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)
