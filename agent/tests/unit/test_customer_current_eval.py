"""Measurement fidelity, not assertions that a live model must answer fixture keywords."""

from copy import deepcopy

import httpx
import pytest
from scripts import customer_current_eval as runner

from resolveflow.harness.live_model import ModelUnavailableError
from tests.unit.test_customer_agent_eval_v2 import completed


def test_failed_accepted_update_survives_without_an_assistant_message_or_gold():
    case = runner.load_cases()[12]
    first, _ = runner.prepare_turn(case, 0, [])
    actual = completed(first)
    second, _ = runner.prepare_turn(case, 1, [actual])
    later = completed(second)
    later["answer"]["task_state"]["tasks"] = [{"task_id": "pause-accepted"}]
    failed = {**later, "status": "FAILED", "answer": None, "conversation_update": {
        **{k: later[k] for k in ["run_id", "conversation_id", "input_version"]}, "version": "support-state-v1",
        **later["answer"],
    }}
    third, archive = runner.prepare_turn(case, 2, [actual, failed])
    assert third.context["previous_tasks"]["tasks"] == [{"task_id": "pause-accepted"}]
    assert third.context["previous_customer_memory"] == later["answer"]["customer_memory"]
    assert len([m for m in archive if m["author"] == "ASSISTANT"]) == 1
    assert "criteria" not in str(third.model_dump())
    wrong = deepcopy(failed)
    wrong["conversation_update"]["customer_memory"]["merchant_id"] = "foreign"
    with pytest.raises(ValueError, match="memory scope"):
        runner.prepare_turn(case, 2, [actual, wrong])


def test_rejected_turn_without_state_retains_last_actual_state_and_prefix_identity():
    case = runner.load_cases()[12]
    first, _ = runner.prepare_turn(case, 0, [])
    actual = completed(first)
    second, _ = runner.prepare_turn(case, 1, [actual])
    failed = {**completed(second), "status": "FAILED", "answer": None}
    third, _ = runner.prepare_turn(case, 2, [actual, failed])
    assert third.context["previous_customer_memory"] == actual["answer"]["customer_memory"]
    with pytest.raises(ValueError, match="identity"):
        runner.prepare_turn(case, 1, [{**actual, "run_id": "foreign"}])


def test_stream_metrics_exclude_retracted_content_and_failed_answers():
    events = [
        {"kind": "answer.delta", "payload": {"text": "rejected"}, "elapsed_ms": 100},
        {"kind": "answer.reset", "payload": {}, "elapsed_ms": 110},
        {"kind": "answer.delta", "payload": {"text": "accepted"}, "elapsed_ms": 200},
    ]
    assert runner.stream_times(events, True) == {"first_provisional_ms": 100, "first_retained_ms": 200, "resets": 1}
    assert runner.stream_times(events, False)["first_retained_ms"] is None
    assert runner.stream_times(events[:2], True)["first_retained_ms"] is None


def test_recorded_stream_is_actual_stream_class_and_counts_failure_without_retry():
    usage = {"used": 0, "save": lambda: None}
    snapshots, requests = [], []

    def transport(call):
        requests.append(call)
        return httpx.Response(503, content=b"unavailable")

    model = runner.RecordedStreamingModel(usage=usage, save=lambda rows: snapshots.append(deepcopy(rows)),
        provider="deepseek", model_id="deepseek-flash", endpoint="https://frozen-provider.local/completions",
        stream_transport=httpx.MockTransport(transport))
    assert isinstance(model, runner.StreamingLiveModelClient)
    with pytest.raises(ModelUnavailableError):
        model.decide(system="frozen", messages=[], max_output_tokens=20)
    assert usage["used"] == len(requests) == len(model.records) == 1
    assert snapshots[0][0]["state"] == "STARTED" and snapshots[-1][0]["state"] == "ERROR"
    assert snapshots[0][0]["body"]["stream"] is True


def test_measured_source_keeps_optional_subqueries(monkeypatch):
    seen = []
    monkeypatch.setattr(runner.BoundSources, "search", lambda self, query, top_k, **kwargs: seen.append(kwargs) or [])
    request, _ = runner.prepare_turn(runner.load_cases()[0], 0, [])
    with httpx.Client() as client:
        sources = runner.MeasuredSources(request, case_url="http://frozen-case.local", token="local", client=client,
                                         records=[])
        sources.search("q", 3, sub_queries=["q1", "q2"])
        assert seen == [{"sub_queries": ["q1", "q2"]}]
        assert sources.records[0]["sub_queries"] == ["q1", "q2"]
