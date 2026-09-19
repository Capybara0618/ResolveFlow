"""C00.2c-3a: the Python core DTOs agree with the schemas and with the corpus.

A DTO is a second description of the same wire object, so it can disagree with the schema
in two directions: it can accept what the schema refuses (a hole), or refuse what the
schema accepts (a wall). The corpus is the cheapest way to check both, because it already
contains 7 positive and 51 negative instances - so these tests replay the whole corpus
through the models rather than inventing a second set of examples that would drift from
the first.

``canonical_payloads`` negatives are excluded on purpose: they are refused by the hasher,
not by a shape, and ``amount_minor: 25.99`` is rejected by the DTO's integer type rather
than by a rule the schema states.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from resolveflow.contracts._schemaio import CORE_SCHEMA_FILES, load_json, schema_registry
from resolveflow.contracts.core_corpus import (
    CORE_REJECT_TARGETS,
    load_core_corpus,
    load_core_reject_corpus,
    resolve_core_instance,
    resolve_core_negative_instance,
)
from resolveflow.contracts.core_models import (
    CORE_DTO_NAMES,
    CoreAgentProposal,
    CoreEnvelope,
    CoreEvidenceRef,
    CorePolicyRef,
    CoreRefundCommand,
    CoreRefundResult,
)

#: Corpus section -> the model that must accept its positive fixtures.
MODEL_OF_SECTION: dict[str, type[Any]] = {
    "execution_commands": CoreRefundCommand,
    "message_envelopes": CoreEnvelope,
    "agent_proposals": CoreAgentProposal,
}

#: Negative-corpus section names are plural by document, positive ones by object, so the
#: two spellings are mapped explicitly rather than assumed to be equal.
REJECT_SECTION_OF: dict[str, str] = {
    "execution_commands": "execution_commands",
    "event_envelopes": "message_envelopes",
    "agent_proposals": "agent_proposals",
}

#: The v1 wire object each core DTO must not be confusable with.
V1_COUNTERPARTS = {
    "CoreRefundCommand": "ExecutionCommand",
    "CoreAgentProposal": "AgentProposal",
}


@pytest.fixture()
def corpus() -> dict[str, Any]:
    return load_core_corpus()


def schema_of(model: type[Any]) -> dict[str, Any]:
    """The core schema document whose title matches a model's wire object."""
    titles = {
        CoreRefundCommand: "CoreRefundCommandV2",
        CoreEnvelope: "CoreEventEnvelopeV2",
        CoreAgentProposal: "AgentProposalV2",
    }
    _, documents = schema_registry(CORE_SCHEMA_FILES)
    wanted = titles[model]
    return next(document for document in documents.values() if document["title"] == wanted)


# ------------------------------------------------------------------ model vs schema


@pytest.mark.parametrize("model", sorted(MODEL_OF_SECTION.values(), key=lambda item: item.__name__))
def test_dto_fields_match_the_schema_properties(model: type[Any]) -> None:
    assert set(model.model_fields) == set(schema_of(model)["properties"])


@pytest.mark.parametrize("model", sorted(MODEL_OF_SECTION.values(), key=lambda item: item.__name__))
def test_dto_required_fields_match_the_schema(model: type[Any]) -> None:
    required = {name for name, field in model.model_fields.items() if field.is_required()}
    assert required == set(schema_of(model)["required"])


def test_nested_ref_models_match_their_schema_fragments() -> None:
    schema = load_json("contracts/core/agent-proposal.schema.json")
    evidence = schema["properties"]["evidence_refs"]["items"]
    assert set(CoreEvidenceRef.model_fields) == set(evidence["properties"])
    assert set(evidence["required"]) == {
        name for name, field in CoreEvidenceRef.model_fields.items() if field.is_required()
    }
    policy = schema["properties"]["policy_refs"]["items"]
    assert set(CorePolicyRef.model_fields) == set(policy["properties"])
    assert set(policy["required"]) == {
        name for name, field in CorePolicyRef.model_fields.items() if field.is_required()
    }


def test_dtos_are_explicitly_distinct_from_the_v1_types() -> None:
    """docs/core-contracts.md:71 requires the new DTOs to be distinguishable from the old."""
    from resolveflow.contracts import models as v1

    assert len(CORE_DTO_NAMES) == 6
    for core_name, v1_name in V1_COUNTERPARTS.items():
        core_type = globals()[core_name]
        v1_type = getattr(v1, v1_name)
        assert core_type is not v1_type
        assert not issubclass(core_type, v1_type)


def test_a_v1_only_field_is_not_representable_in_a_core_dto(corpus: dict[str, Any]) -> None:
    command = resolve_core_instance(corpus, "execution_commands", "lost_parcel_full_line")
    assert "entitlement_id" not in CoreRefundCommand.model_fields
    assert "address_hash" not in CoreRefundCommand.model_fields
    with pytest.raises(ValidationError):
        CoreRefundCommand.model_validate({**command, "entitlement_id": "ent-1"})
    with pytest.raises(ValidationError):
        CoreRefundCommand.model_validate({**command, "address_hash": "a" * 64})
    assert "schema_version" not in CoreRefundCommand.model_fields


# ------------------------------------------------------------ the corpus, replayed


@pytest.mark.parametrize("section", sorted(MODEL_OF_SECTION))
def test_every_positive_fixture_is_accepted_by_its_model(corpus: dict[str, Any], section: str) -> None:
    model = MODEL_OF_SECTION[section]
    names = [name for name in corpus[section] if not name.startswith("_")]
    assert names, section
    for name in names:
        model.model_validate(resolve_core_instance(corpus, section, name))


NEGATIVE_CASES = [
    (section, name)
    for section, entries in load_core_reject_corpus().items()
    if not section.startswith("_") and section in REJECT_SECTION_OF
    for name in entries
    if not name.startswith("_")
]


@pytest.mark.parametrize(("section", "name"), NEGATIVE_CASES, ids=[f"{s}.{n}" for s, n in NEGATIVE_CASES])
def test_every_negative_fixture_is_refused_by_its_model(section: str, name: str) -> None:
    """Every shape the schema refuses, the DTO refuses too - no holes."""
    reject = load_core_reject_corpus()
    assert CORE_REJECT_TARGETS[section] is not None
    instance = resolve_core_negative_instance(reject, section, name)
    with pytest.raises(ValidationError):
        MODEL_OF_SECTION[REJECT_SECTION_OF[section]].model_validate(instance)


def test_the_negative_corpus_covers_every_model() -> None:
    covered = {REJECT_SECTION_OF[section] for section, _ in NEGATIVE_CASES}
    assert covered == set(MODEL_OF_SECTION)


# ------------------------------------------------------------------- the two rules


def proposal_from(corpus: dict[str, Any], name: str = "refund_lost_parcel") -> dict[str, Any]:
    return resolve_core_instance(corpus, "agent_proposals", name)


def test_a_refund_proposal_without_citations_is_refused(corpus: dict[str, Any]) -> None:
    instance = proposal_from(corpus)
    for change in ({"evidence_refs": []}, {"policy_refs": []}, {"missing_evidence": ["照片"]}):
        with pytest.raises(ValidationError, match="refund proposal"):
            CoreAgentProposal.model_validate({**instance, **change})


def test_a_question_proposal_needs_no_citations(corpus: dict[str, Any]) -> None:
    instance = proposal_from(corpus, "request_info_damage")
    model = CoreAgentProposal.model_validate(instance)
    assert model.recommended_action == "REQUEST_INFO"
    assert model.missing_evidence


def test_a_result_event_must_agree_with_its_state(corpus: dict[str, Any]) -> None:
    envelope = resolve_core_instance(corpus, "message_envelopes", "refund_succeeded")
    assert CoreEnvelope.model_validate(envelope).event_type == "RefundSucceeded"
    mismatched = {**envelope, "event_type": "RefundFailed"}
    with pytest.raises(ValidationError, match="the event type and the result state"):
        CoreEnvelope.model_validate(mismatched)


def test_a_requested_event_must_carry_a_command(corpus: dict[str, Any]) -> None:
    requested = resolve_core_instance(corpus, "message_envelopes", "refund_requested")
    result = resolve_core_instance(corpus, "message_envelopes", "refund_succeeded")
    assert isinstance(CoreEnvelope.model_validate(requested).payload, dict)
    wrong_payload = {**requested, "payload": result["payload"]}
    with pytest.raises(ValidationError):
        CoreEnvelope.model_validate(wrong_payload)


def test_routing_that_contradicts_the_event_type_is_refused(corpus: dict[str, Any]) -> None:
    envelope = resolve_core_instance(corpus, "message_envelopes", "refund_succeeded")
    with pytest.raises(ValidationError, match="must come from commerce-service"):
        CoreEnvelope.model_validate({**envelope, "producer": "case-service"})
    requested = resolve_core_instance(corpus, "message_envelopes", "refund_requested")
    with pytest.raises(ValidationError, match="must come from case-service"):
        CoreEnvelope.model_validate({**requested, "topic": "rf.commerce.core.v2"})


def nullable_properties(schema: dict[str, Any]) -> set[str]:
    """Schema properties that explicitly list ``null`` as a permitted type."""
    allowed: set[str] = set()
    for name, spec in schema["properties"].items():
        types = spec.get("type")
        if types == "null" or (isinstance(types, list) and "null" in types):
            allowed.add(name)
    return allowed


@pytest.mark.parametrize("model", sorted(MODEL_OF_SECTION.values(), key=lambda item: item.__name__))
def test_nullable_members_match_the_schema(model: type[Any]) -> None:
    """A DTO that accepts ``{"traceparent": null}`` while the schema refuses it is a hole.

    The core wire says "absent" by omitting the member (docs/domain-model.md:3 keeps the
    wire literal), so only the members the schema types as nullable may be null.
    """
    assert set(model.NULLABLE_MEMBERS) == nullable_properties(schema_of(model))


def test_the_only_nullable_members_in_the_protocol_are_the_two_result_fields() -> None:
    assert set(CoreRefundResult.NULLABLE_MEMBERS) == {"provider_ref", "reason_code"}
    for model in (CoreRefundCommand, CoreEnvelope, CoreEvidenceRef, CorePolicyRef, CoreAgentProposal):
        assert model.NULLABLE_MEMBERS == frozenset()


def test_the_dto_accepts_an_envelope_with_the_optional_members_absent(corpus: dict[str, Any]) -> None:
    """Absent is the only way to say absent, and both optional members may be omitted."""
    envelope = resolve_core_instance(corpus, "message_envelopes", "refund_requested_without_traceparent")
    model = CoreEnvelope.model_validate(envelope)
    assert model.traceparent is None and model.causation_id is None
    for member in ("traceparent", "causation_id"):
        with pytest.raises(ValidationError, match="omit the member instead"):
            CoreEnvelope.model_validate({**envelope, member: None})


def test_a_null_suggested_amount_is_refused_by_both_the_dto_and_the_schema(corpus: dict[str, Any]) -> None:
    """The narrowing recorded in the core README: absence, not null, means "no amount"."""
    instance = proposal_from(corpus)
    schema = schema_of(CoreAgentProposal)
    with pytest.raises(ValidationError, match="omit the member instead"):
        CoreAgentProposal.model_validate({**instance, "suggested_amount_minor": None})
    assert "suggested_amount_minor" not in nullable_properties(schema)
    del instance["suggested_amount_minor"]
    assert CoreAgentProposal.model_validate(instance).suggested_amount_minor is None


def test_a_nullable_result_field_accepts_null(corpus: dict[str, Any]) -> None:
    """The other direction: where the schema allows null, the DTO must not refuse it."""
    result = resolve_core_instance(corpus, "message_envelopes", "refund_failed")["payload"]
    assert CoreRefundResult.model_validate({**result, "provider_ref": None}).provider_ref is None
    assert CoreRefundResult.model_validate({**result, "reason_code": None}).reason_code is None


def test_a_url_reference_is_refused_by_the_dto(corpus: dict[str, Any]) -> None:
    """docs/core-contracts.md:61, enforced with a Python regex because Pydantic has no look-around."""
    evidence = resolve_core_instance(corpus, "agent_proposals", "refund_lost_parcel")["evidence_refs"][0]
    with pytest.raises(ValidationError, match="not a URL"):
        CoreEvidenceRef.model_validate({**evidence, "source_ref": "https://example.com/orders/7001"})
    assert CoreEvidenceRef.model_validate(evidence).source_ref == "line:7001/shipment"


def test_money_and_revisions_are_bounded_in_the_dto(corpus: dict[str, Any]) -> None:
    command = resolve_core_instance(corpus, "execution_commands", "lost_parcel_full_line")
    with pytest.raises(ValidationError):
        CoreRefundCommand.model_validate({**command, "amount_minor": 0})
    with pytest.raises(ValidationError):
        CoreRefundCommand.model_validate({**command, "amount_minor": 1000000001})
    with pytest.raises(ValidationError):
        CoreRefundCommand.model_validate({**command, "input_revision": 9007199254740992})
    with pytest.raises(ValidationError):
        CoreRefundCommand.model_validate({**command, "amount_minor": 25.99})


def test_a_float_amount_is_refused_rather_than_coerced(corpus: dict[str, Any]) -> None:
    """Strict mode: JSON ``25.99`` must not silently become ``25`` via int coercion."""
    command = resolve_core_instance(corpus, "execution_commands", "lost_parcel_full_line")
    with pytest.raises(ValidationError):
        CoreRefundCommand.model_validate({**command, "amount_minor": 2599.0})


def test_a_result_may_omit_the_optional_provider_fields(corpus: dict[str, Any]) -> None:
    result = resolve_core_instance(corpus, "message_envelopes", "refund_failed")["payload"]
    model = CoreRefundResult.model_validate(result)
    assert model.provider_ref is None and model.reason_code == "PROVIDER_DECLINED"
    assert CoreRefundResult.model_validate({**result, "reason_code": None}).reason_code is None


def test_the_dto_does_not_verify_signatures_or_hashes(corpus: dict[str, Any]) -> None:
    """Shape only: a forged digest is still shaped like a digest (Python verifies elsewhere)."""
    command = resolve_core_instance(corpus, "execution_commands", "lost_parcel_full_line")
    model = CoreRefundCommand.model_validate({**command, "payload_hash": "0" * 64})
    assert model.payload_hash == "0" * 64