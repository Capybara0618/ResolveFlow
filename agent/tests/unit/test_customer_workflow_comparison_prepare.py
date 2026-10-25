"""Business scoring does not require the baseline to implement Agent state or prompts."""

from copy import deepcopy

import pytest
from scripts.customer_workflow_comparison_prepare import (
    audit,
    load_dataset,
    review_template,
    summarize,
)


def fixture():
    data = {"version": "test-v2", "cases": [
        {"id": "C", "complex": True, "family": "correction", "turns": [
            {"expected_artifact": "HANDOFF", "business_expectations": ["当前故障草稿"]},
            {"expected_artifact": "HANDOFF", "business_expectations": ["更正后故障草稿"]}]},
        {"id": "O", "complex": False, "family": "ordinary", "turns": [
            {"expected_artifact": "NONE", "business_expectations": ["正确解释流程"]}]}]}
    rows = [{"case_id": c["id"], "variant": v, "turn": i + 1, "run_id": f"{c['id']}-{v}-{i}",
        "status": "SUCCEEDED", "answer": {"text": "回答", "handoff_summary": "待确认草稿"
            if t["expected_artifact"] == "HANDOFF" else None}, "tools": [{"category": "ORDER"}],
        "models": [{"usage": {"input_tokens": 10, "output_tokens": 5}}], "elapsed_ms": 30}
        for c in data["cases"] for v in ("agent", "basic_workflow") for i, t in enumerate(c["turns"])]
    runtime = {"version": data["version"], "dataset_sha256": "dataset", "state": "FINISHED", "rows": rows}
    review = review_template(data, runtime, "dataset")
    for label in review["rows"]:
        label.update(checks={"correctness": True, "completion": True, "context": True}, evidence="来源与对话已审")
    return data, runtime, review


def test_real_data_keeps_all_inputs_but_uses_only_customer_visible_rubrics():
    data = load_dataset()
    report = audit()
    assert report["cases"] == 32 and report["customer_inputs"] == 50
    assert report["complex_cases"] == 24 and report["planned_customer_turns"] == 100
    assert not report["baseline_implemented"] and not report["quality_measured"]
    q25 = next(c for c in data["cases"] if c["id"] == "Q25")["turns"][0]
    assert "不强制调用物流" in q25["business_expectations"][0]
    assert "required_sources" not in q25 and "criteria" not in q25


def test_neutral_baseline_answers_need_no_agent_state_to_pass():
    data, runtime, review = fixture()
    result = summarize(data, runtime, review, "dataset")
    assert result["groups"]["basic_workflow"]["completed"] == 2
    assert result["complex_improvement_percentage_points"] == 0
    assert all("task_state" not in r["answer"] for r in runtime["rows"])


def test_old_protocol_and_other_dataset_results_cannot_be_mixed_in():
    data, runtime, _ = fixture()
    for field, value in (("version", "customer-quantification-v1"), ("dataset_sha256", "other")):
        wrong = deepcopy(runtime)
        wrong[field] = value
        with pytest.raises(ValueError, match="identity/state"):
            review_template(data, wrong, "dataset")


def test_failed_turn_fails_conversation_and_keeps_all_attempt_costs():
    data, runtime, review = fixture()
    row = next(r for r in runtime["rows"] if r["case_id"] == "C" and r["variant"] == "agent" and r["turn"] == 2)
    row.update(status="FAILED", answer=None, tools=[{"category": "SHIPMENT"}] * 2, models=[{}] * 3)
    with pytest.raises(ValueError, match="failed publication"):
        summarize(data, runtime, review, "dataset")
    next(r for r in review["rows"] if r["run_id"] == row["run_id"])["checks"]["completion"] = False
    result = summarize(data, runtime, review, "dataset")
    assert result["groups"]["agent"]["complex_completed"] == 0
    assert result["groups"]["agent"]["model_requests"] == 5
    assert result["groups"]["agent"]["mean_business_http_all_conversations"] == 2


@pytest.mark.parametrize("replacement", [None, "", "   "])
def test_claiming_a_draft_without_actual_draft_cannot_pass(replacement):
    data, runtime, review = fixture()
    runtime["rows"][0]["answer"]["handoff_summary"] = replacement
    with pytest.raises(ValueError, match="artifact"):
        summarize(data, runtime, review, "dataset")


def test_unrequested_or_wrong_draft_cannot_be_marked_successful():
    data, runtime, review = fixture()
    runtime["rows"][-1]["answer"]["refund_summary"] = "误附退款"
    with pytest.raises(ValueError, match="artifact"):
        summarize(data, runtime, review, "dataset")


def test_missing_results_unreviewed_labels_and_wrong_identity_are_rejected():
    data, runtime, review = fixture()
    unreviewed = review_template(data, runtime, "dataset")
    with pytest.raises(ValueError, match="unreviewed"):
        summarize(data, runtime, unreviewed, "dataset")
    wrong = deepcopy(review)
    wrong["rows"][0]["run_id"] = "another"
    with pytest.raises(ValueError, match="identity"):
        summarize(data, runtime, wrong, "dataset")
    runtime["rows"].pop()
    with pytest.raises(ValueError, match="matrix"):
        review_template(data, runtime, "dataset")


def test_timeouts_and_unrun_cases_remain_in_denominator():
    data, runtime, review = fixture()
    for status, variant in (("TIMEOUT", "agent"), ("NOT_RUN", "basic_workflow")):
        row = next(r for r in runtime["rows"] if r["variant"] == variant and r["case_id"] == "O")
        row.update(status=status, answer=None)
        next(r for r in review["rows"] if r["run_id"] == row["run_id"])["checks"]["completion"] = False
    result = summarize(data, runtime, review, "dataset")
    assert all(g["conversations"] == 2 and g["completed"] == 1 for g in result["groups"].values())
