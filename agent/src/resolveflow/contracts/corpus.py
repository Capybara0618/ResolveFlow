"""The shared view of the T02 fixture corpus: where each fixture is validated.

docs/contracts.md:131 requires the OpenAPI documents and the JSON Schemas to agree,
and T02 makes that checkable rather than aspirational. This module holds the single
mapping from a corpus section to the schema that must accept it, so the generator
(``scripts/contracts_freeze.py``) and the test suite
(``tests/unit/test_contracts_fixtures.py``) cannot disagree about what "validated"
means — a fixture checked against a laxer schema by one of them would still look
covered.

Authority: docs/contracts.md for the routes and error bodies, contracts/*.schema.json
for the envelopes and documents, docs/domain-model.md for the state machines.
"""

from __future__ import annotations

from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from resolveflow.contracts._schemaio import ValidatorBundle, component_validator, validator_bundle
from resolveflow.contracts.canonical import (
    CanonicalizationError,
    canonicalize,
    content_hash,
    payload_hash,
)
from resolveflow.contracts.events import sign_envelope, signing_input_bytes
from resolveflow.contracts.fixtures import collect_placeholders, resolve_instance, substitute_values

__all__ = [
    "EVENT_PAYLOAD_DEFS",
    "OPENAPI_COMPONENTS",
    "OPENAPI_GROUPS",
    "REJECT_SCHEMA_TARGETS",
    "REJECT_SECTIONS",
    "RESULT_EVENT_SCHEMA",
    "SCHEMA_SECTIONS",
    "CorpusError",
    "enum_groups",
    "recompute_frozen_values",
    "require_placeholder_coverage",
    "resolve_envelope",
    "sign_corpus_envelopes",
    "strip_annotations",
    "validate_invalid_payloads",
    "validate_negative_corpus",
    "validate_valid_corpus",
]


class CorpusError(Exception):
    """A fixture does not mean what it claims, or no longer satisfies its contract."""


#: Sections validated against a named schema, keyed by corpus section. The value is a
#: standalone schema ``$id`` or a (service, component) pair from an OpenAPI document.
SCHEMA_SECTIONS: dict[str, str | tuple[str, str]] = {
    "execution_command": "urn:resolveflow:execution-command:v1",
    "agent_proposal": "urn:resolveflow:agent-proposal:v1",
    "harness_manifest": "urn:resolveflow:harness-manifest:v1",
    # The error body is the same shape every service returns, so its sample is validated
    # against the case-service component rather than a separate schema file.
    "error_body": ("case", "ErrorResponse"),
}

#: The schema holding the result-event payload variants.
RESULT_EVENT_SCHEMA = "urn:resolveflow:execution-result-event:v1"

#: Result payloads cannot know their own event_type, so each one is validated
#: against the variant that contracts/event-envelope.schema.json selects for it.
#: Without this mapping the section would be decoration: the envelope used to say
#: only ``payload: {type: object}`` for result events.
EVENT_PAYLOAD_DEFS: dict[str, str] = {
    "refund_succeeded": "refundResult",
    "refund_failed": "refundResult",
    "refund_unknown": "refundResult",
    "reship_succeeded": "reshipResult",
    "reship_unknown": "reshipResult",
    "entitlement_committed": "entitlementResult",
    "entitlement_released": "entitlementResult",
}

#: Which OpenAPI component each sample in ``valid.json`` must satisfy. The mapping
#: lives here rather than in the fixture so a fixture cannot pick a laxer schema for
#: itself.
OPENAPI_COMPONENTS: dict[str, tuple[str, str]] = {
    "case_create_request": ("case", "CaseCreateRequest"),
    "case_created_response": ("case", "CaseCreatedResponse"),
    "evidence_append_request": ("case", "EvidenceAppendRequest"),
    "review_request": ("case", "ReviewRequest"),
    # The reconcile body is the shared {reason} schema the spec table names, not a
    # route-specific copy; a copy is how two documents start disagreeing.
    "reconcile_request": ("case", "ReasonRequest"),
    "run_request": ("agent", "RunRequest"),
    # Python -> case callbacks are received by case-service, so case owns the
    # component even though the producer is the Python worker.
    "callback_question": ("case", "AgentCallbackRequest"),
    "callback_proposal": ("case", "AgentCallbackRequest"),
    "callback_failed": ("case", "AgentCallbackRequest"),
    "line_context": ("commerce", "LineContext"),
    "shipment_evidence": ("fulfillment", "ShipmentEvidence"),
    "packing_evidence": ("fulfillment", "PackingEvidence"),
    "entitlement_state": ("commerce", "EntitlementStateView"),
    "published_policy_bundle": ("case", "PublishedPolicyBundle"),
}

#: The OpenAPI sample groups in ``valid.json``.
OPENAPI_GROUPS = ("openapi_external", "openapi_internal")

#: The schema each negative section's instances must be refused by. An individual
#: entry may override this with its own ``schema`` key when a section covers several
#: variants of one document (the result-event payloads do).
REJECT_SCHEMA_TARGETS: dict[str, str | tuple[str, str]] = {
    "execution_command": "urn:resolveflow:execution-command:v1",
    "event_envelope": "urn:resolveflow:event-envelope:v1",
    "result_event_payload": RESULT_EVENT_SCHEMA,
    "agent_proposal": "urn:resolveflow:agent-proposal:v1",
    "harness_manifest": "urn:resolveflow:harness-manifest:v1",
    # Each service restates ErrorResponse in its own OpenAPI document; case is the
    # one with the external API, and the OpenAPI test separately asserts that all
    # four copies are identical, so validating one here is enough.
    "error_body": ("case", "ErrorResponse"),
}

#: The sections the negative corpus must cover.
REJECT_SECTIONS = frozenset(REJECT_SCHEMA_TARGETS)


def strip_annotations(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a corpus entry without its ``_``-prefixed annotations.

    Frozen digests must depend on a fixture's content, not on the prose explaining
    it, so an edited comment cannot invalidate a hash.
    """
    return {key: value for key, value in entry.items() if not key.startswith("_")}


def _validator_for(target: str | tuple[str, str]) -> ValidatorBundle:
    if isinstance(target, tuple):
        service, component = target
        return component_validator(service, component)
    return validator_bundle(target)


def validate_valid_corpus(valid: dict[str, Any], values: dict[str, str]) -> list[str]:
    """Validate every positive fixture. Returns one line per fixture checked."""
    lines: list[str] = []

    for section, target in SCHEMA_SECTIONS.items():
        validator = _validator_for(target)
        for name, entry in valid[section].items():
            instance = substitute_values(resolve_instance(entry, valid), values)
            errors = validator.error_messages(instance)
            if errors:
                raise CorpusError(
                    f"valid fixture {section}.{name} does not satisfy {validator.name}:\n  " + "\n  ".join(errors)
                )
            lines.append(f"validated {section}.{name} against {validator.name}")

    for name, entry in valid["event_payload"].items():
        schema_id = f"{RESULT_EVENT_SCHEMA}#/$defs/{EVENT_PAYLOAD_DEFS[name]}"
        validator = validator_bundle(schema_id)
        instance = substitute_values(resolve_instance(entry, valid), values)
        errors = validator.error_messages(instance)
        if errors:
            raise CorpusError(
                f"valid fixture event_payload.{name} does not satisfy {schema_id}:\n  " + "\n  ".join(errors)
            )
        lines.append(f"validated event_payload.{name} against {schema_id}")

    for group in OPENAPI_GROUPS:
        for section, entry in valid[group].items():
            validator = _validator_for(OPENAPI_COMPONENTS[section])
            instance = substitute_values(resolve_instance(entry, valid), values)
            errors = validator.error_messages(instance)
            if errors:
                raise CorpusError(f"valid fixture {group}.{section} failed {validator.name}:\n  " + "\n  ".join(errors))
            lines.append(f"validated {group}.{section} against {validator.name}")

    return lines


def validate_negative_corpus(reject: dict[str, Any]) -> list[str]:
    """Assert every negative fixture is refused by the schema it names.

    Returns one line per fixture. If a rejection starts passing, the protocol
    regressed: the schema is what needs fixing, not the fixture.
    """
    lines: list[str] = []
    for section, entries in reject.items():
        if section.startswith("_"):
            continue
        if section not in REJECT_SCHEMA_TARGETS:
            raise CorpusError(f"negative corpus section '{section}' names no schema to be refused by")
        for name, entry in entries.items():
            validator = _validator_for(entry.get("schema", REJECT_SCHEMA_TARGETS[section]))
            if not entry.get("why"):
                raise CorpusError(f"negative fixture {section}.{name} does not say why it must be refused")
            if validator.accepts(entry["instance"]):
                raise CorpusError(
                    f"negative fixture {section}.{name} is accepted by {validator.name}, but it must be "
                    f"refused. Reason it exists: {entry['why']}"
                )
            lines.append(f"rejected as required: {section}.{name}")
    return lines


def validate_invalid_payloads(canonical: dict[str, Any]) -> list[str]:
    """Prove every payload in ``invalid_payloads`` is refused rather than hashed.

    These are the cases a JSON Schema cannot express - a float amount, an integer past
    2^53-1, a missing hashed field - so they are checked by calling the hasher, the same
    way a producer would. A payload that silently hashes is worse than one that hashes
    wrongly: both sides would agree on a digest for something that must not exist.
    """
    lines: list[str] = []
    for name, entry in canonical["invalid_payloads"].items():
        if not entry.get("_comment"):
            raise CorpusError(f"invalid payload {name} does not say why it must be refused")
        try:
            payload_hash(strip_annotations(entry))
        except CanonicalizationError as error:
            lines.append(f"refused as required: invalid_payloads.{name} ({error})")
        else:
            raise CorpusError(
                f"invalid payload {name} was hashed instead of refused. Reason it exists: {entry['_comment']}"
            )
    return lines


def resolve_envelope(corpus: dict[str, Any], name: str, values: dict[str, str]) -> dict[str, Any]:
    """Resolve a signed/result envelope and inline the payload it references.

    The envelope's ``payload_ref`` points at an execution command or a result payload
    elsewhere in the corpus, and the command's own ``payload_hash`` is a placeholder,
    so the referenced entry is substituted before being attached: neither language may
    sign over a literal ``PLACEHOLDER_*`` token.
    """
    entry = corpus["message_envelope"][name]
    instance = resolve_instance(entry, corpus)
    reference = entry["payload_ref"]
    section, _, member = reference.partition(".")
    if section not in ("execution_command", "event_payload") or not member:
        raise CorpusError(f"envelope {name} references an unsupported section: {reference}")
    instance["payload"] = substitute_values(resolve_instance(corpus[section][member], corpus), values)
    return instance


def sign_corpus_envelopes(
    valid: dict[str, Any],
    values: dict[str, str],
    private_key: Ed25519PrivateKey,
    expected_key_id: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Sign the case envelopes and freeze every signing input.

    Returns ``(signing_inputs, signatures)`` keyed by envelope name, and records each
    signature in ``values`` under the placeholder the fixture declares. The fixture
    names its own placeholder rather than deriving one from the entry name: two
    envelopes may share an event type (signed and unsigned RefundRequested), so a
    derived name would collide and one frozen signature would silently overwrite the
    other.
    """
    signing_inputs: dict[str, str] = {}
    signatures: dict[str, str] = {}

    validator = validator_bundle("urn:resolveflow:event-envelope:v1")
    for name, entry in valid["message_envelope"].items():
        instance = resolve_envelope(valid, name, values)
        unsigned = "signing_key_id" not in instance

        if not unsigned and instance["signing_key_id"] != expected_key_id:
            raise CorpusError(
                f"envelope {name} names key {instance['signing_key_id']!r}; "
                f"the frozen test key is {expected_key_id!r}"
            )
        if unsigned:
            # Result events published by commerce/fulfillment are not case-signed
            # (docs/contracts.md:121). They still have a signing *input* worth freezing
            # - the byte sequence a future signing producer must reproduce - but there
            # is no signature to compare.
            if "signature" in instance:
                raise CorpusError(f"envelope {name} has a signature but no signing_key_id to name its key")
            if entry.get("_signature_placeholder"):
                raise CorpusError(f"envelope {name} is unsigned but declares a signature placeholder")
        else:
            token = entry.get("_signature_placeholder")
            if not token:
                raise CorpusError(
                    f"signed envelope {name} must declare _signature_placeholder so the frozen signature "
                    f"can be referenced from the corpus"
                )
            instance["signature"] = sign_envelope(instance, private_key)
            signatures[name] = instance["signature"]
            values[token] = instance["signature"]

        errors = validator.error_messages(instance)
        if errors:
            raise CorpusError(
                f"valid fixture message_envelope.{name} failed the envelope schema:\n  " + "\n  ".join(errors)
            )
        signing_inputs[name] = signing_input_bytes(instance).decode("utf-8")

    return signing_inputs, signatures


def recompute_frozen_values(
    canonical: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Recompute the execution payload hashes, content hashes and canonical texts."""
    payload_hashes = {
        name: payload_hash(strip_annotations(payload)) for name, payload in canonical["execution_payloads"].items()
    }
    content_hashes = {
        name: content_hash(strip_annotations(value)) for name, value in canonical["content_hashes"].items()
    }
    canonical_texts = {
        name: canonicalize(strip_annotations(value)) for name, value in canonical["unicode_documents"].items()
    }
    return payload_hashes, content_hashes, canonical_texts


def require_placeholder_coverage(documents: dict[str, Any], values: dict[str, str]) -> None:
    """Prove the frozen table covers exactly what the corpus documents reference.

    ``documents`` maps a name to a corpus document; a token counts as used if any of
    them references it, so a value may not be frozen without a reader and a reader may
    not reference a value that was never frozen.
    """
    used: set[str] = set()
    for document in documents.values():
        used |= collect_placeholders(document)
    unresolved = sorted(token for token in used if token not in values)
    if unresolved:
        raise CorpusError("the corpus uses placeholders that are not frozen: " + ", ".join(unresolved))
    unused = sorted(token for token in values if token not in used)
    if unused:
        raise CorpusError("frozen placeholders no fixture uses: " + ", ".join(unused))


def enum_groups() -> dict[str, list[str]]:
    """Every wire enum, keyed by the JSON key in ``contracts/fixtures/expected-enums.json``.

    Java contributes the same map from ``com.resolveflow.shared.contract.ContractEnums``.
    A group added on one side and not the other fails the comparison instead of being
    ignored.
    """
    from resolveflow.contracts import enums

    groups: dict[str, list[str]] = {
        "event_type": [member.value for member in enums.EventType],
        "producer": [member.value for member in enums.Producer],
        "action": [member.value for member in enums.Action],
        "requested_action": [member.value for member in enums.RequestedAction],
        "case_type": [member.value for member in enums.CaseType],
        "recommended_action": [member.value for member in enums.RecommendedAction],
        "case_status": [member.value for member in enums.CaseStatus],
        "timeline_event_type": [member.value for member in enums.TimelineEventType],
        "callback_kind": [member.value for member in enums.CallbackKind],
        "callback_disposition": [member.value for member in enums.CallbackDisposition],
        "idempotency_disposition": [member.value for member in enums.IdempotencyDisposition],
        "proposal_status": [member.value for member in enums.ProposalStatus],
        "authorization_status": [member.value for member in enums.AuthorizationStatus],
        "decision": [member.value for member in enums.Decision],
        "risk_route": [member.value for member in enums.RiskRoute],
        "entitlement_state": [member.value for member in enums.EntitlementState],
        "operation_state": [member.value for member in enums.OperationState],
        "evidence_source_type": [member.value for member in enums.EvidenceSourceType],
        "error_code": [member.value for member in enums.ErrorCode],
        # Added when the OpenAPI documents turned out to use three value sets the frozen
        # table did not cover: a reviewer verdict, the carrier's own conclusion, and the
        # agent_run lifecycle. Leaving them out is how two languages end up disagreeing
        # about whether a run is STALE or a shipment is UNKNOWN.
        "verification_result": [member.value for member in enums.VerificationResult],
        "carrier_conclusion": [member.value for member in enums.CarrierConclusion],
        "run_status": [member.value for member in enums.RunStatus],
        "verified_status": [member.value for member in enums.VerifiedStatus],
    }
    return groups