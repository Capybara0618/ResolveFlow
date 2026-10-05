"""Calibration follows Java projections, and old malformed responses stay negative tests."""

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from resolveflow.tools.result_validation import InvalidToolResult  # noqa: E402
from scripts.evaluation.build_calibration import build, validate_projection  # noqa: E402
from scripts.evaluation.dataset import ALIGNED_DATA, read, validate  # noqa: E402
from scripts.evaluation.scoring import score_agent  # noqa: E402


def test_calibrated_profile_is_an_immutable_fork(tmp_path):
    dest = tmp_path / "v3"
    build(dest)
    assert validate(dest)["agent_cases"] == 32
    old_gold = read("gold/agent.json", ALIGNED_DATA)
    new_gold = read("gold/agent.json", dest)
    for key in old_gold:
        if key != "A04B":
            assert old_gold[key] == new_gold[key]
    for case in read("agent/cases.json", dest):
        validate_projection(case)
    with pytest.raises(ValueError, match="immutable"):
        build(dest)


@pytest.mark.parametrize("identifier", ["A03B", "A04B", "A07B", "A16B"])
def test_original_malformed_sources_are_rejected_not_normalized(identifier):
    case = next(c for c in read("agent/cases.json", ALIGNED_DATA) if c["id"] == identifier)
    with pytest.raises(InvalidToolResult):
        validate_projection(case)


def test_missing_source_gold_requires_the_exact_observed_failure():
    gold = {"allowed_actions": ["MANUAL_REVIEW"], "forbidden_actions": ["REFUND"],
            "must_tools": [], "must_rules": [],
            "must_read_errors": [{"tool": "get_order_context", "code": "NOT_FOUND"}]}
    result = SimpleNamespace(completed=True, decision=SimpleNamespace(kind="ESCALATE"), observations=[])
    assert not score_agent(result, gold)["joint_correct"]
    failed = SimpleNamespace(observation_id="o", tool_name="get_order_context",
                             error=SimpleNamespace(code="UPSTREAM_UNAVAILABLE"))
    result.observations = [failed]
    assert not score_agent(result, gold)["joint_correct"]
    failed.error.code = "NOT_FOUND"
    assert score_agent(result, gold)["joint_correct"]
    result.decision = SimpleNamespace(kind="PROPOSE", recommended_action="REFUND")
    assert not score_agent(result, gold)["joint_correct"]


def test_incorrect_slot_is_caught_before_mcp_or_model_calls(tmp_path):
    dest = tmp_path / "v3"
    build(dest)
    case = deepcopy(read("agent/cases.json", dest)[0])
    case["backend"]["order"]["line_refund_state"] = "UNKNOWN"
    with pytest.raises(InvalidToolResult):
        validate_projection(case)


def test_all_preserved_malformed_fixtures_still_fail_the_production_contract(tmp_path):
    dest = tmp_path / "v3"
    build(dest)
    negatives = read("harness/malformed-v2.json", dest)
    assert len(negatives) == 16
    for row in negatives:
        with pytest.raises(InvalidToolResult):
            validate_projection(row["original_case"])
