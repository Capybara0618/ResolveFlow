"""Fenced one-shot Choice routing for an existing CHECK_REQUEST; fallback consumes its own budget."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict
from typing import Any

from resolveflow.harness.budget import BudgetExhaustedError
from resolveflow.harness.context import canonical_json, estimate_tokens
from resolveflow.harness.model import ModelReply, ModelUsage
from resolveflow.support.jev import ENDPOINT, JevClient, JevError
from resolveflow.support.jev_intent import IntentPolicy, build_intent_request, intent_decision
from resolveflow.support.protocol import SupportFailure


def route_request_check(agent: Any, packet: dict[str, Any], client: JevClient,
                        policy: IntentPolicy) -> ModelReply | None:
    if (not policy.enabled or packet.get("orchestration", {}).get("phase") != "CHECK_REQUEST"
            or agent.feedback is not None):
        return None
    body = build_intent_request(client.config, packet)
    # Existing audit owns kind=jev, position=1. Intent checks use step+1 in the same fenced ledger.
    position = agent.step + 1
    record = {"purpose": "CHECK_REQUEST", "endpoint": ENDPOINT, "body": body, "policy": policy.manifest()}
    try:
        cached = agent.journal.cached("jev", position, record)
    except SupportFailure as error:
        if error.reason == "INTERRUPTED_TOOL_RESULT":
            # Unknown request keeps its charge and is never resent. Original model remains bounded.
            return None
        raise
    if cached is not None:
        return _reply(cached)
    remaining = (agent.request.deadline_at - dt.datetime.now(dt.UTC)).total_seconds()
    timeout = min(client.config.timeout_seconds, remaining)
    estimated = estimate_tokens(canonical_json(body)) + 256
    reason = "DEADLINE" if timeout < .05 else None
    if reason is None:
        try:
            agent.guard.reserve_model_request(input_tokens=estimated)
        except BudgetExhaustedError as error:
            reason = error.reason_code
    if reason is None:
        current = getattr(agent.sources, "check_current", None)
        if callable(current):
            current()
    agent.journal.start("jev", position, record, asdict(agent.guard.spend))
    if reason is not None:
        outcome: dict[str, Any] = {"status": "FALLBACK", "reason": reason, "attempted": False}
    else:
        try:
            response = client.evaluate_choices(body, timeout=timeout)
            agent.guard.spend.input_tokens += response["usage"]["input_tokens"] - estimated
            try:
                agent.guard.settle_model_output(response["usage"]["output_tokens"])
                if response["usage"]["input_tokens"] > agent.guard.budget.step_input_tokens:
                    raise BudgetExhaustedError("BUDGET_STEP_TOKENS", "actual Jev input exceeded step limit")
                limit = agent.guard.budget.input_tokens
                if limit is not None and agent.guard.spend.input_tokens > limit:
                    raise BudgetExhaustedError("BUDGET_INPUT_TOKENS", "actual Jev input exceeded run limit")
            except BudgetExhaustedError as error:
                agent.journal.complete("jev", position,
                    {"status": "STOPPED", "reason": error.reason_code, "response": response,
                     "usage": response["usage"], "usage_estimated": False, "attempted": True},
                    asdict(agent.guard.spend))
                raise SupportFailure(error.reason_code) from None
            decision = intent_decision(packet, response, policy)
            outcome = {"status": "ACCEPTED" if decision else "FALLBACK", "response": response,
                       "usage": response["usage"], "usage_estimated": False, "attempted": True}
            if decision is not None:
                outcome["decision"] = decision
            else:
                outcome["reason"] = "UNCERTAIN"
        except JevError as error:
            agent.guard.settle_model_output(None, estimated=True)
            outcome = {"status": "FALLBACK", "reason": error.reason, "attempted": True,
                       "usage_estimated": True, "reserved_input_tokens": estimated,
                       "reserved_output_tokens": agent.guard.budget.step_output_tokens}
    agent.journal.complete("jev", position, outcome, asdict(agent.guard.spend))
    return _reply(outcome)


def _reply(outcome: dict[str, Any]) -> ModelReply | None:
    if outcome["status"] != "ACCEPTED":
        return None
    return ModelReply(decision=outcome["decision"], usage=ModelUsage(**outcome["usage"]),
                      mode="live", model_alias=outcome["response"]["response"]["model"])
