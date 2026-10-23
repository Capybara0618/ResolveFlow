from __future__ import annotations

import json
from typing import Any

import httpx

from resolveflow.support.progress import ProgressReporter


def test_projection_batches_real_fragments_and_repair_retracts_same_view() -> None:
    batches: list[dict[str, Any]] = []

    def send(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer progress-only"
        value = json.loads(request.content)
        batches.append(value)
        return httpx.Response(200, json={"batch_sequence": value["batch_sequence"]})

    reporter = ProgressReporter("http://synthetic.invalid", "run", "progress-only", transport=httpx.MockTransport(send))
    reporter.begin(1)
    reporter.content('{"kind":"READ_TOOL","tool_name":"get_shipment_trace"}')
    reporter.end()
    reporter.activity("SHIPMENT", True)
    reporter.activity("SHIPMENT", False)
    reporter.begin(2)
    reporter.content('{"kind":"ANSWER_PARTS","parts":[{"text":"您好，核查中')
    reporter.content('。"}]}')
    reporter.end()
    reporter.reject()
    reporter.begin(3)
    reporter.content('{"kind":"ANSWER_PARTS","parts":[{"text":"修正后的说明。"}]}')
    reporter.end()
    reporter.close()
    events = [event for batch in batches for event in batch["events"]]
    assert [b["batch_sequence"] for b in batches] == list(range(1, len(batches) + 1))
    assert [e["kind"] for e in events] == [
        "activity.started", "activity.completed", "answer.started", "answer.delta", "answer.delta",
        "answer.reset", "answer.started", "answer.delta"]
    assert events[3]["payload"]["text"] + events[4]["payload"]["text"] == "您好，核查中。"
    assert events[-1]["attempt_id"] != events[3]["attempt_id"]
    assert "progress-only" not in json.dumps(batches)


def test_broken_optional_progress_transport_does_not_retry_model_or_progress_requests() -> None:
    sent = []

    def send(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        raise httpx.ReadTimeout("synthetic progress interruption")

    reporter = ProgressReporter("http://synthetic.invalid", "run", "progress-only", transport=httpx.MockTransport(send))
    reporter.activity("ORDER", True)
    reporter.close()
    assert len(sent) == 1 and reporter.failure is not None


def test_malformed_projection_retracts_view_without_rejecting_complete_provider_usage() -> None:
    batches = []
    reporter = ProgressReporter("http://synthetic.invalid", "run", "progress-only", transport=httpx.MockTransport(
        lambda request: (batches.append(json.loads(request.content)) or httpx.Response(200))))
    reporter.begin(1)
    reporter.content('{"kind":"ANSWER_PARTS","parts":[{"text":"' + "可读正文" * 11)
    reporter.content('"}],"kind":"READ_TOOL"}')  # Duplicate kind invalidates the projection, not the provider call.
    reporter.end()
    reporter.close()
    events = [event for batch in batches for event in batch["events"]]
    assert events[0]["kind"] == "answer.started"
    assert events[-1]["kind"] == "answer.reset"
