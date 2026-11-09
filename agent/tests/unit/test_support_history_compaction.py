"""Inspect provider payloads across all three history layouts."""

import json

import httpx
import pytest

from resolveflow.harness.budget import RunBudget
from resolveflow.harness.streaming_model import StreamingLiveModelClient
from resolveflow.harness.token_counting import counter_for
from resolveflow.support.context import read_context
from resolveflow.support.engine import SupportAgent
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import request
from tests.unit.test_support_orchestrated_engine import Sources
from tests.unit.test_support_orchestration import plan


class HistoryCounter:
    def __init__(self, layout):
        self.layout = layout

    def count(self, body):
        packet = json.loads(body["messages"][-1]["content"])
        history = packet.get("history", {})
        rows = {row["read_ref"]: row for row in history.get("messages", [])}
        over = ((self.layout == "trim" and "text" in rows.get("H4", {}))
                or (self.layout in {"compact", "oversized_summary"} and "H3" in rows)
                or (self.layout == "oversized_summary" and history.get("summary"))
                or (self.layout == "protected" and bool(rows)))
        return 8192 if over else 100


def history_case():
    req = request(input_version=16)
    texts = [
        ("ASSISTANT", "头" * 25 + "中" * 60 + "尾" * 25),
        ("ASSISTANT", "恰" * 100),
        ("CUSTOMER", "我问过代收点。" + "其他情况" * 30),
        ("ASSISTANT", "较早客服" * 30),
        ("MERCHANT", "商家" * 55),
        ("ASSISTANT", "最近客服" * 30),
        *[("CUSTOMER", f"短消息{n}") for n in range(7, 16)],
        ("CUSTOMER", req.context["current_request"]),
    ]
    req.context["history"] = [{"sequence": n, "author": author, "recipient": "CUSTOMER", "text": text}
                              for n, (author, text) in enumerate(texts, 1)]
    req.context["history_before"] = 1
    opening = plan(req, intent="OTHER", goal="EXPLAIN").model_dump()
    opening["focus"][0]["context_refs"] = ["H1"]
    return req, [opening, {"kind": "RESPOND", "parts": [{"task_id": "trace", "text": "已了解。"}]}]


@pytest.mark.parametrize("layout", ["full", "trim", "compact"])
def test_only_escalates_when_previous_history_layout_exceeds_budget(monkeypatch, layout):
    monkeypatch.setattr("resolveflow.support.engine.counter_for", lambda _: HistoryCounter(layout))
    req, script = history_case()
    if layout == "compact":
        def choose(packet):
            assert packet["kind"] == "HISTORY_COMPACTION"
            assert [row["read_ref"] for row in packet["messages"]] == [f"H{n}" for n in range(1, 6)]
            assert packet["messages"][0]["excerpt"] == "头" * 25
            return {"items": [{"read_ref": "H3", "quote": "我问过代收点。"}]}

        script.insert(0, choose)
    model = TokenizedScript(mode="live", script=script)
    agent = SupportAgent(req, model, Sources(), architecture="orchestrated-v1")
    result = agent.run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert model.calls == result["spend"]["model_calls"] == (3 if layout == "compact" else 2)
    understand, compose = model.sent_contexts[-2:]
    assert understand["phase"] == "UNDERSTAND" and compose["phase"] == "COMPOSE"
    history = understand["history"]
    rows = {row["read_ref"]: row for row in history["messages"]}
    assert "H16" not in rows and understand["current_request"] == req.context["current_request"]
    assert history["before"] == 1
    assert all("text" in rows[f"H{n}"] for n in range(6, 16))
    if layout == "full":
        assert all("text" in row for row in rows.values()) and len(rows) == 15
    elif layout == "trim":
        assert len(rows) == 15 and rows["H1"]["excerpt"] == "头" * 25 and rows["H1"]["tail"] == "尾" * 25
        assert all("text" in rows[ref] for ref in ("H2", "H3", "H5"))
    else:
        assert set(rows) == {f"H{n}" for n in range(6, 16)}
        assert history["read_refs"] == [f"H{n}" for n in range(1, 6)]
        assert history["summary"][0]["excerpt"] == "我问过代收点。"
        assert model.output_limits[0] == 384
    pinned = next(row for row in compose["history"]["messages"] if row["read_ref"] == "H1")
    assert pinned["text"] == req.context["history"][0]["text"]
    assert read_context(req, agent.observations, {"reference": "H3"})["data"]["text"] == (
        req.context["history"][2]["text"])


@pytest.mark.parametrize("bad", [
    {"items": [{"read_ref": "H999", "quote": "我问过代收点。"}]},
    {"items": [{"read_ref": "H3", "quote": "代收点已经确认收件。"}]},
    {"items": [{"read_ref": "H1", "quote": "头尾"}]},
])
def test_invalid_summary_fails_without_sending_a_silently_pruned_history(monkeypatch, bad):
    monkeypatch.setattr("resolveflow.support.engine.counter_for", lambda _: HistoryCounter("compact"))
    req, script = history_case()
    model = TokenizedScript(script=[bad, *script])
    result = SupportAgent(req, model, Sources(), architecture="orchestrated-v1").run()
    assert result["status"] == "FAILED" and result["reason"] == "CONTEXT_REQUIRED_OVERFLOW"
    assert model.calls == 1


@pytest.mark.parametrize("layout,limit", [("protected", 12), ("compact", 1)])
def test_skips_summary_when_protected_content_or_call_budget_cannot_fit(monkeypatch, layout, limit):
    monkeypatch.setattr("resolveflow.support.engine.counter_for", lambda _: HistoryCounter(layout))
    req, script = history_case()
    model = TokenizedScript(script=script)
    result = SupportAgent(req, model, Sources(), architecture="orchestrated-v1",
                          budget=RunBudget(model_calls=limit)).run()
    assert result["reason"] == "CONTEXT_REQUIRED_OVERFLOW" and model.calls == 0


def test_checks_actual_flash_token_budget_of_all_sent_requests():
    req, script = history_case()
    req.context["history"][2]["text"] += "historical note. " * 400
    summary = {"items": [{"read_ref": "H3", "quote": "我问过代收点。"}]}
    model = TokenizedScript(mode="live", script=[summary, *script])
    agent = SupportAgent(req, model, Sources(), architecture="orchestrated-v1", provider_capacity=5500)
    result = agent.run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    counter = counter_for(model)
    assert result["spend"]["model_calls"] == 3
    for messages, ceiling in zip(model.conversations, model.output_limits, strict=True):
        body = {"messages": [{"role": str(m.role), "content": m.get_content_blocks()[0].text} for m in messages],
                "max_output_tokens": ceiling}
        assert counter.count(body) + 256 <= agent.input_cap


def test_still_oversized_summary_stops_before_business_request(monkeypatch):
    monkeypatch.setattr("resolveflow.support.engine.counter_for", lambda _: HistoryCounter("oversized_summary"))
    req, script = history_case()
    summary = {"items": [{"read_ref": "H3", "quote": "我问过代收点。"}]}
    model = TokenizedScript(script=[summary, *script])
    result = SupportAgent(req, model, Sources(), architecture="orchestrated-v1").run()
    assert result["reason"] == "CONTEXT_REQUIRED_OVERFLOW" and model.calls == 1


def test_streaming_compaction_sends_real_payload_without_emitting_internal_summary(monkeypatch):
    monkeypatch.setattr("resolveflow.support.engine.counter_for", lambda _: HistoryCounter("compact"))
    req, script = history_case()
    sent = []
    streamed = []

    def provider(call):
        body = json.loads(call.content)
        packet = json.loads(body["messages"][-1]["content"])
        sent.append(packet)
        if packet.get("kind") == "HISTORY_COMPACTION":
            assert body["max_tokens"] == 384
            decision = {"items": [{"read_ref": "H3", "quote": "我问过代收点。"}]}
        else:
            decision = script[0 if packet["phase"] == "UNDERSTAND" else 1]
        chunk = {"choices": [{"index": 0, "delta": {"content": json.dumps(decision, ensure_ascii=False)},
                              "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        return httpx.Response(200, text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n")

    model = StreamingLiveModelClient(endpoint="http://synthetic.invalid", model_id="deepseek-flash",
                                     stream_transport=httpx.MockTransport(provider), on_content=streamed.append)
    result = SupportAgent(req, model, Sources(), architecture="orchestrated-v1").run()
    assert result["status"] == "SUCCEEDED", result["reason"]
    assert sent[0]["kind"] == "HISTORY_COMPACTION" and len(sent) == 3
    assert [json.loads(text)["kind"] for text in streamed] == ["TURN_UNDERSTANDING", "RESPOND"]
