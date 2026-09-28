"""Reviewer explanations must retain provenance through the actual callback payload."""

from copy import deepcopy

import pytest

from resolveflow.contracts._schemaio import CORE_SCHEMA_FILES, component_validator, load_json
from resolveflow.contracts.core_models import CoreAgentProposal
from resolveflow.harness.actions import ActionRefusedError, validate_decision


def decision():
    return {
        "kind": "PROPOSE", "recommended_action": "MANUAL_REVIEW", "case_type": "LOGISTICS",
        "summary": "客户陈述与物流记录存在矛盾，请人工核对。", "reason_codes": ["SIGNED_DISPUTE"],
        "evidence_refs": [
            {"observation_id": key, "source_ref": f"line:1/{key}", "source_version": "1", "content_hash": "a" * 64}
            for key in ["customer", "shipment"]
        ],
        "review_findings": [
            {"kind": "FACT", "text": "物流记录显示签收", "observation_ids": ["shipment"]},
            {"kind": "CONFLICT", "text": "客户称未收到，但物流显示签收", "observation_ids": ["customer", "shipment"]},
        ],
    }


def test_findings_require_citations_present_in_the_proposal():
    raw = decision()
    raw["review_findings"][0]["observation_ids"] = ["invented"]
    with pytest.raises(ActionRefusedError):
        validate_decision(raw)


def test_a_conflict_requires_two_distinct_sources():
    raw = decision()
    raw["review_findings"][1]["observation_ids"] = ["shipment", "shipment"]
    with pytest.raises(ActionRefusedError):
        validate_decision(raw)


def test_findings_survive_wire_serialization_and_reject_unknown_sources():
    raw = decision()
    accepted = validate_decision(raw)
    assert accepted.review_findings[1].kind == "CONFLICT"
    payload = {key: value for key, value in raw.items() if key != "kind"}
    payload.update(schema_version=2, proposal_id="11111111-1111-4111-8111-111111111111",
                   run_id="22222222-2222-4222-8222-222222222222",
                   case_id="33333333-3333-4333-8333-333333333333", input_revision=1)
    model = CoreAgentProposal.model_validate(payload)
    assert model.model_dump()["review_findings"] == raw["review_findings"]
    invalid = deepcopy(payload)
    invalid["review_findings"][0]["observation_ids"] = ["invented"]
    with pytest.raises(ValueError):
        CoreAgentProposal.model_validate(invalid)


def test_shared_findings_fixture_matches_wire_contract():
    raw = load_json("contracts/core/fixtures/reviewer-findings.json")
    model = CoreAgentProposal.model_validate(raw)
    assert len(model.review_findings) == 3
    validator = component_validator("case", "ProposalPayload", "contracts/core", CORE_SCHEMA_FILES)
    assert list(validator.error_messages(raw)) == []
