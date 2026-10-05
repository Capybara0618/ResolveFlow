"""C08.2 — the single executor: a queued run is claimed, investigated and answered once.

These are the rules the worker owns, checked against the real schema with the investigation stubbed out. The
**harness** is deliberately not in the loop: what is pinned here is that a ``QUEUED`` row becomes an investigation
exactly once, that the case service is told the run started **in the same transaction**, and that the outcome lands
as one callback plus the status that callback implies. Whether the SDK investigates well is the harness suite's job.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import replace
from typing import Any

import pytest
from resolveflow.contracts._schemaio import CORE_SCHEMA_FILES, component_validator
from resolveflow.contracts.core_models import ToolObservation
from resolveflow.contracts.enums import CallbackKind, EvidenceSourceType
from resolveflow.harness.actions import POLICY_SEARCH_TOOL_NAME, validate_decision
from resolveflow.harness.budget import RunSpend
from resolveflow.harness.manifest import MAX_ACTIVE_DEADLINE_SECONDS
from resolveflow.harness.vocabulary import RunResult
from resolveflow.runtime.callbacks import CallbackStore
from resolveflow.runtime.db import Database
from resolveflow.runtime.runs import RunRequest, RunStore, VerifiedCaller
from resolveflow.runtime.worker import RunWorker

from tests.integration import future_deadline

RUN_ID = "11111111-2222-4333-8444-555555555555"
CASE_ID = "9c858901-8a57-4791-81fe-4c455b099bc9"

CASE_DISPATCHER = VerifiedCaller(
    service="case-service",
    scope="run:dispatch",
    merchant_id="M-1001",
    customer_id="C-2002",
)

STARTED_AT = dt.datetime(2026, 9, 26, 10, 0, tzinfo=dt.UTC)
#: Well beyond the 120s ceiling, so the granted window is the ceiling rather than the queued deadline.
DEADLINE = future_deadline()


def a_run(**overrides: Any) -> RunRequest:
    fields: dict[str, Any] = {
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "input_revision": 1,
        "merchant_id": "M-1001",
        "customer_id": "C-2002",
        "order_id": "00000000-0000-4000-8000-0000000000aa",
        "line_id": "7001",
        "description": "包裹丢了，希望退款",
        "requested_actions": ["REFUND"],
        "evidence_refs": ["ev-1"],
        "policy_manifest": {
            "merchant_id": "M-1001",
            "bundle_ids": ["policy-logistics-2026.09"],
            "manifest_hash": "9" * 64,
            "safety_epoch": 1,
        },
        "deadline_at": DEADLINE,
        "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
    }
    fields.update(overrides)
    return RunRequest(**fields)


def queued(agent_db: Database, **overrides: Any) -> RunStore:
    """A dispatched run waiting in the queue, and the store a caller can read it back from."""
    store = RunStore(agent_db)
    store.queue(a_run(**overrides), caller=CASE_DISPATCHER)
    return store


def worker_for(agent_db: Database, result: RunResult | None = None) -> RunWorker:
    """A worker whose investigation is a fixed outcome, so the worker's own rules are what is under test."""

    def investigate(facts: Any) -> RunResult:
        assert result is not None, "this worker was not expected to be asked to investigate"
        return result

    return RunWorker(agent_db, investigate=investigate)


def proposal_result() -> RunResult:
    evidence = {
        "observation_id": "shipment-observation",
        "source_ref": "order:get_shipment_trace",
        "source_version": "3",
        "content_hash": "a" * 64,
    }
    policy = {
        "bundle_id": "policy-logistics-2026.09",
        "version": "2026.09.1",
        "rule_id": "lost-refund",
        "chunk_id": "chunk-1",
        "content_hash": "b" * 64,
    }
    return RunResult(
        completed=True,
        reason_code="COMPLETED",
        decision=validate_decision(
            {
                "kind": "PROPOSE",
                "case_type": "LOGISTICS",
                "recommended_action": "REFUND",
                "reason_codes": ["LOST_CONFIRMED"],
                "summary": "承运商判定丢失",
                "evidence_refs": [evidence],
                "policy_refs": [policy],
            }
        ),
        observations=(
            ToolObservation(
                **evidence,
                tool_name="get_shipment_trace",
                source_type=EvidenceSourceType.ORDER_LINE,
                observed_at=STARTED_AT.isoformat(),
                result={"conclusion": "LOST"},
            ),
            ToolObservation(
                observation_id="policy-search",
                tool_name=POLICY_SEARCH_TOOL_NAME,
                source_type=EvidenceSourceType.POLICY_RULE,
                source_ref="policy:policy-logistics-2026.09",
                source_version="1",
                content_hash="c" * 64,
                observed_at=STARTED_AT.isoformat(),
                result={"hits": [policy]},
            ),
        ),
        spend=RunSpend(),
    )


def question_result() -> RunResult:
    return RunResult(
        completed=True,
        reason_code="COMPLETED",
        decision=validate_decision(
            {
                "kind": "ASK_CUSTOMER",
                "questions": [{"question_id": "q1", "field": "shipment_photo", "prompt": "包裹是否已收到？"}],
                "summary": "需要客户确认",
            }
        ),
        observations=(),
        spend=RunSpend(),
    )


def stopped_result() -> RunResult:
    return RunResult(
        completed=False,
        reason_code="ACTION_REFUSED",
        decision=validate_decision({"kind": "ESCALATE", "reason_codes": ["NEEDS_HUMAN"], "summary": "转人工"}),
        observations=(),
        spend=RunSpend(),
    )


def read_run(agent_db: Database) -> dict[str, Any]:
    with agent_db.connection() as connection:
        row = connection.execute(
            "SELECT * FROM agent_run WHERE run_id = %(run_id)s", {"run_id": RUN_ID}
        ).fetchone()
    assert row is not None
    return dict(row)


def test_a_queued_run_is_claimed_once_and_the_case_service_is_told_in_the_same_state(
    agent_db: Database,
) -> None:
    """The claim: ``QUEUED`` → ``RUNNING``, a bounded window granted, and ``STARTED`` filed with it.

    The callback is asserted together with the status change rather than in a separate test because the two must not
    be able to disagree: a run that is ``RUNNING`` while the case service was never told is exactly the state
    ``AGENTS.md``'s 业务结果和本地事件同事务 rule exists to prevent.
    """
    queued(agent_db)
    worker = worker_for(agent_db)

    claimed = worker.claim_one(now=STARTED_AT)

    assert claimed is not None
    assert claimed.facts.line_id == "7001"
    assert claimed.facts.description == "包裹丢了，希望退款"
    assert claimed.facts.policy_manifest["manifest_hash"] == "9" * 64

    row = read_run(agent_db)
    assert row["status"] == "RUNNING"
    # The granted window is the spec's ceiling, not the queued deadline: `docs/agent-spec.md:42` bounds how long a
    # run may hold a case, and a grant beyond `deadline_at` would hold it past the published window.
    assert row["active_deadline_at"] == STARTED_AT + dt.timedelta(seconds=MAX_ACTIVE_DEADLINE_SECONDS)
    assert row["active_deadline_at"] < dt.datetime.fromisoformat(DEADLINE.replace("Z", "+00:00"))

    started = CallbackStore(agent_db).list_for_run(RUN_ID)
    assert [record.kind for record in started] == [CallbackKind.STARTED.value]
    assert started[0].status == "PENDING"
    assert started[0].payload["started_at"] == STARTED_AT.isoformat()

    # And a second pass has nothing to do: the claim is once, not once per worker pass.
    assert worker.claim_one(now=STARTED_AT) is None


def test_a_claimed_run_takes_the_window_the_deadline_allows_when_that_is_shorter(
    agent_db: Database,
) -> None:
    """The other half of ``min(deadline, start + ceiling)``: a short queued deadline is not extended."""
    soon = STARTED_AT + dt.timedelta(seconds=30)
    queued(agent_db, deadline_at=soon.isoformat())

    worker_for(agent_db).claim_one(now=STARTED_AT)

    assert read_run(agent_db)["active_deadline_at"] == soon


def test_an_investigated_run_files_its_proposal_and_awaits_java(agent_db: Database) -> None:
    """``PROPOSE`` → a ``PROPOSAL`` callback and ``CALLBACK_PENDING``: the run is waiting on Java's review."""
    queued(agent_db)

    outcome = worker_for(agent_db, proposal_result()).run_once(now=STARTED_AT)

    assert outcome is not None
    assert (outcome.status, outcome.callback_kind) == ("CALLBACK_PENDING", "PROPOSAL")
    assert read_run(agent_db)["status"] == "CALLBACK_PENDING"

    records = CallbackStore(agent_db).list_for_run(RUN_ID)
    proposal = [record for record in records if record.kind == "PROPOSAL"]
    assert len(proposal) == 1, records
    # The id is derived from the run, so a repeated pass computes the same one and cannot file a second proposal.
    assert proposal[0].callback_id == f"cb-{CASE_ID}-1-proposal"
    # `proposal_id` is a uuid the contract can bind, derived from the run so a repeated pass computes the same one.
    assert uuid.UUID(str(proposal[0].payload["proposal_id"]))
    assert proposal[0].payload["run_id"] == RUN_ID
    assert proposal[0].payload["case_id"] == CASE_ID
    assert proposal[0].payload["input_revision"] == 1
    assert proposal[0].payload["recommended_action"] == "REFUND"
    assert proposal[0].payload["evidence_refs"][0]["observation_id"] == "shipment-observation"
    assert proposal[0].payload["policy_refs"][0]["rule_id"] == "lost-refund"
    validator = component_validator("case", "ProposalPayload", "contracts/core", CORE_SCHEMA_FILES)
    assert list(validator.error_messages(proposal[0].payload)) == []
    # Nothing about the run is left claiming it is still being investigated.
    assert read_run(agent_db)["status"] != "RUNNING"


@pytest.mark.parametrize(
    ("defect", "reason"),
    [
        ("summary", "PROPOSAL_SCHEMA_REFUSED"),
        ("no_citations", "REFUND_CITATION_REQUIRED"),
        ("hash", "CITATION_HASH_MISMATCH"),
        ("invisible", "CITATION_NOT_VISIBLE"),
        ("scope", "CROSS_SCOPE_CITATION"),
        ("missing_evidence", "PROPOSAL_SCHEMA_REFUSED"),
    ],
)
def test_invalid_final_proposals_fail_without_filing_a_proposal(
    agent_db: Database, defect: str, reason: str,
) -> None:
    queued(agent_db)
    result = proposal_result()
    decision = result.decision.model_dump()
    if defect == "summary":
        decision.pop("summary")
    elif defect == "no_citations":
        decision.update(evidence_refs=[], policy_refs=[])
    elif defect == "hash":
        decision["evidence_refs"][0]["content_hash"] = "d" * 64
    elif defect == "scope":
        decision["policy_refs"][0]["bundle_id"] = "other-merchant-policy"
    elif defect == "missing_evidence":
        decision["missing_evidence"] = ["carrier-confirmation"]
    elif defect == "invisible":
        result = replace(result, observations=())
    result = replace(result, decision=validate_decision(decision))

    outcome = worker_for(agent_db, result).run_once(now=STARTED_AT)

    assert outcome is not None
    assert (outcome.status, outcome.callback_kind) == ("FAILED", "FAILED")
    assert outcome.result is not None and outcome.result.reason_code == reason
    assert not outcome.result.completed
    assert read_run(agent_db)["status"] == "FAILED"
    records = CallbackStore(agent_db).list_for_run(RUN_ID)
    assert [record.kind for record in records] == ["STARTED", "FAILED"]
    assert records[-1].payload == {"reason_codes": [reason], "retryable": False}


@pytest.mark.parametrize("valid", [True, False])
def test_final_status_and_callback_roll_back_together_on_outbox_failure(
    agent_db: Database, monkeypatch: pytest.MonkeyPatch, valid: bool,
) -> None:
    queued(agent_db)
    worker = worker_for(agent_db)
    claimed = worker.claim_one(now=STARTED_AT)
    assert claimed is not None
    result = proposal_result()
    if not valid:
        result = replace(result, observations=())

    def fail_enqueue(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("outbox write failed")

    monkeypatch.setattr(CallbackStore, "enqueue_for_run", fail_enqueue)
    with pytest.raises(RuntimeError, match="outbox write failed"):
        worker.finish(claimed, result)

    assert read_run(agent_db)["status"] == "RUNNING"
    assert [record.kind for record in CallbackStore(agent_db).list_for_run(RUN_ID)] == ["STARTED"]


def test_claim_and_started_callback_roll_back_together_on_outbox_failure(
    agent_db: Database, monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued(agent_db)

    def fail_enqueue(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("outbox write failed")

    monkeypatch.setattr(CallbackStore, "enqueue_for_run", fail_enqueue)
    with pytest.raises(RuntimeError, match="outbox write failed"):
        worker_for(agent_db).claim_one(now=STARTED_AT)

    assert read_run(agent_db)["status"] == "QUEUED"
    assert read_run(agent_db)["active_deadline_at"] is None
    assert CallbackStore(agent_db).list_for_run(RUN_ID) == []


def test_a_question_is_filed_and_leaves_the_run_awaiting_receipt(agent_db: Database) -> None:
    """``ASK_CUSTOMER`` files a QUESTION callback; the run waits for the case service to take it.

    ``docs/agent-spec.md:9``: QUESTION**接收后**WAITING_INPUT — the receipt is the event, so a question that has
    only been filed leaves the run ``CALLBACK_PENDING``, exactly like a proposal. What moves it to
    ``WAITING_INPUT`` is ``RunStore.apply_callback_disposition``, driven by the delivery loop
    (``test_a_delivery_moves_the_run_to_the_status_its_answer_implies`` in ``test_callback_delivery.py``).
    """
    queued(agent_db)

    outcome = worker_for(agent_db, question_result()).run_once(now=STARTED_AT)

    assert outcome is not None
    assert (outcome.status, outcome.callback_kind) == ("CALLBACK_PENDING", "QUESTION")
    records = CallbackStore(agent_db).list_for_run(RUN_ID)
    question = [record for record in records if record.kind == "QUESTION"][0]
    assert question.status == "PENDING"
    assert question.payload["questions"] == [
        {"field": "shipment_photo", "prompt": "包裹是否已收到？"}
    ]


def test_a_stopped_run_is_reported_failed_with_its_own_reason_code(agent_db: Database) -> None:
    """A run that produced no proposal and no question has nothing to act on, and says why."""
    queued(agent_db)

    outcome = worker_for(agent_db, stopped_result()).run_once(now=STARTED_AT)

    assert outcome is not None
    assert (outcome.status, outcome.callback_kind) == ("FAILED", "FAILED")
    records = CallbackStore(agent_db).list_for_run(RUN_ID)
    failed = [record for record in records if record.kind == "FAILED"][0]
    assert failed.payload["reason_codes"] == ["ACTION_REFUSED"]
    # Not retryable: the harness stopping is a statement about this input, not a transient fault.
    assert failed.payload["retryable"] is False


def test_a_cancelled_run_is_not_claimed(agent_db: Database) -> None:
    """Cancellation wins over the queue: a cancelled run is not work, and is never started."""
    store = queued(agent_db)
    store.cancel(RUN_ID)

    claimed = worker_for(agent_db).claim_one(now=STARTED_AT)

    assert claimed is None
    assert read_run(agent_db)["status"] == "CANCELLED"
    assert CallbackStore(agent_db).list_for_run(RUN_ID) == []


def test_a_cancellation_during_the_investigation_is_not_overwritten(agent_db: Database) -> None:
    """The race a single executor can still lose, stated honestly: the worker refuses to write.

    The run is cancelled after the claim and before the outcome is filed. Writing ``CALLBACK_PENDING`` over a
    cancellation would resurrect work the case service has already withdrawn, and filing a proposal for it would be
    worse — so the conditional update is what decides, and no callback is filed. Fencing the worker properly is C09's
    job; refusing the write is what is available here.
    """
    store = queued(agent_db)
    worker = worker_for(agent_db, proposal_result())
    claimed = worker.claim_one(now=STARTED_AT)
    assert claimed is not None
    store.cancel(RUN_ID)

    outcome = worker.finish(claimed, proposal_result(), now=STARTED_AT)

    assert outcome.status == "CANCELLED"
    assert outcome.callback_kind is None
    assert read_run(agent_db)["status"] == "CANCELLED"
    kinds = [record.kind for record in CallbackStore(agent_db).list_for_run(RUN_ID)]
    assert "PROPOSAL" not in kinds, kinds


def test_draining_an_empty_queue_is_not_an_error(agent_db: Database) -> None:
    """Nothing queued means nothing to do — the loop a deployment runs must idle quietly."""
    worker = worker_for(agent_db)

    assert worker.run_once(now=STARTED_AT) is None
    assert worker.drain(limit=3, now=STARTED_AT) == []


def test_drain_investigates_every_queued_run_at_most_once(agent_db: Database) -> None:
    """A backlog is drained in order, and the limit is a limit.

    The two runs are for **two different cases**: one case and revision is one run, and a second revision of the
    same case would supersede the first rather than queue beside it (``docs/agent-spec.md:9``, pinned in
    ``test_supersede_on_new_revision.py``). What is being checked here is the drain, so the fixture is two
    independent pieces of work.
    """
    second_run = "22222222-3333-4444-8555-666666666666"
    store = queued(agent_db)
    store.queue(
        a_run(run_id=second_run, case_id="44444444-5555-4666-8777-888888888888"), caller=CASE_DISPATCHER
    )

    outcomes = worker_for(agent_db, proposal_result()).drain(limit=5, now=STARTED_AT)

    assert [outcome.run_id for outcome in outcomes] == [RUN_ID, second_run]
    assert all(outcome.status == "CALLBACK_PENDING" for outcome in outcomes)
    assert worker_for(agent_db).drain(limit=5, now=STARTED_AT) == []


def test_the_worker_never_asks_the_model_itself(agent_db: Database) -> None:
    """The worker's boundary: it owns the queue, the status and the outbox — not the investigation.

    Stated as a test because the temptation to let the worker start making decisions is how a second agent loop
    appears. The only thing it may do with a run is call the injected investigation and file what came back.
    """
    queued(agent_db)
    seen: list[str] = []

    def investigate(facts: Any) -> RunResult:
        seen.append(facts.run_id)
        return proposal_result()

    outcome = RunWorker(agent_db, investigate=investigate).run_once(now=STARTED_AT)

    assert seen == [RUN_ID]
    assert outcome is not None
    assert outcome.result is not None and outcome.result.decision is not None


def test_an_unexpected_failure_is_not_dressed_up_as_a_decision(agent_db: Database) -> None:
    """A crash is a crash: this worker does not turn a harness bug into a ``FAILED`` callback.

    The opposite — a catch-all that filed ``FAILED`` — would make a defect look like an investigation that reached a
    conclusion, and the run's record would say the harness decided something it never decided. Recovery of a run left
    ``RUNNING`` is C09's, and it is named there rather than approximated here.
    """
    queued(agent_db)

    def explode(facts: Any) -> RunResult:
        raise RuntimeError("the harness fell over")

    with pytest.raises(RuntimeError):
        RunWorker(agent_db, investigate=explode).run_once(now=STARTED_AT)

    assert read_run(agent_db)["status"] == "RUNNING"
