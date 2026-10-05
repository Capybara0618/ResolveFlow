"""Regression failures from the Harness audit; no paid model calls."""

import pytest
from resolveflow.harness.sdk_runner import ActionGateMiddleware
from resolveflow.harness.verifier import ProposalVerifier

from tests.unit.test_harness_loop import propose
from tests.unit.test_investigation_sources import scenario, source, verify
from tests.unit.test_proposal_verifier import BUNDLE, RULE, search


@pytest.mark.parametrize("field,value,expected", [
    ("line_refund_state", "RESERVED", "FREE"),
    ("fulfillment_status", "UNKNOWN", "NOT_SHIPPED"),
    ("fulfillment_version", 2, "1"),
    ("order_status", "CREATED", "PAID"),
    ("payment_version", 0, "positive integer"),
])
def test_unshipped_refusal_names_actual_failed_field(field, value, expected):
    case = scenario("A01A")
    case["backend"]["order"][field] = value
    result = verify(case, rule="R-UNSHIPPED-001", omitted=("get_shipment_trace",))
    assert not result.ok
    detail = result.detail()
    assert f"{field}={value}" in detail and expected in detail


def test_insufficient_order_balance_names_integer_minor_unit_amounts():
    case = scenario("A01A")
    body = case["backend"]["order"]
    body["reserved_refund_amount"] = body["order_paid_amount"]
    detail = verify(case, rule="R-UNSHIPPED-001", omitted=("get_shipment_trace",)).detail()
    assert f"reserved_refund_amount={body['order_paid_amount']}" in detail
    assert "minor units" in detail and "ESCALATE" in detail


def test_occupied_slot_feedback_reaches_next_turn_and_can_handover():
    body = scenario("A01A")["backend"]["order"]
    body["line_refund_state"] = "RESERVED"
    order = source("get_order_context", body)
    rule = {**RULE, "rule_id": "R-UNSHIPPED-001"}
    policy = search(rule)
    evidence = [{k: getattr(order, k) for k in (
        "observation_id", "source_ref", "source_version", "content_hash")}]
    policies = [{k: rule[k] for k in ("bundle_id", "version", "rule_id", "chunk_id", "content_hash")}]
    gate = ActionGateMiddleware()
    gate.verifier = ProposalVerifier([order, policy], frozenset({BUNDLE}))
    assert gate.check(propose("REFUND", evidence_refs=evidence, policy_refs=policies)) is None
    assert "line_refund_state=RESERVED" in gate.notices[-1]
    assert gate.repairs_used == 1 and gate.stop_reason is None
    assert gate.check({"kind": "ESCALATE", "reason_codes": ["NEEDS_HUMAN_VERIFICATION"]}).kind == "ESCALATE"
