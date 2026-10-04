"""Current commerce snapshots and scenario gates, using synthetic inputs only."""
import json

import pytest

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator
from resolveflow.harness.context import extract_facts
from resolveflow.harness.facts import FactsView
from resolveflow.harness.verifier import ProposalVerifier
from resolveflow.tools.catalog import get_order_context
from tests.unit.test_context_builder import build, observation
from tests.unit.test_context_quality import cited, text_of
from tests.unit.test_proposal_verifier import POLICY, search
from tests.unit.test_tool_catalog import client_for, context


def order_body(**changes):
    samples = json.loads((REPO_ROOT / "contracts/core/fixtures/agent-order-facts.json").read_text(encoding="utf-8"))
    return {**samples[0]["value"], **changes}


def order(**changes):
    return get_order_context(client_for(order_body(**changes)), context())


def check(action, sources, rule="R-UNSHIPPED-001"):
    policy = {**POLICY, "rule_id": rule}
    verifier = ProposalVerifier([*sources, search({**policy, "text": "完整条件及例外"})],
                                frozenset({POLICY["bundle_id"]}))
    return verifier.verify_citations(recommended_action=action, evidence_refs=[cited(s) for s in sources],
                                     policy_refs=[policy])


def test_order_source_version_and_hash_cover_payment_and_fulfillment_changes():
    first = order()
    second = order(fulfillment_status="IN_TRANSIT", fulfillment_version=2)
    third = order(payment_version=2, reserved_refund_amount=32900)
    assert len({s.source_version for s in (first, second, third)}) == 3
    assert len({s.content_hash for s in (first, second, third)}) == 3
    assert first.source_version == "order-1:payment-1:fulfillment-1"
    assert first.result == order_body()
    large = order(version=9223372036854775807, payment_version=9223372036854775807,
                  fulfillment_version=9223372036854775807)
    assert len(large.source_version) == 64
    assert large.result["fulfillment_version"] == 9223372036854775807


def test_real_order_status_and_fulfillment_are_protected_once_and_history_remains():
    first, second = order(), order(fulfillment_status="IN_TRANSIT", fulfillment_version=2)
    second = second.model_copy(update={"observation_id": "second-order"})
    view = FactsView()
    for source in (first, second):
        extract_facts(view, source)
    text = text_of(build(observations=[first, second], view=view))
    assert "order_status=PAID" in text
    assert "order_fulfillment_status=IN_TRANSIT" in text
    assert "order_fulfillment_version=2" in text
    assert "payment_order_paid_amount_minor=32900" in text
    assert "line_refund_state=FREE" in text
    assert "order_reserved_amount_minor=0" in text
    assert "order_fulfillment_status=NOT_SHIPPED" not in text
    assert first.result["fulfillment_status"] == "NOT_SHIPPED"


def test_core_snapshot_wire_is_strict_but_legacy_fulfillment_is_absent():
    validator = component_validator("commerce", "LineContext", "contracts/core")
    assert validator.accepts(order_body())
    old = order_body()
    for key in ("fulfillment_status", "fulfillment_version", "payment_version"):
        del old[key]
    assert validator.accepts(old)
    for changes in ({"fulfillment_status": "made-up"}, {"fulfillment_version": 0}, {"payment_version": 0}):
        assert not validator.accepts(order_body(**changes))
    missing = order_body()
    del missing["fulfillment_version"]
    assert not validator.accepts(missing)


def test_unshipped_refund_needs_only_relevant_payment_and_explicit_fulfillment():
    assert check("REFUND", [order()]).ok
    assert not check("REJECT", [order()]).ok  # This positive eligibility cannot justify denial.


@pytest.mark.parametrize("changes", [
    {"fulfillment_status": "UNKNOWN"}, {"fulfillment_status": "IN_TRANSIT", "fulfillment_version": 2},
    {"fulfillment_version": None}, {"payment_version": None}, {"paid_at": None},
    {"order_status": "CANCELLED"}, {"currency": "USD"}, {"line_refund_state": "CONSUMED"},
    {"reserved_refund_amount": 32900}, {"order_paid_amount": 0},
])
def test_unshipped_refund_fails_on_unknown_changed_or_consumed_facts(changes):
    assert not check("REFUND", [order(**changes)]).ok


def test_old_read_cannot_be_cited_as_current_after_shipment_or_a_failed_refresh():
    first = order()
    newer = order(fulfillment_status="IN_TRANSIT", fulfillment_version=2).model_copy(
        update={"observation_id": "newer"})
    policy = {**POLICY, "rule_id": "R-UNSHIPPED-001"}
    verifier = ProposalVerifier([first, newer, search(policy)], frozenset({POLICY["bundle_id"]}))
    result = verifier.verify_citations(recommended_action="REFUND", evidence_refs=[cited(first)], policy_refs=[policy])
    assert not result.ok
    failed = first.model_copy(update={"observation_id": "failed", "source_version": None, "content_hash": None,
                                     "result": None, "error": {"code": "NOT_FOUND", "message": "missing",
                                                               "retryable": False}})
    verifier.observations = [first, failed, search(policy)]
    assert not verifier.verify_citations(recommended_action="REFUND", evidence_refs=[cited(first)],
                                         policy_refs=[policy]).ok


def test_missing_fulfillment_and_shipment_cannot_be_inferred_as_unshipped():
    body = order_body()
    del body["fulfillment_status"]
    del body["fulfillment_version"]
    source = get_order_context(client_for(body), context())
    assert source.result.get("fulfillment_status") is None
    assert not check("REFUND", [source]).ok
    assert not check("REJECT", [source]).ok


def test_logistics_rejection_still_requires_known_shipment_and_policy():
    assert not check("REJECT", [order(fulfillment_status="IN_TRANSIT", fulfillment_version=2)], "R-SIGNED-001").ok
    shipment = observation(tool="get_shipment_trace", observation_id="shipment", source_ref="shipment:1",
                           result={"status": "SIGNED", "carrier_conclusion": "DELIVERED"})
    assert check("REJECT", [order(fulfillment_status="DELIVERED", fulfillment_version=3), shipment],
                 "R-SIGNED-001").ok


def test_shipped_fact_rules_out_unshipped_policy_but_does_not_justify_denial_of_the_whole_application():
    assert not check("REJECT", [order(fulfillment_status="IN_TRANSIT", fulfillment_version=2)]).ok


@pytest.mark.parametrize("tool,result", [
    ("get_shipment_trace", {"status": "IN_TRANSIT", "carrier_conclusion": "IN_TRANSIT"}),
    ("get_refund_status", {"state": "EXECUTION_PENDING"}),
    ("get_refund_status", {"state": "CONSUMED"}),
])
def test_a_new_conflicting_trace_or_refund_slot_cannot_be_hidden_by_omitting_its_citation(tool, result):
    first = order()
    hidden = observation(tool=tool, observation_id="hidden", source_ref="commerce:other-facts", result=result)
    policy = {**POLICY, "rule_id": "R-UNSHIPPED-001"}
    verifier = ProposalVerifier([first, hidden, search(policy)], frozenset({POLICY["bundle_id"]}))
    assert not verifier.verify_citations(recommended_action="REFUND", evidence_refs=[cited(first)],
                                         policy_refs=[policy]).ok


def test_no_extra_model_permissions_or_input_mutation():
    body = order_body()
    before = json.dumps(body, sort_keys=True)
    get_order_context(client_for(body), context())
    assert json.dumps(body, sort_keys=True) == before
