"""C00.2a: the core-v1.2 command and envelope schemas enforce the narrowed scope.

docs/core-contracts.md section 6 makes C00 responsible for refusing, at the schema
level, the things the compat baseline still allows: a RESHIP command, the
``entitlement_id``/``address_hash`` helper fields, a float or negative amount, a
foreign target service, a v1 version marker, an old topic, and an unsigned result.

Several assertions are deliberately about the *old* files: the migration has to leave
the v1 protocol exactly as permissive as it was (its fixtures still validate) while the
core files are strict. A migration that tightened the old schema to make the new one
look clean would be rewriting the baseline rather than adding to it.
"""

from __future__ import annotations

from typing import Any

import pytest

from resolveflow.contracts import canonical
from resolveflow.contracts._schemaio import CORE_SCHEMA_FILES, SCHEMA_FILES, schema_registry, validator_bundle

CORE_COMMAND = "urn:resolveflow:core:refund-command:v2"
CORE_ENVELOPE = "urn:resolveflow:core:event-envelope:v2"
V1_COMMAND = "urn:resolveflow:execution-command:v1"
V1_ENVELOPE = "urn:resolveflow:event-envelope:v1"

OPERATION_ID = "6f1c1c3e-0f4a-4a9e-9a0e-2f6d1b9c7a11"
CASE_ID = "0f9a2f4c-6b1d-4c8e-8f2a-1d3b5c7e9a02"
AUTHORIZATION_ID = "3c7e9a02-5d1b-4f6a-9c3e-7b2d4f6a8c04"
EVENT_ID = "9a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
PAYLOAD_HASH = "a" * 64
OCCURRED_AT = "2026-09-18T09:30:00Z"


def refund_command(**overrides: Any) -> dict[str, Any]:
    """A well-formed core refund command; overrides let a test break one rule."""
    payload: dict[str, Any] = {
        "operation_id": OPERATION_ID,
        "case_id": CASE_ID,
        "authorization_id": AUTHORIZATION_ID,
        "input_revision": 3,
        "line_id": "LINE-1001",
        "merchant_id": "MERCHANT-7",
        "action": "REFUND",
        "quantity": 2,
        "currency": "CNY",
        "amount_minor": 2599,
        "payload_hash": PAYLOAD_HASH,
        "policy_version": "policy-2026.09#3",
        "target_service": "commerce-service",
    }
    payload.update(overrides)
    return payload


def refund_result(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "operation_id": OPERATION_ID,
        "line_id": "LINE-1001",
        "state": "SUCCEEDED",
        "amount_minor": 2599,
        "aggregate_version": 4,
    }
    payload.update(overrides)
    return payload


def core_envelope(event_type: str, payload: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """A well-formed core envelope; the event type picks the default producer/topic."""
    is_command = event_type == "RefundRequested"
    envelope: dict[str, Any] = {
        "event_id": EVENT_ID,
        "event_type": event_type,
        "schema_version": 2,
        "merchant_id": "MERCHANT-7",
        "occurred_at": OCCURRED_AT,
        "producer": "case-service" if is_command else "commerce-service",
        "topic": "rf.case.core.v2" if is_command else "rf.commerce.core.v2",
        "payload": payload,
        "signing_key_id": "case-signing-key-2026-09" if is_command else "commerce-signing-key-2026-09",
        "signature": "c2lnbmF0dXJlLWVkMjU1MTk=",
    }
    envelope.update(overrides)
    return envelope


@pytest.fixture(scope="module")
def command_validator():  # type: ignore[no-untyped-def]
    return validator_bundle(CORE_COMMAND, CORE_SCHEMA_FILES)


@pytest.fixture(scope="module")
def envelope_validator():  # type: ignore[no-untyped-def]
    return validator_bundle(CORE_ENVELOPE, CORE_SCHEMA_FILES)


@pytest.fixture(scope="module")
def result_validator():  # type: ignore[no-untyped-def]
    return validator_bundle(f"{CORE_ENVELOPE}#/$defs/refundResult", CORE_SCHEMA_FILES)


# --------------------------------------------------------------------------- identity


def test_core_schemas_use_their_own_urns() -> None:
    core_registry, core_documents = schema_registry(CORE_SCHEMA_FILES)
    compat_registry, compat_documents = schema_registry(SCHEMA_FILES)
    core_ids = {document["$id"] for document in core_documents.values()}
    compat_ids = {document["$id"] for document in compat_documents.values()}
    assert core_ids == {CORE_COMMAND, CORE_ENVELOPE}
    assert core_ids.isdisjoint(compat_ids)
    assert len(core_documents) == len(CORE_SCHEMA_FILES)
    assert core_registry is not None and compat_registry is not None


def test_core_registry_cannot_resolve_the_compat_protocol() -> None:
    with pytest.raises(KeyError):
        validator_bundle(V1_COMMAND, CORE_SCHEMA_FILES)
    with pytest.raises(KeyError):
        validator_bundle(V1_ENVELOPE, CORE_SCHEMA_FILES)


def test_compat_registry_cannot_resolve_the_core_protocol() -> None:
    with pytest.raises(KeyError):
        validator_bundle(CORE_COMMAND, SCHEMA_FILES)


def test_command_schema_carries_exactly_the_hashed_fields(command_validator) -> None:  # type: ignore[no-untyped-def]
    schema = command_validator.schema
    expected = set(canonical.REFUND_FIELDS) | {"payload_hash"}
    assert set(schema["properties"]) == expected
    assert set(schema["required"]) == expected
    assert schema["additionalProperties"] is False


def test_result_schema_carries_exactly_the_documented_result_fields() -> None:
    _, documents = schema_registry(CORE_SCHEMA_FILES)
    envelope = next(document for document in documents.values() if document["$id"] == CORE_ENVELOPE)
    result = envelope["$defs"]["refundResult"]
    assert set(result["properties"]) == {
        "operation_id",
        "line_id",
        "state",
        "amount_minor",
        "provider_ref",
        "reason_code",
        "aggregate_version",
    }
    assert result["additionalProperties"] is False


def test_the_envelope_no_longer_repeats_the_aggregate_version() -> None:
    _, documents = schema_registry(CORE_SCHEMA_FILES)
    envelope = next(document for document in documents.values() if document["$id"] == CORE_ENVELOPE)
    assert "aggregate_version" not in envelope["properties"]
    assert "aggregate_id" not in envelope["properties"]
    # ... while the compat envelope still carries both, untouched.
    compat = next(
        document
        for _, document in schema_registry(SCHEMA_FILES)[1].items()
        if document["$id"] == V1_ENVELOPE
    )
    assert {"aggregate_id", "aggregate_version"} <= set(compat["properties"])


# -------------------------------------------------------------------------- positives


def test_well_formed_refund_command_is_accepted(command_validator) -> None:  # type: ignore[no-untyped-def]
    assert command_validator.accepts(refund_command())


def test_refund_requested_envelope_is_accepted(envelope_validator) -> None:  # type: ignore[no-untyped-def]
    assert envelope_validator.accepts(core_envelope("RefundRequested", refund_command()))


@pytest.mark.parametrize("event_type", ["RefundSucceeded", "RefundFailed", "RefundUnknown"])
def test_result_envelopes_are_accepted(envelope_validator, event_type: str) -> None:  # type: ignore[no-untyped-def]
    state = {"RefundSucceeded": "SUCCEEDED", "RefundFailed": "FAILED", "RefundUnknown": "UNKNOWN"}[event_type]
    envelope = core_envelope(event_type, refund_result(state=state))
    assert envelope_validator.accepts(envelope)


def test_envelope_may_carry_trace_context(envelope_validator) -> None:  # type: ignore[no-untyped-def]
    envelope = core_envelope(
        "RefundRequested",
        refund_command(),
        traceparent="00-" + "b" * 32 + "-" + "c" * 16 + "-01",
    )
    assert envelope_validator.accepts(envelope)


def test_result_payload_accepts_a_null_provider_ref_and_reason(result_validator) -> None:  # type: ignore[no-untyped-def]
    assert result_validator.accepts(refund_result(provider_ref=None, reason_code=None))
    assert result_validator.accepts(
        refund_result(state="FAILED", provider_ref="masked-7f3a", reason_code="PROVIDER_TIMEOUT")
    )


# -------------------------------------------------------------------------- negatives


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("action", "RESHIP"),
        ("target_service", "fulfillment-service"),
        ("currency", "USD"),
        ("amount_minor", 0),
        ("amount_minor", -1),
        ("amount_minor", 1_000_000_001),
        ("amount_minor", 25.99),
        ("quantity", 0),
        ("input_revision", 0),
        ("input_revision", 2**53),
        ("operation_id", "not-a-uuid"),
        ("payload_hash", "A" * 64),
    ],
)
def test_command_refuses_out_of_scope_values(command_validator, field: str, value: Any) -> None:  # type: ignore[no-untyped-def]
    assert not command_validator.accepts(refund_command(**{field: value})), f"{field}={value!r} must be refused"


@pytest.mark.parametrize("field", ["entitlement_id", "address_hash", "schema_version", "trace_id"])
def test_command_refuses_v1_helper_and_unknown_fields(command_validator, field: str) -> None:  # type: ignore[no-untyped-def]
    instance = refund_command(**{field: "x" if field.endswith("id") or field == "address_hash" else 1})
    assert not command_validator.accepts(instance)
    assert field in " ".join(command_validator.error_messages(instance))


def test_command_requires_the_amount_that_v1_made_conditional(command_validator) -> None:  # type: ignore[no-untyped-def]
    instance = refund_command()
    del instance["amount_minor"]
    assert not command_validator.accepts(instance)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 1),
        ("event_type", "ReshipRequested"),
        ("event_type", "EntitlementCommitted"),
        ("topic", "rf.case.v1"),
        ("topic", "rf.fulfillment.v1"),
    ],
)
def test_envelope_refuses_the_compat_version_events_and_topics(envelope_validator, field: str, value: Any) -> None:  # type: ignore[no-untyped-def]
    envelope = core_envelope("RefundRequested", refund_command())
    envelope[field] = value
    assert not envelope_validator.accepts(envelope)


def test_command_envelope_refuses_the_result_topic(envelope_validator) -> None:  # type: ignore[no-untyped-def]
    envelope = core_envelope("RefundRequested", refund_command(), topic="rf.commerce.core.v2")
    assert not envelope_validator.accepts(envelope)
    assert "rf.case.core.v2" in " ".join(envelope_validator.error_messages(envelope))


def test_result_envelope_refuses_the_case_producer(envelope_validator) -> None:  # type: ignore[no-untyped-def]
    envelope = core_envelope("RefundSucceeded", refund_result(), producer="case-service")
    assert not envelope_validator.accepts(envelope)


def test_result_envelope_requires_a_signature_in_core(envelope_validator) -> None:  # type: ignore[no-untyped-def]
    envelope = core_envelope("RefundSucceeded", refund_result())
    del envelope["signature"]
    assert not envelope_validator.accepts(envelope)
    # The compat envelope still allows an unsigned result, which is why core is a new file.
    assert validator_bundle(V1_ENVELOPE).accepts(
        {
            "event_id": EVENT_ID,
            "event_type": "RefundSucceeded",
            "schema_version": 1,
            "aggregate_id": "LINE-1001",
            "aggregate_version": 4,
            "merchant_id": "MERCHANT-7",
            "occurred_at": OCCURRED_AT,
            "producer": "commerce-service",
            "payload": {
                "operation_id": OPERATION_ID,
                "line_id": "LINE-1001",
                "state": "SUCCEEDED",
                "amount_minor": 2599,
            },
        }
    )


def test_command_envelope_refuses_a_result_payload(envelope_validator) -> None:  # type: ignore[no-untyped-def]
    envelope = core_envelope("RefundRequested", refund_result())
    assert not envelope_validator.accepts(envelope)


def test_result_envelope_refuses_a_command_payload(envelope_validator) -> None:  # type: ignore[no-untyped-def]
    envelope = core_envelope("RefundSucceeded", refund_command())
    assert not envelope_validator.accepts(envelope)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity", 2),
        ("aggregate_version", None),
        ("state", "CREATED"),
        ("state", "RESERVED"),
        ("amount_minor", 0),
        ("reason_code", "provider_timeout"),
    ],
)
def test_result_payload_refuses_non_terminal_or_foreign_fields(result_validator, field: str, value: Any) -> None:  # type: ignore[no-untyped-def]
    instance = refund_result()
    if value is None:
        del instance[field]
    else:
        instance[field] = value
    assert not result_validator.accepts(instance)


def test_envelope_refuses_a_naive_timestamp(envelope_validator) -> None:  # type: ignore[no-untyped-def]
    envelope = core_envelope("RefundRequested", refund_command(), occurred_at="2026-09-18T09:30:00")
    assert not envelope_validator.accepts(envelope)


def test_envelope_refuses_unknown_members(envelope_validator) -> None:  # type: ignore[no-untyped-def]
    envelope = core_envelope("RefundRequested", refund_command(), entitlement_id="fake")
    assert not envelope_validator.accepts(envelope)


def test_result_payload_hash_is_recomputed_from_the_core_field_set(command_validator) -> None:  # type: ignore[no-untyped-def]
    """The schema's field list and the hasher must agree, not merely both exist."""
    instance = refund_command()
    instance["payload_hash"] = canonical.payload_hash(instance)
    assert command_validator.accepts(instance)
    # A RESHIP payload is not hashable in core at all: fields_for_action refuses it.
    with pytest.raises(canonical.CanonicalizationError):
        canonical.payload_hash(refund_command(action="RESHIP"))