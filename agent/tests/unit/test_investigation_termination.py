"""Regression boundaries exposed by real-model investigation, with no paid test calls."""

import pytest
from resolveflow.harness.actions import ActionRefusedError, validate_decision
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.references import ReferenceCatalog, expand_references
from resolveflow.harness.sdk_runner import AgentScopeRunner, _tool_schema_document

from tests.conftest import input_text_of
from tests.unit.test_harness_loop import FACTS, StubTools, observation, propose, read
from tests.unit.test_proposal_verifier import EVIDENCE, RULE, search
from tests.unit.test_proposal_verifier import observation as shipment


def ask(field):
    return {"kind": "ASK_CUSTOMER", "questions": [
        {"question_id": "q1", "field": field, "prompt": "请提供该信息"}], "reason_codes": ["NEEDS_EVIDENCE"]}


@pytest.mark.parametrize("field", ["order_id", "line_id", "case_id", "merchant_id", "customer_id", "run_id"])
def test_bound_identity_question_is_repaired_before_customer_callback(field):
    model = MockModelClient(script=[ask(field), read("get_order_context"), propose("MANUAL_REVIEW")])
    tools = StubTools(observation())
    result = AgentScopeRunner(model=model, tools=tools, facts=FACTS).run()
    assert result.completed and result.decision.kind == "PROPOSE"
    assert len(tools.calls) == 1 and model.calls == 3
    assert "QUESTION_ALREADY_BOUND" in input_text_of(model, 1)


def test_repeating_invalid_identity_question_stops_after_one_repair():
    model = MockModelClient.always(ask("order_id"))
    tools = StubTools()
    result = AgentScopeRunner(model=model, tools=tools, facts=FACTS).run()
    assert not result.completed and result.reason_code == "QUESTION_ALREADY_BOUND"
    assert model.calls == 2 and tools.calls == []


def test_customer_only_information_can_be_asked_without_forcing_tool_route():
    model = MockModelClient(script=[ask("package_photo")])
    result = AgentScopeRunner(model=model, tools=StubTools(), facts=FACTS).run()
    assert result.completed and result.decision.kind == "ASK_CUSTOMER"
    assert model.calls == 1


def test_explicit_handoff_can_end_without_forcing_every_tool_read():
    model = MockModelClient(script=[{"kind": "ESCALATE", "reason_codes": ["NEEDS_HUMAN_VERIFICATION"]}])
    result = AgentScopeRunner(model=model, tools=StubTools(), facts=FACTS).run()
    assert result.completed and model.calls == 1 and result.spend.tool_attempts == 0


@pytest.mark.parametrize("payload", [
    {"type": "json_object", "action_fields": {"action": "READ_TOOL", "tool_name": "get_case_evidence"}},
    {"SEARCH_POLICY": {"query": "退款", "arguments": {"top_k": 2}}},
    {"kind": "SEARCH_POLICY", "arguments": {"query": "退款", "top_k": 2}},
])
def test_observed_provider_wrappers_are_not_silently_normalized(payload):
    with pytest.raises(ActionRefusedError):
        validate_decision(payload)


def test_advertised_flat_examples_satisfy_strict_abi():
    runner = AgentScopeRunner(model=MockModelClient(script=[]), tools=StubTools(), facts=FACTS)
    examples = _tool_schema_document(runner)["syntax_examples_only"]
    catalog = ReferenceCatalog([shipment(), search(RULE)])
    catalog.evidence(EVIDENCE)
    catalog.policy(RULE)
    assert {validate_decision(expand_references(example, catalog.references, catalog.read_ids)).kind
            for example in examples} == {
        "READ_TOOL", "SEARCH_POLICY", "READ_OBSERVATION", "ASK_CUSTOMER", "PROPOSE", "ESCALATE"}
