"""Known policy conditions cannot be satisfied by citing the wrong source kind."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from resolveflow.harness.verifier import ProposalVerifier

from tests.unit.test_harness_loop import observation
from tests.unit.test_proposal_verifier import BUNDLE, RULE, search


def scenario(case_id="A05A"):
    cases = json.loads((Path(__file__).resolve().parents[3] / "evals/aligned-v2/agent/cases.json").read_text("utf-8"))
    return deepcopy(next(c for c in cases if c["id"] == case_id))


def source(name, body, version="1"):
    return observation().model_copy(update={
        "observation_id": f"obs-{name}-{version}", "tool_name": name, "source_ref": f"source:{name}",
        "source_version": version, "result": body,
    })


def verify(case, *, rule="R-LOST-001", omitted=(), replacements=None, extra=()):
    bodies = {"get_order_context": case["backend"]["order"],
              "get_shipment_trace": case["backend"]["shipment"],
              "get_case_evidence": case["backend"]["evidence"]}
    bodies.update(replacements or {})
    sources = [source(name, body) for name, body in bodies.items() if name not in omitted]
    policy = search({**RULE, "rule_id": rule})
    verifier = ProposalVerifier(observations=[*sources, *extra, policy], pinned_bundle_ids=frozenset({BUNDLE}),
        case_id=case["case_id"], input_revision=case["input_revision"], review_context=case["review_context"])
    result = verifier.verify_citations(recommended_action="REFUND",
        evidence_refs=[{k: getattr(item, k) for k in (
            "observation_id", "source_ref", "source_version", "content_hash")} for item in sources],
        policy_refs=[{k: ({**RULE, "rule_id": rule})[k] for k in (
            "bundle_id", "version", "rule_id", "chunk_id", "content_hash")}])
    return result


def test_confirmed_loss_with_registered_material_carrier_and_order_passes():
    assert verify(scenario()).ok


@pytest.mark.parametrize("rule", ["R-MONEY-001", "R-SIGNED-001", "R-INTRANSIT-001"])
def test_procedural_clause_cannot_substitute_for_refund_entitlement(rule):
    assert not verify(scenario(), rule=rule).ok


@pytest.mark.parametrize("name", ["get_order_context", "get_shipment_trace", "get_case_evidence"])
def test_order_or_snapshot_alone_cannot_replace_missing_loss_source(name):
    result = verify(scenario(), omitted=(name,))
    assert not result.ok and "INVESTIGATION_FACTS_REQUIRED" in result.reason_codes


@pytest.mark.parametrize("mutation", ["unknown", "different_target", "different_hash", "different_case",
                                      "different_revision", "later_refutation"])
def test_human_confirmation_requires_current_registered_target_and_source(mutation):
    case = scenario()
    material = case["review_context"]["materials"][-1]
    if mutation == "unknown":
        material["verification_result"] = "INCONCLUSIVE"
    elif mutation == "different_target":
        material["reviewed_evidence_id"] = "unrelated-material"
    elif mutation == "different_hash":
        case["backend"]["evidence"]["evidence"][-1]["content_hash"] = "f" * 64
    elif mutation == "different_case":
        case["backend"]["evidence"]["case_id"] = "unrelated-case"
    elif mutation == "different_revision":
        case["backend"]["evidence"]["input_revision"] = 1
    else:
        case["review_context"]["materials"].append({**material, "evidence_id": "later",
            "input_revision": 3, "verification_result": "REFUTED"})
    assert not verify(case).ok


@pytest.mark.parametrize("change", [{"status": "IN_TRANSIT", "carrier_conclusion": "IN_TRANSIT"},
                                    {"status": "LOST", "carrier_conclusion": "UNKNOWN"},
                                    {"status": "DELIVERED", "carrier_conclusion": "SIGNED"}])
def test_loss_requires_carrier_confirmation_not_just_order_fulfillment(change):
    case = scenario()
    case["backend"]["shipment"].update(change)
    assert not verify(case).ok


def test_loss_with_signed_event_is_not_unambiguous_loss():
    case = scenario()
    case["backend"]["shipment"]["events"] = [{"code": "SIGNED"}]
    assert not verify(case).ok


@pytest.mark.parametrize("field,value", [("line_refund_state", "UNKNOWN"), ("reserved_refund_amount", 1),
                                        ("order_status", "CREATED"), ("payment_version", 0)])
def test_confirmed_loss_still_requires_paid_available_line(field, value):
    case = scenario()
    case["backend"]["order"][field] = value
    assert not verify(case).ok


def test_new_failed_read_cannot_be_hidden_by_older_successful_citation():
    from tests.unit.test_harness_loop import failed_observation
    later = failed_observation().model_copy(update={"tool_name": "get_shipment_trace",
                                                    "source_ref": "source:get_shipment_trace"})
    assert not verify(scenario(), extra=(later,)).ok


def test_delivered_order_suffices_for_quality_without_forcing_carrier_read():
    assert verify(scenario("A13A"), rule="R-DMG-001", omitted=("get_shipment_trace",)).ok


def test_inconclusive_quality_claim_does_not_establish_refund_entitlement():
    assert not verify(scenario("A13B"), rule="R-DMG-001", omitted=("get_shipment_trace",)).ok


def test_quality_does_not_hide_a_conflicting_carrier_read():
    case = scenario("A13A")
    case["backend"]["shipment"]["status"] = "IN_TRANSIT"
    assert not verify(case, rule="R-DMG-001").ok
