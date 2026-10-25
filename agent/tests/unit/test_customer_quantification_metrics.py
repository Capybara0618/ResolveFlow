"""Success requires whole conversations and source review; failures never disappear from means."""

from copy import deepcopy

import pytest
from scripts.evaluation.customer_quantification_metrics import review_template, summarize


def fixture():
    cases = [{"id": f"Q1-{v}", "source_case_id": "Q1", "variant": v, "repeat": 1, "complex": True,
              "turns": [{"criteria": ["必须回答"], "text": "咨询"}, {"criteria": ["采纳纠正"], "text": "纠正"}]}
             for v in ("dynamic", "fixed")]
    rows = [{"id": c["id"], "turn": i + 1, "state": "FINISHED", "input": {"run_id": f"{c['id']}-{i}"},
             "result": {"status": "SUCCEEDED"}, "tools": [{"name": "get_order_context"}] * (
                 1 if c["variant"] == "dynamic" else 2), "models": [{"usage": {"input_tokens": 5,
                     "output_tokens": 2, "estimated": False}}], "elapsed_ms": 10}
            for c in cases for i in range(2)]
    return cases, {"state": "FINISHED", "rows": rows}


def test_unreviewed_or_missing_results_cannot_emit_a_success_percentage():
    cases, result = fixture()
    labels = review_template(result, cases)
    with pytest.raises(ValueError, match="unreviewed"):
        summarize(result, cases, labels)
    result["rows"].pop()
    with pytest.raises(ValueError, match="incomplete"):
        review_template(result, cases)


def test_one_failed_turn_fails_the_whole_conversation_and_keeps_costs_in_denominator():
    cases, result = fixture()
    review = review_template(result, cases)
    for label in review["rows"]:
        label.update({"pass": True, "evidence": "逐项来源审查通过"})
    result["rows"][1]["result"]["status"] = "FAILED"
    with pytest.raises(ValueError, match="failed publication"):
        summarize(result, cases, review)
    review["rows"][1]["pass"] = False
    report = summarize(result, cases, review)
    assert report["groups"]["dynamic"]["completed"] == 0
    assert report["groups"]["dynamic"]["mean_business_http_all_runs"] == 2
    assert report["business_http_reduction_all_runs"] == .5
    assert report["complex_improvement_percentage_points"] == -100
    assert report["both_completed_pairs"] == 0 and report["provider_attempts"] == 4


def test_duplicate_or_wrong_identity_reviews_are_not_accepted():
    cases, result = fixture()
    review = review_template(result, cases)
    for label in review["rows"]:
        label.update({"pass": True, "evidence": "source"})
    review["rows"][0]["run_id"] = "another-run"
    with pytest.raises(ValueError, match="identity"):
        summarize(result, cases, review)
    review["rows"].append(deepcopy(review["rows"][-1]))
    with pytest.raises(ValueError, match="denominator"):
        summarize(result, cases, review)
