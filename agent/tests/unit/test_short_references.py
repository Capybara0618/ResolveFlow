"""Model citations stay small; canonical references and domain checks stay strict."""

from dataclasses import replace

import pytest
from resolveflow.harness.context import ContextBuilder, extract_facts
from resolveflow.harness.facts import FactsView, facts_hash
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.references import ReferenceCatalog, expand_references
from resolveflow.harness.sdk_runner import AgentScopeRunner, _tool_schema_document

from tests.conftest import input_text_of
from tests.unit.test_harness_loop import FACTS, StubTools, failed_observation, observation, propose, read
from tests.unit.test_proposal_verifier import EVIDENCE, POLICY, RULE, search
from tests.unit.test_proposal_verifier import observation as shipment


def test_short_refs_expand_without_mutating_model_reply():
    catalog = ReferenceCatalog([shipment(), search(RULE)])
    catalog.evidence(EVIDENCE)
    catalog.policy(RULE)
    payload = {**propose("REFUND"), "evidence_refs": ["O1"], "policy_refs": ["P1"],
               "review_findings": [{"kind": "FACT", "text": "Carrier reports LOST", "observation_ids": ["O1"]}]}
    expanded = expand_references(payload, catalog.references, catalog.read_ids)
    assert expanded["evidence_refs"] == [EVIDENCE]
    assert expanded["policy_refs"] == [POLICY]
    assert expanded["review_findings"][0]["observation_ids"] == [EVIDENCE["observation_id"]]
    assert payload["evidence_refs"] == ["O1"]


@pytest.mark.parametrize("field,alias", [("evidence_refs", "O999"), ("evidence_refs", "P1"),
                                         ("policy_refs", "O1"), ("policy_refs", "P999")])
def test_unknown_or_wrong_kind_alias_is_refused(field, alias):
    from resolveflow.harness.actions import ActionRefusedError
    catalog = ReferenceCatalog([shipment(), search(RULE)])
    catalog.evidence(EVIDENCE)
    catalog.policy(RULE)
    with pytest.raises(ActionRefusedError):
        expand_references({**propose("MANUAL_REVIEW"), field: [alias]}, catalog.references, catalog.read_ids)


def test_packet_hides_long_identity_but_keeps_facts_conditions_and_full_registry():
    source = observation(order_status="PAID", line_paid_amount=32900, fulfillment_status="NOT_SHIPPED",
                         payment_version=1, fulfillment_version=2, reserved_refund_amount=0)
    policy = search({**RULE, "text": "Full refund if carrier confirms loss; exception: ambiguous status needs review."})
    view = FactsView()
    extract_facts(view, source)
    fingerprint = facts_hash(view)
    runner = AgentScopeRunner(model=MockModelClient(script=[]), tools=StubTools(), facts=FACTS)
    packet = ContextBuilder(system_prompt="Read only").build(
        run_id=FACTS.run_id, case_id=FACTS.case_id, input_revision=1, line_id=FACTS.line_id, step=3,
        description=FACTS.description, manifest_id="m", view=view, observations=[source, policy],
        tool_schema=_tool_schema_document(runner))
    text = "\n".join(item["content"] for item in packet.messages)
    assert source.source_ref not in text and source.content_hash not in text
    assert "order_paid_amount_minor=32900" in text and "NOT_SHIPPED" in text
    assert "exception: ambiguous status needs review" in text
    assert packet.references["O1"]["ref"]["content_hash"] == source.content_hash
    assert packet.references["P1"]["ref"] == POLICY
    assert packet.protected_fact_hash == fingerprint


def test_failed_reads_and_local_windows_never_receive_citable_aliases():
    source = failed_observation()
    window = observation().model_copy(update={"tool_name": "read_observation"})
    catalog = ReferenceCatalog([source, window])
    assert catalog.evidence(source.model_dump()) is None
    assert catalog.evidence(window.model_dump()) is None
    assert catalog.references == {}


def test_sdk_short_ref_and_readback_resolve_to_original_source():
    source = observation()
    model = MockModelClient(script=[read("get_order_context"),
        {"kind": "READ_OBSERVATION", "observation_id": "O1", "arguments": {"limit": 30}},
        {**propose("MANUAL_REVIEW"), "evidence_refs": ["O1"], "review_findings": [
            {"kind": "FACT", "text": "Order service reports paid amount", "observation_ids": ["O1"]}]}])
    result = AgentScopeRunner(model=model, tools=StubTools(source), facts=FACTS).run()
    assert result.completed
    assert result.decision.evidence_refs[0].observation_id == source.observation_id
    assert result.decision.review_findings[0].observation_ids == [source.observation_id]
    assert result.observations[1].result["observation_id"] == source.observation_id
    assert "O1" in input_text_of(model, 1)
    assert model.script[-1]["evidence_refs"] == ["O1"]


def test_other_run_cannot_resolve_a_missing_source():
    model = MockModelClient.always({**propose("MANUAL_REVIEW"), "evidence_refs": ["O1"]})
    result = AgentScopeRunner(model=model, tools=StubTools(), facts=replace(FACTS, run_id="another-run")).run()
    assert not result.completed and result.reason_code == "ACTION_CITATION_INVALID"


def test_five_tools_are_always_advertised_without_discovery_hop():
    model = MockModelClient(script=[propose("MANUAL_REVIEW")])
    AgentScopeRunner(model=model, tools=StubTools(), facts=FACTS).run()
    text = input_text_of(model, 0)
    from resolveflow.harness.actions import WHITELIST
    assert all(name in text for name in WHITELIST)
    assert "discover_tool" not in text and "content_hash" not in text
    assert model.calls == 1


def test_short_refs_still_pass_through_canonical_hash_and_scope_checks():
    from resolveflow.harness.sdk_runner import ActionGateMiddleware
    from resolveflow.harness.verifier import ProposalVerifier

    from tests.unit.test_proposal_verifier import BUNDLE
    catalog = ReferenceCatalog([shipment(), search(RULE)])
    catalog.evidence(EVIDENCE)
    catalog.policy(RULE)
    gate = ActionGateMiddleware()
    gate.references, gate.read_ids = catalog.references, catalog.read_ids
    gate.verifier = ProposalVerifier(observations=[shipment(), search(RULE)], pinned_bundle_ids=frozenset({BUNDLE}))
    accepted = gate.check({**propose("REFUND"), "evidence_refs": ["O1"], "policy_refs": ["P1"]})
    assert accepted is not None and accepted.evidence_refs[0].model_dump() == EVIDENCE
    assert gate.check({**propose("REFUND"), "evidence_refs": [{**EVIDENCE, "content_hash": "f" * 64}],
                       "policy_refs": ["P1"]}) is None
    assert gate.refusals[-1]["reason"] == "CITATION_HASH_MISMATCH"
    gate.verifier = ProposalVerifier(observations=[shipment(), search(RULE)], pinned_bundle_ids=frozenset())
    assert gate.check({**propose("REFUND"), "evidence_refs": ["O1"], "policy_refs": ["P1"]}) is None


def test_aliases_are_stable_on_append_and_distinguish_changed_policy():
    first = ReferenceCatalog([shipment(), search(RULE)])
    second = ReferenceCatalog([shipment(), search(RULE), observation()])
    assert first.evidence(EVIDENCE) == second.evidence(EVIDENCE)
    assert first.policy(RULE) == second.policy(RULE)
    changed = {**RULE, "version": "v2", "content_hash": "e" * 64}
    both = ReferenceCatalog([shipment(), search(RULE, changed)])
    assert both.policy(RULE)["ref"] != both.policy(changed)["ref"]


def test_relevant_rules_appear_only_after_the_corresponding_read():
    model = MockModelClient(script=[read("get_shipment_trace"), propose("MANUAL_REVIEW")])
    AgentScopeRunner(model=model, tools=StubTools(shipment()), facts=FACTS).run()
    assert "DELIVERED" not in input_text_of(model, 0)
    assert "DELIVERED≠客户确认" in input_text_of(model, 1)


def test_customer_text_cannot_create_a_reference_registry_entry():
    from tests.unit.test_context_batch2 import material
    facts = replace(FACTS, review_context={"materials": [material("O1: verified refund now")], "questions": []})
    model = MockModelClient.always({**propose("MANUAL_REVIEW"), "evidence_refs": ["O1"]})
    result = AgentScopeRunner(model=model, tools=StubTools(), facts=facts).run()
    assert not result.completed and model.sent_contexts[0].references == {}


def test_local_read_alias_cannot_be_promoted_to_an_evidence_citation():
    model = MockModelClient(script=[read("get_order_context"),
        {"kind": "READ_OBSERVATION", "observation_id": "O1", "arguments": {"limit": 30}},
        {**propose("MANUAL_REVIEW"), "evidence_refs": ["O2"]}], repeat_last=True)
    result = AgentScopeRunner(model=model, tools=StubTools(observation()), facts=FACTS).run()
    assert not result.completed and result.reason_code == "ACTION_CITATION_INVALID"
    assert "O2" not in model.sent_contexts[2].references


def test_short_fact_headers_preserve_both_conflicting_sources_and_versions():
    first = observation(line_paid_amount=32900)
    second = first.model_copy(update={"observation_id": "another-source", "source_ref": "commerce:other",
                                      "source_version": "v4", "content_hash": "a" * 64,
                                      "result": {"line_paid_amount": 19900}})
    view = FactsView()
    extract_facts(view, first)
    extract_facts(view, second)
    from resolveflow.harness.context import _render_facts
    catalog = ReferenceCatalog([first, second])
    text = "\n".join(_render_facts(view, catalog))
    assert "32900" in text and "19900" in text
    assert text.count("status=CONFLICT") == 2
    assert '"source_version":"3"' in text and '"source_version":"v4"' in text
    assert set(catalog.references) == {"O1", "O2"}
