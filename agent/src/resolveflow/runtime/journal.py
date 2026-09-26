"""Fenced domain snapshots and recorded tool observations for SDK reconstruction."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from resolveflow.harness.budget import BudgetExhaustedError, BudgetGuard, RunBudget, RunSpend
from resolveflow.runtime.recovery_store import RecoveryBudgetStore, RecoveryConflictError, _locked_run


class RunJournal(RecoveryBudgetStore):
    def bind(self, run_id: str, *, fence: int, owner: str, manifest: dict[str, Any], budget: RunBudget) -> None:
        self.initialize(run_id, fence=fence, owner=owner, manifest_id=manifest["manifest_id"], budget=budget)
        with self.database.connection() as connection, connection.transaction():
            _locked_run(connection, run_id, fence=fence, owner=owner)
            row = connection.execute("SELECT manifest FROM agent_run_model_budget WHERE run_id=%s",
                                     (run_id,)).fetchone()
            assert row is not None
            if row["manifest"] is not None and row["manifest"] != manifest:
                raise RecoveryConflictError("MIGRATION_REQUIRED: manifest/state version mismatch")
            connection.execute("UPDATE agent_run_model_budget SET manifest=%s WHERE run_id=%s",
                               (Jsonb(manifest), run_id))

    def read(self, run_id: str, *, fence: int, owner: str, call_id: str,
             tool: bool = False) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        with self.database.connection() as connection, connection.transaction():
            run = _locked_run(connection, run_id, fence=fence, owner=owner)
            if tool:
                row = connection.execute("SELECT * FROM agent_tool_call WHERE run_id=%s AND call_id=%s",
                                         (run_id, call_id)).fetchone()
            else:
                row = connection.execute("SELECT * FROM agent_model_call WHERE run_id=%s AND call_id=%s",
                                         (run_id, call_id)).fetchone()
            return row, dict(run["budget_spent"])

    def reserve_tool(self, run_id: str, *, fence: int, owner: str, call_id: str, request_hash: str,
                     local: bool) -> dict[str, Any]:
        with self.database.connection() as connection, connection.transaction():
            run = _locked_run(connection, run_id, fence=fence, owner=owner)
            frozen = connection.execute("SELECT * FROM agent_run_model_budget WHERE run_id=%s",
                                        (run_id,)).fetchone()
            assert frozen is not None
            if frozen["stop_reason"]:
                raise BudgetExhaustedError(frozen["stop_reason"], "run stopped")
            old = connection.execute("SELECT * FROM agent_tool_call WHERE run_id=%s AND call_id=%s",
                                     (run_id, call_id)).fetchone()
            if old is not None:
                if old["request_hash"] != request_hash or old["local_read"] != local:
                    raise RecoveryConflictError("recorded tool request mismatch")
                if old["observation"] is not None:
                    return dict(old["after_spend"])
                if old["attempts"] >= 3:
                    raise BudgetExhaustedError("TOOL_RETRIES_EXHAUSTED", "tool retry allowance exhausted")
            before = dict(run["budget_spent"])
            guard = BudgetGuard(RunBudget(**frozen["budget"]), RunSpend(**before), run["active_deadline_at"])
            guard.reserve_tool_attempt()
            if local:
                guard.reserve_local_read()
            after = guard.spend.as_dict()
            connection.execute(
                "INSERT INTO agent_tool_call(run_id,call_id,request_hash,local_read,before_spend,after_spend) "
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(run_id,call_id) DO UPDATE SET "
                "attempts=agent_tool_call.attempts+1,before_spend=EXCLUDED.before_spend,after_spend=EXCLUDED.after_spend",
                (run_id, call_id, request_hash, local, Jsonb(before), Jsonb(after)),
            )
            connection.execute("UPDATE agent_run SET budget_spent=%s WHERE run_id=%s", (Jsonb(after), run_id))
            return after

    def save_tool(self, run_id: str, *, fence: int, owner: str, call_id: str,
                  observation: dict[str, Any]) -> None:
        with self.database.connection() as connection, connection.transaction():
            _locked_run(connection, run_id, fence=fence, owner=owner)
            row = connection.execute("SELECT observation FROM agent_tool_call WHERE run_id=%s AND call_id=%s",
                                     (run_id, call_id)).fetchone()
            if row is None or (row["observation"] is not None and row["observation"] != observation):
                raise RecoveryConflictError("tool result has no reservation or conflicts")
            connection.execute("UPDATE agent_tool_call SET observation=%s WHERE run_id=%s AND call_id=%s",
                               (Jsonb(observation), run_id, call_id))
