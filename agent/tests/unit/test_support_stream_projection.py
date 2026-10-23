"""Candidate body projection, not final domain approval or a persisted answer."""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest

from resolveflow.harness.streaming_model import StreamingLiveModelClient
from resolveflow.support.stream_projection import AnswerDelta, AnswerProjection, ProjectionError


def bodies(deltas: list[AnswerDelta]) -> str:
    return "".join(delta.text for delta in deltas)


def test_partial_string_emits_body_before_closing_json_or_provider_tail() -> None:
    projection = AnswerProjection()
    first = projection.feed('{"kind":"ANSWER_PARTS","parts":[{"task_id":"t1","text":"我先帮您核查')
    assert first == [AnswerDelta("part-0", 0, "我先帮您核查")]
    second = projection.feed('物流。","status":"ANSWERED","citations":["O1"]}]}')
    assert second == [AnswerDelta("part-0", len("我先帮您核查"), "物流。")]
    projection.finish()


@pytest.mark.parametrize("escaped", [False, True])
def test_every_split_handles_quotes_backslashes_newlines_unicode_and_surrogate_pairs(escaped: bool) -> None:
    text = '中文😀："您好"\\材料\n可以继续。'
    raw = json.dumps({"kind": "ANSWER_PARTS", "parts": [{"text": text}]}, ensure_ascii=escaped)
    for split in range(len(raw) + 1):
        projection = AnswerProjection()
        deltas = projection.feed(raw[:split]) + projection.feed(raw[split:])
        projection.finish()
        assert bodies(deltas) == text


def test_kind_after_parts_is_buffered_and_non_answer_or_nested_text_is_hidden() -> None:
    projection = AnswerProjection()
    assert projection.feed('{"parts":[{"text":"您好"}],') == []
    assert projection.feed('"kind":"ANSWER_PARTS"}') == [AnswerDelta("part-0", 0, "您好")]
    projection.finish()
    for kind in ("READ_TOOL", "UNDERSTANDING", "ANSWER"):
        projection = AnswerProjection()
        assert projection.feed(json.dumps({"kind": kind, "parts": [{"text": "隐藏"}]})) == []
        projection.finish()
    projection = AnswerProjection()
    raw = {"kind": "ANSWER_PARTS", "reasoning": {"parts": [{"text": "隐藏"}]},
           "parts": [{"blocker": {"text": "隐藏"}, "text": "您好"}, {"text": "继续核查。"}]}
    deltas = projection.feed(json.dumps(raw))
    assert [(d.part_id, d.text) for d in deltas] == [("part-0", "您好"), ("part-1", "继续核查。")]


@pytest.mark.parametrize("suffix", ["{{PAID_AMOUNT}}。", "{{SHIPMENT_STATUS}}。", "{", "￥329元。", "329元。"])
def test_unresolved_fact_or_numeric_tail_is_held_for_final_grounding(suffix: str) -> None:
    projection = AnswerProjection()
    deltas = projection.feed(json.dumps({"kind": "ANSWER_PARTS", "parts": [{"text": "核查结果：" + suffix}]}))
    projection.finish()
    assert bodies(deltas) == "核查结果："


@pytest.mark.parametrize("raw", [
    '{"kind":"ANSWER_PARTS","parts":[{"text":"未完成',
    '{"kind":"ANSWER_PARTS","kind":"READ_TOOL"}',
    '{"kind":"ANSWER_PARTS","parts":[{"text":"a","text":"b"}]}',
    '{"kind":"ANSWER_PARTS",}',
    '{"parts":[,]}',
    '{"kind":"ANSWER_PARTS"} trailing',
    '{"kind":"ANSWER_PARTS","parts":[{"text":"\\uD800x"}]}',
])
def test_malformed_or_truncated_document_never_finishes_as_success(raw: str) -> None:
    projection = AnswerProjection()
    with pytest.raises(ProjectionError):
        projection.feed(raw)
        projection.finish()


def test_projection_is_bounded_and_failed_projection_cannot_resume() -> None:
    projection = AnswerProjection(max_chars=20)
    with pytest.raises(ProjectionError, match="limit"):
        projection.feed(" " * 21)
    with pytest.raises(ProjectionError):
        projection.feed("{}")


def test_one_character_chunks_preserve_offsets_and_hold_a_split_placeholder() -> None:
    projection = AnswerProjection()
    raw = json.dumps({"kind": "ANSWER_PARTS", "parts": [{"text": "您好😀，查到{{SHIPMENT_STATUS}}。"}]})
    deltas = [delta for character in raw for delta in projection.feed(character)]
    projection.finish()
    text = ""
    for delta in deltas:
        assert delta.offset == len(text)
        text += delta.text
    assert text == "您好😀，查到"


@pytest.mark.parametrize("raw", [
    json.dumps({"kind": "ANSWER_PARTS", "parts": [{"text": "x" * 4001}]}),
    json.dumps({"kind": "ANSWER_PARTS", "parts": [{"text": "x"}] * 9}),
    '{"x":' + "[" * 33 + "0" + "]" * 33 + "}",
])
def test_part_count_text_length_and_nesting_limits(raw: str) -> None:
    with pytest.raises(ProjectionError, match="limit"):
        AnswerProjection().feed(raw)


def test_provider_and_projection_together_emit_before_next_network_piece() -> None:
    projection = AnswerProjection()
    seen: list[AnswerDelta] = []

    def observe(fragment: str) -> None:
        seen.extend(projection.feed(fragment))

    def event(text: str) -> bytes:
        return ("data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + "\n\n").encode()

    class Network(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield event('{"kind":"ANSWER_PARTS","parts":[{"text":"您好，正在核查')
            assert bodies(seen) == "您好，正在核查"
            yield event('。"}]}')
            yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'

    model = StreamingLiveModelClient(
        endpoint="https://synthetic.invalid", model_id="synthetic", on_content=observe,
        stream_transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Network())),
    )
    reply = model.decide(system="JSON", messages=[], max_output_tokens=80)
    projection.finish()
    assert bodies(seen) == "您好，正在核查。"
    assert reply.decision["kind"] == "ANSWER_PARTS" and model.calls == len(model.requests) == 1
