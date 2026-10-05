"""C09 pre-network reservations, serialized on the run row and checked under its fence.

The store cannot claim runs. Its caller must already own a live lease.
A repeated call_id returns the original reservation with
new_reservation=False; it is a lookup, never permission to send another request.
Saved explicit replies and usage are committed once under the same fence. Only an
explicit reserve_retry may charge a new UNKNOWN attempt. SDK/checkpoint integration is a later C09 slice.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from resolveflow.harness.budget import (
    REASON_BUDGET_INPUT_TOKENS,
    REASON_BUDGET_OUTPUT_TOKENS,
    BudgetExhaustedError,
    BudgetGuard,
    RunBudget,
    RunSpend,
)
from resolveflow.harness.context import hash_document
from resolveflow.harness.live_model import ModelUnavailableError
from resolveflow.harness.model import ModelReply, ModelUsage
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
    attempt_no: int = 0


@dataclass(frozen=True, slots=True)
class SavedModelResult:
    reply: ModelReply
    stop_reason: str | None
    new_result: bool


def _saved_result(row: dict[str, Any], *, new_result: bool = False) -> SavedModelResult:
    body = row["response"]
    if row["state"] != "SAVED" or not isinstance(body, dict):
        raise RecoveryConflictError("saved call has no recoverable explicit response")
    return SavedModelResult(
        ModelReply(decision=body["decision"], usage=ModelUsage(**body["usage"]),
                   mode=body["mode"], model_alias=body["model_alias"]),
        row.get("run_stop_reason") or row["stop_reason"], new_result,
    )


def _response_document(reply: ModelReply) -> dict[str, Any]:
    usage = reply.usage
    if (
        type(usage.input_tokens) is not int or usage.input_tokens < 0
        or type(usage.output_tokens) is not int or usage.output_tokens < 0
        or type(usage.estimated) is not bool or reply.mode not in ("live", "mock")
        or not isinstance(reply.decision, dict)
        or (reply.model_alias is not None and not isinstance(reply.model_alias, str))
    ):
        raise ValueError("invalid explicit reply or token usage")
    body = asdict(reply)
    if len(json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 65536:
        raise ValueError("explicit model reply exceeds 64KiB")
    return body


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
                kind: str, input_tokens: int, request_body: dict[str, Any] | None = None,
                replay_spend: dict[str, Any] | None = None, sdk_state: dict[str, Any] | None = None,
                ceiling_parameter: str = "max_tokens") -> ModelReservation:
        if not isinstance(call_id, str) or not 1 <= len(call_id) <= 200:
            raise ValueError("call_id must be 1-200 characters")
        if not re.fullmatch(r"[a-f0-9]{64}", request_hash):
            raise ValueError("request_hash must be canonical SHA-256")
        if type(input_tokens) is not int or input_tokens < 0:
            raise ValueError("input_tokens must be a non-negative integer")
        if request_body is not None and hash_document(request_body) != request_hash:
            raise RecoveryConflictError("provider request hash mismatch")
        with self.database.connection() as connection, connection.transaction():
            run = _locked_run(connection, run_id, fence=fence, owner=owner)
            frozen = connection.execute("SELECT * FROM agent_run_model_budget WHERE run_id=%s",
                                        (run_id,)).fetchone()
            if frozen is None:
                raise RecoveryConflictError("run budget is not initialized")
            if frozen["stop_reason"] is not None:
                raise BudgetExhaustedError(frozen["stop_reason"], "prior provider usage exceeded the run reservation")
            prior = connection.execute("SELECT * FROM agent_model_call WHERE run_id=%s AND call_id=%s",
                                       (run_id, call_id)).fetchone()
            if prior is not None:
                if (prior["request_hash"], prior["kind"], prior["reserved_input"]) != (
                    request_hash, kind, input_tokens,
                ):
                    raise RecoveryConflictError("stable call_id reused for a different request")
                return ModelReservation(call_id, int(prior["reserved_output"]), str(prior["state"]), False,
                                        int(prior["current_attempt"]))
            partition = RecoveryCallBudget.from_dict(frozen["call_partition"])
            spend = RunSpend(**run["budget_spent"])
            if partition.total_spent != spend.model_calls:
                raise RecoveryConflictError("persisted call partition and spend disagree")
            next_partition = partition.reserve(kind)
            guard = BudgetGuard(RunBudget(**frozen["budget"]), spend=spend,
                                active_deadline=run["active_deadline_at"])
            ceiling = guard.reserve_model_request(input_tokens=input_tokens)
            if request_body is not None and request_body.get(ceiling_parameter) != ceiling:
                raise RecoveryConflictError("provider request output ceiling mismatch")
            connection.execute(
                "INSERT INTO agent_model_call(run_id,call_id,kind,request_hash,reserved_input,reserved_output,"
                "state,created_at) VALUES (%s,%s,%s,%s,%s,%s,'UNKNOWN',now())",
                (run_id, call_id, kind, request_hash, input_tokens, ceiling),
            )
            connection.execute(
                "UPDATE agent_model_call SET request_body=%s,replay_spend=%s,sdk_state=%s "
                "WHERE run_id=%s AND call_id=%s",
                (Jsonb(request_body), Jsonb(replay_spend), Jsonb(sdk_state), run_id, call_id),
            )
            connection.execute(
                "INSERT INTO agent_model_attempt(run_id,call_id,attempt_no,reserved_fence,reserved_input,"
                "reserved_output,state,created_at) VALUES (%s,%s,0,%s,%s,%s,'UNKNOWN',now())",
                (run_id, call_id, fence, input_tokens, ceiling),
            )
            connection.execute("UPDATE agent_run_model_budget SET call_partition=%s WHERE run_id=%s",
                               (Jsonb(next_partition.as_dict()), run_id))
            connection.execute("UPDATE agent_run SET budget_spent=%s,updated_at=now(),version=version+1 "
                               "WHERE run_id=%s", (Jsonb(spend.as_dict()), run_id))
            return ModelReservation(call_id, ceiling, "UNKNOWN", True)

    def reserve_retry(self, run_id: str, *, fence: int, owner: str, call_id: str,
                      request_hash: str, expected_attempt: int) -> ModelReservation:
        """Reserve at most one explicit retry. Repeated intent is a lookup, not another transmission permit."""
        if type(expected_attempt) is not int or expected_attempt not in (0, 1):
            raise ValueError("expected_attempt must identify the original or first retry")
        with self.database.connection() as connection, connection.transaction():
            run = _locked_run(connection, run_id, fence=fence, owner=owner)
            frozen = connection.execute("SELECT * FROM agent_run_model_budget WHERE run_id=%s",
                                        (run_id,)).fetchone()
            row = connection.execute("SELECT * FROM agent_model_call WHERE run_id=%s AND call_id=%s",
                                     (run_id, call_id)).fetchone()
            if frozen is None or row is None:
                raise RecoveryConflictError("retry has no prior call reservation")
            if row["request_hash"] != request_hash:
                raise RecoveryConflictError("retry request differs from the frozen logical call")
            if row["state"] == "SAVED":
                raise RecoveryConflictError("saved result must be reused instead of retried")
            if frozen["stop_reason"] is not None:
                raise BudgetExhaustedError(frozen["stop_reason"], "run is stopped after provider overage")
            if expected_attempt == 1:
                raise RecoveryConflictError("model retry allowance exhausted")
            if row["current_attempt"] == 1:
                return ModelReservation(call_id, int(row["reserved_output"]), "UNKNOWN", False, 1)
            if run["model_retry_after"] is not None:
                clock = connection.execute("SELECT clock_timestamp() AS now").fetchone()
                assert clock is not None
                if run["model_retry_after"] > clock["now"]:
                    raise ModelUnavailableError("persisted model retry cooldown has not elapsed")
            partition = RecoveryCallBudget.from_dict(frozen["call_partition"])
            spend = RunSpend(**run["budget_spent"])
            if partition.total_spent != spend.model_calls:
                raise RecoveryConflictError("persisted call partition and spend disagree")
            next_partition = partition.reserve(row["kind"])
            guard = BudgetGuard(RunBudget(**frozen["budget"]), spend=spend,
                                active_deadline=run["active_deadline_at"])
            # Exact request reuse requires the original output ceiling. No silent shrinking/hash mismatch.
            guard.reserve_model_call(input_tokens=row["reserved_input"], output_tokens=row["reserved_output"])
            connection.execute(
                "INSERT INTO agent_model_attempt(run_id,call_id,attempt_no,reserved_fence,reserved_input,"
                "reserved_output,state,created_at) VALUES (%s,%s,1,%s,%s,%s,'UNKNOWN',now())",
                (run_id, call_id, fence, row["reserved_input"], row["reserved_output"]),
            )
            connection.execute("UPDATE agent_model_call SET current_attempt=1 WHERE run_id=%s AND call_id=%s",
                               (run_id, call_id))
            connection.execute("UPDATE agent_run_model_budget SET call_partition=%s WHERE run_id=%s",
                               (Jsonb(next_partition.as_dict()), run_id))
            connection.execute("UPDATE agent_run SET budget_spent=%s,updated_at=now(),version=version+1 "
                               "WHERE run_id=%s", (Jsonb(spend.as_dict()), run_id))
            return ModelReservation(call_id, int(row["reserved_output"]), "UNKNOWN", True, 1)

    def recorded_result(self, run_id: str, *, fence: int, owner: str,
                        call_id: str) -> SavedModelResult | None:
        """Read a saved result without charging or writing a checkpoint; UNKNOWN is never an answer."""
        with self.database.connection() as connection, connection.transaction():
            _locked_run(connection, run_id, fence=fence, owner=owner)
            row = connection.execute(
                "SELECT c.*,b.stop_reason AS run_stop_reason FROM agent_model_call c "
                "JOIN agent_run_model_budget b ON b.run_id=c.run_id WHERE c.run_id=%s AND c.call_id=%s",
                (run_id, call_id),
            ).fetchone()
            if row is None:
                raise RecoveryConflictError("call has no reservation")
            return None if row["state"] == "UNKNOWN" else _saved_result(row)

    def save_result(self, run_id: str, *, fence: int, owner: str, call_id: str,
                    reply: ModelReply, attempt_no: int = 0) -> SavedModelResult:
        """Commit response and actual/estimated usage once. Caller must stop before actions if stop_reason is set."""
        body = _response_document(reply)
        with self.database.connection() as connection, connection.transaction():
            run = _locked_run(connection, run_id, fence=fence, owner=owner)
            row = connection.execute(
                "SELECT c.*,b.stop_reason AS run_stop_reason FROM agent_model_call c "
                "JOIN agent_run_model_budget b ON b.run_id=c.run_id WHERE c.run_id=%s AND c.call_id=%s",
                (run_id, call_id),
            ).fetchone()
            if row is None:
                raise RecoveryConflictError("result has no prior call reservation")
            if type(attempt_no) is not int or row["current_attempt"] != attempt_no:
                raise RecoveryConflictError("response is not from the current attempt")
            if row["state"] == "SAVED":
                if row["response"] != body:
                    raise RecoveryConflictError("stable call already has a different saved result")
                return _saved_result(row)
            attempt = connection.execute(
                "SELECT * FROM agent_model_attempt WHERE run_id=%s AND call_id=%s AND attempt_no=%s",
                (run_id, call_id, attempt_no),
            ).fetchone()
            if attempt is None or attempt["reserved_fence"] != fence:
                raise RecoveryConflictError("attempt was not reserved under the current fence")
            frozen = connection.execute("SELECT * FROM agent_run_model_budget WHERE run_id=%s",
                                        (run_id,)).fetchone()
            if frozen is None:
                raise RecoveryConflictError("run budget is not initialized")
            spend = RunSpend(**run["budget_spent"])
            budget = RunBudget(**frozen["budget"])
            usage = reply.usage
            charged_input = (
                max(attempt["reserved_input"], usage.input_tokens) if usage.estimated else usage.input_tokens
            )
            charged_output = (
                max(attempt["reserved_output"], usage.output_tokens) if usage.estimated else usage.output_tokens
            )
            spend.input_tokens += charged_input - attempt["reserved_input"]
            spend.output_tokens += charged_output - attempt["reserved_output"]
            stop_reason = frozen["stop_reason"]
            if charged_input > budget.step_input_tokens or (
                budget.input_tokens is not None and spend.input_tokens > budget.input_tokens
            ):
                stop_reason = stop_reason or REASON_BUDGET_INPUT_TOKENS
            if charged_output > attempt["reserved_output"] or (
                budget.output_tokens is not None and spend.output_tokens > budget.output_tokens
            ):
                stop_reason = stop_reason or REASON_BUDGET_OUTPUT_TOKENS
            connection.execute(
                "UPDATE agent_model_call SET response=%s,state='SAVED',saved_at=now(),stop_reason=%s,settled_spend=%s "
                "WHERE run_id=%s AND call_id=%s", (Jsonb(body), stop_reason, Jsonb(spend.as_dict()), run_id, call_id),
            )
            connection.execute(
                "UPDATE agent_model_attempt SET response=%s,state='SAVED',saved_at=now(),stop_reason=%s "
                "WHERE run_id=%s AND call_id=%s AND attempt_no=%s",
                (Jsonb(body), stop_reason, run_id, call_id, attempt_no),
            )
            connection.execute("UPDATE agent_run SET budget_spent=%s,updated_at=now(),version=version+1 "
                               "WHERE run_id=%s", (Jsonb(spend.as_dict()), run_id))
            connection.execute("UPDATE agent_run_model_budget SET stop_reason=%s WHERE run_id=%s",
                               (stop_reason, run_id))
            # Returning a stop reason after commit preserves overage accounting instead of rolling it back.
            return _saved_result({"response": body, "state": "SAVED", "stop_reason": stop_reason}, new_result=True)
