"""Pydantic models for the core-v1.2 wire contracts.

These are the Python half of the core code types. The Java half is
``java/shared-kernel/src/main/java/com/resolveflow/shared/core/CoreContract.java``; both
are checked against ``contracts/core/*.schema.json`` **and** against the same core fixture
corpus, so a field renamed on one side fails a test instead of reaching production.

Explicitly distinct from the v1 models in ``resolveflow.contracts.models``
(docs/core-contracts.md:71 requires the new types to be distinguishable from the old
ones): nothing here is an alias or a subclass of a v1 type, no v1-only field is
representable, and the class names carry the protocol they belong to. The compat types
stay as they are so the old corpus keeps validating against them.

Two rules that live only in prose in the JSON Schemas are enforced here as well, because
a schema cannot express either:

* **Routing agrees with the event type** (docs/core-contracts.md:9). ``event_type``
  decides producer and topic, and the ``state`` in a result payload decides which result
  event may carry it. Both are the same fact stated twice, so both copies are checked
  rather than one being trusted.
* **An actionable proposal cites evidence and policy** (docs/core-scope.md:7). The schema
  says this with ``allOf``/``if``/``then``; here it is a model validator.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, ClassVar, Final, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from resolveflow.contracts.enums import EvidenceSourceType

__all__ = [
    "CORE_DTO_NAMES",
    "CoreAgentProposal",
    "CoreEnvelope",
    "CoreEvidenceRef",
    "CoreObservation",
    "CorePolicyRef",
    "CoreRefundCommand",
    "CoreRefundResult",
    "CoreToolError",
    "ToolObservation",
]

#: Marks every type in this module, so a test can prove the core DTOs are distinct from
#: the v1 ones instead of assuming it from the module name.
CORE_DTO_NAMES: Final = (
    "CoreRefundCommand",
    "CoreRefundResult",
    "CoreEnvelope",
    "CoreEvidenceRef",
    "CoreObservation",
    "CorePolicyRef",
    "CoreAgentProposal",
)

WireUuid = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
WireHash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
WireRevision = Annotated[int, Field(ge=1, le=9007199254740991)]
WireAmount = Annotated[int, Field(ge=1, le=1_000_000_000)]
WireSuggestedAmount = Annotated[int, Field(ge=0, le=1_000_000_000)]
WireShortText = Annotated[str, StringConstraints(min_length=1, max_length=64)]
WireReasonCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")]
WireTimestamp = Annotated[
    str,
    StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$"),
]
WireTraceparent = Annotated[str, StringConstraints(pattern=r"^00-[a-f0-9]{32}-[a-f0-9]{16}-[a-f0-9]{2}$")]

#: ``docs/core-contracts.md:61``: a reference is a controlled value, never a requestable
#: URL. Enforced with a Python regex rather than ``pattern=`` because Pydantic compiles
#: patterns with the Rust ``regex`` crate, which has no look-around support - a look-ahead
#: in ``pattern=`` fails at model definition time rather than at validation time.
_SOURCE_REF = re.compile(r"^(?!https?://)[a-z][a-z0-9_]*:\S+$")


def _check_source_ref(value: str) -> str:
    if not _SOURCE_REF.match(value):
        raise ValueError("source_ref must be a controlled 'namespace:rest' reference, not a URL")
    return value


WireSourceRef = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200),
    AfterValidator(_check_source_ref),
]

_EVENT_ROUTING: Final[dict[str, tuple[str, str]]] = {
    "RefundRequested": ("case-service", "rf.case.core.v2"),
    "RefundSucceeded": ("commerce-service", "rf.commerce.core.v2"),
    "RefundFailed": ("commerce-service", "rf.commerce.core.v2"),
    "RefundUnknown": ("commerce-service", "rf.commerce.core.v2"),
}

_EVENT_FOR_STATE: Final[dict[str, str]] = {
    "SUCCEEDED": "RefundSucceeded",
    "FAILED": "RefundFailed",
    "UNKNOWN": "RefundUnknown",
}

_CORE_CONFIG = ConfigDict(extra="forbid", frozen=True, strict=True)


class CoreWireModel(BaseModel):
    """Shared behaviour of every core wire object.

    ``extra="forbid"`` matches ``additionalProperties: false``: an unknown field is a
    protocol error, not something to ignore, because it usually means the two sides
    disagree about the protocol version. ``strict=True`` keeps JSON ``25.99`` from being
    coerced into ``25``.

    The one rule that is easy to get wrong: **the core wire says "absent" by omitting the
    member, not by sending null.** Only the members the schemas type as ``["string",
    "null"]`` may be null (the two optional result fields), and each model lists them in
    ``NULLABLE_MEMBERS``. Without this check a DTO happily accepts ``{"traceparent": null}``
    while the schema refuses it, and the disagreement shows up as a validation failure in
    production rather than in a test.
    """

    model_config = _CORE_CONFIG

    #: Members the schema declares as nullable. Everything else must be omitted, not null.
    NULLABLE_MEMBERS: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="before")
    @classmethod
    def refuse_explicit_null(cls, data: Any) -> Any:
        if isinstance(data, dict):
            wrong = sorted(
                key
                for key, value in data.items()
                if value is None and key in cls.model_fields and key not in cls.NULLABLE_MEMBERS
            )
            if wrong:
                raise ValueError(
                    f"explicit null is not part of the core wire shape: {wrong}; omit the member instead"
                )
        return data


class CoreRefundCommand(CoreWireModel):
    """The only executable core command (docs/core-contracts.md:65).

    No ``schema_version`` field: the URN and the envelope's ``schema_version`` identify the
    protocol, and every field here is covered by ``payload_hash`` - a field outside the
    hash would let two different commands share a digest. No ``entitlement_id`` and no
    ``address_hash`` either (docs/core-contracts.md:19).
    """

    operation_id: WireUuid
    case_id: WireUuid
    authorization_id: WireUuid
    input_revision: WireRevision
    line_id: WireShortText
    merchant_id: WireShortText
    action: Literal["REFUND"]
    quantity: Annotated[int, Field(ge=1)]
    currency: Literal["CNY"]
    amount_minor: WireAmount
    policy_version: WireShortText
    target_service: Literal["commerce-service"]
    payload_hash: WireHash


class CoreRefundResult(CoreWireModel):
    """RefundSucceeded / RefundFailed / RefundUnknown payload (docs/core-contracts.md:67).

    ``aggregate_version`` is the authoritative operation's version and is used for
    out-of-order detection; it is never the case's ``input_revision``
    (docs/domain-model.md:3).
    """

    NULLABLE_MEMBERS: ClassVar[frozenset[str]] = frozenset({"provider_ref", "reason_code"})

    operation_id: WireUuid
    line_id: WireShortText
    state: Literal["SUCCEEDED", "FAILED", "UNKNOWN"]
    amount_minor: WireAmount
    provider_ref: Annotated[str, StringConstraints(max_length=200)] | None = None
    reason_code: WireReasonCode | None = None
    aggregate_version: WireRevision


class CoreEnvelope(CoreWireModel):
    """A core event envelope (docs/core-contracts.md:9, :19).

    The version lives in the payload for results, so the envelope does not repeat
    ``aggregate_id``/``aggregate_version`` (docs/domain-model.md:3).
    """

    event_id: WireUuid
    event_type: Literal["RefundRequested", "RefundSucceeded", "RefundFailed", "RefundUnknown"]
    schema_version: Literal[2]
    merchant_id: WireShortText
    occurred_at: WireTimestamp
    producer: Literal["case-service", "commerce-service"]
    topic: Literal["rf.case.core.v2", "rf.commerce.core.v2"]
    traceparent: WireTraceparent | None = None
    causation_id: Annotated[str, StringConstraints(min_length=1)] | None = None
    payload: dict[str, Any]
    signing_key_id: Annotated[str, StringConstraints(min_length=1)]
    signature: Annotated[str, StringConstraints(min_length=1)]

    @model_validator(mode="after")
    def check_routing_and_payload(self) -> CoreEnvelope:
        expected_producer, expected_topic = _EVENT_ROUTING[self.event_type]
        if (self.producer, self.topic) != (expected_producer, expected_topic):
            raise ValueError(
                f"{self.event_type} must come from {expected_producer} on {expected_topic}, "
                f"not from {self.producer} on {self.topic}"
            )
        if self.event_type == "RefundRequested":
            CoreRefundCommand.model_validate(self.payload)
            return self
        result = CoreRefundResult.model_validate(self.payload)
        if _EVENT_FOR_STATE[result.state] != self.event_type:
            raise ValueError(
                f"{self.event_type} carries state={result.state}; the event type and the result state "
                "are the same fact, so they cannot disagree"
            )
        return self


class CoreEvidenceRef(CoreWireModel):
    observation_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    source_ref: WireSourceRef
    source_version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    content_hash: WireHash


class CorePolicyRef(CoreWireModel):
    bundle_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    rule_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    chunk_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    content_hash: WireHash


class CoreObservation(CoreWireModel):
    """One thing a tool saw, in the shape a citation is later checked against (C06.2b).

    ``contracts/core/openapi-agent.yaml`` ``ObservationRecord`` is the authority; this is that schema minus
    ``run_id``, because a tool produces an observation **before** anything knows which run will store it, and
    inventing a run id at the tool boundary would be a made-up fact in the one place the protocol insists on
    facts. The run assembler adds ``run_id`` when it persists the record.

    Two members are easy to get wrong and are therefore typed rather than left as ``str``:

    - ``source_ref`` uses :data:`WireSourceRef`, the same validator the rest of the core wire uses, so a tool
      cannot hand back a requestable URL where a controlled reference belongs
      (``docs/core-contracts.md:61``). A URL here would make the evidence dependent on something outside the
      audited surface.
    - ``content_hash`` is the sha256 of the stored result, which is what makes ``docs/agent-spec.md:52``'s
      "ref/来源/版本/hash 匹配" checkable at all: without it, a citation points at a name rather than at the
      bytes that were seen.

    - ``result`` is the only optional member and is absent, not null, when a tool observed nothing — the same
    rule the rest of the wire follows (:class:`CoreWireModel`).

    ``source_version`` and ``content_hash`` are nullable **only** to represent a failed observation, and the two
    are null together or not at all (enforced below). ``ObservationRecord`` requires them because it describes an
    observation that happened; an observation that did not happen has no version and no hash, and inventing
    them would make an unread source look citable — a citation check comparing a made-up hash against itself
    cannot catch that after the fact. A stored record is only ever written for a successful read, so the
    contract's required members are satisfied where they apply.
    """

    NULLABLE_MEMBERS: ClassVar[frozenset[str]] = frozenset({"result", "source_version", "content_hash"})

    observation_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    tool_name: WireShortText
    source_type: EvidenceSourceType
    source_ref: WireSourceRef
    source_version: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = None
    content_hash: WireHash | None = None
    observed_at: WireTimestamp
    result: dict[str, Any] | None = None

    @model_validator(mode="after")
    def version_and_hash_agree_about_whether_anything_was_observed(self) -> CoreObservation:
        """A citation needs both, so half of one is a bug rather than a state.

        An observation with a hash but no version cannot be checked for staleness, and one with a version but no
        hash cannot be checked for tampering. Either alone is worse than neither: it looks citable.
        """
        if (self.source_version is None) != (self.content_hash is None):
            raise ValueError(
                "source_version and content_hash must both be present or both absent: a citation needs both "
                "to be checkable"
            )
        return self


class CoreToolError(CoreWireModel):
    """Why a tool could not observe, in the shape a run records it.

    Deliberately not the ``ApiError`` of the HTTP contracts: this one has no ``trace_id`` (it is the Agent's own
    attempt, not a service response) and it carries the two flags a decision needs — whether another attempt
    could change the answer, and which reference was being read when it failed.
    """

    NULLABLE_MEMBERS: ClassVar[frozenset[str]] = frozenset({"source_ref"})

    code: WireShortText
    message: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    retryable: bool
    source_ref: WireSourceRef | None = None


class ToolObservation(CoreObservation):
    """What a tool hands back: a core observation, plus the one member the wire form does not have.

    ``ObservationRecord`` has no ``error`` member, and adding one to :class:`CoreObservation` would make the
    Python DTO and the schema disagree — the disagreement this module exists to prevent. So the extra member
    lives in a subclass, and the wire form stays exactly the schema's shape.

    ``error`` is how ``docs/agent-spec.md:36`` ("返回Observation带...错误") is representable at all: a tool that
    could not observe has to say so *in the observation*, rather than throwing and losing the attempt, because
    ``docs/agent-harness.md:51`` requires an error observation to go back to the model.
    """

    NULLABLE_MEMBERS: ClassVar[frozenset[str]] = frozenset({"result", "error"})

    error: CoreToolError | None = None


class CoreAgentProposal(CoreWireModel):
    """The proposal a run submits (docs/core-contracts.md:59).

    ``schema_version`` and ``case_id`` are both carried: the compat proposal is the field
    authority (docs/core-contracts.md:9 keeps its structure) and docs/core-contracts.md:57
    requires the body's subject to agree with the service JWT and the Case binding.
    ``suggested_amount_minor`` absent means nothing was suggested; ``null`` is not a
    second way to say that, and Java recomputes the real amount anyway
    (docs/product-spec.md:25).
    """

    schema_version: Literal[2]
    proposal_id: WireUuid
    run_id: WireUuid
    case_id: WireUuid
    input_revision: WireRevision
    case_type: Literal["LOGISTICS", "DAMAGED", "WRONG_MISSING", "OUT_OF_SCOPE"]
    recommended_action: Literal["REFUND", "REQUEST_INFO", "MANUAL_REVIEW", "REJECT"]
    suggested_amount_minor: WireSuggestedAmount | None = None
    summary: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    reason_codes: Annotated[list[WireReasonCode], Field(min_length=1, max_length=16)]
    evidence_refs: Annotated[list[CoreEvidenceRef], Field(max_length=32)] = []
    policy_refs: Annotated[list[CorePolicyRef], Field(max_length=10)] = []
    missing_evidence: Annotated[
        list[Annotated[str, StringConstraints(max_length=200)]], Field(max_length=10)
    ] = []

    @model_validator(mode="after")
    def check_actionable_proposal_cites_sources(self) -> CoreAgentProposal:
        if self.recommended_action != "REFUND":
            return self
        if not self.evidence_refs:
            raise ValueError("a refund proposal must cite at least one evidence reference")
        if not self.policy_refs:
            raise ValueError("a refund proposal must cite at least one policy reference")
        if self.missing_evidence:
            raise ValueError("a refund proposal cannot also ask for more evidence")
        return self