"""Pydantic models for every wire contract in docs/contracts.md.

These are the Python half of the T02 code types. The Java half lives in
``java/shared-kernel/src/main/java/com/resolveflow/shared/contract``; both are
checked against ``contracts/*.schema.json`` and against the same fixture corpus in
``contracts/fixtures``, so a field renamed on one side fails a test rather than
reaching production.

Naming: JSON is snake_case (docs/contracts.md:3), so Python fields keep the wire
name directly and Java maps it with ``@JsonProperty``. That asymmetry is
deliberate — the wire format is the shared artefact, not either language's idiom.

Field typing notes:

* Identifiers are UUID *strings*, not ``uuid.UUID``, so ``model_dump_json()``
  reproduces the wire text instead of an object repr.
* Money is ``int`` minor units. ``docs/contracts.md:19`` caps it at
  1_000_000_000 and forbids floats; a float is rejected by the integer type.
* ``extra="forbid"`` matches ``additionalProperties: false``. An unknown field is
  a protocol error, not something to ignore, because it usually means the two
  sides disagree about the contract version.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from resolveflow.contracts.enums import (
    Action,
    AuthorizationStatus,
    CallbackDisposition,
    CallbackKind,
    CaseStatus,
    CaseType,
    Decision,
    EntitlementState,
    ErrorCode,
    EvidenceSourceType,
    EventType,
    IdempotencyDisposition,
    OperationState,
    Producer,
    ProposalStatus,
    RecommendedAction,
    RequestedAction,
    RiskRoute,
    TimelineEventType,
)

__all__ = [
    "AgentProposal",
    "ApiError",
    "AuthorizationState",
    "CallbackAccepted",
    "CallbackEnvelope",
    "CancelRequest",
    "CaseCreated",
    "CaseSnapshot",
    "CaseSummary",
    "ClaimedRun",
    "EntitlementStateView",
    "ErrorResponse",
    "EvidenceAppendRequest",
    "EvidenceRef",
    "EvidenceSubmission",
    "ExecutionCommand",
    "ExecutionResultEvent",
    "ExpectedEnums",
    "HealthResponse",
    "InternalCancelAck",
    "LineContext",
    "LoginRequest",
    "LoginResponse",
    "ManualProposalRequest",
    "MessageEnvelope",
    "MonetaryLimits",
    "OrderLineSummary",
    "OperationView",
    "PageMeta",
    "PolicyManifestRef",
    "PolicyRef",
    "ProposalView",
    "ReviewedEvidenceRequest",
    "ReviewQueueItem",
    "ReviewRequest",
    "ReviewResponse",
    "RunAccepted",
    "RunRequest",
    "RunView",
    "TraceContext",
    "Uuid",
    "VersionRef",
]

# --------------------------------------------------------------------------
# Shared scalar shapes
# --------------------------------------------------------------------------

#: Canonical lowercase UUID text. Both languages compare these as strings.
Uuid = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]

#: W3C trace context, version 00, per contracts/event-envelope.schema.json.
TRACEPARENT_PATTERN = r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"

SHA256_HEX = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
ReasonCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")]

#: docs/contracts.md:19 — the single money ceiling for the whole project.
MAX_AMOUNT_MINOR = 1_000_000_000
#: 2^53-1; the largest integer Java, Python and JavaScript agree on exactly.
MAX_SAFE_INTEGER = 2**53 - 1

MoneyMinor = Annotated[int, Field(ge=1, le=MAX_AMOUNT_MINOR)]
PositiveRevision = Annotated[int, Field(ge=1, le=MAX_SAFE_INTEGER)]
Version = Annotated[int, Field(ge=1, le=MAX_SAFE_INTEGER)]

JSON_WIRE = ConfigDict(extra="forbid")


class ContractModel(BaseModel):
    """Base for every wire model: unknown fields are protocol errors, not noise."""

    model_config = JSON_WIRE


class TraceContext(ContractModel):
    """The optional trace context both REST and MQ carry."""

    traceparent: Annotated[str, StringConstraints(pattern=TRACEPARENT_PATTERN)] | None = None


class PageMeta(ContractModel):
    """docs/contracts.md:15 — created_at+id cursor paging, never deep offset."""

    next_cursor: str | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 20


class MonetaryLimits(ContractModel):
    """The money bounds contract tests assert against; not a payload of its own."""

    max_amount_minor: Literal[1000000000] = MAX_AMOUNT_MINOR
    currency: Literal["CNY"] = "CNY"
    max_safe_integer: Literal[9007199254740991] = MAX_SAFE_INTEGER


# --------------------------------------------------------------------------
# Error protocol (docs/contracts.md:14)
# --------------------------------------------------------------------------

#: Status mapping fixed by docs/contracts.md:14. Route code -> HTTP status.
ERROR_STATUS: dict[str, int] = {
    ErrorCode.VALIDATION_FAILED: 400,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN_SCOPE: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.STATE_CONFLICT: 409,
    ErrorCode.VERSION_CONFLICT: 409,
    ErrorCode.SEMANTIC_INVALID: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
}


class ApiError(ContractModel):
    """``{code,message,retryable,trace_id,details}`` — the one error body shape.

    ``retryable`` is explicit because the money path depends on it: a network
    timeout must never be reclassified as a failed refund, and only an
    explicitly non-retryable answer may release a reservation.
    """

    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    retryable: bool
    trace_id: str | None = Field(default=None, min_length=1, max_length=64)
    details: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _status_matches_code(self) -> ApiError:
        # A code outside the fixed set is allowed (routes add their own), but a
        # code inside it must not claim a different retryability than documented.
        if self.code in ERROR_STATUS:
            expected_retryable = ERROR_STATUS[self.code] in (429, 503)
            if self.retryable is not expected_retryable:
                raise ValueError(
                    f"code {self.code} must have retryable={expected_retryable} "
                    f"per docs/contracts.md:14"
                )
        return self


class ErrorResponse(ContractModel):
    """The single documented error envelope."""

    error: ApiError


# --------------------------------------------------------------------------
# External API bodies (docs/contracts.md:22-42)
# --------------------------------------------------------------------------


class HealthResponse(ContractModel):
    status: Literal["UP"]
    service: str = Field(min_length=1)
    version: str = Field(min_length=1)


class LoginRequest(ContractModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class LoginResponse(ContractModel):
    access_token: str = Field(min_length=1)
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: Annotated[int, Field(ge=1, le=86400)]
    role: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1)
    customer_id: str | None = None


class OrderLineSummary(ContractModel):
    order_id: Uuid
    line_id: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    category: str = Field(min_length=1)
    quantity: Annotated[int, Field(ge=1, le=1000)]
    line_paid_amount: Annotated[int, Field(ge=0, le=MAX_AMOUNT_MINOR)]
    currency: Literal["CNY"] = "CNY"
    paid_at: str = Field(description="RFC 3339 UTC timestamp ending in Z")
    status: str = Field(min_length=1)
    version: Version


class OrderLinePage(ContractModel):
    items: list[OrderLineSummary]
    page: PageMeta


class CaseCreateRequest(ContractModel):
    """POST /api/v1/cases — customer-submitted request."""

    line_id: str = Field(min_length=1)
    description: str = Field(min_length=1, max_length=4000)
    requested_actions: Annotated[list[RequestedAction], Field(min_length=1, max_length=3)]

    @field_validator("requested_actions")
    @classmethod
    def _no_duplicates(cls, value: list[RequestedAction]) -> list[RequestedAction]:
        if len(set(value)) != len(value):
            raise ValueError("requested_actions must not repeat an action")
        return value


class CaseCreated(ContractModel):
    """202 response for case creation (docs/contracts.md:28)."""

    case_id: Uuid
    status: CaseStatus
    input_revision: PositiveRevision
    version: Version


class EvidenceAppendRequest(ContractModel):
    """POST /api/v1/cases/{case_id}/evidence."""

    question_id: str | None = None
    text: str = Field(min_length=1, max_length=8000)
    evidence_kind: EvidenceSourceType


class EvidenceSubmission(ContractModel):
    case_id: Uuid
    input_revision: PositiveRevision
    version: Version


class CancelRequest(ContractModel):
    reason: str = Field(min_length=1, max_length=500)


class CaseCancelResponse(ContractModel):
    case_id: Uuid
    status: CaseStatus
    version: Version


class PolicyRef(ContractModel):
    """A citation into one immutable policy bundle version."""

    bundle_id: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=64)
    rule_id: str = Field(min_length=1, max_length=64)
    chunk_id: str = Field(min_length=1, max_length=64)
    content_hash: SHA256_HEX


class EvidenceRef(ContractModel):
    """A citation into one stored observation. ``source_ref`` is never a URL."""

    observation_id: str = Field(min_length=1, max_length=64)
    source_ref: str = Field(min_length=1, max_length=200)
    source_version: str = Field(min_length=1, max_length=64)
    content_hash: SHA256_HEX

    @field_validator("source_ref")
    @classmethod
    def _not_a_url(cls, value: str) -> str:
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
            raise ValueError("source_ref must be a controlled reference, not a URL")
        return value


class ProposalView(ContractModel):
    """The public projection of a proposal; never carries model scratch text."""

    proposal_id: Uuid
    run_id: Uuid
    input_revision: PositiveRevision
    case_type: CaseType
    recommended_action: RecommendedAction
    suggested_amount_minor: Annotated[int, Field(ge=0, le=MAX_AMOUNT_MINOR)] | None = None
    summary: str = Field(min_length=1, max_length=2000)
    reason_codes: Annotated[list[ReasonCode], Field(min_length=1, max_length=16)]
    evidence_refs: Annotated[list[EvidenceRef], Field(max_length=32)] = Field(default_factory=list)
    policy_refs: Annotated[list[PolicyRef], Field(max_length=10)] = Field(default_factory=list)
    missing_evidence: Annotated[list[str], Field(max_length=10)] = Field(default_factory=list)
    status: ProposalStatus
    route: RiskRoute | None = None

    @model_validator(mode="after")
    def _executable_actions_are_evidenced(self) -> ProposalView:
        if self.recommended_action in (RecommendedAction.REFUND, RecommendedAction.RESHIP):
            if not self.evidence_refs or not self.policy_refs:
                raise ValueError("REFUND/RESHIP proposals require evidence_refs and policy_refs")
            if self.missing_evidence:
                raise ValueError("REFUND/RESHIP proposals cannot also report missing_evidence")
        return self


class OperationView(ContractModel):
    """Summary of the executable operation linked to a case."""

    operation_id: Uuid
    action: Action
    state: OperationState
    target_service: str = Field(min_length=1)
    amount_minor: Annotated[int, Field(ge=0, le=MAX_AMOUNT_MINOR)] | None = None
    quantity: Annotated[int, Field(ge=0, le=1000)] | None = None
    version: Version


class AuthorizationState(ContractModel):
    authorization_id: Uuid
    authorization_version: Version
    status: AuthorizationStatus
    expires_at: str | None = None
    action: Action
    planned_operation_id: Uuid
    payload_hash: SHA256_HEX


class CaseSummary(ContractModel):
    case_id: Uuid
    status: CaseStatus
    input_revision: PositiveRevision
    version: Version
    created_at: str
    updated_at: str
    requested_actions: Annotated[list[RequestedAction], Field(min_length=1, max_length=3)]
    line_id: str = Field(min_length=1)


class CaseSnapshot(ContractModel):
    """GET /api/v1/cases/{case_id}: the authoritative view SSE only hints at."""

    case: CaseSummary
    proposal: ProposalView | None = None
    authorization: AuthorizationState | None = None
    operation: OperationView | None = None
    evidence: Annotated[list[EvidenceRef], Field(max_length=64)] = Field(default_factory=list)


class ReviewQueueItem(ContractModel):
    case_id: Uuid
    status: CaseStatus
    input_revision: PositiveRevision
    version: Version
    updated_at: str
    line_id: str = Field(min_length=1)
    requested_actions: Annotated[list[RequestedAction], Field(min_length=1, max_length=3)]


class ReviewQueuePage(ContractModel):
    items: list[ReviewQueueItem]
    page: PageMeta


class ReviewRequest(ContractModel):
    """POST /api/v1/cases/{case_id}/reviews — the human authorisation decision."""

    authorization_id: Uuid
    authorization_version: Version
    decision: Decision
    reason: str = Field(min_length=1, max_length=1000)


class ReviewResponse(ContractModel):
    case_id: Uuid
    authorization_id: Uuid
    authorization_version: Version
    status: AuthorizationStatus
    case_version: Version


class ManualProposalRequest(ContractModel):
    """A reviewer's replacement proposal. It never edits an existing payload."""

    action: Action
    evidence_refs: Annotated[list[EvidenceRef], Field(min_length=1, max_length=32)]
    policy_refs: Annotated[list[PolicyRef], Field(min_length=1, max_length=10)]
    reason: str = Field(min_length=1, max_length=1000)


class ManualProposalResponse(ContractModel):
    case_id: Uuid
    proposal_id: Uuid
    input_revision: PositiveRevision
    case_version: Version


class ReviewedEvidenceRequest(ContractModel):
    """Human verification of damage-style material; appends, never overwrites."""

    source_evidence_id: str = Field(min_length=1, max_length=64)
    verification_result: Literal["CONFIRMED", "REFUTED", "INCONCLUSIVE"]
    reason: str = Field(min_length=1, max_length=1000)


class ReviewedEvidenceResponse(ContractModel):
    case_id: Uuid
    evidence_id: str = Field(min_length=1, max_length=64)
    input_revision: PositiveRevision
    case_version: Version
    revoked_authorization_id: Uuid | None = None


class ReconcileRequest(ContractModel):
    reason: str = Field(min_length=1, max_length=500)


class ReconcileResponse(ContractModel):
    operation_id: Uuid
    state: OperationState
    reconciled: bool
    version: Version


class PolicyImportRequest(ContractModel):
    bundle_json: dict[str, Any]
    source_markdown: str = Field(min_length=1)


class PolicyImportResponse(ContractModel):
    bundle_id: str = Field(min_length=1, max_length=64)
    status: Literal["DRAFT"]
    content_hash: SHA256_HEX


class PolicyPublishRequest(ContractModel):
    expected_hash: SHA256_HEX


class PolicyPublishResponse(ContractModel):
    bundle_id: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=64)
    status: Literal["PUBLISHED"]
    safety_epoch: Annotated[int, Field(ge=0, le=MAX_SAFE_INTEGER)]


class PolicyRevokeRequest(ContractModel):
    reason: str = Field(min_length=1, max_length=500)


class PolicyRevokeResponse(ContractModel):
    bundle_id: str = Field(min_length=1, max_length=64)
    status: Literal["REVOKED"]
    safety_epoch: Annotated[int, Field(ge=0, le=MAX_SAFE_INTEGER)]


class IdempotentResponse(ContractModel):
    """Disposition carried by replay-aware write responses (docs/contracts.md:76)."""

    disposition: IdempotencyDisposition
    resource_id: str = Field(min_length=1)


# --------------------------------------------------------------------------
# Internal Java <-> Java bodies (docs/contracts.md:99-109)
# --------------------------------------------------------------------------


class EntitlementReserveRequest(ContractModel):
    operation_id: Uuid
    line_id: str = Field(min_length=1)
    action: Action
    payload_hash: SHA256_HEX


class EntitlementPayloadHashRequest(ContractModel):
    payload_hash: SHA256_HEX


class EntitlementStartRequest(ContractModel):
    target_service: str = Field(min_length=1)
    payload_hash: SHA256_HEX


class EntitlementCommitRequest(ContractModel):
    result_ref: str = Field(min_length=1, max_length=200)
    payload_hash: SHA256_HEX


class EntitlementReleaseRequest(ContractModel):
    terminal_failure_ref: str = Field(min_length=1, max_length=200)
    payload_hash: SHA256_HEX


class EntitlementStateView(ContractModel):
    entitlement_id: str = Field(min_length=1, max_length=64)
    operation_id: Uuid | None = None
    line_id: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1)
    action: Action | None = None
    state: EntitlementState
    version: Version


class CancelBeforeStartRequest(ContractModel):
    reason: str = Field(min_length=1, max_length=500)


class CancelBeforeStartResponse(ContractModel):
    operation_id: Uuid
    state: Literal["CANCELLED"]
    tombstone_created: bool
    version: Version


class LineContext(ContractModel):
    """GET /internal/v1/order-lines/{line_id}/context — commerce authority."""

    order_id: Uuid
    line_id: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    category: str = Field(min_length=1)
    quantity: Annotated[int, Field(ge=1, le=1000)]
    line_paid_amount: Annotated[int, Field(ge=0, le=MAX_AMOUNT_MINOR)]
    refunded_amount: Annotated[int, Field(ge=0, le=MAX_AMOUNT_MINOR)]
    reserved_refund_amount: Annotated[int, Field(ge=0, le=MAX_AMOUNT_MINOR)]
    currency: Literal["CNY"] = "CNY"
    paid_at: str
    order_status: str = Field(min_length=1)
    version: Version

    @model_validator(mode="after")
    def _refunds_never_exceed_paid(self) -> LineContext:
        # INV-01 stated where the Agent can see it: refunded + reserved <= paid.
        if self.refunded_amount + self.reserved_refund_amount > self.line_paid_amount:
            raise ValueError("refunded_amount + reserved_refund_amount must not exceed line_paid_amount")
        return self


class ShipmentEvent(ContractModel):
    code: str = Field(min_length=1, max_length=64)
    occurred_at: str
    source_version: Version


class ShipmentEvidence(ContractModel):
    line_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    carrier_conclusion: Literal["LOST", "DELIVERED", "IN_TRANSIT", "UNKNOWN"]
    events: Annotated[list[ShipmentEvent], Field(max_length=200)]
    source_version: Version
    updated_at: str


class PackingEvidence(ContractModel):
    line_id: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    shipped_quantity: Annotated[int, Field(ge=0, le=1000)]
    verified_status: Literal["VERIFIED", "NOT_VERIFIED", "NO_RECORD"]
    version: Version


class VersionRef(ContractModel):
    """A source version used to detect that Java facts moved under a run."""

    source_type: EvidenceSourceType
    source_ref: str = Field(min_length=1, max_length=200)
    source_version: str = Field(min_length=1, max_length=64)
    content_hash: SHA256_HEX


class PolicyManifestRef(ContractModel):
    bundle_ids: Annotated[list[str], Field(min_length=1, max_length=16)]
    manifest_hash: SHA256_HEX
    safety_epoch: Annotated[int, Field(ge=0, le=MAX_SAFE_INTEGER)]


class PolicyManifestView(ContractModel):
    bundles: Annotated[list[PolicyManifestRef], Field(min_length=1, max_length=16)]
    effective_from: str
    effective_to: str | None = None


class PublishedPolicyRule(ContractModel):
    rule_id: str = Field(min_length=1, max_length=64)
    action: Action
    amount_cap_minor: Annotated[int, Field(ge=0, le=MAX_AMOUNT_MINOR)] | None = None
    requires_human: bool
    text: str = Field(min_length=1)


class PublishedPolicyBundle(ContractModel):
    bundle_id: str = Field(min_length=1, max_length=64)
    merchant_id: str = Field(min_length=1)
    version: str = Field(min_length=1, max_length=64)
    category: CaseType
    effective_from: str
    effective_to: str | None = None
    safety_epoch: Annotated[int, Field(ge=0, le=MAX_SAFE_INTEGER)]
    rules: Annotated[list[PublishedPolicyRule], Field(min_length=1, max_length=200)]
    source_hash: SHA256_HEX


# --------------------------------------------------------------------------
# Agent control plane (docs/contracts.md:44-79)
# --------------------------------------------------------------------------


class RunRequestContext(ContractModel):
    merchant_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    order_id: Uuid
    line_id: str = Field(min_length=1)


class RunRequestPayload(ContractModel):
    description: str = Field(min_length=1, max_length=4000)
    requested_actions: Annotated[list[RequestedAction], Field(min_length=1, max_length=3)]
    evidence_refs: Annotated[list[str], Field(max_length=64)] = Field(default_factory=list)


class RunRequest(ContractModel):
    """POST /internal/v1/runs from case-service to the Agent."""

    run_id: Uuid
    case_id: Uuid
    input_revision: PositiveRevision
    context: RunRequestContext
    request: RunRequestPayload
    policy_manifest: PolicyManifestRef
    deadline_at: str
    traceparent: Annotated[str, StringConstraints(pattern=TRACEPARENT_PATTERN)] | None = None


class RunAccepted(ContractModel):
    run_id: Uuid
    status: Literal["QUEUED", "ANALYZING"]


class RunView(ContractModel):
    """GET /internal/v1/runs/{run_id} — how case-service reconciles a run."""

    run_id: Uuid
    case_id: Uuid
    input_revision: PositiveRevision
    status: Literal["QUEUED", "ANALYZING", "WAITING_CUSTOMER", "PROPOSED", "FAILED", "CANCELLED", "COMPLETED"]
    version: Version
    callback_ids: Annotated[list[str], Field(max_length=64)] = Field(default_factory=list)
    result_summary: str | None = Field(default=None, max_length=2000)


class InternalCancelAck(ContractModel):
    run_id: Uuid
    status: Literal["CANCELLED", "COMPLETED", "FAILED"]
    cancellation_requested: bool


class ClaimedRun(ContractModel):
    """A worker lease on a run; the lease is what fences a stale worker (T22)."""

    run_id: Uuid
    case_id: Uuid
    input_revision: PositiveRevision
    lease_owner: str = Field(min_length=1, max_length=128)
    lease_until: str
    fence: Annotated[int, Field(ge=1, le=MAX_SAFE_INTEGER)]
    attempt: Annotated[int, Field(ge=1, le=100)]


class QuestionItem(ContractModel):
    field: str = Field(min_length=1, max_length=64)
    prompt: str = Field(min_length=1, max_length=500)


class CallbackEnvelope(ContractModel):
    """POST /internal/v1/cases/{case_id}/agent-callbacks."""

    callback_id: str = Field(min_length=1, max_length=64)
    run_id: Uuid
    input_revision: PositiveRevision
    kind: CallbackKind
    payload: dict[str, Any]
    traceparent: Annotated[str, StringConstraints(pattern=TRACEPARENT_PATTERN)] | None = None

    @model_validator(mode="after")
    def _payload_matches_kind(self) -> CallbackEnvelope:
        """Each kind has one documented payload shape (docs/contracts.md:75)."""
        required: dict[CallbackKind, tuple[str, ...]] = {
            CallbackKind.STARTED: ("started_at",),
            CallbackKind.QUESTION: ("question_id", "questions", "reason_codes"),
            CallbackKind.PROPOSAL: ("proposal_id", "recommended_action"),
            CallbackKind.FAILED: ("reason_codes", "retryable"),
        }
        missing = [key for key in required[self.kind] if key not in self.payload]
        if missing:
            raise ValueError(f"{self.kind} callback payload is missing {missing}")
        if self.kind is CallbackKind.QUESTION:
            for index, question in enumerate(self.payload.get("questions", [])):
                try:
                    QuestionItem.model_validate(question)
                except Exception as error:  # noqa: BLE001 - re-raised with position context
                    raise ValueError(f"questions[{index}] is not a valid QuestionItem: {error}") from error
        return self


class CallbackAccepted(ContractModel):
    disposition: CallbackDisposition
    case_version: Version | None = None


class AgentProposal(ContractModel):
    """The external proposal contract, mirrored from agent-proposal.schema.json.

    Only the runtime may fill ``proposal_id``/``run_id``/``input_revision``/``case_id``;
    a model that emits them is rejected downstream (docs/contracts.md:58).
    """

    schema_version: Literal[1] = 1
    proposal_id: Uuid
    run_id: Uuid
    case_id: Uuid
    input_revision: PositiveRevision
    case_type: CaseType
    recommended_action: RecommendedAction
    suggested_amount_minor: Annotated[int, Field(ge=0, le=MAX_AMOUNT_MINOR)] | None = None
    evidence_refs: Annotated[list[EvidenceRef], Field(max_length=32)] = Field(default_factory=list)
    policy_refs: Annotated[list[PolicyRef], Field(max_length=10)] = Field(default_factory=list)
    reason_codes: Annotated[list[ReasonCode], Field(min_length=1, max_length=16)]
    summary: str = Field(min_length=1, max_length=2000)
    missing_evidence: Annotated[list[str], Field(max_length=10)] = Field(default_factory=list)

    @field_validator("reason_codes")
    @classmethod
    def _reason_codes_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("reason_codes must be unique")
        return value

    @model_validator(mode="after")
    def _executable_actions_are_evidenced(self) -> AgentProposal:
        if self.recommended_action in (RecommendedAction.REFUND, RecommendedAction.RESHIP):
            if not self.evidence_refs or not self.policy_refs:
                raise ValueError("REFUND/RESHIP proposals require evidence_refs and policy_refs")
            if self.missing_evidence:
                raise ValueError("REFUND/RESHIP proposals cannot also report missing_evidence")
        return self


# --------------------------------------------------------------------------
# MQ envelopes and payloads (docs/contracts.md:111-127)
# --------------------------------------------------------------------------


class ExecutionCommand(ContractModel):
    """contracts/execution-command.schema.json — the case -> target command."""

    operation_id: Uuid
    case_id: Uuid
    authorization_id: Uuid
    input_revision: PositiveRevision
    line_id: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1)
    action: Action
    quantity: Annotated[int, Field(ge=1, le=1000)]
    amount_minor: MoneyMinor | None = None
    currency: Literal["CNY"] = "CNY"
    address_hash: SHA256_HEX | None = None
    payload_hash: SHA256_HEX
    policy_version: str = Field(min_length=1, max_length=64)
    entitlement_id: str = Field(min_length=1, max_length=64)
    target_service: Literal["commerce-service", "fulfillment-service"]

    @model_validator(mode="after")
    def _action_matches_target(self) -> ExecutionCommand:
        """The wrong action/target pairing must be refused, not routed and ignored."""
        if self.action is Action.REFUND:
            if self.target_service != "commerce-service":
                raise ValueError("REFUND must target commerce-service")
            if self.amount_minor is None:
                raise ValueError("REFUND requires amount_minor")
            if self.address_hash is not None:
                raise ValueError("REFUND must not carry address_hash")
        else:
            if self.target_service != "fulfillment-service":
                raise ValueError("RESHIP must target fulfillment-service")
            if self.address_hash is None:
                raise ValueError("RESHIP requires address_hash")
            if self.amount_minor is not None:
                raise ValueError("RESHIP must not carry amount_minor")
        return self


class ExecutionResultEvent(ContractModel):
    """Payload of Refund*/Reship*/Entitlement* events (docs/contracts.md:121-123)."""

    operation_id: Uuid
    line_id: str = Field(min_length=1)
    state: OperationState
    provider_ref: str | None = Field(default=None, max_length=200)
    amount_minor: Annotated[int, Field(ge=0, le=MAX_AMOUNT_MINOR)] | None = None
    quantity: Annotated[int, Field(ge=0, le=1000)] | None = None
    reason_code: ReasonCode | None = None
    version: Version | None = None


class MessageEnvelope(ContractModel):
    """contracts/event-envelope.schema.json — the MQ envelope for every event."""

    event_id: Uuid
    event_type: EventType
    schema_version: Literal[1] = 1
    aggregate_id: str = Field(min_length=1, max_length=64)
    aggregate_version: Version
    merchant_id: str = Field(min_length=1)
    occurred_at: str
    producer: Producer
    traceparent: Annotated[str, StringConstraints(pattern=TRACEPARENT_PATTERN)] | None = None
    causation_id: str | None = Field(default=None, min_length=1, max_length=64)
    payload: dict[str, Any]
    signature: str | None = Field(default=None, min_length=1, max_length=200)
    signing_key_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _command_events_are_signed_by_case(self) -> MessageEnvelope:
        if self.event_type in (EventType.REFUND_REQUESTED, EventType.RESHIP_REQUESTED):
            if self.payload.get("action") != self.event_type.value.replace("Requested", "").upper():
                raise ValueError(f"{self.event_type} payload action does not match the event type")
            if self.producer is not Producer.CASE:
                raise ValueError("only case-service may publish execution commands")
            if not self.signature or not self.signing_key_id:
                raise ValueError("execution commands must be signed and name their signing_key_id")
        return self


#: Frozen enum values asserted by both languages, see contracts/fixtures/expected-enums.json.
class ExpectedEnums(ContractModel):
    event_type: list[EventType]
    producer: list[Producer]
    action: list[Action]
    requested_action: list[RequestedAction]
    case_type: list[CaseType]
    recommended_action: list[RecommendedAction]
    case_status: list[CaseStatus]
    timeline_event_type: list[TimelineEventType]
    callback_kind: list[CallbackKind]
    callback_disposition: list[CallbackDisposition]
    idempotency_disposition: list[IdempotencyDisposition]
    proposal_status: list[ProposalStatus]
    authorization_status: list[AuthorizationStatus]
    decision: list[Decision]
    risk_route: list[RiskRoute]
    entitlement_state: list[EntitlementState]
    operation_state: list[OperationState]
    evidence_source_type: list[EvidenceSourceType]
    error_code: list[ErrorCode]