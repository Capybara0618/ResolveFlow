"""Unit tests for RFC 8785 canonicalisation and the envelope signature rules.

These are the rules the frozen corpus cannot express as a list of values: key ordering,
escaping, and what must be refused rather than serialised. The cross-language half -
Java recomputing the same digests from the same fixtures - lives in
``tests/unit/test_contracts_fixtures.py`` and in Java's
``ContractCorpusAgreementTest``.

Authority: docs/contracts.md:17 (signing input and signature), docs/contracts.md:19
(2^53-1 bound), RFC 8785.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from resolveflow.contracts.canonical import (
    MAX_EXACT_INTEGER,
    CanonicalizationError,
    canonical_bytes,
    canonicalize,
    content_hash,
    fields_for_action,
    payload_hash,
)
from resolveflow.contracts.events import (
    ENVELOPE_KEYS,
    SIGNABLE_KEYS,
    EventSignatureError,
    sign_envelope,
    signing_input_bytes,
    verify_envelope,
)

PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"unit-test-seed").digest())
PUBLIC_KEY = PRIVATE_KEY.public_key()

SUPPLEMENTARY = "\U00010000"
REPLACEMENT = "\ufffd"
PRIVATE_USE = "\ue000"


def payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "operation_id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
        "case_id": "9c858901-8a57-4791-81fe-4c455b099bc9",
        "authorization_id": "7d444840-9dc0-11d1-b245-5ffdce74fad2",
        "input_revision": 12,
        "line_id": "7001",
        "merchant_id": "1",
        "action": "REFUND",
        "quantity": 1,
        "currency": "CNY",
        "amount_minor": 20000,
        "policy_version": "policy-2026.09-refund-v3",
        "target_service": "commerce-service",
    }
    base.update(overrides)
    return base


def envelope(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event_id": "018f0a3c-4b1e-7a2d-9f30-1c2b3a4d5e6f",
        "event_type": "RefundRequested",
        "schema_version": 1,
        "aggregate_id": "9c858901-8a57-4791-81fe-4c455b099bc9",
        "aggregate_version": 7,
        "merchant_id": "1",
        "occurred_at": "2026-09-18T05:00:00Z",
        "producer": "case-service",
        "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        "causation_id": None,
        "payload": payload(),
        "signing_key_id": "rf-case-events-2026-09",
    }
    base.update(overrides)
    return base


class TestKeyOrdering:
    def test_keys_sort_by_utf16_code_unit_not_code_point(self) -> None:
        # U+10000 is the surrogate pair D800 DC00, so UTF-16 code-unit order puts it
        # before both BMP keys; a code-point sort would put it last. This is the one case
        # where the two rules disagree, so it is asserted directly.
        text = json.dumps(
            {SUPPLEMENTARY: "supplementary", REPLACEMENT: "replacement", PRIVATE_USE: "private-use"}
        )
        canonical = canonicalize(json.loads(text))

        assert canonical == (
            '{"' + SUPPLEMENTARY + '":"supplementary","' + PRIVATE_USE + '":"private-use","' + REPLACEMENT
            + '":"replacement"}'
        )
        assert canonical.index(SUPPLEMENTARY) < canonical.index(PRIVATE_USE) < canonical.index(REPLACEMENT)

    def test_sorts_by_code_unit_not_locale_or_case(self) -> None:
        assert canonicalize({"b": 1, "A": 2, "a": 3}) == '{"A":2,"a":3,"b":1}'

    def test_keeps_array_order_because_it_is_data(self) -> None:
        assert canonicalize([3, 1, 2]) == "[3,1,2]"

    def test_null_and_booleans_keep_their_json_form(self) -> None:
        assert canonicalize({"n": None, "t": True, "f": False}) == '{"f":false,"n":null,"t":true}'


class TestEscaping:
    def test_escapes_only_what_json_requires(self) -> None:
        value = {"t": 'tab:\t newline:\n quote:" backslash:\\'}
        assert canonicalize(value) == '{"t":"tab:\\t newline:\\n quote:\\" backslash:\\\\"}'

    def test_control_characters_use_a_lowercase_four_digit_escape(self) -> None:
        assert canonicalize({"c": "unit-sep:\x1f"}) == '{"c":"unit-sep:\\u001f"}'

    def test_non_ascii_stays_raw_because_the_hash_is_over_bytes(self) -> None:
        # Escaping the CJK text below parses to the same string but produces different
        # bytes, and the digest is over bytes.
        cjk = "\u5f20\u4e09"
        assert canonicalize({"n": cjk}) == '{"n":"' + cjk + '"}'
        assert canonical_bytes({"n": cjk}) == ('{"n":"' + cjk + '"}').encode()


class TestNumberRules:
    def test_integers_are_emitted_without_a_decimal_point(self) -> None:
        assert canonicalize({"amount_minor": 20000, "zero": 0}) == '{"amount_minor":20000,"zero":0}'

    def test_float_is_refused_rather_than_rounded(self) -> None:
        # Money is integer minor units; 200.5 must never become 200 or 201.
        with pytest.raises(CanonicalizationError, match="floating point"):
            canonicalize({"amount_minor": 200.5})

    def test_the_largest_exact_integer_is_accepted(self) -> None:
        assert canonicalize({"revision": MAX_EXACT_INTEGER}) == '{"revision":' + str(MAX_EXACT_INTEGER) + "}"

    def test_an_integer_beyond_the_exact_range_is_refused(self) -> None:
        # docs/contracts.md:19. Java refuses this too; if only one side did, the two would
        # freeze different digests for the same fixture.
        with pytest.raises(CanonicalizationError, match="2\\^53-1"):
            canonicalize({"revision": MAX_EXACT_INTEGER + 1})

    def test_unsupported_types_are_refused(self) -> None:
        with pytest.raises(CanonicalizationError, match="unsupported type"):
            canonicalize({"when": object()})

    def test_nested_structures_are_canonicalised_recursively(self) -> None:
        assert canonicalize({"z": [{"b": 1, "a": 2}]}) == '{"z":[{"a":2,"b":1}]}'


class TestPayloadHash:
    def test_hash_is_sha256_over_the_canonical_field_subset(self) -> None:
        instance = payload()
        expected = hashlib.sha256(canonical_bytes({name: instance[name] for name in fields_for_action("REFUND")}))
        assert payload_hash(instance) == expected.hexdigest()

    def test_hash_ignores_fields_outside_the_documented_set(self) -> None:
        # payload_hash and entitlement_id are added by later steps; the digest computed
        # before the reservation must still match afterwards.
        assert payload_hash(payload(payload_hash="x" * 64, entitlement_id="e-1")) == payload_hash(payload())

    def test_reship_and_refund_hash_different_field_sets(self) -> None:
        reship = payload(action="RESHIP", address_hash="a" * 64, replacement_sku="SKU-2")
        assert payload_hash(reship) != payload_hash(payload())
        assert "amount_minor" not in fields_for_action("RESHIP")
        assert "amount_minor" in fields_for_action("REFUND")
        assert "address_hash" in fields_for_action("RESHIP")

    def test_missing_field_is_refused(self) -> None:
        incomplete = payload()
        del incomplete["line_id"]
        with pytest.raises(CanonicalizationError, match="missing field"):
            payload_hash(incomplete)

    def test_unknown_action_is_refused(self) -> None:
        with pytest.raises(CanonicalizationError, match="unknown action"):
            payload_hash(payload(action="PARTIAL_REFUND"))

    def test_content_hash_covers_any_document(self) -> None:
        assert content_hash({"b": 1, "a": 2}) == hashlib.sha256(b'{"a":2,"b":1}').hexdigest()


class TestSigningInput:
    def test_signature_is_excluded_from_its_own_input(self) -> None:
        signed = envelope(signature="not-checked")
        assert "signature" not in SIGNABLE_KEYS
        assert signing_input_bytes(signed) == signing_input_bytes(envelope())

    def test_signing_key_id_is_covered(self) -> None:
        # The key id has to be signed, or a signature could be replayed under another
        # key's name.
        assert "signing_key_id" in SIGNABLE_KEYS
        assert signing_input_bytes(envelope(signing_key_id="other-key")) != signing_input_bytes(envelope())

    def test_absent_optional_member_normalises_to_null(self) -> None:
        # Producer A omits traceparent and producer B sends null; the same event must
        # produce the same signing bytes or the signature is unmatchable.
        without = envelope()
        del without["traceparent"]
        assert signing_input_bytes(without) == signing_input_bytes(envelope(traceparent=None))

    def test_envelope_keys_match_the_schema_member_list(self) -> None:
        # additionalProperties:false makes ENVELOPE_KEYS exhaustive; a member added to the
        # schema but not here would drift the signing bytes silently.
        assert set(ENVELOPE_KEYS) == set(envelope()) | {"signature"}

    def test_non_object_payload_is_refused(self) -> None:
        with pytest.raises(EventSignatureError, match="must be a JSON object"):
            signing_input_bytes(envelope(payload="not-an-object"))


class TestEnvelopeSignature:
    def test_signature_round_trips(self) -> None:
        signature = sign_envelope(envelope(), PRIVATE_KEY)
        verify_envelope(envelope(), signature, PUBLIC_KEY)

    def test_signature_is_base64_of_a_64_byte_ed25519_signature(self) -> None:
        signature = sign_envelope(envelope(), PRIVATE_KEY)
        assert len(base64.b64decode(signature, validate=True)) == 64

    def test_tampered_payload_fails_verification(self) -> None:
        signature = sign_envelope(envelope(), PRIVATE_KEY)
        tampered = envelope()
        tampered["payload"] = payload(amount_minor=999999)
        with pytest.raises(EventSignatureError, match="does not cover"):
            verify_envelope(tampered, signature, PUBLIC_KEY)

    def test_tampered_metadata_fails_verification(self) -> None:
        signature = sign_envelope(envelope(), PRIVATE_KEY)
        with pytest.raises(EventSignatureError, match="does not cover"):
            verify_envelope(envelope(aggregate_version=8), signature, PUBLIC_KEY)

    def test_signature_from_another_key_is_rejected(self) -> None:
        other = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"another-seed").digest())
        with pytest.raises(EventSignatureError, match="does not cover"):
            verify_envelope(envelope(), sign_envelope(envelope(), other), PUBLIC_KEY)

    def test_malformed_signature_is_refused_before_verifying(self) -> None:
        with pytest.raises(EventSignatureError, match="not valid base64"):
            verify_envelope(envelope(), "not base64!!", PUBLIC_KEY)

    def test_signature_of_the_wrong_length_is_refused(self) -> None:
        short = base64.b64encode(b"too short").decode()
        with pytest.raises(EventSignatureError, match="must be 64 bytes"):
            verify_envelope(envelope(), short, PUBLIC_KEY)