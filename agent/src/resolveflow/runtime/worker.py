"""Run ownership, fenced terminal status and transactional callbacks; SDK owns investigation."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Final

from resolveflow.contracts.enums import CallbackKind
from resolveflow.harness.manifest import MAX_ACTIVE_DEADLINE_SECONDS
from resolveflow.harness.verifier import ProposalVerifier
from resolveflow.harness.vocabulary import RunFacts, RunResult
from resolveflow.runtime.callbacks import CallbackEnvelope, CallbackStore
from resolveflow.runtime.db import Database
from resolveflow.runtime.runs import QUEUED, RUN_STATUSES

__all__ = ["ClaimedRun", "RunOutcome", "RunWorker", "callback_payload", "started_payload"]


def started_payload(started_at: dt.datetime) -> dict[str, Any]:
    """The ``STARTED`` body, in the shape ``contracts/core/openapi-case.yaml``'s ``StartedPayload`` fixes.

    Its own function rather than an inline literal because the payload is a **contract** artifact: a test validates
    every kind this module composes against the published components, and a composition buried in the claim could
    only be checked by running a whole claim against a database.
    """
    return {"started_at": started_at.isoformat()}


def _status(name: str) -> str:
    """One of the run store's statuses, by name.

    Taken from ``RUN_STATUSES`` rather than spelled again here, so a status the store stops accepting cannot keep
    being written by this module. The failure is at import, which is where a vocabulary change should be noticed.
    """
    if name not in RUN_STATUSES:
        raise RuntimeError(f"{name!r} is not one of the run statuses: {RUN_STATUSES}")
    return name


#: The status a claim moves a run to.
RUNNING: Final = _status("RUNNING")

#: A proposal filed and awaiting Java's review.
CALLBACK_PENDING: Final = _status("CALLBACK_PENDING")

#: A question filed and awaiting the customer.
WAITING_INPUT: Final = _status("WAITING_INPUT")

#: The run stopped without a proposal or a question.
FAILED: Final = _status("FAILED")


@dataclass(frozen=True, slots=True)
class ClaimedRun:
    """A run this worker now owns, with everything the investigation needs and nothing it does not."""

    facts: RunFacts
    case_id: str
    traceparent: str | None
    legacy: bool = False


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """What one pass did, as a reader sees it: the status the run holds and the callback that was filed."""

    run_id: str
    status: str
    callback_kind: str | None
    result: RunResult | None


@dataclass(slots=True)
class RunWorker:
    """Claims queued runs and investigates them, one at a time.

    ``investigate`` is the seam that keeps this module free of the agent loop: it takes the run's facts and returns how
    the investigation ended. The C08.2 factory (mock or live model, MCP tools, a policy index) is what a deployment
    passes here, and a test can pass a lambda — which is how the claim/status/callback rules are checked without a
    model in the loop.
    """

    database: Database
    investigate: Callable[[RunFacts], RunResult]
    recoverable: bool = False
    callbacks: CallbackStore = field(init=False)

    def __post_init__(self) -> None:
        self.callbacks = CallbackStore(self.database)

    def claim_one(self, *, now: dt.datetime | None = None) -> ClaimedRun | None:
        """Take the oldest queued run, or return ``None`` when there is nothing to do.

        ``ORDER BY created_at`` keeps a backlog visible as an age rather than an arbitrary pick (the queue index was
        built for it). ``SKIP LOCKED`` is what makes "single executor" a fact rather than a deployment
        assumption: a second worker skips a locked row instead of blocking on it or claiming it twice.
        """
        started = now or dt.datetime.now(dt.UTC)
        with self.database.connection() as connection, connection.transaction():
            row = connection.execute(
                """
                SELECT run_id, case_id, input_revision, line_id, request_description, merchant_id, buyer_id,
                       policy_manifest, review_context, deadline_at, traceparent
                FROM agent_run
                WHERE status = %(queued)s AND cancelled_at IS NULL
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                {"queued": QUEUED},
            ).fetchone()
            if row is None:
                return None
            window = _active_deadline(row["deadline_at"], started)
            connection.execute(
                """
                UPDATE agent_run
                SET status = %(running)s, active_deadline_at = %(window)s, updated_at = %(now)s, version = version + 1
                WHERE run_id = %(run_id)s
                """,
                {"running": RUNNING, "window": window, "now": started, "run_id": row["run_id"]},
            )
            # Same transaction as the status change: a run that is RUNNING and a case service that was never told
            # is exactly the state this pairing exists to make impossible.
            self.callbacks.enqueue_for_run(
                str(row["run_id"]),
                CallbackEnvelope(
                    kind=CallbackKind.STARTED,
                    payload=started_payload(started),
                    traceparent=row["traceparent"],
                ),
                connection=connection,
            )
        return ClaimedRun(
            facts=RunFacts(
                run_id=str(row["run_id"]),
                case_id=str(row["case_id"]),
                input_revision=int(row["input_revision"]),
                line_id=str(row["line_id"]),
                description=str(row["request_description"]),
                merchant_id=row["merchant_id"],
                buyer_id=row["buyer_id"],
                active_deadline_at=window.isoformat(),
                policy_manifest=dict(row["policy_manifest"] or {}),
                review_context=dict(row["review_context"] or {}),
            ),
            case_id=str(row["case_id"]),
            traceparent=row["traceparent"],
        )

    def finish(self, claimed: ClaimedRun, result: RunResult, *, now: dt.datetime | None = None) -> RunOutcome:
        """Close a claimed run: file its outcome callback and move it to the status that callback implies.

        Refuses to write when the run is no longer ``RUNNING`` — a cancellation that arrived mid-investigation wins,
        and no callback is filed for a run this worker no longer owns. ``None`` from the conditional update is what
        detects that; reading the row back is only for the honest status in the outcome.
        A proposal is checked in its final wire shape against the run's observations and pinned policies before
        opening the write transaction. Refusal files FAILED instead; Python acceptance is not Java approval.
        """
        kind, status, payload, result = verified_callback(claimed, result)
        finished = now or dt.datetime.now(dt.UTC)
        with self.database.connection() as connection, connection.transaction():
            # Lock waiting consumes lease time: read the clock only after owning the row.
            connection.execute("SELECT run_id FROM agent_run WHERE run_id=%s FOR UPDATE",
                               (claimed.facts.run_id,)).fetchone()
            updated = connection.execute(
                """
                UPDATE agent_run
                SET status = %(status)s, updated_at = %(now)s, version = version + 1,
                    budget_spent = CASE WHEN %(fence)s::bigint IS NOT NULL THEN
                        jsonb_set(budget_spent, '{no_progress_rounds}', to_jsonb(%(no_progress)s::int))
                        ELSE budget_spent END
                WHERE run_id = %(run_id)s AND status = %(running)s AND cancelled_at IS NULL
                  AND ((%(fence)s::bigint IS NULL AND fence IS NULL) OR
                       (fence=%(fence)s AND lease_owner=%(owner)s AND lease_until>clock_timestamp()))
                RETURNING run_id
                """,
                {"status": status, "now": finished, "run_id": claimed.facts.run_id, "running": RUNNING,
                 "fence": claimed.facts.fence, "owner": claimed.facts.lease_owner,
                 "no_progress": result.spend.no_progress_rounds if claimed.facts.fence is not None else 0},
            ).fetchone()
            if updated is None:
                current = connection.execute(
                    "SELECT status FROM agent_run WHERE run_id = %(run_id)s",
                    {"run_id": claimed.facts.run_id},
                ).fetchone()
                return RunOutcome(
                    run_id=claimed.facts.run_id,
                    status=str(current["status"]) if current is not None else "MISSING",
                    callback_kind=None,
                    result=result,
                )
            self.callbacks.enqueue_for_run(
                claimed.facts.run_id,
                CallbackEnvelope(kind=kind, payload=payload),
                connection=connection,
            )
        return RunOutcome(run_id=claimed.facts.run_id, status=status, callback_kind=kind.value, result=result)

    def run_once(self, *, now: dt.datetime | None = None) -> RunOutcome | None:
        """Claim one run, investigate it, and finish it. ``None`` means the queue was empty."""
        if self.recoverable:
            return self._recoverable_once()
        claimed = self.claim_one(now=now)
        if claimed is None:
            return None
        return self.finish(claimed, self.investigate(claimed.facts))

    def _recoverable_once(self) -> RunOutcome | None:
        # Local import avoids the lease's dependency on the claim vocabulary.
        from resolveflow.harness.budget import BudgetExhaustedError, RunSpend
        from resolveflow.harness.live_model import ModelRefusedError, ModelUnavailableError
        from resolveflow.runtime.durable import ModelRetryExhaustedError
        from resolveflow.runtime.leases import RunLease
        from resolveflow.runtime.recovery_budget import RecoveryCallBudgetExhausted
        from resolveflow.runtime.recovery_store import RecoveryConflictError, StaleFenceError

        with RunLease(self.database).acquire() as claimed:
            if claimed is None:
                return None
            reason = None
            try:
                if claimed.legacy:
                    reason = "MIGRATION_REQUIRED"
                elif dt.datetime.fromisoformat(claimed.facts.active_deadline_at or "") <= dt.datetime.now(dt.UTC):
                    reason = "BUDGET_DEADLINE"
                else:
                    return self.finish(claimed, self.investigate(claimed.facts))
            except ModelUnavailableError:
                # Leave UNKNOWN charged and RUNNING reclaimable. The resident loop remains alive.
                return RunOutcome(claimed.facts.run_id, RUNNING, None, None)
            except ModelRefusedError:
                reason = "MODEL_REFUSED"
            except ModelRetryExhaustedError:
                reason = "MODEL_RETRY_EXHAUSTED"
            except RecoveryConflictError:
                reason = "MIGRATION_REQUIRED"
            except RecoveryCallBudgetExhausted:
                reason = "BUDGET_MODEL_CALLS"
            except BudgetExhaustedError as error:
                reason = error.reason_code
            except StaleFenceError:
                # An expired deadline is terminal; a lost owner cannot publish a callback.
                reason = "BUDGET_DEADLINE" if dt.datetime.fromisoformat(
                    claimed.facts.active_deadline_at or ""
                ) <= dt.datetime.now(dt.UTC) else "STALE_FENCE"
            with self.database.connection() as connection:
                row = connection.execute("SELECT budget_spent FROM agent_run WHERE run_id=%s",
                                         (claimed.facts.run_id,)).fetchone()
            result = RunResult(False, reason or "MIGRATION_REQUIRED", None, (),
                               RunSpend(**row["budget_spent"]) if row else RunSpend())
            return self.finish(claimed, result)

    def drain(self, *, limit: int = 1, now: dt.datetime | None = None) -> list[RunOutcome]:
        """Investigate up to ``limit`` runs. The loop is the SDK's per run and this is the one around it."""
        outcomes: list[RunOutcome] = []
        for _ in range(max(0, limit)):
            outcome = self.run_once(now=now)
            if outcome is None:
                break
            outcomes.append(outcome)
        return outcomes


def _active_deadline(deadline_at: dt.datetime, started: dt.datetime) -> dt.datetime:
    """``min(queued deadline, start + the spec's ceiling)`` — never an extension of the queued deadline.

    ``docs/agent-spec.md:42``: recovery must not extend the deadline, so the granted window is the *smaller* of the
    two. A grant that could exceed ``deadline_at`` would let a worker hold a case past the window the dispatch
    published.
    """
    return min(deadline_at, started + dt.timedelta(seconds=MAX_ACTIVE_DEADLINE_SECONDS))


def _callback_of(result: RunResult) -> tuple[CallbackKind, str]:
    """Which callback an outcome owes, and the status that follows from it.

    A ``PROPOSE`` awaits Java's review, so ``CALLBACK_PENDING``. A question awaits the **case service's receipt**
    before it awaits the customer: ``docs/agent-spec.md:9`` says QUESTION接收后WAITING_INPUT, so a filed question is
    ``CALLBACK_PENDING`` too and ``RunStore.apply_callback_disposition`` is what moves it on. Everything else — a
    refusal, an exhausted budget, a stopped loop — is reported as ``FAILED`` with the run's own reason code, because
    a run that produced no proposal and no question has nothing for the case service to act on.
    """
    decision = result.decision
    kind = str(getattr(decision, "kind", "") or "")
    if kind == "PROPOSE":
        return CallbackKind.PROPOSAL, CALLBACK_PENDING
    if kind == "ASK_CUSTOMER":
        return CallbackKind.QUESTION, CALLBACK_PENDING
    return CallbackKind.FAILED, FAILED


def verified_callback(claimed: ClaimedRun, result: RunResult) -> tuple[CallbackKind, str, dict[str, Any], RunResult]:
    """The production terminal rule, also used by strict replay's local sink."""
    kind, status = _callback_of(result)
    payload = callback_payload(kind, claimed, result)
    if kind is CallbackKind.PROPOSAL:
        verification = ProposalVerifier(
            observations=result.observations,
            review_context=claimed.facts.review_context,
            case_id=claimed.facts.case_id,
            input_revision=claimed.facts.input_revision,
            pinned_bundle_ids=frozenset(
                str(bundle) for bundle in (claimed.facts.policy_manifest.get("bundle_ids") or [])
            ),
        ).verify_proposal(payload)
        if not verification.ok:
            result = replace(result, completed=False, reason_code=verification.reason_codes[0])
            kind, status = CallbackKind.FAILED, FAILED
            payload = callback_payload(kind, claimed, result)
    return kind, status, payload, result


def _proposal_id(run_id: str) -> str:
    """A **uuid** derived from the run, because the contract types ``proposal_id`` as one.

    Derived rather than random for the same reason the ``callback_id`` is: a repeated pass over one run must compute
    the same proposal, or the case service would hold two proposals for one investigation.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"resolveflow:proposal:{run_id}"))


def _question_id(run_id: str) -> str:
    """The stable id of the aggregated question, derived from the run (``maxLength: 64``)."""
    return f"question-{run_id}"


def callback_payload(kind: CallbackKind, claimed: ClaimedRun, result: RunResult) -> dict[str, Any]:
    """The callback body, in the shape ``contracts/core`` requires for each kind.

    Ids are **derived from the run**, so a repeated pass over the same run computes the same ones and the outbox's
    idempotency on ``callback_id`` is joined by idempotency on the payload. Nothing here is invented from the model's
    free text except the proposal's own ``summary``, which is the proposal.
    """
    decision = result.decision
    facts = claimed.facts
    if kind is CallbackKind.PROPOSAL:
        # `ProposalPayload`'s runtime bindings plus the candidate's declared members:
        # the component is `additionalProperties: false`, and `run_id`/`case_id`/`input_revision` are carried so Java
        # can cross-check the body against the service token and the Case binding rather than trust a copy.
        payload: dict[str, Any] = {
            "schema_version": 2,
            "proposal_id": _proposal_id(facts.run_id),
            "run_id": facts.run_id,
            "case_id": facts.case_id,
            "input_revision": facts.input_revision,
            "case_type": str(getattr(decision, "case_type", "") or ""),
            "recommended_action": str(getattr(decision, "recommended_action", "") or ""),
            "reason_codes": list(getattr(decision, "reason_codes", []) or []),
        }
        summary = getattr(decision, "summary", None)
        if summary:
            payload["summary"] = str(summary)
        missing = list(getattr(decision, "missing_evidence", []) or [])
        if missing:
            payload["missing_evidence"] = missing
        findings = getattr(decision, "review_findings", []) or []
        if findings:
            payload["review_findings"] = [finding.model_dump(mode="json") for finding in findings]
        for member in ("evidence_refs", "policy_refs"):
            refs = getattr(decision, member, []) or []
            if refs:
                payload[member] = [ref.model_dump(mode="json") for ref in refs]
        return payload
    if kind is CallbackKind.QUESTION:
        # Exactly `QuestionPayload`: `question_id`, `questions` (each an `AgentQuestion`: `field` + `prompt`) and an
        # optional `reason_codes`. No `schema_version`, no `summary` — both would be refused as undeclared members.
        return {
            "question_id": _question_id(facts.run_id),
            "questions": [
                {"field": question.field, "prompt": question.prompt}
                for question in getattr(decision, "questions", []) or []
            ],
            "reason_codes": list(getattr(decision, "reason_codes", []) or []),
        }
    # FAILED: the run's own reason code, and "not retryable" because the harness stopping is a decision about this
    # input, not a transient fault. A retryable failure (a tool outage the model could route around) is the model's
    # to make inside the run, and the run's budget is what bounds it. Exactly `FailedPayload`'s members and no more:
    # the component is `additionalProperties: false`, so an invented `schema_version` would be a refusal.
    codes = [result.reason_code]
    if result.completed and getattr(decision, "kind", None) == "ESCALATE":
        # A genuine model handover finished investigation, but COMPLETED is not why Case needs a human.
        codes = list(decision.reason_codes) or ["NEEDS_HUMAN_VERIFICATION"]
    return {"reason_codes": codes, "retryable": False}
