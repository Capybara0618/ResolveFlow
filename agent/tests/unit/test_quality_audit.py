"""Incomplete investigations and estimated counts must not become accuracy/usage successes."""

from copy import deepcopy

import pytest
from scripts.evaluation.quality_audit import ALIGNED_DATA, audit, digest


def sample():
    return {"mode": "live", "synthetic": True, "state": "FINISHED",
        "manifest_hash": digest(ALIGNED_DATA / "manifest.json"), "results": [
            {"id": "A01A", "split": "dev", "pair_id": "P01", "status": "INCOMPLETE",
             "completed": False, "action_correct": False, "joint_correct": False,
             "reason_code": "CONTEXT_REQUIRED_OVERFLOW", "model_calls": 3,
             "requests": [{"usage": {"input_tokens": 10, "output_tokens": 2, "estimated": False}},
                          {"usage": {"input_tokens": 100, "output_tokens": 20, "estimated": True}},
                          {"error": "read timeout"}]}]}


def test_incomplete_remains_in_denominator_and_usage_kinds_do_not_mix():
    result = audit(sample())
    assert result["n"] == result["incomplete"] == 1
    assert result["automatic_joint_correct"] == result["completed"] == 0
    assert result["usage"] == {"provider_input_tokens": 10, "provider_output_tokens": 2,
        "provider_usage_requests": 1, "estimated_usage_requests": 1, "missing_usage_requests": 1}
    assert result["independent_semantic_review"] == "PENDING"


@pytest.mark.parametrize("changes", [{"mode": "mock"}, {"state": "RUNNING"},
                                    {"manifest_hash": "a" * 64}, {"results": []}])
def test_audit_rejects_unfinished_or_different_source(changes):
    report = sample()
    report.update(changes)
    with pytest.raises(ValueError):
        audit(report)


def test_duplicate_cases_and_unrecorded_requests_fail():
    report = sample()
    report["results"].append(deepcopy(report["results"][0]))
    with pytest.raises(ValueError, match="denominator"):
        audit(report)
    report = sample()
    report["results"][0]["model_calls"] = 4
    with pytest.raises(ValueError, match="request count"):
        audit(report)
