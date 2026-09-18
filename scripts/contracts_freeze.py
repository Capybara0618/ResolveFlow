#!/usr/bin/env python3
"""Regenerate (or verify) the frozen T02 expectations: contracts/fixtures/expected-*.json.

Run from anywhere:

    uv run --project agent --frozen python scripts/contracts_freeze.py
    uv run --project agent --frozen python scripts/contracts_freeze.py --check

Why a generator at all: docs/contracts.md:17 requires T02 to freeze both the
signing inputs and the resulting bytes, and docs/contracts.md:13 the same for the
execution payload hash. Hand-typing 64-character hashes into a JSON file is how
those numbers stop matching the fixtures they describe. Here the values are
*computed* from the corpus, and the corpus is validated in the same pass, so a
fixture edit that changes a hash cannot leave the frozen file stale.

``--check`` recomputes everything and compares against the files on disk without
writing, which is what ``verify -Suite contracts`` runs. A fixture edited without
re-freezing, or a canonicalisation regression, therefore fails the suite instead
of quietly disagreeing with the frozen file.

Editing this script, or running it without ``--check``, is the intended way to
re-freeze. Re-freezing because a test failed is not: a changed hash means either
the corpus changed on purpose or the canonicalisation regressed, and those need
different answers.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# Allow running the script directly without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent" / "src"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from resolveflow.contracts import enums  # noqa: E402
from resolveflow.contracts._schemaio import (  # noqa: E402
    REPO_ROOT,
    component_validator,
    load_json,
    validator_bundle,
)
from resolveflow.contracts.canonical import canonicalize, content_hash, payload_hash  # noqa: E402
from resolveflow.contracts.events import sign_envelope, signing_input_bytes  # noqa: E402
from resolveflow.contracts.fixtures import (  # noqa: E402
    CORPUS_PATHS,
    GENERATED_PATHS,
    collect_placeholders,
    resolve_instance,
    substitute_values,
)

#: A fixed test seed. The private key derived from it is a *fixture*, never a
#: deployment key: docs/contracts.md:17 mounts the real private key at runtime and
#: keeps it out of the repository. Anyone can reproduce this key, which is exactly
#: what makes the frozen signature verifiable in CI.
TEST_KEY_SEED = b"resolveflow-t02-event-signature-fixture-v1"
TEST_SIGNING_KEY_ID = "rf-case-events-2026-09"

#: Which OpenAPI component each ``valid.json`` section must satisfy. The mapping
#: lives here rather than in the fixture so a fixture cannot pick a laxer schema
#: for itself.
OPENAPI_COMPONENTS = {
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

#: JSON Schema id for the sections validated against a standalone schema file.
SCHEMA_SECTIONS = {
    "execution_command": "urn:resolveflow:execution-command:v1",
    "agent_proposal": "urn:resolveflow:agent-proposal:v1",
    "harness_manifest": "urn:resolveflow:harness-manifest:v1",
}

#: Result payloads cannot know their own event_type, so each one is validated
#: against the variant that contracts/event-envelope.schema.json selects for it.
#: Without this mapping the section would be decoration: the envelope only used to
#: say ``payload: {type: object}`` for result events.
EVENT_PAYLOAD_DEFS = {
    "refund_succeeded": "refundResult",
    "refund_failed": "refundResult",
    "refund_unknown": "refundResult",
    "reship_succeeded": "reshipResult",
    "reship_unknown": "reshipResult",
    "entitlement_committed": "entitlementResult",
    "entitlement_released": "entitlementResult",
}

RESULT_EVENT_SCHEMA = "urn:resolveflow:execution-result-event:v1"

#: The schema each negative section's instances must be refused by. An individual
#: entry may override this with its own ``schema`` key when the section covers
#: several variants of one document.
REJECT_SCHEMA_TARGETS: dict[str, Any] = {
    "execution_command": "urn:resolveflow:execution-command:v1",
    "event_envelope": "urn:resolveflow:event-envelope:v1",
    "result_event_payload": RESULT_EVENT_SCHEMA,
    "agent_proposal": "urn:resolveflow:agent-proposal:v1",
    "harness_manifest": "urn:resolveflow:harness-manifest:v1",
    # Each service restates ErrorResponse in its own OpenAPI document; case is the
    # one with the external API, and test_contract_openapi.py separately asserts
    # that all four copies are identical, so validating one here is enough.
    "error_body": ("case", "ErrorResponse"),
}


def strip_annotations(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a corpus entry without its ``_``-prefixed annotations."""
    return {key: value for key, value in entry.items() if not key.startswith("_")}


def test_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(TEST_KEY_SEED).digest())


def placeholder_token(name: str) -> str:
    return f"PLACEHOLDER_{name.upper().replace('-', '_')}"


def render_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def enum_expectations() -> dict[str, Any]:
    """Freeze every wire enum so a rename on one side fails a test on both."""
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
    }
    return {
        "_comment": [
            "T02 frozen enum mapping. Java (com.resolveflow.shared.contract.ContractEnums) and Python (resolveflow.contracts.enums) both assert against this file.",
            "A member renamed on one side therefore fails a test on both, instead of producing an unroutable action at runtime.",
            "Regenerate with: uv run --project agent --frozen python scripts/contracts_freeze.py",
        ],
        "enums": groups,
    }


def check_placeholder_coverage(documents: dict[str, Any], values: dict[str, str]) -> None:
    """Prove the frozen table covers exactly what the fixtures reference.

    ``documents`` maps a name to a corpus document; a token counts as used if any
    of them references it, so a value may not be frozen without a reader and a
    reader may not reference a value that was never frozen.
    """
    used: set[str] = set()
    for document in documents.values():
        used |= collect_placeholders(document)
    unresolved = sorted(token for token in used if token not in values)
    if unresolved:
        raise SystemExit("the corpus uses placeholders the generator does not freeze: " + ", ".join(unresolved))
    unused = sorted(token for token in values if token not in used)
    if unused:
        raise SystemExit(f"the generator freezes placeholders no fixture uses: {', '.join(unused)}")


def build() -> dict[str, str]:
    """Validate the whole corpus and return ``path -> file text`` for the frozen files."""
    canonical = load_json(CORPUS_PATHS["canonical"])
    valid = load_json(CORPUS_PATHS["valid"])
    private_key = test_private_key()
    public_key = private_key.public_key()

    # ``_``-prefixed members are annotations for the reader, never data. They are
    # removed before hashing so that editing a comment cannot change a frozen
    # digest: a frozen value should depend on the fixture's content, not on the
    # prose explaining it.
    payload_hashes = {
        name: payload_hash(strip_annotations(payload)) for name, payload in canonical["execution_payloads"].items()
    }
    content_hashes = {
        name: content_hash(strip_annotations(value)) for name, value in canonical["content_hashes"].items()
    }
    canonical_texts = {
        name: canonicalize(strip_annotations(value)) for name, value in canonical["unicode_documents"].items()
    }

    # Placeholder table, hashes first. A placeholder exists so a fixture can refer
    # to a frozen digest instead of repeating 64 characters. Only the payloads some
    # fixture actually embeds need one: the remaining canonical payloads are hash
    # *inputs* with nothing to reference, and are still frozen below and asserted
    # by both languages. Requiring a placeholder for every one of them would mean
    # inventing a use for it.
    referenced_tokens = collect_placeholders(valid) | collect_placeholders(canonical)
    values: dict[str, str] = {
        placeholder_token(name): digest
        for name, digest in payload_hashes.items()
        if placeholder_token(name) in referenced_tokens
    }

    # 1) Resolve and validate every section backed by a standalone JSON Schema.
    substituted: dict[str, dict[str, Any]] = {
        "execution_command": {},
        "event_payload": {},
        "agent_proposal": {},
        "harness_manifest": {},
    }
    for section, schema_id in SCHEMA_SECTIONS.items():
        validator = validator_bundle(schema_id)
        for name, entry in valid[section].items():
            instance = substitute_values(resolve_instance(entry, valid), values)
            errors = validator.error_messages(instance)
            if errors:
                raise SystemExit(
                    f"valid fixture {section}.{name} does not satisfy {schema_id}:\n  " + "\n  ".join(errors)
                )
            substituted[section][name] = instance
            print(f"validated {section}.{name} against {schema_id}")

    # 1b) Result payloads, one variant each, selected by the event that carries them.
    for name, entry in valid["event_payload"].items():
        schema_id = f"{RESULT_EVENT_SCHEMA}#/$defs/{EVENT_PAYLOAD_DEFS[name]}"
        validator = validator_bundle(schema_id)
        instance = substitute_values(resolve_instance(entry, valid), values)
        errors = validator.error_messages(instance)
        if errors:
            raise SystemExit(f"valid fixture event_payload.{name} does not satisfy {schema_id}:\n  " + "\n  ".join(errors))
        substituted["event_payload"][name] = instance
        print(f"validated event_payload.{name} against {schema_id}")

    # 2) Sign the command envelopes and validate the full envelope document. The
    #    envelope payload *is* the execution command, so the two share bytes.
    signatures: dict[str, str] = {}
    signing_bytes: dict[str, str] = {}
    envelope_validator = validator_bundle("urn:resolveflow:event-envelope:v1")
    for name, entry in valid["message_envelope"].items():
        instance = resolve_instance(entry, valid)
        reference = entry["payload_ref"]
        if reference.startswith("execution_command."):
            # The envelope payload *is* the execution command, so the two share
            # bytes and therefore share the frozen payload_hash.
            action = substituted["execution_command"][reference.split(".")[-1]]["action"]
            instance["payload"] = substituted["execution_command"]["refund" if action == "REFUND" else "reship"]
        elif reference.startswith("event_payload."):
            instance["payload"] = substituted["event_payload"][reference.split(".")[-1]]
        else:
            raise SystemExit(f"envelope {name} references an unsupported section: {reference}")

        unsigned = "signing_key_id" not in instance
        if not unsigned and instance["signing_key_id"] != TEST_SIGNING_KEY_ID:
            raise SystemExit(
                f"envelope {name} names key {instance['signing_key_id']!r}; "
                f"the frozen test key is {TEST_SIGNING_KEY_ID!r}"
            )
        if unsigned:
            # Result events published by commerce/fulfillment are not case-signed
            # (docs/contracts.md:121). They still have a signing *input* worth
            # freezing — it is the byte sequence a future signing producer would
            # have to reproduce — but there is no signature to compare.
            if "signature" in instance:
                raise SystemExit(f"envelope {name} has a signature but no signing_key_id to name its key")
            if entry.get("_signature_placeholder"):
                raise SystemExit(f"envelope {name} is unsigned but declares a signature placeholder")
        else:
            instance["signature"] = sign_envelope(instance, private_key)
            signatures[name] = instance["signature"]
            # The fixture names its own placeholder rather than deriving one from
            # the entry name: two envelopes may share an event type (signed and
            # unsigned RefundRequested), so a derived name would collide and one
            # frozen signature would silently overwrite the other.
            token = entry.get("_signature_placeholder")
            if not token:
                raise SystemExit(
                    f"signed envelope {name} must declare _signature_placeholder so the frozen "
                    f"signature can be referenced from the corpus"
                )
            values[token] = instance["signature"]

        errors = envelope_validator.error_messages(instance)
        if errors:
            raise SystemExit(
                f"valid fixture message_envelope.{name} failed the envelope schema:\n  " + "\n  ".join(errors)
            )
        signing_bytes[name] = signing_input_bytes(instance).decode("utf-8")
        print(f"validated message_envelope.{name}" + ("" if unsigned else " and signed it"))

    # 3) OpenAPI component samples: one frozen sample per documented route, checked
    #    against the component schema the OpenAPI document itself declares, so a
    #    sample cannot disagree with the document that describes it. (Whether each
    #    operation carries an example at all is asserted by
    #    agent/tests/unit/test_contract_openapi.py.)
    for group in ("openapi_external", "openapi_internal"):
        for section, entry in valid[group].items():
            service, component = OPENAPI_COMPONENTS[section]
            validator = component_validator(service, component)
            instance = substitute_values(resolve_instance(entry, valid), values)
            errors = validator.error_messages(instance)
            if errors:
                raise SystemExit(f"valid fixture {group}.{section} failed {validator.name}:\n  " + "\n  ".join(errors))
            print(f"validated {group}.{section} against {validator.name}")

    # 4) The negative corpus must actually be refused by the schema it names. If a
    #    rejection starts passing, the protocol regressed - the fixture is not the
    #    thing to update.
    reject = load_json(CORPUS_PATHS["reject"])
    for section, entries in reject.items():
        if section.startswith("_"):
            continue
        for name, entry in entries.items():
            target = entry.get("schema", REJECT_SCHEMA_TARGETS[section])
            if isinstance(target, tuple):
                service, component = target
                validator = component_validator(service, component)
            else:
                validator = validator_bundle(target)
            if not entry.get("why"):
                raise SystemExit(f"negative fixture {section}.{name} does not say why it must be refused")
            if validator.accepts(entry["instance"]):
                raise SystemExit(
                    f"negative fixture {section}.{name} is accepted by {validator.name}, but it must be refused. "
                    f"Reason it exists: {entry['why']}"
                )
            print(f"rejected as required: {section}.{name}")

    # 5) Freeze. Signature values were registered as each envelope was signed, so
    #    the placeholder table and the frozen signatures cannot disagree. Coverage
    #    is checked across both corpus documents, since either may reference a
    #    frozen value.
    merged: dict[str, Any] = {"valid": valid, "canonical": canonical}
    check_placeholder_coverage(merged, values)

    hashes = {
        "_comment": [
            "Frozen T02 expectations. Generated by scripts/contracts_freeze.py; do not hand-edit.",
            "docs/contracts.md:17 requires both the signing input and the resulting bytes to be fixed by a cross-language test, and the same for the execution payload hash.",
            "Java (com.resolveflow.shared.contract) and Python (resolveflow.contracts) each reproduce these values from contracts/fixtures/examples/*.json. Either side failing means the two implementations disagree.",
            "The signing keys below are derived from a public fixture seed and exist only so the frozen signature can be verified in CI. They are not deployment keys.",
            "signing_inputs covers every envelope in the corpus, signed or not: for an unsigned result event it is the byte sequence a producer would sign, which is what makes the normalisation rule testable.",
        ],
        "algorithm": {
            "payload_hash": "SHA-256 over RFC 8785 canonical JSON of the documented field set",
            "event_signature": "Ed25519 (RFC 8032) over the canonical envelope with `signature` excluded",
        },
        "signing_keys": {
            "key_id": TEST_SIGNING_KEY_ID,
            "seed_sha256_preimage": TEST_KEY_SEED.decode("ascii"),
            "private_key_pkcs8_base64": base64.b64encode(
                private_key.private_bytes(
                    encoding=serialization.Encoding.DER,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            ).decode("ascii"),
            "public_key_spki_base64": base64.b64encode(
                public_key.public_bytes(
                    encoding=serialization.Encoding.DER,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            ).decode("ascii"),
        },
        "execution_payload_hashes": payload_hashes,
        "content_hashes": content_hashes,
        "canonical_documents": canonical_texts,
        "signing_inputs": signing_bytes,
        "event_signatures": signatures,
        "placeholder_values": values,
    }

    return {
        GENERATED_PATHS["hashes"]: render_json(hashes),
        GENERATED_PATHS["enums"]: render_json(enum_expectations()),
    }


def main(argv: list[str]) -> int:
    check_only = "--check" in argv[1:]
    unexpected = [arg for arg in argv[1:] if arg != "--check"]
    if unexpected:
        print(f"unknown argument(s): {' '.join(unexpected)}", file=sys.stderr)
        return 64

    documents = build()

    if check_only:
        stale = []
        for relative, text in documents.items():
            path = REPO_ROOT / relative
            if not path.exists():
                stale.append(f"{relative}: missing")
            elif path.read_text(encoding="utf-8") != text:
                stale.append(f"{relative}: differs from the freshly computed values")
        if stale:
            print("frozen expectations are stale:", file=sys.stderr)
            for line in stale:
                print(f"  - {line}", file=sys.stderr)
            print(
                "Re-run without --check only if the corpus changed on purpose; otherwise the "
                "canonicalisation regressed.",
                file=sys.stderr,
            )
            return 1
        print("frozen expectations match the corpus")
        return 0

    for relative, text in documents.items():
        path = REPO_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {relative} ({len(text)} bytes)")
    print("frozen expectations regenerated and every fixture validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))