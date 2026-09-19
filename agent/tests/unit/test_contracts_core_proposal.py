"""C00.2c: the core proposal schema, and its agreement with the case OpenAPI.

Two documents describe the same wire object: ``contracts/core/agent-proposal.schema.json``
fixes what a run may submit, and ``ProposalPayload`` in
``contracts/core/openapi-case.yaml`` is what case-service accepts. Two copies of one
shape are exactly how a contract drifts, so this file asserts they agree field for
field, required for required, constraint for constraint. The compat proposal is kept
separate and is asserted to still allow what core does not.
"""

from __future__ import annotations

from typing import Any

import pytest

from resolveflow.contracts._schemaio import (
    CORE_SCHEMA_FILES,
    SCHEMA_FILES,
    component_validator,
    load_json,
    load_openapi,
    schema_registry,
    validator_bundle,
)

PROPOSAL = "urn:resolveflow:core:agent-proposal:v2"
COMPAT_PROPOSAL = "urn:resolveflow:agent-proposal:v1"

#: Keys that describe a JSON Schema shape. ``description``/``title`` are documentation
#: and are deliberately excluded: the two documents are allowed to word things
#: differently, they are not allowed to constrain differently.
SHAPE_KEYS = (
    "type",
    "pattern",
    "enum",
    "const",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "uniqueItems",
    "additionalProperties",
    "required",
)


def proposal_schema() -> dict[str, Any]:
    return load_json("contracts/core/agent-proposal.schema.json")


def payload_component() -> dict[str, Any]:
    return load_openapi("case", "contracts/core")["components"]["schemas"]["ProposalPayload"]


def view_component() -> dict[str, Any]:
    return load_openapi("case", "contracts/core")["components"]["schemas"]["ProposalView"]


def shape(node: dict[str, Any]) -> dict[str, Any]:
    return {key: node[key] for key in SHAPE_KEYS if key in node}


def resolve_component(node: dict[str, Any]) -> dict[str, Any]:
    """Follow a ``$ref`` to the case document's component, or return the inline schema."""
    if "$ref" not in node:
        return node
    name = node["$ref"].rsplit("/", 1)[-1]
    return load_openapi("case", "contracts/core")["components"]["schemas"][name]


def compatible_property(name: str) -> None:
    """One proposal property must constrain exactly what the OpenAPI property constrains.

    The OpenAPI property is taken from the same document the component lives in and its
    ``$ref``s are followed, so a constraint added on either side without the other fails
    here rather than at runtime.
    """
    schema_property = proposal_schema()["properties"][name]
    target = resolve_component(payload_component()["properties"][name])
    assert shape(schema_property) == shape(target), f"the proposal schema and {name} disagree"
    if "items" not in schema_property:
        return
    schema_items = schema_property["items"]
    target_items = resolve_component(target["items"])
    assert shape(schema_items) == shape(target_items), f"the items of {name} disagree"
    for key, fragment in schema_items.get("properties", {}).items():
        assert shape(fragment) == shape(resolve_component(target_items["properties"][key])), f"{name}.{key}"


# ------------------------------------------------------------------ schema identity


def test_core_proposal_has_its_own_id_disjoint_from_the_compat_one() -> None:
    core_ids = {document["$id"] for document in schema_registry(CORE_SCHEMA_FILES)[1].values()}
    compat_ids = {document["$id"] for document in schema_registry(SCHEMA_FILES)[1].values()}
    assert PROPOSAL in core_ids
    assert COMPAT_PROPOSAL in compat_ids
    assert not core_ids & compat_ids, "a v2 document may not reuse a v1 id"


def test_core_registry_cannot_resolve_the_compat_proposal_and_vice_versa() -> None:
    with pytest.raises(KeyError):
        validator_bundle(COMPAT_PROPOSAL, CORE_SCHEMA_FILES)
    with pytest.raises(KeyError):
        validator_bundle(PROPOSAL, SCHEMA_FILES)


def test_compat_document_is_untouched() -> None:
    compat = load_json("contracts/agent-proposal.schema.json")
    assert compat["$id"] == COMPAT_PROPOSAL
    assert compat["title"] == "AgentProposalV1"


# ------------------------------------------------------------------------- action set


def test_core_proposal_drops_reship_from_the_action_set() -> None:
    action = proposal_schema()["properties"]["recommended_action"]["enum"]
    assert action == ["REFUND", "REQUEST_INFO", "MANUAL_REVIEW", "REJECT"]
    compat = load_json("contracts/agent-proposal.schema.json")["properties"]["recommended_action"]["enum"]
    assert compat == ["REFUND", "RESHIP", "REQUEST_INFO", "MANUAL_REVIEW", "REJECT"]


def test_core_proposal_carries_its_protocol_version_and_case_binding() -> None:
    """Correction of an earlier (uncommitted-authority) narrowing.

    This test first asserted the opposite - that a core proposal carries neither
    ``schema_version`` nor ``case_id`` - on the reasoning that the callback endpoint is
    already case-scoped and that the payload is not hashed. ``docs/core-contracts.md:9``
    settles it the other way ("核心Agent方案schema_version=2...其他字段复用旧结构"): the
    compat proposal is the field authority and it carries both. ``:57`` adds the reason
    ``case_id`` is useful rather than redundant - "body主体必须与service JWT及Case绑定
    一致" only has something to check if the binding is in the body.
    """
    schema = proposal_schema()
    assert schema["properties"]["schema_version"] == {"const": 2}
    assert "case_id" in schema["required"]
    assert set(schema["required"]) <= set(schema["properties"])
    compat = load_json("contracts/agent-proposal.schema.json")
    assert compat["properties"]["schema_version"] == {"const": 1}
    assert compat["required"].count("case_id") == 1


def test_actionable_proposal_must_cite_evidence_and_policy() -> None:
    conditional = proposal_schema()["allOf"][0]
    assert conditional["if"]["properties"]["recommended_action"] == {"const": "REFUND"}
    then = conditional["then"]["properties"]
    assert then["evidence_refs"]["minItems"] == 1
    assert then["policy_refs"]["minItems"] == 1
    assert then["missing_evidence"]["maxItems"] == 0


def test_only_the_refund_action_is_conditional() -> None:
    """REQUEST_INFO may legitimately name missing evidence; the compat schema said so for two actions."""
    actions = proposal_schema()["properties"]["recommended_action"]["enum"]
    conditional_actions = {proposal_schema()["allOf"][0]["if"]["properties"]["recommended_action"]["const"]}
    assert conditional_actions == {"REFUND"}
    assert set(actions) - conditional_actions == {"REQUEST_INFO", "MANUAL_REVIEW", "REJECT"}


# ----------------------------------------------------------- agreement with OpenAPI


def test_proposal_properties_match_the_case_openapi_payload() -> None:
    schema = proposal_schema()
    component = payload_component()
    assert set(schema["properties"]) == set(component["properties"]), "the two documents describe different fields"
    assert set(schema["required"]) == set(component["required"])


@pytest.mark.parametrize("name", sorted(proposal_schema()["properties"]))
def test_each_proposal_property_constrains_what_its_component_constrains(name: str) -> None:
    compatible_property(name)


def test_suggested_amount_is_absent_or_an_integer_never_null() -> None:
    schema_property = proposal_schema()["properties"]["suggested_amount_minor"]
    assert shape(schema_property) == {"type": "integer", "minimum": 0, "maximum": 1000000000}
    assert shape(payload_component()["properties"]["suggested_amount_minor"]) == shape(schema_property)
    assert shape(view_component()["properties"]["suggested_amount_minor"]) == shape(schema_property)


def test_proposal_view_is_the_payload_plus_the_status_case_owns() -> None:
    payload = set(payload_component()["properties"])
    view = set(view_component()["properties"])
    assert payload <= view
    assert view - payload == {"status", "created_at"}
    assert set(view_component()["required"]) - set(payload_component()["required"]) == {"status"}


# ------------------------------------------------------------------------- instances


def refund_proposal() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "proposal_id": "5f0f0f0f-1111-4222-8333-444455556666",
        "run_id": "e2e2e2e2-3333-4444-8555-aaaaaaaaaaaa",
        "case_id": "9c858901-8a57-4791-81fe-4c455b099bc9",
        "input_revision": 1,
        "case_type": "LOGISTICS",
        "recommended_action": "REFUND",
        "suggested_amount_minor": 2599,
        "summary": "物流7天无更新且承运商结论为丢失，按政策可全额退款",
        "reason_codes": ["CARRIER_LOST", "NO_SCAN_7D"],
        "evidence_refs": [
            {
                "observation_id": "obs-1",
                "source_ref": "line:7001/shipment",
                "source_version": "2",
                "content_hash": "1" * 64,
            }
        ],
        "policy_refs": [
            {
                "bundle_id": "policy-logistics-2026.09",
                "version": "2026.09",
                "rule_id": "R-LOST-001",
                "chunk_id": "c-01",
                "content_hash": "2" * 64,
            }
        ],
        "missing_evidence": [],
    }


def test_a_refund_proposal_is_accepted() -> None:
    validator = validator_bundle(PROPOSAL, CORE_SCHEMA_FILES)
    assert validator.error_messages(refund_proposal()) == []


def test_the_case_openapi_accepts_the_same_instance() -> None:
    instance = refund_proposal()
    assert component_validator("case", "ProposalPayload", "contracts/core", CORE_SCHEMA_FILES).accepts(instance)
    assert component_validator("case", "ProposalView", "contracts/core", CORE_SCHEMA_FILES).accepts(
        {**instance, "status": "VALIDATED", "created_at": "2026-09-18T04:28:00Z"}
    )


def test_request_info_proposal_without_citations_is_accepted() -> None:
    """Only REFUND is conditional; asking the customer for material cites nothing yet."""
    instance = {
        "schema_version": 2,
        "proposal_id": "5f0f0f0f-1111-4222-8333-444455556666",
        "run_id": "e2e2e2e2-3333-4444-8555-aaaaaaaaaaaa",
        "case_id": "9c858901-8a57-4791-81fe-4c455b099bc9",
        "input_revision": 1,
        "case_type": "DAMAGED",
        "recommended_action": "REQUEST_INFO",
        "summary": "损坏描述不足，需要客户补充照片与签收时间",
        "reason_codes": ["DAMAGE_NOT_DESCRIBED"],
        "missing_evidence": ["损坏部位照片", "签收日期"],
    }
    assert validator_bundle(PROPOSAL, CORE_SCHEMA_FILES).error_messages(instance) == []


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"recommended_action": "RESHIP"}, "reship is not a core action"),
        ({"recommended_action": "EITHER"}, "the compat customer-facing value is not a proposal action"),
        ({"recommended_action": "refund"}, "lowercase is not the wire vocabulary"),
        ({"evidence_refs": []}, "a refund proposal must cite evidence"),
        ({"policy_refs": []}, "a refund proposal must cite policy"),
        ({"missing_evidence": ["损坏照片"]}, "a refund proposal cannot also ask for evidence"),
        ({"suggested_amount_minor": 25.99}, "money is integer minor units"),
        ({"suggested_amount_minor": None}, "absent is how 'no suggestion' is expressed"),
        ({"suggested_amount_minor": 1000000001}, "above the amount ceiling"),
        ({"schema_version": 1}, "a v2 proposal is never the compat version"),
        ({"schema_version": "2"}, "the version is a number, not a string"),
        ({"status": "VALIDATED"}, "the payload cannot carry the status case-service owns"),
        ({"created_at": "2026-09-18T04:28:00Z"}, "created_at belongs to the view, not the payload"),
        ({"case_id": "9c858901"}, "the case binding is a UUID"),
        ({"reason_codes": []}, "a proposal without a reason cannot be reviewed"),
        ({"reason_codes": ["carrier_lost"]}, "reason codes are upper case"),
        ({"summary": ""}, "the reviewer has nothing to read"),
        ({"input_revision": 0}, "revisions start at 1"),
    ],
)
def test_a_broken_proposal_is_refused(change: dict[str, Any], reason: str) -> None:
    instance = {**refund_proposal(), **change}
    errors = validator_bundle(PROPOSAL, CORE_SCHEMA_FILES).error_messages(instance)
    assert errors, f"accepted a proposal that should fail: {reason}"


def evidence(**overrides: Any) -> dict[str, Any]:
    citation: dict[str, Any] = {
        "observation_id": "obs-1",
        "source_ref": "line:7001/shipment",
        "source_version": "2",
        "content_hash": "1" * 64,
    }
    citation.update(overrides)
    return citation


def policy(**overrides: Any) -> dict[str, Any]:
    citation: dict[str, Any] = {
        "bundle_id": "policy-logistics-2026.09",
        "version": "2026.09",
        "rule_id": "R-LOST-001",
        "chunk_id": "c-01",
        "content_hash": "2" * 64,
    }
    citation.update(overrides)
    return citation


@pytest.mark.parametrize(
    "change",
    [
        {"evidence_refs": [evidence(source_ref="https://example.com/x")]},
        {"evidence_refs": [evidence(content_hash="A" * 64)]},
        {"evidence_refs": [{key: value for key, value in evidence().items() if key != "source_ref"}]},
        {"policy_refs": [{key: value for key, value in policy().items() if key != "chunk_id"}]},
    ],
)
def test_a_citation_that_java_could_not_re_read_is_refused(change: dict[str, Any]) -> None:
    """A URL is not a source_ref, and a citation missing its chunk or hash cannot be re-read."""
    instance = {**refund_proposal(), **change}
    assert validator_bundle(PROPOSAL, CORE_SCHEMA_FILES).error_messages(instance)


def test_the_compat_proposal_still_accepts_a_reship_proposal() -> None:
    """The v1 document keeps its behaviour; only the core document narrows."""
    instance = {
        "schema_version": 1,
        "proposal_id": "5f0f0f0f-1111-4222-8333-444455556666",
        "run_id": "e2e2e2e2-3333-4444-8555-aaaaaaaaaaaa",
        "case_id": "9c858901-8a57-4791-81fe-4c455b099bc9",
        "input_revision": 1,
        "case_type": "LOGISTICS",
        "recommended_action": "RESHIP",
        "summary": "补发同款商品",
        "reason_codes": ["CARRIER_LOST"],
        "evidence_refs": [
            {
                "observation_id": "obs-1",
                "source_ref": "line:7001/shipment",
                "source_version": "2",
                "content_hash": "1" * 64,
            }
        ],
        "policy_refs": [
            {
                "bundle_id": "policy-logistics-2026.09",
                "version": "2026.09",
                "rule_id": "R-LOST-001",
                "chunk_id": "c-01",
                "content_hash": "2" * 64,
            }
        ],
        "missing_evidence": [],
    }
    assert validator_bundle(COMPAT_PROPOSAL, SCHEMA_FILES).error_messages(instance) == []