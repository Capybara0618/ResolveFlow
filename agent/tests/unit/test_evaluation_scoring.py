from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.evaluation.harness_checks import evidence_ref, order_observation, policy_observation  # noqa: E402
from scripts.evaluation.scoring import score_agent, score_rag  # noqa: E402


def test_always_manual_does_not_pass_clear_refund_case():
    result = SimpleNamespace(
        completed=True,
        decision=SimpleNamespace(recommended_action="MANUAL_REVIEW", kind="PROPOSE", evidence_refs=[], policy_refs=[]),
        observations=[],
    )
    scored = score_agent(
        result,
        {
            "allowed_actions": ["REFUND"],
            "forbidden_actions": ["REJECT"],
            "must_tools": ["get_order_context"],
            "must_rules": ["R-UNSHIPPED-001"],
        },
    )
    assert not scored["action_correct"] and not scored["joint_correct"]


def test_correct_action_without_cited_evidence_does_not_pass():
    result = SimpleNamespace(
        completed=True,
        decision=SimpleNamespace(recommended_action="REFUND", kind="PROPOSE", evidence_refs=[], policy_refs=[]),
        observations=[SimpleNamespace(observation_id="one", tool_name="get_order_context", error=None)],
    )
    scored = score_agent(
        result,
        {"allowed_actions": ["REFUND"], "forbidden_actions": [], "must_tools": ["get_order_context"], "must_rules": []},
    )
    assert scored["action_correct"] and not scored["joint_correct"]
    assert scored["missing_cited_tools"] == ["get_order_context"]


def test_rag_multi_rule_and_wrong_scope_are_not_hidden():
    pin = {"manifest_hash": "bound"}
    query = {"bundle_id": "b1", "merchant_id": "m1"}
    hit = SimpleNamespace(rule_id="rule1", bundle_id="b2", merchant_id="m2", manifest_hash="wrong")
    scored = score_rag([hit], query, {"must_rules": ["rule1", "rule2"]}, pin)
    assert scored["coverage_at_1"] == 0.5 and not scored["all_required_at_5"]
    assert scored["violations"] == 1


def test_negative_query_is_not_counted_as_successful_positive():
    scored = score_rag([], {"bundle_id": "b", "merchant_id": "m"}, {"must_rules": []}, {"manifest_hash": "h"})
    assert scored["coverage_at_5"] is None
    assert not scored["negative_returned_candidates"]


def _supported_result():
    order, policy = order_observation(), policy_observation()
    hit = policy.result["hits"][0]
    decision = SimpleNamespace(
        recommended_action="REFUND",
        kind="PROPOSE",
        evidence_refs=[SimpleNamespace(**evidence_ref(order))],
        policy_refs=[
            SimpleNamespace(**{k: hit[k] for k in ("bundle_id", "version", "rule_id", "chunk_id", "content_hash")})
        ],
    )
    return SimpleNamespace(completed=True, decision=decision, observations=[order, policy])


GOLD = {
    "allowed_actions": ["REFUND"],
    "forbidden_actions": ["REJECT"],
    "must_tools": ["get_order_context"],
    "must_rules": ["R-UNSHIPPED-001"],
}


def test_real_sources_and_exact_citations_can_pass():
    assert score_agent(_supported_result(), GOLD)["joint_correct"]


def test_fabricated_evidence_hash_cannot_pass_correct_action():
    result = _supported_result()
    result.decision.evidence_refs[0].content_hash = "0" * 64
    scored = score_agent(result, GOLD)
    assert scored["action_correct"] and not scored["joint_correct"]
    assert scored["citation_errors"]


def test_policy_rule_id_with_wrong_version_cannot_pass():
    result = _supported_result()
    result.decision.policy_refs[0].version = "outdated"
    scored = score_agent(result, GOLD)
    assert not scored["joint_correct"] and scored["missing_rules"] == ["R-UNSHIPPED-001"]
