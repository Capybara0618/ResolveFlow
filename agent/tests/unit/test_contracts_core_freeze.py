"""C00.2c-3b: the frozen core expectations.

A digest Python computes at load time proves nothing to Java, so the core corpus
expectations are frozen into ``contracts/core/fixtures/expected.json`` and both languages
reproduce them from the same fixture. These tests are the Python half: they recompute
every frozen value from the corpus, so the file cannot quietly go stale, and they check
the two DER encodings Java needs (a PKCS#8 private key and an SPKI public key) decode back
to the same key the corpus declares.

The file being on disk *and* matching a fresh build is what ``scripts/contracts_core_freeze.py
--check`` asserts in the contracts suite; doing it here as well means a developer running
only pytest still sees the regression.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from resolveflow.contracts._schemaio import REPO_ROOT, load_json
from resolveflow.contracts.canonical import payload_hash
from resolveflow.contracts.core_corpus import (
    CORE_EXPECTED_PATH,
    computed_placeholder_values,
    core_signing_keys,
    load_core_corpus,
    resolve_core_instance,
    strip_annotations,
)
from resolveflow.contracts.events import (
    CORE_SIGNABLE_KEYS,
    core_signing_input_bytes,
    verify_core_envelope,
)


@pytest.fixture()
def frozen() -> dict[str, Any]:
    return load_json(CORE_EXPECTED_PATH)


def core_freeze_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "contracts_core_freeze", REPO_ROOT / "scripts" / "contracts_core_freeze.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_frozen_file_is_what_a_fresh_build_produces(frozen: dict[str, Any]) -> None:
    """The ``--check`` guarantee, duplicated here so pytest alone catches a stale file."""
    module = core_freeze_module()
    document, _ = module.core_document()
    fresh = module.render(document)
    with open(REPO_ROOT / CORE_EXPECTED_PATH, encoding="utf-8", newline="") as handle:
        assert handle.read() == fresh


def test_every_frozen_placeholder_is_recomputed_identically(frozen: dict[str, Any]) -> None:
    assert frozen["placeholder_values"] == computed_placeholder_values(load_core_corpus())


def test_frozen_payload_hashes_match_the_hasher(frozen: dict[str, Any]) -> None:
    corpus = load_core_corpus()
    hashed = {
        name: payload_hash(strip_annotations(component))
        for name, component in corpus["components"].items()
        if not name.startswith("_") and "action" in component
    }
    assert hashed == frozen["payload_hashes"]
    assert set(hashed) == set(frozen["canonical_payloads"])


def test_frozen_signatures_verify_against_the_core_signing_input(frozen: dict[str, Any]) -> None:
    corpus = load_core_corpus()
    _, public_key = core_signing_keys(corpus)
    values = computed_placeholder_values(corpus)
    for name, signature in frozen["event_signatures"].items():
        envelope = resolve_core_instance(corpus, "message_envelopes", name, values)
        verify_core_envelope(envelope, signature, public_key)


def test_frozen_signing_inputs_are_the_bytes_the_signature_covers(frozen: dict[str, Any]) -> None:
    corpus = load_core_corpus()
    values = computed_placeholder_values(corpus)
    for name, recorded in frozen["signing_inputs"].items():
        envelope = resolve_core_instance(corpus, "message_envelopes", name, values)
        unsigned = {key: value for key, value in envelope.items() if key != "signature"}
        assert core_signing_input_bytes(unsigned).decode("utf-8") == recorded
    assert set(frozen["signing_inputs"]) == set(frozen["event_signatures"])


def test_the_frozen_signed_member_list_is_the_core_one(frozen: dict[str, Any]) -> None:
    """Signing the compat member list would leave ``topic`` unsigned (docs/core-contracts.md:19)."""
    assert frozen["signing_keys"]["signed_members"] == list(CORE_SIGNABLE_KEYS)
    assert "topic" in frozen["signing_keys"]["signed_members"]
    assert "aggregate_id" not in frozen["signing_keys"]["signed_members"]


def test_the_frozen_der_keys_decode_to_the_declared_key(frozen: dict[str, Any]) -> None:
    """Java loads these two DER blobs with ``EventSignature``; both must be the same key."""
    import base64

    corpus = load_core_corpus()
    declared = corpus["signing_keys"][frozen["signing_keys"]["key_id"]]["public_key_hex"]
    private_key = serialization.load_der_private_key(
        base64.b64decode(frozen["signing_keys"]["private_key_pkcs8_base64"]), password=None
    )
    assert private_key.private_bytes_raw().hex() == frozen["signing_keys"]["private_seed_hex"]
    assert private_key.public_key().public_bytes_raw().hex() == declared
    spki = serialization.load_der_public_key(base64.b64decode(frozen["signing_keys"]["public_key_spki_base64"]))
    assert isinstance(spki, Ed25519PublicKey)
    assert spki.public_bytes_raw().hex() == declared


def test_a_frozen_signature_does_not_verify_under_the_compat_rules(frozen: dict[str, Any]) -> None:
    """Why core needed its own signer: the compat input injects aggregate_* and omits topic."""
    from resolveflow.contracts.events import signing_input_bytes

    corpus = load_core_corpus()
    values = computed_placeholder_values(corpus)
    envelope = resolve_core_instance(corpus, "message_envelopes", "refund_succeeded", values)
    unsigned = {key: value for key, value in envelope.items() if key != "signature"}
    assert core_signing_input_bytes(unsigned) != signing_input_bytes(unsigned)
    assert b'"topic"' in core_signing_input_bytes(unsigned)
    assert b'"aggregate_version":null' in signing_input_bytes(unsigned)