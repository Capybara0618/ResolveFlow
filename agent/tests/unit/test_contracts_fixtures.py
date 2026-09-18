"""Prove the T02 corpus means what it claims, and that Python reproduces the frozen values.

Two things are checked here:

1. Every fixture is what its name says. Positive fixtures must satisfy the schema or
   OpenAPI component the corpus maps them to; negative fixtures must be *refused* by the
   schema they name (docs/contracts.md:131 requires schema and documents to agree, and a
   rejection that starts passing is a protocol regression).
2. Python recomputes the frozen digests, signatures and enum mapping from the corpus.
   Java recomputes the same values from the same files in
   ``com.resolveflow.shared.contract.ContractCorpusAgreementTest``; the two suites
   together are the cross-language evidence docs/contracts.md:17 asks for.

Re-freezing is never the answer to a failure here: either the corpus changed on purpose
(which needs a deliberate regeneration) or canonicalisation regressed.
"""

from __future__ import annotations

import base64
import re
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_der_private_key, load_der_public_key

from resolveflow.contracts._schemaio import load_json
from resolveflow.contracts.canonical import payload_hash
from resolveflow.contracts.corpus import (
    EVENT_PAYLOAD_DEFS,
    OPENAPI_COMPONENTS,
    OPENAPI_GROUPS,
    REJECT_SECTIONS,
    RESULT_EVENT_SCHEMA,
    SCHEMA_SECTIONS,
    enum_groups,
    recompute_frozen_values,
    require_placeholder_coverage,
    resolve_envelope,
    sign_corpus_envelopes,
    strip_annotations,
    validate_invalid_payloads,
    validate_negative_corpus,
    validate_valid_corpus,
)
from resolveflow.contracts.events import signing_input_bytes, verify_envelope
from resolveflow.contracts.fixtures import GENERATED_PATHS, load_corpus

EXPECTED_HASHES: dict[str, Any] = load_json(GENERATED_PATHS["hashes"])
EXPECTED_ENUMS: dict[str, Any] = load_json(GENERATED_PATHS["enums"])
VALUES: dict[str, str] = EXPECTED_HASHES["placeholder_values"]
CANONICAL = load_corpus("canonical")
VALID = load_corpus("valid")
REJECT = load_corpus("reject")

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
DIGEST_GROUPS = ("execution_payload_hashes", "content_hashes")


def frozen_public_key() -> Any:
    return load_der_public_key(base64.b64decode(EXPECTED_HASHES["signing_keys"]["public_key_spki_base64"]))


def frozen_private_key() -> Ed25519PrivateKey:
    return load_der_private_key(
        base64.b64decode(EXPECTED_HASHES["signing_keys"]["private_key_pkcs8_base64"]), password=None
    )


class TestCorpusIsCovered:
    """A fixture that no mapping validates would pass every other test in this file."""

    def test_every_positive_section_is_mapped_to_a_schema(self) -> None:
        sections = {key for key in VALID if not key.startswith("_")}
        mapped = set(SCHEMA_SECTIONS) | {"event_payload", "message_envelope"} | set(OPENAPI_GROUPS)
        assert sections == mapped

    def test_every_openapi_sample_names_a_component_that_exists(self) -> None:
        # The mapping's keys must match the corpus exactly, or a sample is unvalidated.
        assert set(OPENAPI_COMPONENTS) == {name for group in OPENAPI_GROUPS for name in VALID[group]}

    def test_every_result_payload_names_the_variant_it_is_validated_against(self) -> None:
        assert set(EVENT_PAYLOAD_DEFS) == set(VALID["event_payload"])

    def test_every_negative_section_names_a_schema(self) -> None:
        sections = {key for key in REJECT if not key.startswith("_")}
        assert sections == set(REJECT_SECTIONS)


class TestPositiveCorpus:
    def test_every_positive_fixture_satisfies_its_schema(self) -> None:
        lines = validate_valid_corpus(VALID, VALUES)
        expected = (
            sum(len(VALID[section]) for section in SCHEMA_SECTIONS)
            + len(VALID["event_payload"])
            + sum(len(VALID[group]) for group in OPENAPI_GROUPS)
        )
        # Equality, not ">= 1": a fixture that silently stopped being validated would
        # still pass a truthiness check.
        assert len(lines) == expected
        # And every mapped section is actually represented, so a section emptied of its
        # fixtures cannot shrink the expected count in step with the regression.
        for section in SCHEMA_SECTIONS:
            assert any(f"validated {section}." in line for line in lines), section
        for group in OPENAPI_GROUPS:
            assert any(f"validated {group}." in line for line in lines), group
        assert any("validated event_payload." in line for line in lines)


class TestNegativeCorpus:
    def test_every_negative_fixture_is_refused(self) -> None:
        lines = validate_negative_corpus(REJECT)
        expected = sum(len(entries) for section, entries in REJECT.items() if not section.startswith("_"))
        assert len(lines) == expected
        assert len(lines) >= 54

    def test_every_negative_fixture_says_why_it_exists(self) -> None:
        # validate_negative_corpus raises on a missing reason; asserted here too so the
        # requirement is visible in the suite rather than only inside the helper.
        for section, entries in REJECT.items():
            if section.startswith("_"):
                continue
            for name, entry in entries.items():
                assert entry.get("why"), f"{section}.{name} does not say why it must be refused"

    def test_result_payload_rejections_name_a_variant_of_the_result_event_schema(self) -> None:
        # A result payload is refused as the variant its event type selects, not as the
        # whole envelope, so each rejection has to name which variant it violates.
        variants = {"#/$defs/" + name for name in EVENT_PAYLOAD_DEFS.values()}
        for name, entry in REJECT["result_event_payload"].items():
            suffix = next((variant for variant in variants if entry["schema"].endswith(variant)), None)
            assert suffix is not None, name
            assert entry["schema"] == RESULT_EVENT_SCHEMA + suffix, name


class TestFrozenValues:
    def test_execution_payload_hashes_reproduce(self) -> None:
        payload_hashes, _, _ = recompute_frozen_values(CANONICAL)
        assert payload_hashes == EXPECTED_HASHES["execution_payload_hashes"]

    def test_content_hashes_reproduce(self) -> None:
        _, content_hashes, _ = recompute_frozen_values(CANONICAL)
        assert content_hashes == EXPECTED_HASHES["content_hashes"]

    def test_canonical_documents_reproduce_byte_for_byte(self) -> None:
        # The text matters, not only its digest: a difference in escaping shows up here as
        # a readable diff instead of as an unexplained hash mismatch.
        _, _, canonical_texts = recompute_frozen_values(CANONICAL)
        assert canonical_texts == EXPECTED_HASHES["canonical_documents"]

    def test_frozen_digests_are_sha256_hex(self) -> None:
        # Guards the guard: an empty or truncated digest would compare equal on both sides
        # and prove nothing.
        for group in DIGEST_GROUPS:
            assert EXPECTED_HASHES[group], group
            for name, digest in EXPECTED_HASHES[group].items():
                assert SHA256_HEX.match(digest), f"{group}.{name}"

    def test_annotations_do_not_change_a_digest(self) -> None:
        instance = CANONICAL["execution_payloads"]["refund-basic"]
        assert payload_hash(strip_annotations(instance)) == EXPECTED_HASHES["execution_payload_hashes"]["refund-basic"]
        edited = dict(instance, _comment="a different explanation entirely")
        assert payload_hash(strip_annotations(edited)) == payload_hash(strip_annotations(instance))

    def test_a_changed_field_changes_the_digest(self) -> None:
        # The cheapest proof that the frozen digest is a function of the payload rather
        # than of something incidental.
        instance = dict(CANONICAL["execution_payloads"]["refund-basic"])
        instance["amount_minor"] = instance["amount_minor"] + 1
        assert payload_hash(strip_annotations(instance)) != EXPECTED_HASHES["execution_payload_hashes"]["refund-basic"]

    def test_invalid_payloads_are_refused_by_the_hasher(self) -> None:
        lines = validate_invalid_payloads(CANONICAL)
        assert len(lines) == len(CANONICAL["invalid_payloads"]) >= 4

    def test_placeholder_table_resolves_every_reference(self) -> None:
        # Raises if a token is referenced but unfrozen, or frozen but unused.
        require_placeholder_coverage({"valid": VALID, "canonical": CANONICAL}, VALUES)
        assert VALUES

    def test_placeholder_values_are_digests_or_signatures(self) -> None:
        for token, value in VALUES.items():
            assert token.startswith("PLACEHOLDER_"), token
            if token.endswith("_SIGNATURE"):
                assert len(base64.b64decode(value, validate=True)) == 64, token
            else:
                assert SHA256_HEX.match(value), token

    @pytest.mark.parametrize("group", DIGEST_GROUPS)
    def test_frozen_groups_are_not_empty(self, group: str) -> None:
        assert EXPECTED_HASHES[group]


class TestEnvelopes:
    def test_signing_inputs_reproduce(self) -> None:
        for name in VALID["message_envelope"]:
            envelope = resolve_envelope(VALID, name, VALUES)
            assert signing_input_bytes(envelope).decode("utf-8") == EXPECTED_HASHES["signing_inputs"][name], name

    def test_every_envelope_in_the_corpus_has_a_frozen_signing_input(self) -> None:
        assert set(EXPECTED_HASHES["signing_inputs"]) == set(VALID["message_envelope"])

    def test_frozen_signatures_verify_under_the_frozen_public_key(self) -> None:
        public_key = frozen_public_key()
        assert EXPECTED_HASHES["event_signatures"], "no signature is frozen, so nothing is proven"
        for name, signature in EXPECTED_HASHES["event_signatures"].items():
            verify_envelope(resolve_envelope(VALID, name, VALUES), signature, public_key)

    def test_frozen_signatures_are_real_ed25519_signatures(self) -> None:
        for name, signature in EXPECTED_HASHES["event_signatures"].items():
            assert not signature.startswith("PLACEHOLDER_"), name
            assert len(base64.b64decode(signature, validate=True)) == 64, name

    def test_resigning_reproduces_the_frozen_signature(self) -> None:
        # Ed25519 is deterministic, so an equal signature proves the fixture was signed by
        # exactly the key the frozen file publishes, not merely by some valid key.
        values = dict(VALUES)
        signing_inputs, signatures = sign_corpus_envelopes(
            VALID, values, frozen_private_key(), EXPECTED_HASHES["signing_keys"]["key_id"]
        )
        assert signatures == EXPECTED_HASHES["event_signatures"]
        assert signing_inputs == EXPECTED_HASHES["signing_inputs"]

    def test_the_unsigned_result_event_has_an_input_but_no_signature(self) -> None:
        # docs/contracts.md:121: result events are published by commerce/fulfillment, so
        # they are not case-signed. Their signing input is still frozen, because that byte
        # sequence is what a producer must reproduce if signing is added later.
        unsigned = set(VALID["message_envelope"]) - set(EXPECTED_HASHES["event_signatures"])
        assert unsigned == {"refund_succeeded_from_commerce"}
        assert unsigned <= set(EXPECTED_HASHES["signing_inputs"])

    def test_signed_envelopes_name_the_frozen_key(self) -> None:
        for name in EXPECTED_HASHES["event_signatures"]:
            envelope = resolve_envelope(VALID, name, VALUES)
            assert envelope["signing_key_id"] == EXPECTED_HASHES["signing_keys"]["key_id"], name

    def test_frozen_signing_input_is_canonical_text_without_the_signature(self) -> None:
        for name, text in EXPECTED_HASHES["signing_inputs"].items():
            assert text.startswith("{") and text.endswith("}"), name
            assert '"signature"' not in text, name


class TestEnums:
    def test_frozen_enum_mapping_matches_python(self) -> None:
        # Java asserts the same file, so a member renamed on one side fails on both,
        # instead of producing an unroutable action at runtime.
        assert enum_groups() == EXPECTED_ENUMS["enums"]

    def test_every_enum_group_is_non_empty_and_unique(self) -> None:
        for group, members in EXPECTED_ENUMS["enums"].items():
            assert members, group
            assert len(set(members)) == len(members), group

    def test_state_enums_cover_the_documented_lifecycles(self) -> None:
        # docs/domain-model.md: the entitlement reservation and the target operation are
        # two different state machines, and an UNKNOWN result holds the reservation until
        # reconciliation - so both have to exist as wire values, with UNKNOWN on the
        # operation one.
        operation_states = set(EXPECTED_ENUMS["enums"]["operation_state"])
        assert {"RESERVED", "SUCCEEDED", "UNKNOWN", "RELEASING", "FAILED", "CANCELLED"} <= operation_states
        entitlement_states = set(EXPECTED_ENUMS["enums"]["entitlement_state"])
        assert {"FREE", "RESERVED", "IN_USE", "CONSUMED"} <= entitlement_states

    def test_error_code_enum_covers_the_documented_statuses(self) -> None:
        codes = set(EXPECTED_ENUMS["enums"]["error_code"])
        assert {
            "VALIDATION_FAILED",
            "UNAUTHENTICATED",
            "FORBIDDEN_SCOPE",
            "NOT_FOUND",
            "STATE_CONFLICT",
            "SEMANTIC_INVALID",
            "RATE_LIMITED",
            "SERVICE_UNAVAILABLE",
        } <= codes


def test_the_frozen_files_are_generated_not_hand_written() -> None:
    # Both frozen files carry their generator note; a hand-edited file loses it, and the
    # suite says so before anyone debugs a hash mismatch.
    assert any("contracts_freeze.py" in line for line in EXPECTED_HASHES["_comment"])
    assert any("contracts_freeze.py" in line for line in EXPECTED_ENUMS["_comment"])