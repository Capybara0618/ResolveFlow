"""Run the production AgentScope/Harness loop against recorded calls in memory."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from agentscope.state import AgentState

from resolveflow.contracts.core_models import ToolObservation
from resolveflow.harness import budget as budget_module
from resolveflow.harness.budget import RunBudget, RunSpend
from resolveflow.harness.context import hash_document
from resolveflow.harness.model import ModelReply, ModelUsage
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.harness.vocabulary import RunFacts, RunResult
from resolveflow.replay.isolation import block_network
from resolveflow.replay.pack import PackInvalid, ReplayMiss, UnsupportedRecord, read_pack
from resolveflow.runtime.worker import ClaimedRun, verified_callback


class ReplayMismatch(RuntimeError):
    """The first semantic difference, with its logical step."""


@dataclass
class ReplayCallbackSink:
    """Local terminal sink; never opens the production outbox or a database."""

    expected: dict[str, Any]

    def capture(self, claimed: ClaimedRun, result: RunResult) -> str:
        kind, _, payload, verified = verified_callback(claimed, result)
        if kind.value != self.expected["callback_kind"] or payload != self.expected["callback_payload"]:
            raise ReplayMismatch("terminal: callback kind/payload differs")
        if verified.spend.as_dict() != self.expected["budget_spent"]:
            raise ReplayMismatch("terminal: budget differs")
        return kind.value


@dataclass
class RecordedModel:
    model_alias: str | None
    mode: str = "mock"

    def decide(self, **_: Any) -> ModelReply:
        raise ReplayMiss("REPLAY_MISS: direct model call outside recorded adapter")


class RecordedTools:
    def call_tool(self, **_: Any) -> ToolObservation:
        raise ReplayMiss("REPLAY_MISS: direct tool call outside recorded adapter")

    def note_trace_page(self) -> None:
        return None

    def close(self) -> None:
        return None


@dataclass
class RecordedCalls:
    pack: dict[str, Any]
    model_step: int = 0
    tool_step: int = 0
    model_row: dict[str, Any] | None = None
    tool_row: dict[str, Any] | None = None
    failure: Exception | None = None
    network_guard: Any = None
    network_attempts: list[str] | None = None

    def bind(self, runner: AgentScopeRunner) -> None:
        self.network_guard = block_network()
        self.network_attempts = self.network_guard.__enter__()
        if runner.manifest() != self.pack["manifest"]:
            raise PackInvalid("PACK_INVALID: incompatible harness manifest/state/code")
        if runner.budget != RunBudget(**self.pack["budget"]):
            raise PackInvalid("PACK_INVALID: budget differs")

    def close(self) -> None:
        if self.network_guard is not None:
            self.network_guard.__exit__(None, None, None)
            self.network_guard = None

    def capture_error(self, error: Exception) -> str | None:
        if isinstance(error, (ReplayMiss, ReplayMismatch, PackInvalid)):
            self.failure = error
            return "REPLAY_MISS"
        return None

    def before_model(self, agent: Any, guard: Any) -> None:
        rows = self.pack["model_calls"]
        if self.model_step >= len(rows):
            raise ReplayMiss(f"REPLAY_MISS: model-{self.model_step} absent")
        row = rows[self.model_step]
        if row["call_id"] != f"model-{self.model_step}":
            raise PackInvalid("PACK_INVALID: model call order")
        AgentState.model_validate(row["sdk_state"])
        self.model_row = row
        guard.guard.spend = RunSpend(**row["replay_spend"])

    def decide(self, model: Any, guard: Any, kwargs: dict[str, Any]) -> ModelReply:
        del model
        row = self.model_row
        assert row is not None
        body = {
            "messages": [{"role": msg.role, "content": msg.get_text_content()} for msg in kwargs["messages"]],
            "max_tokens": guard.output_ceiling,
        }
        if hash_document(body) != row["request_hash"] or body != row["request_body"]:
            raise ReplayMismatch(f"model-{self.model_step}: provider request differs")
        response = row["response"]
        reply = ModelReply(decision=response["decision"], usage=ModelUsage(**response["usage"]),
                           mode=response["mode"], model_alias=response["model_alias"])
        self.model_step += 1
        return reply

    def after_model(self, guard: Any) -> None:
        assert self.model_row is not None
        guard.guard.spend = RunSpend(**self.model_row["settled_spend"])

    def before_tool(self, name: str, arguments: dict[str, Any], guard: Any) -> None:
        rows = self.pack["tool_calls"]
        if self.tool_step >= len(rows):
            raise ReplayMiss(f"REPLAY_MISS: tool-{self.tool_step} absent")
        row = rows[self.tool_step]
        if (row["call_id"] != f"tool-{self.tool_step}"
                or (row["local_read"] and name != "read_observation")):
            raise UnsupportedRecord("UNSUPPORTED_RECORD: nonsequential/local tool")
        request = {"name": name, "arguments": arguments}
        if row["request_hash"] != hash_document(request) or row["request_body"] != request:
            raise ReplayMismatch(f"tool-{self.tool_step}: request differs")
        self.tool_row = row
        guard.guard.spend = RunSpend(**row["before_spend"])

    def observe(self, name: str, arguments: dict[str, Any], invoke: Any, guard: Any,
                *, local: bool) -> ToolObservation:
        del arguments, invoke
        row = self.tool_row
        assert row is not None
        if bool(row["local_read"]) != local or (local and name != "read_observation"):
            raise UnsupportedRecord("UNSUPPORTED_RECORD: local tool differs")
        observation = ToolObservation.model_validate_json(json.dumps(row["observation"]))
        guard.guard.spend = RunSpend(**row["after_spend"])
        self.tool_step += 1
        return observation


def strict_replay(directory: Path) -> dict[str, Any]:
    """Use the same SDK driver and domain guard; compare every saved call and terminal callback."""
    pack = read_pack(directory)
    if not pack.get("model_calls"):
        raise ReplayMiss("REPLAY_MISS: no model response")
    if any(row["response"].get("mode") != "mock" for row in pack["model_calls"]):
        raise UnsupportedRecord("UNSUPPORTED_RECORD: selected packs are mock trajectories")
    facts = RunFacts(**pack["facts"])
    budget = RunBudget(**pack["budget"])
    model = RecordedModel(model_alias=pack["model_calls"][0]["response"]["model_alias"])
    adapter = RecordedCalls(pack)
    runner = AgentScopeRunner(model=model, tools=RecordedTools(), facts=facts, budget=budget, durability=adapter)
    frozen_now = dt.datetime.fromisoformat(pack["clock"])

    class FrozenDateTime(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> FrozenDateTime:
            return cls.fromtimestamp(frozen_now.timestamp(), tz)

    with patch.object(budget_module, "dt", SimpleNamespace(datetime=FrozenDateTime, UTC=dt.UTC)):
        result = runner.run()
    if adapter.model_step != len(pack["model_calls"]):
        raise ReplayMismatch(f"model-{adapter.model_step}: recorded suffix was not used")
    if adapter.tool_step != len(pack["tool_calls"]):
        raise ReplayMismatch(f"tool-{adapter.tool_step}: recorded suffix was not used")
    callback_kind = ReplayCallbackSink(pack["expected"]).capture(ClaimedRun(facts, facts.case_id, None), result)
    return {"status": "MATCH", "evaluation_run_id": pack["evaluation_run_id"],
            "source_run_id": pack["source_run_id"],
            "model_calls": adapter.model_step, "tool_calls": adapter.tool_step,
            "callback_kind": callback_kind}
