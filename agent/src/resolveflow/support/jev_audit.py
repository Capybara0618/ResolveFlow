"""One optional post-answer decision, reserved and saved under the consultation's existing fence."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import asdict
from typing import Any

from resolveflow.harness.budget import BudgetExhaustedError
from resolveflow.harness.context import canonical_json, estimate_tokens
from resolveflow.support.jev import ENDPOINT, VERSION, JevClient, JevConfig, JevError, build_request
from resolveflow.support.protocol import SupportFailure

LOG = logging.getLogger(__name__)


def remaining_seconds(deadline: dt.datetime) -> float:
    return (deadline - dt.datetime.now(dt.UTC)).total_seconds()


def audit_answer(agent: Any, result: dict[str, Any], config: JevConfig, client: JevClient) -> None:
    """Observe only: never edits the answer or grants authority. Unknown calls are never retried."""
    if not config.enabled or result["status"] != "SUCCEEDED":
        return
    journal, guard = agent.journal, agent.guard
    body = build_request(config, str(agent.request.context.get("current_request", "")),
                         result["answer"], agent.observations)
    recorded = {"version": VERSION, "provider": "typesafe", "endpoint": ENDPOINT, "body": body}
    try:
        cached = journal.cached("jev", 1, recorded)
    except SupportFailure as error:
        if error.reason != "INTERRUPTED_TOOL_RESULT":
            raise
        # A crash may have lost a billed response. Keep the reservation and the STARTED row visible.
        LOG.warning("jev_audit run=%s status=UNKNOWN reason=UNSAVED_RESPONSE", agent.request.run_id)
        return
    if cached is not None:
        return
    timeout = min(config.timeout_seconds, remaining_seconds(agent.request.deadline_at))
    # UTF-8 bytes are a conservative allowance, never advertised as provider token usage.
    estimated = estimate_tokens(canonical_json(body)) + 256
    skip = None
    if timeout < .05:
        skip = "DEADLINE"
    else:
        try:
            guard.reserve_model_request(input_tokens=estimated)
        except BudgetExhaustedError as error:
            skip = error.reason_code
    journal.start("jev", 1, recorded, asdict(guard.spend))
    if skip is not None:
        outcome: dict[str, Any] = {"status": "SKIPPED", "reason": skip, "mode": "not-called"}
    else:
        try:
            outcome = client.evaluate(body, timeout=timeout)
        except JevError as error:
            outcome = {"status": "ERROR", "reason": error.reason, "mode": "live",
                       "usage_estimated": True, "reserved_input_tokens": estimated,
                       "reserved_output_tokens": guard.budget.step_output_tokens}
        # Successful inference is accounted even if its typed response exceeds the reservation.
        if outcome["status"] == "COMPLETE":
            outcome.update(mode="live", usage_estimated=False)
            guard.spend.input_tokens += outcome["usage"]["input_tokens"] - estimated
            try:
                guard.settle_model_output(outcome["usage"]["output_tokens"])
            except BudgetExhaustedError as error:
                outcome["accounting_warning"] = error.reason_code
        else:
            guard.settle_model_output(None, estimated=True)
    journal.complete("jev", 1, outcome, asdict(guard.spend))
    result["spend"] = asdict(guard.spend)
    LOG.info("jev_audit run=%s status=%s verdict=%s reason=%s elapsed_ms=%s", agent.request.run_id,
             outcome["status"], outcome.get("verdict"), outcome.get("reason"), outcome.get("elapsed_ms"))
