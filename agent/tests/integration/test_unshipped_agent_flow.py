"""SDK loop + PG policy index + real order tool adapter, scripted model only."""
from dataclasses import replace

import pytest

from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.policies import PolicyIndex, ServedBundle
from tests.conftest import input_text_of
from tests.unit.test_agent_order_facts import order
from tests.unit.test_context_quality import cited
from tests.unit.test_harness_loop import FACTS


@pytest.mark.parametrize("state,expected", [("NOT_SHIPPED", "REFUND"), ("IN_TRANSIT", "MANUAL_REVIEW")])
def test_only_needed_facts_and_retrieved_policy_drive_a_bounded_proposal(agent_db, stub_embedder, state, expected):
    bundle = ServedBundle(bundle_id="synthetic-unshipped-policy", merchant_id=FACTS.merchant_id, version="v1",
                          manifest_hash="b" * 64, safety_epoch=1, rules=[{
                              "rule_id": "R-UNSHIPPED-001", "title": "已付款未发货",
                              "text": "订单已付款且明确未发货，可申请该订单行实付全额退款；未知或已发货需另行核对。"}])
    index = PolicyIndex(agent_db)
    index.build(bundle, embedder=stub_embedder)
    pin = {"merchant_id": bundle.merchant_id, "bundle_ids": [bundle.bundle_id],
           "manifest_hash": bundle.manifest_hash, "safety_epoch": bundle.safety_epoch}
    hit = index.search(merchant_id=bundle.merchant_id, bundle_ids=[bundle.bundle_id],
                       manifest_hash=bundle.manifest_hash,
                       query="已付款 未发货", path="dense", embedder=stub_embedder, top_k=1)[0]
    source = order(fulfillment_status=state, fulfillment_version=1 if state == "NOT_SHIPPED" else 2)

    class Tools:
        def __init__(self):
            self.calls = []

        def call_tool(self, *, run_id, tool_name, arguments):
            self.calls.append(tool_name)
            assert tool_name == "get_order_context" and arguments == {}
            return source

        def note_trace_page(self):
            raise AssertionError("No trace needed in this scenario")

        def close(self):
            pass

    proposed = {"kind": "PROPOSE", "case_type": "LOGISTICS", "recommended_action": "REFUND",
                "reason_codes": ["UNSHIPPED_PAYMENT"], "summary": "依据付款与履约申请整行退款",
                "evidence_refs": [cited(source)], "policy_refs": [hit.citation()]}
    model = MockModelClient(script=[{"kind": "READ_TOOL", "tool_name": "get_order_context", "arguments": {}},
                                   {"kind": "SEARCH_POLICY", "query": "已付款 未发货", "arguments": {"top_k": 1}},
                                   proposed, {"kind": "PROPOSE", "case_type": "LOGISTICS",
                                              "recommended_action": "MANUAL_REVIEW", "reason_codes": ["CHANGED"]}])
    tools = Tools()
    result = AgentScopeRunner(model=model, tools=tools, facts=replace(FACTS, policy_manifest=pin),
                              policy_index=index, policy_embedder=stub_embedder).run()
    assert result.completed and result.decision.recommended_action == expected
    assert tools.calls == ["get_order_context"]
    assert model.calls == (3 if state == "NOT_SHIPPED" else 4)
    assert "order_fulfillment_status=" + state in input_text_of(model, 2)
    assert bundle.rules[0]["text"] in input_text_of(model, 2)
    if state != "NOT_SHIPPED":
        assert "UNSHIPPED_FACTS_REQUIRED" in input_text_of(model, 3)
