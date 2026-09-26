"""Reconstruct the same SDK reply from fenced call records; never a second agent loop."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agentscope.state import AgentState

from resolveflow.contracts.core_models import ToolObservation
from resolveflow.harness.budget import BudgetExhaustedError, RunSpend
from resolveflow.harness.context import canonical_json, estimate_tokens, hash_document
from resolveflow.harness.model import MockModelClient
from resolveflow.runtime.db import Database
from resolveflow.runtime.journal import RunJournal
from resolveflow.runtime.recovery_store import RecoveryConflictError, StaleFenceError


class ModelRetryExhaustedError(RuntimeError):
    """Both transmissions of one logical request remain UNKNOWN."""


@dataclass
class DurableRun:
    database: Database
    facts: Any
    fault: Callable[[str], None] = lambda _: None
    journal: RunJournal = field(init=False)
    model_step: int = 0
    tool_step: int = 0
    recovering: bool = False
    recovery_turn_used: bool = False
    before_spend: dict[str, Any] = field(default_factory=dict)
    sdk_state: dict[str, Any] = field(default_factory=dict)
    model_record: Any = None
    tool_record: Any = None
    tool_saved: bool = False
    failure: Exception | None = None

    def __post_init__(self) -> None:
        self.journal = RunJournal(self.database)

    def identity(self) -> dict[str, Any]:
        return {"fence": self.facts.fence, "owner": self.facts.lease_owner}

    def bind(self, runner: Any) -> None:
        self.journal.bind(self.facts.run_id, **self.identity(), manifest=runner.manifest(), budget=runner.budget)
        if hasattr(runner.tools, "trace_pages"):
            runner.tools.trace_pages = self.journal.trace_pages(self.facts.run_id, **self.identity())
        if isinstance(runner.model, MockModelClient):
            runner.model.use_context_step = True

    def capture_error(self, error: Exception) -> str | None:
        if isinstance(error, (StaleFenceError, RecoveryConflictError, BudgetExhaustedError)):
            self.failure = error
            return error.reason_code if isinstance(error, BudgetExhaustedError) else "RECOVERY_REFUSED"
        return None

    def transmit(self, target: Any, invoke: Callable[[], Any], guard: Any) -> Any:
        remaining = self.journal.remaining_seconds(self.facts.run_id, **self.identity())
        if remaining <= 0:
            raise BudgetExhaustedError("BUDGET_DEADLINE", "original deadline expired before transmission")
        if not hasattr(target, "timeout_seconds"):
            return invoke()
        original = target.timeout_seconds
        target.timeout_seconds = min(original, guard.guard.budget.timeout_seconds, remaining)
        try:
            return invoke()
        finally:
            target.timeout_seconds = original

    def before_model(self, agent: Any, guard: Any) -> None:
        if self.tool_saved:
            self.tool_saved = False
            self.fault("after_tool_saved")
        self.model_record, spend = self.journal.read(self.facts.run_id, **self.identity(),
                                                   call_id=f"model-{self.model_step}")
        row = self.model_record
        if self.model_step == 0:
            self.recovering = row is not None
        if row is not None:
            if not isinstance(row["replay_spend"], dict) or not isinstance(row["sdk_state"], dict):
                raise RecoveryConflictError("MIGRATION_REQUIRED: incomplete reconstruction snapshot")
            AgentState.model_validate(row["sdk_state"])
            spend = row["replay_spend"]
        self.before_spend = dict(spend)
        self.sdk_state = agent.state.model_dump(mode="json")
        guard.guard.spend = RunSpend(**spend)

    def decide(self, model: Any, guard: Any, kwargs: dict[str, Any]) -> Any:
        call_id = f"model-{self.model_step}"
        row = self.model_record
        ceiling = guard.output_ceiling
        body = (
            model.prepare_request(system=kwargs["system"], messages=kwargs["messages"], max_output_tokens=ceiling)
            if hasattr(model, "prepare_request") else {
                "messages": [{"role": msg.role, "content": msg.get_text_content()} for msg in kwargs["messages"]],
                "max_tokens": ceiling,
            }
        )
        digest = hash_document(body)
        if row is not None and row["request_hash"] != digest:
            raise RecoveryConflictError("MIGRATION_REQUIRED: reconstructed provider request differs")
        saved = self.journal.recorded_result(self.facts.run_id, **self.identity(), call_id=call_id) if row else None
        if saved is not None:
            if saved.stop_reason:
                raise BudgetExhaustedError(saved.stop_reason, "saved provider overage")
            reply = saved.reply
        else:
            if row is None:
                kind = "RECOVERY_TURN" if self.recovering and not self.recovery_turn_used else "ORDINARY"
                reservation = self.journal.reserve(
                    self.facts.run_id, **self.identity(), call_id=call_id, request_hash=digest, kind=kind,
                    input_tokens=max(estimate_tokens(canonical_json(body)), guard.guard.spend.input_tokens -
                                     self.before_spend.get("input_tokens", 0)),
                    request_body=body, replay_spend=self.before_spend, sdk_state=self.sdk_state,
                    ceiling_parameter=getattr(model, "ceiling_parameter", "max_tokens"),
                )
                if kind == "RECOVERY_TURN":
                    self.recovery_turn_used = True
            else:
                if row["current_attempt"] == 1:
                    raise ModelRetryExhaustedError("original and one retry already consumed")
                reservation = self.journal.reserve_retry(
                    self.facts.run_id, **self.identity(), call_id=call_id, request_hash=digest,
                    expected_attempt=row["current_attempt"],
                )
            if not reservation.new_reservation:
                raise RecoveryConflictError("UNKNOWN attempt already reserved; no duplicate transmission")
            reply = self.transmit(model, lambda: model.decide(**kwargs), guard)
            self.fault("before_model_saved")
            saved = self.journal.save_result(self.facts.run_id, **self.identity(), call_id=call_id,
                                            attempt_no=reservation.attempt_no, reply=reply)
            self.fault("after_model_saved")
            if saved.stop_reason:
                raise BudgetExhaustedError(saved.stop_reason, "provider overage committed")
        self.model_record, _ = self.journal.read(self.facts.run_id, **self.identity(), call_id=call_id)
        self.model_step += 1
        return reply

    def after_model(self, guard: Any) -> None:
        if not isinstance(self.model_record["settled_spend"], dict):
            raise RecoveryConflictError("MIGRATION_REQUIRED: missing settled spend snapshot")
        guard.guard.spend = RunSpend(**self.model_record["settled_spend"])

    def before_tool(self, name: str, arguments: dict[str, Any], guard: Any) -> None:
        self.tool_record, spend = self.journal.read(self.facts.run_id, **self.identity(),
                                                  call_id=f"tool-{self.tool_step}", tool=True)
        if self.tool_record is not None and self.tool_record["observation"] is not None:
            if self.tool_record["request_hash"] != hash_document({"name": name, "arguments": arguments}):
                raise RecoveryConflictError("MIGRATION_REQUIRED: tool request differs")
            spend = self.tool_record["before_spend"]
        guard.guard.spend = RunSpend(**spend)

    def observe(self, name: str, arguments: dict[str, Any], invoke: Callable[[], Any],
                guard: Any, *, local: bool) -> ToolObservation:
        call_id = f"tool-{self.tool_step}"
        row = self.tool_record
        if row is not None and row["observation"] is not None:
            observation = ToolObservation.model_validate_json(json.dumps(row["observation"]))
            spend = row["after_spend"]
        else:
            spend = self.journal.reserve_tool(self.facts.run_id, **self.identity(), call_id=call_id,
                                             request_hash=hash_document({"name": name, "arguments": arguments}),
                                             local=local)
            observation = invoke()
            self.journal.save_tool(self.facts.run_id, **self.identity(), call_id=call_id,
                                   observation=observation.model_dump(mode="json"))
            self.tool_saved = True
        guard.guard.spend = RunSpend(**spend)
        self.tool_step += 1
        return observation
