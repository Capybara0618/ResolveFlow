"""Saved real failure regression and normal merchant verification handoff through the SDK."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from resolveflow.contracts.core_models import ToolObservation
from resolveflow.harness.correction import feedback
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.harness.vocabulary import RunFacts
from resolveflow.runtime.worker import verified_callback
from tests.conftest import input_text_of
from tests.unit.test_context_builder import build
from tests.unit.test_harness_loop import StubTools

ROOT = Path(__file__).resolve().parents[3]
SAVED = ROOT / "agent/tests/fixtures/regressions/chat-refund-live-v1/manual-continuation"


def saved():
    report = json.loads((SAVED / "runtime-results.json").read_text(encoding="utf-8"))
    diagnostic = json.loads((SAVED / "diagnostic.json").read_text(encoding="utf-8"))
    row = report["general_runs"][0]
    facts = RunFacts(**{key: row[key] for key in (
        "run_id", "case_id", "input_revision", "line_id", "merchant_id", "customer_id", "policy_manifest",
        "review_context")}, description=row["request_description"])
    observations = {r["observation"]["tool_name"]: ToolObservation.model_validate_json(json.dumps(r["observation"]))
                    for r in diagnostic["agent_tool_call"]}
    decisions = [r["response"]["decision"] for r in report["model_attempt_records"]]
    return facts, observations, decisions


def test_verification_refusal_names_normal_manual_proposal_and_the_responsible_party():
    value = feedback("INVESTIGATION_FACTS_REQUIRED", "缺少CONFIRMED核验", repair=True)
    assert value["category"] == "FACT"
    assert "MANUAL_REVIEW" in value["next_step"] and "商家" in value["next_step"]
    assert value["repair_remaining"] == 1


def test_actual_context_explains_missing_human_verification_without_authorizing_a_refund():
    facts, observations, _ = saved()
    text = "\n".join(m["content"] for m in build(observations=list(observations.values()),
        review_context=facts.review_context, tool_schema={"reference_format": "run-short-v1"}).messages)
    assert "MANUAL_REVIEW" in text and "商家核验" in text
    assert "CONFIRMED" in text


@pytest.mark.parametrize("repaired", [True, False])
def test_saved_refund_failure_keeps_one_repair_and_can_publish_a_normal_manual_review(repaired):
    facts, observations, decisions = saved()
    original = deepcopy(decisions)

    class Index:
        def generation_for(self, *_args):
            return SimpleNamespace(generation_id="11111111-1111-4111-8111-111111111111")

        def search(self, **_kwargs):
            return [SimpleNamespace(**hit) for hit in observations["search_policy"].result["hits"]]

    manual = {"kind": "PROPOSE", "case_type": "LOGISTICS", "recommended_action": "MANUAL_REVIEW",
              "reason_codes": ["NEEDS_HUMAN_VERIFICATION"],
              "summary": "承运商记录为丢失；客户未收到的陈述尚待商家核验，请在材料区核对并登记结论后继续处理。",
              "evidence_refs": ["O1", "O2", "O4"], "policy_refs": ["P1"],
              "missing_evidence": ["商家对本案客户陈述的关联核验记录"]}
    script = [*decisions[:-1], manual if repaired else decisions[-1]]
    class TokenizedModel(MockModelClient):
        provider = "deepseek"
        model_id = "deepseek-flash"

    model = TokenizedModel(script=script)
    tools = StubTools(*(observations[name] for name in (
        "get_order_context", "get_shipment_trace", "get_case_evidence")))
    runner = AgentScopeRunner(model=model, tools=tools, facts=facts, policy_index=Index())
    result = runner.run()
    assert model.calls == 6 and len(tools.calls) == 3, (result.reason_code, result.notices, result.trajectory)
    assert "MANUAL_REVIEW" in input_text_of(model) and "商家核验" in input_text_of(model)
    if repaired:
        assert result.completed and result.decision.recommended_action == "MANUAL_REVIEW"
        kind, _, payload, checked = verified_callback(SimpleNamespace(facts=facts), result)
        assert kind.value == "PROPOSAL" and checked.completed
        assert payload["recommended_action"] == "MANUAL_REVIEW"
    else:
        assert not result.completed and result.reason_code == "INVESTIGATION_FACTS_REQUIRED"
    assert decisions == original
