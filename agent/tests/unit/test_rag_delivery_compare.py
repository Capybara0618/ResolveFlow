import pytest
from scripts.rag_delivery_compare import compare, metrics, semantic_metrics


def test_incomplete_and_protocol_failures_are_unassessed_not_passes():
    review = {"results": [
        {"id": "a", "status": "VALIDATED_MODEL_JUDGMENT", "mapping": {"X": "candidate", "Y": "baseline"},
         "judgment": {"evaluations": [{"candidate": "X", "factual_support": True, "policy_application": False,
                                       "action_reason_alignment": True}]}},
        {"id": "b", "status": "ERROR", "mapping": {"X": "baseline", "Y": "candidate"}, "judgment": None},
    ]}
    result = semantic_metrics(review)
    assert result["baseline"]["validated_judgment_denominator"] == 0
    assert result["candidate"]["validated_judgment_denominator"] == 1
    assert result["candidate"]["all_three_passed"] == 0
    assert result["candidate"]["uncertainty_unspecified"] == 1
    assert len(result["candidate"]["unassessed"]) == 1


def test_unknown_provider_usage_is_not_reported_as_zero_cost():
    report = {"summary": {}, "results": [{"completed": True, "joint_correct": True, "requests": [
        {"usage": {"estimated": False, "input_tokens": 100, "output_tokens": 10}},
        {"usage": {"estimated": True, "input_tokens": 999, "output_tokens": 99}},
    ]}]}
    result = metrics(report)
    assert result["provider_input_tokens"] == 100
    assert result["requests_without_provider_usage"] == 1


def test_configuration_changes_refuse_controlled_comparison():
    before = {"state": "FINISHED", "mode": "live", "manifest_hash": "same", "evaluation_config": {"calls": 12}}
    after = {**before, "evaluation_config": {"calls": 6}}
    with pytest.raises(ValueError, match="evaluation_config"):
        compare(before, after, {})
