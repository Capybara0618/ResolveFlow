import pytest
from scripts.evaluation.fixed_workflow import run_fixed

from resolveflow.harness.budget import RunBudget
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from tests.unit.test_harness_loop import FACTS, StubTools, observation, propose


def test_fixed_reads_do_not_consume_model_requests():
    model = MockModelClient(script=[{"kind": "PROPOSE", **propose("MANUAL_REVIEW")}])
    tools = StubTools(*(observation(name) for name in ("get_order_context", "get_shipment_trace", "get_case_evidence")))
    runner = AgentScopeRunner(model=model, tools=tools, facts=FACTS, budget=RunBudget())
    result = run_fixed(runner)
    assert not result.completed
    assert result.reason_code == "FIXED_QUERY_INVALID"
    assert model.calls == 1
    assert result.spend.model_calls == 1
    assert result.spend.tool_attempts == 3


@pytest.mark.parametrize("needs_correction", [False, True])
def test_fixed_query_then_terminal_and_bounded_correction(needs_correction):
    class Index:
        def search(self, **kwargs):
            return []

    script = [{"kind": "SEARCH_POLICY", "query": "物流未到退款", "arguments": {"top_k": 3}}]
    if needs_correction:
        script.append({"kind": "READ_TOOL", "tool_name": "get_refund_status", "arguments": {}})
    script.append({"kind": "ESCALATE", "reason_codes": ["NEEDS_HUMAN_VERIFICATION"], "summary": "商家核查物流记录"})
    model = MockModelClient(script=script)
    tools = StubTools(*(observation(name) for name in ("get_order_context", "get_shipment_trace", "get_case_evidence")))
    result = run_fixed(AgentScopeRunner(model=model, tools=tools, facts=FACTS, policy_index=Index()))
    assert result.completed
    assert result.decision.kind == "ESCALATE"
    assert result.spend.model_calls == 2 + needs_correction
    assert result.spend.tool_attempts == 4  # the production ledger includes the local search attempt
    assert result.spend.local_reads == 1
    assert len(tools.calls) == 3
