"""C00.2c-2a: the core positive corpus, its placeholders and its signing rules.

The corpus is only evidence if three things hold, and each has its own test here: every
fixture satisfies the schema its section pins, every placeholder is both used and
fillable, and the signatures cover the fields the authority says they cover. The last one
is the interesting one - a signature test that only re-signs the same bytes proves
nothing about *which* bytes, so these tests mutate members and assert the signature stops
verifying, and they compare the core signing input against the compat rule that cannot be
reused for it.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import ValidationError

from resolveflow.contracts import canonical
from resolveflow.contracts._schemaio import CORE_SCHEMA_FILES, load_json, schema_registry, validator_bundle
from resolveflow.contracts.core_corpus import (
    CORE_COMMAND,
    CORE_SCHEMA_SECTIONS,
    SIGNING_KEY_ID,
    SUPPORT_SECTIONS,
    CoreCorpusError,
    computed_placeholder_values,
    core_placeholder_tokens,
    core_signing_keys,
    load_core_corpus,
    resolve_core_instance,
    validate_core_corpus,
)
from resolveflow.contracts.events import (
    CORE_ENVELOPE_KEYS,
    CORE_SIGNABLE_KEYS,
    EventSignatureError,
    core_signing_input_bytes,
    sign_envelope,
    signing_input_bytes,
    verify_core_envelope,
)


@pytest.fixture()
def corpus() -> dict[str, Any]:
    return load_core_corpus()


def corpus_fixtures(section: str) -> list[str]:
    return [name for name in load_core_corpus()[section] if not name.startswith("_")]


# ------------------------------------------------------------------ shape of the file


def test_the_corpus_has_exactly_the_sections_it_declares(corpus: dict[str, Any]) -> None:
    declared = set(CORE_SCHEMA_SECTIONS) | set(SUPPORT_SECTIONS)
    present = {key for key in corpus if not key.startswith("_")}
    assert present == declared, "a section that no validator pins would be validated by nobody"


def test_every_core_schema_has_a_positive_section(corpus: dict[str, Any]) -> None:
    _, documents = schema_registry(CORE_SCHEMA_FILES)
    core_ids = {document["$id"] for document in documents.values()}
    assert set(CORE_SCHEMA_SECTIONS.values()) == core_ids, "a core schema without fixtures has no evidence"


def test_every_section_has_at_least_one_fixture(corpus: dict[str, Any]) -> None:
    for section in CORE_SCHEMA_SECTIONS:
        entries = [name for name in corpus[section] if not name.startswith("_")]
        assert entries, f"section {section} is empty"


def test_the_corpus_covers_all_four_core_event_types(corpus: dict[str, Any]) -> None:
    event_types = {
        entry["event_type"] for name, entry in corpus["message_envelopes"].items() if not name.startswith("_")
    }
    assert event_types == {"RefundRequested", "RefundSucceeded", "RefundFailed", "RefundUnknown"}


def test_the_corpus_covers_an_actionable_and_a_question_proposal(corpus: dict[str, Any]) -> None:
    actions = {entry["recommended_action"] for entry in (resolve_proposals(corpus))}
    assert {"REFUND", "REQUEST_INFO"} <= actions


def resolve_proposals(corpus: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        resolve_core_instance(corpus, "agent_proposals", name)
        for name in corpus["agent_proposals"]
        if not name.startswith("_")
    ]


# ------------------------------------------------------------------------ validation


def test_every_positive_fixture_satisfies_its_schema() -> None:
    checked = validate_core_corpus()
    assert len(checked) >= 7, checked
    assert any(line.startswith("execution_commands.") for line in checked)
    assert any(line.startswith("agent_proposals.") for line in checked)
    envelope_count = len(corpus_fixtures("message_envelopes"))
    assert sum(1 for line in checked if "signature verified" in line) == envelope_count


def test_the_corpus_does_not_need_a_frozen_digest_file(corpus: dict[str, Any]) -> None:
    """Recomputing twice must give the same bytes; that is why nothing is frozen."""
    first = computed_placeholder_values(corpus)
    second = computed_placeholder_values(corpus)
    assert first == second
    assert all(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in first.values()) is False


def test_placeholders_are_exactly_what_the_corpus_uses(corpus: dict[str, Any]) -> None:
    used = core_placeholder_tokens(corpus)
    filled = set(computed_placeholder_values(corpus))
    assert used == filled, "a token used but not fillable, or filled but unused, is a fixture that lies"


def test_no_fixture_still_contains_a_literal_token(corpus: dict[str, Any]) -> None:
    for section in CORE_SCHEMA_SECTIONS:
        for name in corpus[section]:
            if name.startswith("_"):
                continue
            instance = resolve_core_instance(corpus, section, name)
            assert "PLACEHOLDER_" not in str(instance), f"{section}.{name} kept an unresolved token"


def test_the_fixture_public_key_must_match_its_seed(corpus: dict[str, Any]) -> None:
    broken = copy.deepcopy(corpus)
    broken["signing_keys"][SIGNING_KEY_ID]["public_key_hex"] = "00" * 32
    with pytest.raises(CoreCorpusError, match="seed derives"):
        core_signing_keys(broken)


def test_an_unknown_section_or_fixture_is_reported(corpus: dict[str, Any]) -> None:
    with pytest.raises(CoreCorpusError, match="unknown core corpus section"):
        resolve_core_instance(corpus, "no_such_section", "x")
    with pytest.raises(CoreCorpusError, match="no fixture"):
        resolve_core_instance(corpus, "agent_proposals", "no_such_fixture")


# ---------------------------------------------------------- the payload hash's scope


def test_payload_hash_covers_exactly_the_twelve_refund_fields(corpus: dict[str, Any]) -> None:
    command = resolve_core_instance(corpus, "execution_commands", "lost_parcel_full_line")
    assert set(canonical.REFUND_FIELDS) <= set(command)
    assert set(command) == set(canonical.REFUND_FIELDS) | {"payload_hash"}
    assert command["payload_hash"] == canonical.payload_hash(command)


@pytest.mark.parametrize("field", sorted(set(canonical.REFUND_FIELDS) - {"action"}))
def test_changing_any_hashed_field_changes_the_digest(corpus: dict[str, Any], field: str) -> None:
    command = resolve_core_instance(corpus, "execution_commands", "lost_parcel_full_line")
    changed = copy.deepcopy(command)
    value = changed[field]
    changed[field] = value + 1 if isinstance(value, int) else f"{value}-changed"
    assert canonical.payload_hash(changed) != command["payload_hash"]


def test_the_digest_does_not_cover_itself(corpus: dict[str, Any]) -> None:
    command = resolve_core_instance(corpus, "execution_commands", "lost_parcel_full_line")
    forged = {**command, "payload_hash": "0" * 64}
    assert canonical.payload_hash(forged) == command["payload_hash"]


def test_a_float_amount_cannot_be_hashed_at_all(corpus: dict[str, Any]) -> None:
    command = resolve_core_instance(corpus, "execution_commands", "lost_parcel_full_line")
    with pytest.raises(canonical.CanonicalizationError, match="floating point"):
        canonical.payload_hash({**command, "amount_minor": 25.99})


def test_the_action_selects_the_hashed_field_set(corpus: dict[str, Any]) -> None:
    """`action` is not a value the digest covers: it chooses which field set is covered.

    ``canonical.payload_hash`` still has the compat reship branch (a compat asset,
    docs/core-scope.md:34), so asking for a reship digest demands ``address_hash`` rather
    than silently hashing the refund fields under a different action name. The core
    *schema* is what refuses a reship command, and it refuses it twice over: the action
    is a const and a v1 reship field would be an unknown property.
    """
    command = resolve_core_instance(corpus, "execution_commands", "lost_parcel_full_line")
    with pytest.raises(canonical.CanonicalizationError, match="address_hash"):
        canonical.payload_hash({**command, "action": "RESHIP"})
    validator = validator_bundle(CORE_COMMAND, CORE_SCHEMA_FILES)
    assert not validator.accepts({**command, "action": "RESHIP"})
    assert not validator.accepts({**command, "address_hash": "a" * 64})


# ------------------------------------------------------------- the signature's scope


def test_the_core_signing_tuple_matches_the_core_schema(corpus: dict[str, Any]) -> None:
    """Signed members must be exactly the schema's members minus the signature."""
    _, documents = schema_registry(CORE_SCHEMA_FILES)
    envelope = next(document for document in documents.values() if document["title"] == "CoreEventEnvelopeV2")
    declared = set(envelope["properties"])
    assert set(CORE_ENVELOPE_KEYS) == declared
    assert set(CORE_SIGNABLE_KEYS) == declared - {"signature"}


def test_the_compat_signer_cannot_be_reused_for_a_core_envelope(corpus: dict[str, Any]) -> None:
    """The regression this tuple exists for.

    The compat list still contains aggregate_id/aggregate_version (which core dropped)
    and lacks topic (which core added). Signing a core envelope with the compat rule
    would therefore add two nulls and omit topic: both languages would be
    self-consistent and still disagree, which is the failure mode the whole signing
    design exists to prevent.
    """
    envelope = resolve_core_instance(corpus, "message_envelopes", "refund_requested")
    compat_bytes = signing_input_bytes(envelope)
    core_bytes = core_signing_input_bytes(envelope)
    assert compat_bytes != core_bytes
    assert b'"aggregate_id":null' in compat_bytes
    assert b'"aggregate_version":null' in compat_bytes
    assert b'"topic"' in core_bytes and b'"topic"' not in compat_bytes


def test_an_absent_optional_member_signs_the_same_as_an_explicit_null(corpus: dict[str, Any]) -> None:
    """Otherwise "omit it" and "send null" would be two different signatures for one fact."""
    envelope = resolve_core_instance(corpus, "message_envelopes", "refund_requested_without_traceparent")
    explicit = {**envelope, "traceparent": None, "causation_id": None}
    assert core_signing_input_bytes(explicit) == core_signing_input_bytes(envelope)


def test_the_fixture_signature_is_deterministic(corpus: dict[str, Any]) -> None:
    private_key, _ = core_signing_keys(corpus)
    envelope = resolve_core_instance(corpus, "message_envelopes", "refund_succeeded")
    assert sign_envelope(envelope, private_key) == sign_envelope(envelope, private_key)


@pytest.mark.parametrize(
    "field",
    ["event_id", "event_type", "schema_version", "merchant_id", "occurred_at", "producer", "topic", "signing_key_id"],
)
def test_the_signature_covers_every_declared_member(corpus: dict[str, Any], field: str) -> None:
    _, public_key = core_signing_keys(corpus)
    envelope = resolve_core_instance(corpus, "message_envelopes", "refund_succeeded")
    tampered = copy.deepcopy(envelope)
    value = tampered[field]
    tampered[field] = value + 1 if isinstance(value, int) else f"{value}-tampered"
    with pytest.raises(EventSignatureError):
        verify_core_envelope(tampered, envelope["signature"], public_key)


def test_the_signature_covers_an_optional_member_when_present(corpus: dict[str, Any]) -> None:
    _, public_key = core_signing_keys(corpus)
    envelope = resolve_core_instance(corpus, "message_envelopes", "refund_requested")
    assert envelope["traceparent"].startswith("00-")
    tampered = {**envelope, "traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01"}
    with pytest.raises(EventSignatureError):
        verify_core_envelope(tampered, envelope["signature"], public_key)


def test_the_signature_covers_the_payload(corpus: dict[str, Any]) -> None:
    """A result that reports a different amount must not keep its signature."""
    _, public_key = core_signing_keys(corpus)
    envelope = resolve_core_instance(corpus, "message_envelopes", "refund_succeeded")
    tampered = copy.deepcopy(envelope)
    tampered["payload"]["amount_minor"] = 1
    with pytest.raises(EventSignatureError):
        verify_core_envelope(tampered, envelope["signature"], public_key)


def test_a_signature_from_another_key_does_not_verify(corpus: dict[str, Any]) -> None:
    _, public_key = core_signing_keys(corpus)
    envelope = resolve_core_instance(corpus, "message_envelopes", "refund_failed")
    other_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    assert other_key.public_key().public_bytes_raw() != public_key.public_bytes_raw()
    with pytest.raises(EventSignatureError):
        verify_core_envelope(envelope, sign_envelope(envelope, other_key), public_key)


def test_the_command_envelope_payload_is_the_command_itself(corpus: dict[str, Any]) -> None:
    envelope = resolve_core_instance(corpus, "message_envelopes", "refund_requested")
    command = resolve_core_instance(corpus, "execution_commands", "lost_parcel_full_line")
    assert envelope["payload"] == command
    assert envelope["producer"] == "case-service"
    assert envelope["topic"] == "rf.case.core.v2"


def test_a_result_envelope_carries_no_aggregate_members(corpus: dict[str, Any]) -> None:
    """The version lives in the payload exactly once (docs/domain-model.md:3)."""
    envelope = resolve_core_instance(corpus, "message_envelopes", "refund_unknown")
    assert "aggregate_id" not in envelope and "aggregate_version" not in envelope
    assert envelope["payload"]["aggregate_version"] == 9


def test_the_corpus_file_is_valid_json_with_the_declared_top_level_keys() -> None:
    raw = load_json("contracts/core/fixtures/valid.json")
    present = {key for key in raw if not key.startswith("_")}
    assert present == set(CORE_SCHEMA_SECTIONS) | set(SUPPORT_SECTIONS)


def test_validation_reports_a_broken_fixture_instead_of_skipping_it(corpus: dict[str, Any]) -> None:
    broken = copy.deepcopy(corpus)
    broken["execution_commands"]["lost_parcel_full_line"] = {
        "_ref": "components.refundCommandLostParcel",
    }
    broken["components"]["refundCommandLostParcel"]["amount_minor"] = 0
    with pytest.raises((CoreCorpusError, ValidationError)):
        validate_core_corpus(broken)