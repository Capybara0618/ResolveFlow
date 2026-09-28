"""C08.2 — every callback body this project composes, checked against the **published case contract**.

The delivery tests prove the outbox, the retry schedule and the token; they hand the case service's answer back
through a ``ScriptedPoster`` and never check the body against the contract the case service validates with. That is
how four contract violations survived from C07 to here (``reports/c08-2-5-callback-payload-contract-gap.md``):
``additionalProperties: false`` makes an extra ``schema_version`` a refusal, ``ProposalPayload`` requires six members
this project never sent, and its ``proposal_id`` is a ``Uuid`` rather than an id we invented the shape of.

``docs/agent-harness.md:13``: Python通过不等于Java批准. This file is that sentence made executable — the payloads are
fed to ``contracts/core/openapi-case.yaml``'s own components, and the contract, not a copy of it, decides.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from resolveflow.contracts._schemaio import CORE_SCHEMA_FILES, component_validator
from resolveflow.contracts.enums import CallbackKind
from resolveflow.harness.actions import validate_decision
from resolveflow.harness.vocabulary import RunFacts, RunResult
from resolveflow.runtime.worker import ClaimedRun, callback_payload, started_payload

RUN_ID = "11111111-2222-4333-8444-555555555555"
CASE_ID = "9c858901-8a57-4791-81fe-4c455b099bc9"
STARTED_AT = dt.datetime(2026, 9, 26, 10, 0, tzinfo=dt.UTC)


def claimed_run() -> ClaimedRun:
    return ClaimedRun(
        facts=RunFacts(
            run_id=RUN_ID,
            case_id=CASE_ID,
            input_revision=3,
            line_id="7001",
            description="包裹丢了，希望退款",
        ),
        case_id=CASE_ID,
        traceparent=None,
    )


def result_for(decision: dict[str, Any], *, completed: bool = True) -> RunResult:
    return RunResult(
        completed=completed,
        reason_code="COMPLETED" if completed else "ACTION_REFUSED",
        decision=validate_decision(decision),
        observations=(),
        spend=object(),
    )


def proposal_result() -> RunResult:
    return result_for(
        {
            "kind": "PROPOSE",
            "case_type": "LOGISTICS",
            "recommended_action": "REFUND",
            "reason_codes": ["LOST_CONFIRMED"],
            "summary": "承运商判定丢失",
        }
    )


def question_result() -> RunResult:
    return result_for(
        {
            "kind": "ASK_CUSTOMER",
            "questions": [{"question_id": "q1", "field": "shipment_photo", "prompt": "包裹是否已收到？"}],
            "summary": "需要客户确认",
        }
    )


def stopped_result() -> RunResult:
    return result_for(
        {"kind": "ESCALATE", "reason_codes": ["NEEDS_HUMAN"], "summary": "转人工"}, completed=False
    )


def contract_errors(component: str, payload: dict[str, Any]) -> list[str]:
    """What the published contract says about this body — read from the schema, never restated here."""
    validator = component_validator("case", component, "contracts/core", CORE_SCHEMA_FILES)
    return list(validator.error_messages(payload))


def test_the_started_body_is_a_started_payload(agent_db: Any = None) -> None:
    """``StartedPayload``: ``additionalProperties: false``, and ``started_at`` is the only member it has."""
    payload = started_payload(STARTED_AT)

    assert contract_errors("StartedPayload", payload) == []
    assert payload == {"started_at": STARTED_AT.isoformat()}


def test_reviewer_findings_are_not_lost_in_the_outbound_callback() -> None:
    raw = {
        "kind": "PROPOSE", "case_type": "LOGISTICS", "recommended_action": "MANUAL_REVIEW",
        "summary": "需要人工核对", "reason_codes": ["NEEDS_HUMAN"],
        "evidence_refs": [{"observation_id": "obs-1", "source_ref": "line:7001/shipment",
                           "source_version": "1", "content_hash": "a" * 64}],
        "review_findings": [{"kind": "INFERENCE", "text": "现有资料仍需人工核对", "observation_ids": ["obs-1"]}],
    }
    payload = callback_payload(CallbackKind.PROPOSAL, claimed_run(), result_for(raw))
    assert payload["review_findings"] == raw["review_findings"]
    assert contract_errors("ProposalPayload", payload) == []


def test_the_proposal_body_is_a_proposal_payload() -> None:
    """``ProposalPayload``: the six members this project was not sending, and a ``proposal_id`` that is a uuid.

    ``schema_version``/``case_id`` are carried deliberately by the contract ("a copy Java can cross-check, not a
    second truth"), and ``case_type`` is there because **the run classified the case** — so a proposal composed
    without a classification is not a proposal the case service accepts.

    **Skipped, not passed**: ``case_type`` has no producer yet (the model ABI does not ask for a classification), so
    the body cannot be made valid by reshaping it. See ``reports/c08-2-5-callback-payload-contract-gap.md`` §5.
    """
    payload = callback_payload(CallbackKind.PROPOSAL, claimed_run(), proposal_result())

    errors = contract_errors("ProposalPayload", payload)
    assert errors == [], errors


def test_the_question_body_is_a_question_payload() -> None:
    """``QuestionPayload``: ``question_id`` + ``questions``, each question ``field`` + ``prompt``, nothing else.

    **Skipped, not passed**: the contract's ``AgentQuestion`` wants a ``field`` (which line member the question is
    about) and the ABI's question carries ``question_id`` + ``prompt``, so the member cannot be invented here.
    """
    payload = callback_payload(CallbackKind.QUESTION, claimed_run(), question_result())

    errors = contract_errors("QuestionPayload", payload)
    assert errors == [], errors


def test_the_failed_body_is_a_failed_payload() -> None:
    """``FailedPayload``: ``reason_codes`` and ``retryable``, and no extra member to be refused for."""
    payload = callback_payload(CallbackKind.FAILED, claimed_run(), stopped_result())

    errors = contract_errors("FailedPayload", payload)
    assert errors == [], errors
