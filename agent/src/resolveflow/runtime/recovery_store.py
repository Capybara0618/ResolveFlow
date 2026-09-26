"""C09 pre-network reservations, serialized on the run row and checked under its fence.

The store cannot claim runs or authorize an UNKNOWN retry. Its caller must already
own a live lease. A repeated call_id returns the original reservation with
new_reservation=False; it is a lookup, never permission to send another request.
Response saving, retry-attempt charging and SDK integration are later C09 slices.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from resolveflow.harness.budget import BudgetGuard, RunBudget, RunSpend
from resolveflow.runtime.db import Database
from resolveflow.runtime.recovery_budget import RecoveryCallBudget


class StaleFenceError(RuntimeError):
    """Caller no longer owns an active run/lease; stop writing and calling out."""


class RecoveryConflictError(RuntimeError):
    """The frozen manifest/budget or stable call request does not match."""


@dataclass(frozen=True, slots=True)
class ModelReservation:
    call_id: str
    output_ceiling: int
    state: str
    new_reservation: bool


def _locked_run(connection: psycopg.Connection[dict[str, Any]], run_id: str, *, fence: int,
                owner: str) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM agent_run WHERE run_id=%s FOR UPDATE", (run_id,)).fetchone()
    # Read the database clock after acquiring the row lock: lock waiting consumes lease/deadline time.
    clock = connection.execute("SELECT clock_timestamp() AS now").fetchone()
    assert clock is not None
    now = clock["now"]
    if (
        row is None or row["status"] != "RUNNING" or row["cancelled_at"] is not None
        or row["fence"] != fence or row["lease_owner"] != owner
        or row["lease_until"] is None or row["lease_until"] <= now
        or row["active_deadline_at"] is None or row["active_deadline_at"] <= now
    ):
        raise StaleFenceError("run is inactive, expired or owned by a different fence/worker")
    return row


class RecoveryBudgetStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def initialize(self, run_id: str, *, fence: int, owner: str, manifest_id: str, budget: RunBudget) -> None:
        if not manifest_id or not owner:
            raise ValueError("manifest and lease owner are required")
        partition = RecoveryCallBudget(total_limit=budget.model_calls,
                                       recovery_reserve=min(2, budget.model_calls))
        frozen = asdict(budget)
        with self.database.connection() as connection, connection.transaction():
            run = _locked_run(connection, run_id, fence=fence, owner=owner)
            previous = connection.execute("SELECT * FROM agent_run_model_budget WHERE run_id=%s",
                                          (run_id,)).fetchone()
            if previous is not None:
                if previous["manifest_id"] != manifest_id or previous["budget"] != frozen:
                    raise RecoveryConflictError("frozen manifest or budget mismatch; migration required")
                return
            if any(run["budget_spent"].values()):
                raise RecoveryConflictError("cannot initialize a partition over unclassified existing spend")
            connection.execute(
                "INSERT INTO agent_run_model_budget(run_id,manifest_id,budget,call_partition) VALUES (%s,%s,%s,%s)",
                (run_id, manifest_id, Jsonb(frozen), Jsonb(partition.as_dict())),
            )

    def reserve(self, run_id: str, *, fence: int, owner: str, call_id: str, request_hash: str,
                kind: str, input_tokens: int) -> ModelReservation:
        if not isinstance(call_id, str) or not 1 <= len(call_id) <= 200:
            raise ValueError("call_id must be 1-200 characters")
        if not re.fullmatch(r"[a-f0-9]{64}", request_hash):
            raise ValueError("request_hash must be canonical SHA-256")
        if type(input_tokens) is not int or input_tokens < 0:
            raise ValueError("input_tokens must be a non-negative integer")
        with self.database.connection() as connection, connection.transaction():
            run = _locked_run(connection, run_id, fence=fence, owner=owner)
            frozen = connection.execute("SELECT * FROM agent_run_model_budget WHERE run_id=%s",
                                        (run_id,)).fetchone()
            if frozen is None:
                raise RecoveryConflictError("run budget is not initialized")
            prior = connection.execute("SELECT * FROM agent_model_call WHERE run_id=%s AND call_id=%s",
                                       (run_id, call_id)).fetchone()
            if prior is not None:
                if (prior["request_hash"], prior["kind"], prior["reserved_input"]) != (
                    request_hash, kind, input_tokens,
                ):
                    raise RecoveryConflictError("stable call_id reused for a different request")
                return ModelReservation(call_id, int(prior["reserved_output"]), str(prior["state"]), False)
            partition = RecoveryCallBudget.from_dict(frozen["call_partition"])
            spend = RunSpend(**run["budget_spent"])
            if partition.total_spent != spend.model_calls:
                raise RecoveryConflictError("persisted call partition and spend disagree")
            next_partition = partition.reserve(kind)
            guard = BudgetGuard(RunBudget(**frozen["budget"]), spend=spend,
                                active_deadline=run["active_deadline_at"])
            ceiling = guard.reserve_model_request(input_tokens=input_tokens)
            connection.execute(
                "INSERT INTO agent_model_call(run_id,call_id,kind,request_hash,reserved_input,reserved_output,"
                "state,created_at) VALUES (%s,%s,%s,%s,%s,%s,'UNKNOWN',now())",
                (run_id, call_id, kind, request_hash, input_tokens, ceiling),
            )
            connection.execute("UPDATE agent_run_model_budget SET call_partition=%s WHERE run_id=%s",
                               (Jsonb(next_partition.as_dict()), run_id))
            connection.execute("UPDATE agent_run SET budget_spent=%s,updated_at=now(),version=version+1 "
                               "WHERE run_id=%s", (Jsonb(spend.as_dict()), run_id))
            return ModelReservation(call_id, ceiling, "UNKNOWN", True)
