"""The durable run record: what ``POST /internal/v1/runs`` accepts, and what it means (C06.1).

A run is one investigation of one case revision (docs/agent-spec.md:9). C06.1 makes the *record* real:
the run is committed before the caller is told 202 (docs/core-contracts.md:38), the same
``(case_id, input_revision)`` never becomes two runs, and a redelivered dispatch is the same run rather
than a second investigation. Nothing here starts an investigation — no worker, no model client, no tool
call exists yet — and that is the point of this slice: a run can be queued reliably before there is
anything to run it.

Three decisions are worth stating, because each one could reasonably have gone the other way:

**The body identity is checked here, not only at the edge.** docs/core-contracts.md:60 requires the body to
agree with the service token *and* the case binding. The token half is the API layer's job (it holds the
`ServiceIdentity`); the "is this row what this caller may create" half is a property of the record, so
:meth:`RunStore.queue` takes the verified identity and refuses a body that names another merchant's line.
That refusal is a 422 (the body is not a run), not a 409 (the key is spent).

**The request hash is computed from a canonical form.** "Same key, different body" has to be decidable, and
deciding it by comparing surfaces means two spellings of one request are two requests. The hash is taken
over the members that define the dispatch — not over the raw JSON, whose key order and whitespace are the
sender's business — so a redelivery that re-serialises the same request is recognised as the same request.

**Absence is spelled NULL.** ``active_deadline_at``, the lease columns and ``cancelled_at`` are NULL until
something actually does those things. A placeholder would claim a worker had started or a window had been
granted; the columns exist now because the schema is append-only (docs/engineering.md:77), and being empty
is the truthful value (docs/domain-model.md:59's rule about states that must not outlive their facts).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Final

from resolveflow.runtime.db import Database, reuse_or_open
from resolveflow.contracts.reviewer_input import ReviewerInput

#: The run vocabulary, fixed by docs/agent-spec.md:9 and mirrored in
#: ``contracts/core/openapi-agent.yaml``'s ``RunView.status``. ANALYZING is a *case* state and is
#: deliberately absent: a run does not borrow the case's words.
RUN_STATUSES: Final[tuple[str, ...]] = (
    "QUEUED",
    "RUNNING",
    "CALLBACK_PENDING",
    "WAITING_INPUT",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "STALE",
)

#: The only status a newly accepted run can hold (``RunAccepted.status`` is ``const: QUEUED``).
QUEUED: Final = "QUEUED"

#: What an unfinished run becomes when a newer revision of its case is dispatched: its result can no longer be
#: applied (``docs/agent-spec.md:9`` — 补证创建新revision/new run，旧run STALE).
STALE: Final = "STALE"

#: What ``CancelAck.status`` may say: the status the run actually holds afterwards
#: (contracts/core/openapi-agent.yaml:528). Narrower than ``RUN_STATUSES`` on purpose — answering
#: RUNNING to a cancellation would be a lie.
TERMINAL_STATUSES: Final[tuple[str, ...]] = ("COMPLETED", "FAILED", "CANCELLED")

#: The only action a core case can request (``RequestedAction`` is ``enum: [REFUND]``).
REQUESTED_ACTIONS: Final[tuple[str, ...]] = ("REFUND",)

#: Reason codes on a refusal, so a caller and a test can name what was wrong instead of matching prose.
REJECTED_IDENTITY_MISMATCH: Final = "IDENTITY_MISMATCH"
REJECTED_UNKNOWN_ACTION: Final = "UNKNOWN_ACTION"
REJECTED_BAD_BODY: Final = "BAD_BODY"

_UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_TRACEPARENT_PATTERN = re.compile(r"^00-[a-f0-9]{32}-[a-f0-9]{16}-[a-f0-9]{2}$")
#: A deadline is a UTC instant on the wire (docs/core-contracts.md:17).
_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")


class RunRefusedError(RuntimeError):
    """A dispatch this service will not turn into a run. The API layer maps it to its own status."""

    #: The HTTP status the contract declares for this refusal (422 for a body that is not a run).
    status_code = 422
    #: The reason code, which is what a caller should branch on.
    reason_code = REJECTED_BAD_BODY

    def __init__(self, message: str, *, reason_code: str | None = None) -> None:
        super().__init__(message)
        if reason_code is not None:
            self.reason_code = reason_code


class RunIdentityMismatchError(RunRefusedError):
    """The body names a merchant, customer, order or line the verified caller did not present.

    docs/core-contracts.md:60: "body主体必须与service JWT及Case绑定一致". This is the whole point of
    sending the context in the body rather than letting the run read whatever it likes: a run that could
    name someone else's line would be an investigation of someone else's order.
    """

    status_code = 422
    reason_code = REJECTED_IDENTITY_MISMATCH


class RunConflictError(RunRefusedError):
    """The run key is already used, by this run with a different body or by another run for the revision.

    Neither is a retry: the contract answers 409 (contracts/core/openapi-agent.yaml:105) and nothing is
    overwritten. The two cases are told apart by the message, because only the caller can act on which one
    it hit.
    """

    status_code = 409


class RunNotFoundError(LookupError):
    """No run with that id. A 404, and never an empty run."""

    status_code = 404


@dataclass(frozen=True, slots=True)
class VerifiedCaller:
    """The identity behind a verified service token, as the run store needs it.

    The API layer builds this from the token; the store never sees the raw token. ``scope`` is carried as the
    raw claim for the record, and ``merchant_id``/``buyer_id`` are what docs/core-contracts.md:60 means by
    "the body must agree with the service token": a dispatch may only name the subjects its own token was
    minted for.

    **Where the scope is enforced.** Not here. A ``require_run_scope`` method used to sit on this dataclass
    comparing ``self.scope != required`` — the same whole-string equality that AS02.3 fixed in
    ``ServiceTokenVerifier``, and wrong for the same reason (a claim carrying two scopes would satisfy
    nothing). Rather than repair it in a second place, it and the ``RunScopeError`` it raised are deleted:
    the check belongs where the token is verified (``ServiceTokenVerifier``, asked per route), and two
    implementations of one rule is how the two ends drift. Nothing called it, so nothing replaces it.
    """

    service: str
    scope: str | None = None
    merchant_id: str | None = None
    buyer_id: str | None = None

@dataclass(frozen=True, slots=True)
class RunRequest:
    """One dispatch, validated. Field set fixed by docs/core-contracts.md:60.

    The dataclass is flat where the wire is nested (``context``/``request``) because the flat form is what
    the row stores and what every reader compares; the nesting is a wire spelling, and re-deriving it at
    each use would put the wire's shape inside the record.
    """

    run_id: str
    case_id: str
    input_revision: int
    merchant_id: str
    buyer_id: str
    order_id: str
    line_id: str
    description: str
    requested_actions: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    policy_manifest: dict[str, Any]
    deadline_at: str
    traceparent: str | None = None
    review_context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_uuid("run_id", self.run_id)
        _require_uuid("case_id", self.case_id)
        _require_uuid("order_id", self.order_id)
        if not isinstance(self.input_revision, int) or isinstance(self.input_revision, bool):
            raise RunRefusedError("input_revision must be an integer")
        if self.input_revision < 1:
            raise RunRefusedError("input_revision starts at 1; there is no revision 0")
        for member in ("merchant_id", "buyer_id", "line_id"):
            value = getattr(self, member)
            if not isinstance(value, str) or not value or len(value) > 64:
                raise RunRefusedError(f"{member} must be 1-64 characters")
        if not isinstance(self.description, str) or not self.description or len(self.description) > 4000:
            raise RunRefusedError("description must be 1-4000 characters")
        if not self.requested_actions:
            raise RunRefusedError("at least one requested action is required")
        unknown = [action for action in self.requested_actions if action not in REQUESTED_ACTIONS]
        if unknown:
            raise RunRefusedError(
                f"core cases request only {list(REQUESTED_ACTIONS)}; refusing {unknown}",
                reason_code=REJECTED_UNKNOWN_ACTION,
            )
        if len(set(self.requested_actions)) != len(self.requested_actions):
            raise RunRefusedError("the requested actions must be distinct")
        if len(self.evidence_refs) > 64:
            raise RunRefusedError("at most 64 evidence refs may be carried")
        for ref in self.evidence_refs:
            if not isinstance(ref, str) or not ref or len(ref) > 200:
                raise RunRefusedError("an evidence ref must be 1-200 characters")
        self._check_manifest()
        if not isinstance(self.deadline_at, str) or not _TIMESTAMP_PATTERN.match(self.deadline_at):
            raise RunRefusedError("deadline_at must be an ISO-8601 UTC instant")
        _parse_instant(self.deadline_at)
        if self.traceparent is not None and not _TRACEPARENT_PATTERN.match(self.traceparent):
            raise RunRefusedError("traceparent is not a W3C traceparent")
        if self.review_context:
            snapshot = ReviewerInput.model_validate(self.review_context)
            if any(item.input_revision > self.input_revision for item in [*snapshot.materials, *snapshot.questions]):
                raise RunRefusedError("review_context must not include a future revision")
            if any(item.evidence_id not in self.evidence_refs for item in snapshot.materials):
                raise RunRefusedError("review_context materials must belong to this dispatch's evidence_refs")

    def _check_manifest(self) -> None:
        manifest = self.policy_manifest
        if not isinstance(manifest, dict):
            raise RunRefusedError("policy_manifest must be an object")
        # The merchant the pin was selected for (C07.1). Required, and deliberately **not** defaulted from
        # ``self.merchant_id``: the record stores the pin as the dispatcher sent it, and a default would let
        # a dispatch with no merchant be stored as one whose pin silently agrees with the context. The two
        # must agree, so that is checked rather than assumed.
        pinned_merchant = manifest.get("merchant_id")
        if not isinstance(pinned_merchant, str) or not pinned_merchant or len(pinned_merchant) > 64:
            raise RunRefusedError("policy_manifest.merchant_id must be 1-64 characters (C07.1)")
        if pinned_merchant != self.merchant_id:
            raise RunRefusedError(
                "policy_manifest.merchant_id must be the run's own merchant: a run cannot be pinned to "
                "another merchant's policy set"
            )
        bundles = manifest.get("bundle_ids")
        if not isinstance(bundles, list) or not bundles or len(bundles) > 16:
            raise RunRefusedError("policy_manifest.bundle_ids must carry 1-16 bundle ids")
        for bundle in bundles:
            if not isinstance(bundle, str) or not bundle or len(bundle) > 64:
                raise RunRefusedError("a policy bundle id must be 1-64 characters")
        if not isinstance(manifest.get("manifest_hash"), str) or not _SHA256_PATTERN.match(manifest["manifest_hash"]):
            raise RunRefusedError("policy_manifest.manifest_hash must be a sha-256 hex digest")
        epoch = manifest.get("safety_epoch")
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
            raise RunRefusedError("policy_manifest.safety_epoch must be a non-negative integer")

    def content_hash(self) -> str:
        """The canonical hash that decides "same body" (and therefore 409 versus a redelivery).

        It covers exactly the members that define the dispatch. ``deadline_at`` is one of them: two
        dispatches that differ only in the deadline are genuinely different requests, and pretending
        otherwise would let a retry silently move a queued deadline (docs/agent-spec.md:42).
        """
        return hashlib.sha256(self._canonical_form().encode("utf-8")).hexdigest()

    def _canonical_form(self) -> str:
        return json.dumps(
            {
                "run_id": self.run_id,
                "case_id": self.case_id,
                "input_revision": self.input_revision,
                "context": {
                    "merchant_id": self.merchant_id,
                    "buyer_id": self.buyer_id,
                    "order_id": self.order_id,
                    "line_id": self.line_id,
                },
                "request": {
                    "description": self.description,
                    "requested_actions": sorted(self.requested_actions),
                    "evidence_refs": sorted(self.evidence_refs),
                    **({"review_context": self.review_context} if self.review_context else {}),
                },
                "policy_manifest": {
                    "merchant_id": self.policy_manifest["merchant_id"],
                    "bundle_ids": sorted(self.policy_manifest["bundle_ids"]),
                    "manifest_hash": self.policy_manifest["manifest_hash"],
                    "safety_epoch": self.policy_manifest["safety_epoch"],
                },
                "deadline_at": _parse_instant(self.deadline_at).isoformat(),
                "traceparent": self.traceparent,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class RunAccepted:
    """``RunAccepted``: the answer to an accepted dispatch, built from the committed row."""

    run_id: str
    status: str


@dataclass(frozen=True, slots=True)
class RunView:
    """``RunView``: what case-service reconciles against. Never raw model text, never credentials."""

    run_id: str
    case_id: str
    input_revision: int
    status: str
    version: int
    callback_ids: tuple[str, ...] = ()
    result_summary: str | None = None


@dataclass(frozen=True, slots=True)
class CancelAck:
    """``CancelAck``: what the run actually holds after the request."""

    run_id: str
    status: str
    cancellation_requested: bool


class RunStore:
    """The run records, over :class:`~resolveflow.runtime.db.Database`.

    Every method is one transaction's worth of work and nothing here holds a connection open across a
    network call: the dispatch is decided before the store is called and the store only records it
    (docs/agent-harness.md:27 — 网络期间不持有长业务事务).
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    @property
    def database(self) -> Database:
        return self._database

    def queue(self, request: RunRequest, *, caller: VerifiedCaller | None = None) -> RunAccepted:
        """Accept a dispatch, or explain why it is already spent.

        Returns the committed row's status, so a 202 means exactly "this is in the database"
        (docs/core-contracts.md:38). The lookup-then-insert order is deliberate: the lookup is what turns
        a redelivery into the same answer, and the unique index behind it is what makes two simultaneous
        dispatches impossible rather than unlikely.
        """
        request_hash = request.content_hash()
        with self._database.connection() as connection:
            existing = self._load_by_identity(connection, request)
            if existing is not None:
                return self._resolve_existing(connection, existing, request, request_hash)
            if caller is not None:
                _require_body_agrees_with_caller(request, caller)
            connection.execute(
                """
                INSERT INTO agent_run (
                    run_id, case_id, input_revision, merchant_id, buyer_id, order_id, line_id,
                    request_hash, request_description, requested_actions, evidence_refs,
                    policy_manifest, review_context, traceparent, status, version, deadline_at, created_at, updated_at
                ) VALUES (
                    %(run_id)s, %(case_id)s, %(input_revision)s, %(merchant_id)s, %(buyer_id)s,
                    %(order_id)s, %(line_id)s, %(request_hash)s, %(description)s, %(actions)s,
                    %(evidence_refs)s, %(policy_manifest)s::jsonb, %(review_context)s::jsonb, %(traceparent)s, %(status)s, 1,
                    %(deadline_at)s, %(now)s, %(now)s
                )
                """,
                {
                    "run_id": request.run_id,
                    "case_id": request.case_id,
                    "input_revision": request.input_revision,
                    "merchant_id": request.merchant_id,
                    "buyer_id": request.buyer_id,
                    "order_id": request.order_id,
                    "line_id": request.line_id,
                    "request_hash": request_hash,
                    "description": request.description,
                    "actions": list(request.requested_actions),
                    "evidence_refs": list(request.evidence_refs),
                    "policy_manifest": json.dumps(request.policy_manifest, sort_keys=True),
                    "review_context": json.dumps(request.review_context, sort_keys=True, ensure_ascii=False),
                    "traceparent": request.traceparent,
                    "status": QUEUED,
                    "deadline_at": _parse_instant(request.deadline_at),
                    "now": dt.datetime.now(dt.UTC),
                },
            )
            self._supersede_older_revisions(connection, request, now=dt.datetime.now(dt.UTC))
        return RunAccepted(run_id=request.run_id, status=QUEUED)

    def _supersede_older_revisions(
        self, connection: Any, request: RunRequest, *, now: dt.datetime
    ) -> list[str]:
        """A newer revision of a case makes the older revision's unfinished run unapplicable.

        ``docs/agent-spec.md:9``: 补证创建新revision/new run，旧run STALE. The new run is this dispatch, so this is
        where that happens — and it happens **in the dispatch's own transaction**, because the invariant is "a case
        has at most one run that can still produce a result". Doing it anywhere else would leave a window in which
        two runs of one case could both believe they are current.

        **Only non-terminal runs are superseded.** ``COMPLETED`` means the proposal callback was accepted
        (``docs/agent-spec.md:9``: it does not mean the refund succeeded) — that acceptance already happened and
        rewriting it to ``STALE`` would erase a fact. That the *proposal* is no longer applicable belongs to the
        case service's own ``case_proposal`` row (``docs/domain-model.md:57``), not to the agent's record of what it
        did. ``FAILED`` and ``CANCELLED`` runs are already finished for their own reasons, and a cancelled run must
        not have its cancellation relabelled.

        The superseded run's undelivered callbacks are closed in the same transaction: a question or proposal for a
        revision the case has moved past must not be handed to the case service at all
        (``docs/agentscope-migration.md:68`` — 终局方案、run状态和callback_outbox在同一事务提交).
        """
        # Imported here rather than at module scope: `callbacks` imports `_require_uuid` from this module, so a
        # module-level import would be a cycle whose behaviour depends on which one is imported first.
        from resolveflow.runtime.callbacks import CallbackStore

        superseded = connection.execute(
            """
            UPDATE agent_run
            SET status = %(stale)s, updated_at = %(now)s, version = version + 1
            WHERE case_id = %(case_id)s
              AND input_revision < %(revision)s
              AND status <> ALL(%(terminal)s)
              AND status <> %(stale)s
            RETURNING run_id
            """,
            {
                "stale": STALE,
                "now": now,
                "case_id": request.case_id,
                "revision": request.input_revision,
                "terminal": list(TERMINAL_STATUSES),
            },
        ).fetchall()
        store = CallbackStore(self._database)
        for row in superseded:
            store.void_pending_for_run(
                str(row["run_id"]),
                reason=f"SUPERSEDED_BY_REVISION:{request.input_revision}",
                connection=connection,
            )
        return [str(row["run_id"]) for row in superseded]

    def apply_callback_disposition(
        self, run_id: str, *, kind: str, disposition: str, connection: Any = None
    ) -> str | None:
        """The case service's answer decides what the run's own status becomes, and returns the status it left.

        ``docs/agent-spec.md:9`` makes *receipt* the event, not filing: **COMPLETED表示方案回调被Case接收** and
        **QUESTION接收后WAITING_INPUT**. A run whose terminal callback is merely filed is therefore
        ``CALLBACK_PENDING``, and this is what moves it on:

        ==========  ====================  ==================
        callback    answer                run status
        ==========  ====================  ==================
        PROPOSAL    ACCEPTED / DUPLICATE  COMPLETED
        QUESTION    ACCEPTED / DUPLICATE  WAITING_INPUT
        FAILED      ACCEPTED / DUPLICATE  FAILED
        any         STALE                 STALE
        ==========  ====================  ==================

        ``DUPLICATE`` means the same thing as ``ACCEPTED`` here: the case service applied this callback once and has
        it (``docs/contracts.md:80``), so the run's status must not depend on how many times the network needed
        telling. ``STALE`` is the case service saying the message is about a revision that is no longer current, or
        that a human took the case over (``docs/core-contracts.md:62``): the run becomes ``STALE`` for the same
        reason a superseding dispatch would have made it.

        Written as a conditional update, so a run that is already terminal or cancelled is left alone — an answer
        arriving after a cancellation cannot resurrect the run, and a redelivery cannot rewrite a status the run
        already reached. ``None`` means this answer changed nothing; the status it left is read back only to say so.
        """
        target = _status_for_answer(kind, disposition)
        if target is None:
            return None
        with reuse_or_open(self._database, connection) as opened:
            row = opened.execute(
                """
                UPDATE agent_run
                SET status = %(status)s, updated_at = %(now)s, version = version + 1
                WHERE run_id = %(run_id)s
                  AND status <> ALL(%(terminal)s)
                  AND status <> %(stale)s
                RETURNING status
                """,
                {
                    "status": target,
                    "now": dt.datetime.now(dt.UTC),
                    "run_id": run_id,
                    "terminal": list(TERMINAL_STATUSES),
                    "stale": STALE,
                },
            ).fetchone()
        return str(row["status"]) if row is not None else None

    def read(self, run_id: str) -> RunView:
        """The run as case-service reconciles it (docs/core-contracts.md:39)."""
        _require_uuid("run_id", run_id, not_found=True)
        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT run_id, case_id, input_revision, status, version, result_summary
                FROM agent_run WHERE run_id = %(run_id)s
                """,
                {"run_id": run_id},
            ).fetchone()
            if row is None:
                raise RunNotFoundError(f"no run with id {run_id}")
            # Read in the same transaction as the row, so the view cannot report a run without the
            # callbacks it has already emitted: a reconciliation that ran between the two reads would
            # otherwise see a state that never existed (docs/core-contracts.md:39).
            callbacks = connection.execute(
                """
                SELECT callback_id FROM agent_callback_outbox
                WHERE run_id = %(run_id)s ORDER BY created_at
                """,
                {"run_id": run_id},
            ).fetchall()
        return RunView(
            run_id=str(row["run_id"]),
            case_id=str(row["case_id"]),
            input_revision=int(row["input_revision"]),
            status=str(row["status"]),
            version=int(row["version"]),
            # What the Agent has actually emitted, in emission order — the ids case-service de-duplicates
            # on, not a count and not a placeholder (contracts/core/openapi-agent.yaml:509).
            callback_ids=tuple(str(item["callback_id"]) for item in callbacks),
            result_summary=row["result_summary"],
        )

    def cancel(self, run_id: str) -> CancelAck:
        """Stop a run, or report the terminal state it already reached.

        Cancellation is recorded even for a run that has not started: the row exists from accept time, so
        "never investigate this" must be answerable before a worker ever looks at it. A run that already
        finished is *not* relabelled — ``CancelAck`` says which terminal state it holds.
        """
        _require_uuid("run_id", run_id, not_found=True)
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT run_id, status FROM agent_run WHERE run_id = %(run_id)s",
                {"run_id": run_id},
            ).fetchone()
            if row is None:
                raise RunNotFoundError(f"no run with id {run_id}")
            current = str(row["status"])
            if current in TERMINAL_STATUSES:
                return CancelAck(run_id=run_id, status=current, cancellation_requested=False)
            connection.execute(
                """
                UPDATE agent_run
                SET status = 'CANCELLED', version = version + 1, cancelled_at = %(now)s, updated_at = %(now)s
                WHERE run_id = %(run_id)s
                """,
                {"run_id": run_id, "now": dt.datetime.now(dt.UTC)},
            )
        return CancelAck(run_id=run_id, status="CANCELLED", cancellation_requested=True)

    def _load_by_identity(self, connection: Any, request: RunRequest) -> dict[str, Any] | None:
        """The row this dispatch collides with, if there is one.

        Two identities mean the same run: the run id the caller derived, and the ``(case_id,
        input_revision)`` pair it was derived from. Both are looked up, because a caller that derived a
        different id for a revision that already has a run must be told, not allowed to open a second
        investigation.
        """
        row: dict[str, Any] | None = connection.execute(
            """
            SELECT run_id, case_id, input_revision, request_hash, status
            FROM agent_run
            WHERE run_id = %(run_id)s
               OR (case_id = %(case_id)s AND input_revision = %(input_revision)s)
            """,
            {
                "run_id": request.run_id,
                "case_id": request.case_id,
                "input_revision": request.input_revision,
            },
        ).fetchone()
        return row

    def _resolve_existing(
        self,
        connection: Any,
        existing: dict[str, Any],
        request: RunRequest,
        request_hash: str,
    ) -> RunAccepted:
        same_run = str(existing["run_id"]) == request.run_id
        if same_run and str(existing["request_hash"]) == request_hash:
            # A redelivery of one dispatch. The answer is the committed row's, not a rebuilt guess.
            return RunAccepted(run_id=request.run_id, status=str(existing["status"]))
        if same_run:
            raise RunConflictError(f"run {request.run_id} was already used with a different request body")
        raise RunConflictError(
            f"case {request.case_id} revision {request.input_revision} already has run "
            f"{existing['run_id']}; one revision is one investigation"
        )


def _require_body_agrees_with_caller(request: RunRequest, caller: VerifiedCaller) -> None:
    """The token's own subjects are the only ones the body may name.

    docs/core-contracts.md:60: "body主体必须与service JWT及Case绑定一致". A service token carries no
    ownership of its own — it is not a user token — so what it can be checked against is the identity it
    was minted for. The dispatched context is exactly that identity: case-service derived it from the
    verified principal and then minted the run token for it. A body that disagrees is refused before any
    row exists, because storing it would create an investigation of someone else's order.
    """
    expected_service = "case-service"
    if caller.service != expected_service:
        raise RunIdentityMismatchError(
            f"the run dispatcher is {expected_service}; this token's subject is {caller.service}"
        )
    for member, claimed in (("merchant_id", caller.merchant_id), ("buyer_id", caller.buyer_id)):
        presented = getattr(request, member)
        if claimed is not None and presented != claimed:
            raise RunIdentityMismatchError(
                f"the body names {member} {presented}, but this token was minted for {claimed}"
            )


def _status_for_answer(kind: str, disposition: str) -> str | None:
    """What the case service's answer makes of the run, or ``None`` when it changes nothing.

    A ``STARTED`` acknowledgement changes nothing: the run was moved to ``RUNNING`` by the claim that filed it, and
    the answer only confirms what the worker already recorded.
    """
    if disposition == "STALE":
        return STALE
    if disposition not in ("ACCEPTED", "DUPLICATE"):
        return None
    if kind == "PROPOSAL":
        return "COMPLETED"
    if kind == "QUESTION":
        return "WAITING_INPUT"
    if kind == "FAILED":
        return "FAILED"
    return None


def _require_uuid(member: str, value: object, *, not_found: bool = False) -> None:
    if not isinstance(value, str) or not _UUID_PATTERN.match(value):
        message = f"{member} is not a uuid"
        if not_found:
            # A malformed id cannot name an existing run, and answering 404 is the honest answer: it is
            # the same answer a caller gets for an id that is well formed and unknown.
            raise RunNotFoundError(message)
        raise RunRefusedError(message)


def _parse_instant(value: str) -> dt.datetime:
    """Parse an ISO-8601 instant, tolerating the ``Z`` the wire allows and Python's 3.12 parser does not."""
    normalised = value.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(normalised)
    except ValueError as error:
        raise RunRefusedError(f"deadline_at is not an instant: {value}") from error
    if parsed.tzinfo is None:
        raise RunRefusedError("deadline_at must carry a UTC offset")
    return parsed


#: The namespace run ids are derived under, character for character as ``AgentRunId.java`` declares it.
#:
#: It is written here rather than taken from :mod:`uuid`'s ``NAMESPACE_DNS``/``NAMESPACE_URL`` because the Java
#: side mints its own, and the namespace literal is *part* of the derivation: two implementations that agreed on
#: the algorithm but not on the namespace would produce two plausible v5 ids that never match. That is not a bug
#: that announces itself — the credential route would answer 404 for a run Case really holds, and the symptom
#: would read as "the run does not exist" rather than as "Python derived a different id".
RUN_NAMESPACE = "6b3f2c1a-9d4e-5f60-8a71-2c3d4e5f6a7b"


def agent_run_id_for(case_id: str, input_revision: int) -> str:
    """The run id Case derives for one case revision (``AgentRunId.forRevision``).

    Python has to be able to derive this for the two paths where Case's dispatch loop is not what produced the
    run: a probe or driver that talks to the credential route directly, and C09's worker, which will read the run
    id Case already wrote. Deriving rather than generating is the whole point — ``docs/core-contracts.md:38``
    makes a redelivered dispatch the *same* run, and an id invented per attempt would open a second
    investigation for one revision.

    **This is the same function Case runs, not a second opinion about it.** It is RFC 9562 version 5 with the
    version and variant bits set, over ``namespace:case_id:revision`` as UTF-8, using
    :data:`RUN_NAMESPACE`. :func:`uuid.uuid5` is deliberately **not** used: it is the same algorithm but under a
    namespace of the caller's choosing, and the obvious-looking ``uuid.NAMESPACE_DNS`` would produce an id Case
    has never heard of. ``test_tool_credential.py`` pins this against the namespace literal parsed out of
    ``AgentRunId.java``, so the two files cannot drift apart silently.
    """
    if not case_id or not case_id.strip():
        raise RunRefusedError("a case id is required to derive a run id")
    if not isinstance(input_revision, int) or isinstance(input_revision, bool) or input_revision < 1:
        raise RunRefusedError(f"input_revision must be at least 1, got {input_revision!r}")
    name = f"{RUN_NAMESPACE}:{case_id}:{input_revision}".encode()
    # SHA-1 is 20 bytes and a UUID is 16, so the **first 16** bytes are kept — the same truncation
    # ``UUID.nameUUIDFromBytes`` and ``uuid.uuid5`` perform. Taking all 20 is a real mistake and a loud one
    # (``ValueError: bytes is not a 16-char string``), but taking the *last* 16 or a hash of the hash would be
    # silent and would produce ids Case never derives.
    digest = bytearray(hashlib.sha1(name, usedforsecurity=False).digest()[:16])
    # The high 4 bits of octet 6 become the version (5) and the low 6 bits of octet 8 the variant (10 = RFC
    # 9562), exactly as the Java side does it; the other 122 bits are the hash.
    digest[6] = (digest[6] & 0x0F) | 0x50
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))
