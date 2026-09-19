"""Business enumerations shared by the Java and Python sides of the protocol.

Python-side values must equal the Java enum wire values exactly. T02 freezes that
mapping in ``contracts/fixtures/expected-enums.json`` and both languages assert
against the same file, so a future rename on one side fails a test instead of
silently producing an unroutable action.

Every member here is wire-visible. ``docs/domain-model.md`` names the state
machines these belong to and is the authority for the value sets.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "CASE_STATUSES",
    "ENTITLEMENT_STATES",
    "OPERATION_STATES",
    "PROPOSAL_STATES",
    "REQUESTED_ACTIONS",
    "Action",
    "AuthorizationStatus",
    "CallbackDisposition",
    "CallbackKind",
    "CaseStatus",
    "CaseType",
    "CarrierConclusion",
    "Decision",
    "EntitlementState",
    "ErrorCode",
    "EventType",
    "EvidenceSourceType",
    "IdempotencyDisposition",
    "OperationState",
    "Producer",
    "ProposalStatus",
    "RecommendedAction",
    "RequestedAction",
    "RiskRoute",
    "RunStatus",
    "ServiceName",
    "TimelineEventType",
    "VerificationResult",
    "VerifiedStatus",
]


class ServiceName(StrEnum):
    """The four Java processes plus the Python service (README.md:34)."""

    GATEWAY = "gateway"
    COMMERCE = "commerce-service"
    FULFILLMENT = "fulfillment-service"
    CASE = "case-service"
    AGENT = "agent-service"


class Producer(StrEnum):
    """Who is allowed to publish an envelope; mirrors the schema's enum."""

    CASE = "case-service"
    COMMERCE = "commerce-service"
    FULFILLMENT = "fulfillment-service"


class EventType(StrEnum):
    """contracts/event-envelope.schema.json event_type."""

    REFUND_REQUESTED = "RefundRequested"
    RESHIP_REQUESTED = "ReshipRequested"
    REFUND_SUCCEEDED = "RefundSucceeded"
    REFUND_FAILED = "RefundFailed"
    REFUND_UNKNOWN = "RefundUnknown"
    RESHIP_SUCCEEDED = "ReshipSucceeded"
    RESHIP_FAILED = "ReshipFailed"
    RESHIP_UNKNOWN = "ReshipUnknown"
    ENTITLEMENT_COMMITTED = "EntitlementCommitted"
    ENTITLEMENT_RELEASED = "EntitlementReleased"


class Action(StrEnum):
    """The only two remediation actions in scope (docs/domain-model.md:10)."""

    REFUND = "REFUND"
    RESHIP = "RESHIP"


class RequestedAction(StrEnum):
    """What the customer asked for; a superset of what can be executed."""

    REFUND = "REFUND"
    RESHIP = "RESHIP"
    EITHER = "EITHER"


class CaseType(StrEnum):
    """The three fixed scenarios plus the explicit out-of-scope bucket."""

    LOGISTICS = "LOGISTICS"
    DAMAGED = "DAMAGED"
    WRONG_MISSING = "WRONG_MISSING"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class RecommendedAction(StrEnum):
    """docs/contracts.md:14 — the Agent proposes, Java authorises."""

    REFUND = "REFUND"
    RESHIP = "RESHIP"
    REQUEST_INFO = "REQUEST_INFO"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    REJECT = "REJECT"


class CaseStatus(StrEnum):
    """docs/domain-model.md:55 case lifecycle."""

    QUEUED = "QUEUED"
    ANALYZING = "ANALYZING"
    WAITING_CUSTOMER = "WAITING_CUSTOMER"
    PENDING_REVIEW = "PENDING_REVIEW"
    AUTHORIZED = "AUTHORIZED"
    EXECUTING = "EXECUTING"
    RECONCILING = "RECONCILING"
    CLOSED_SUCCESS = "CLOSED_SUCCESS"
    CLOSED_REJECTED = "CLOSED_REJECTED"
    CANCELLED = "CANCELLED"


class TimelineEventType(StrEnum):
    """docs/contracts.md:42 progress kinds carried over SSE."""

    CASE_CREATED = "CASE_CREATED"
    AGENT_STARTED = "AGENT_STARTED"
    QUESTION_REQUIRED = "QUESTION_REQUIRED"
    PROPOSAL_READY = "PROPOSAL_READY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    EXECUTION_UPDATED = "EXECUTION_UPDATED"
    CASE_CLOSED = "CASE_CLOSED"


class CallbackKind(StrEnum):
    """docs/contracts.md:71 Python -> case callback kinds."""

    STARTED = "STARTED"
    QUESTION = "QUESTION"
    PROPOSAL = "PROPOSAL"
    FAILED = "FAILED"


class CallbackDisposition(StrEnum):
    """docs/contracts.md:77 idempotent callback outcomes."""

    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    STALE = "STALE"


class IdempotencyDisposition(StrEnum):
    """docs/contracts.md:76 response dispositions for idempotency keys."""

    CREATED = "CREATED"
    REPLAYED = "REPLAYED"
    CONFLICT = "CONFLICT"


class ProposalStatus(StrEnum):
    """docs/domain-model.md:57."""

    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    STALE = "STALE"
    REJECTED = "REJECTED"


class AuthorizationStatus(StrEnum):
    """docs/domain-model.md:57."""

    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    CONSUMED = "CONSUMED"


class Decision(StrEnum):
    """docs/contracts.md:34 reviewer decisions on a pending authorisation."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_INFO = "REQUEST_INFO"


class RiskRoute(StrEnum):
    """docs/product-spec.md:19 low-risk gate outcome, computed by Java."""

    AUTO = "AUTO"
    REVIEW = "REVIEW"
    NEED_INFO = "NEED_INFO"
    BLOCK = "BLOCK"


class EntitlementState(StrEnum):
    """docs/domain-model.md:47 line_entitlement states."""

    FREE = "FREE"
    RESERVED = "RESERVED"
    IN_USE = "IN_USE"
    CONSUMED = "CONSUMED"


class OperationState(StrEnum):
    """docs/domain-model.md:59: a compat superset kept for deserialisation.

    The target core vocabulary is five states (docs/domain-model.md:57), and
    supporting deserialisation of the old ones is not permission to execute them.
    """

    CREATED = "CREATED"
    RESERVING = "RESERVING"
    RESERVED = "RESERVED"
    RECEIVED = "RECEIVED"
    STARTING = "STARTING"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    TARGET_SUCCEEDED = "TARGET_SUCCEEDED"
    COMMITTING = "COMMITTING"
    SUCCEEDED = "SUCCEEDED"
    UNKNOWN = "UNKNOWN"
    RELEASING = "RELEASING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EvidenceSourceType(StrEnum):
    """Authority-ranked evidence sources; tool ``source_ref`` may not be a URL."""

    ORDER_LINE = "ORDER_LINE"
    PAYMENT_LEDGER = "PAYMENT_LEDGER"
    LINE_ENTITLEMENT = "LINE_ENTITLEMENT"
    SHIPMENT = "SHIPMENT"
    SHIPMENT_TRACK = "SHIPMENT_TRACK"
    PACKING_MANIFEST = "PACKING_MANIFEST"
    CUSTOMER_STATEMENT = "CUSTOMER_STATEMENT"
    REVIEWER_VERIFICATION = "REVIEWER_VERIFICATION"
    POLICY_RULE = "POLICY_RULE"


class ErrorCode(StrEnum):
    """docs/contracts.md:14 error codes that T02 fixes before services exist.

    Only codes whose meaning is already decided by the documents appear here.
    Route-specific codes are added by the task that implements the route.
    """

    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN_SCOPE = "FORBIDDEN_SCOPE"
    NOT_FOUND = "NOT_FOUND"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    STATE_CONFLICT = "STATE_CONFLICT"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    SEMANTIC_INVALID = "SEMANTIC_INVALID"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


# Convenience frozensets for validation and for the frozen enum fixture.
class VerificationResult(StrEnum):
    """The reviewer's verdict on submitted evidence (docs/contracts.md:36).

    Kept apart from Decision: a reviewer may confirm or refute a piece of evidence
    without approving the case, and the two must not be conflated in the timeline.
    """

    CONFIRMED = "CONFIRMED"
    REFUTED = "REFUTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class CarrierConclusion(StrEnum):
    """What the carrier's own tracking concludes (docs/domain-model.md:57).

    UNKNOWN means the carrier could not say; it is not a failure, and the Agent must
    not read it as one.
    """

    LOST = "LOST"
    DELIVERED = "DELIVERED"
    IN_TRANSIT = "IN_TRANSIT"
    UNKNOWN = "UNKNOWN"


class RunStatus(StrEnum):
    """agent_run status, fixed by docs/agent-spec.md:17.

    COMPLETED means the callback was accepted by Java, not that money moved, and STALE
    means the revision moved under a run that was waiting for input - both distinctions
    are load-bearing, so the names are frozen rather than derived.
    """

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CALLBACK_PENDING = "CALLBACK_PENDING"
    WAITING_INPUT = "WAITING_INPUT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    STALE = "STALE"

class VerifiedStatus(StrEnum):
    """Packing-manifest verification (docs/domain-model.md:59).

    NO_RECORD is not a failed verification: the line simply has no authoritative
    warehouse record, and only a record may be used to judge a short or wrong shipment.
    """

    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    NO_RECORD = "NO_RECORD"


REQUESTED_ACTIONS = frozenset(RequestedAction)
CASE_STATUSES = frozenset(CaseStatus)
PROPOSAL_STATES = frozenset(ProposalStatus)
ENTITLEMENT_STATES = frozenset(EntitlementState)
OPERATION_STATES = frozenset(OperationState)