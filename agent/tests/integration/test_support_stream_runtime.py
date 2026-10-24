"""Real SDK/PG and synthetic streaming HTTP; no paid model or daily business writes."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from resolveflow.harness.streaming_model import StreamingLiveModelClient
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.progress import ProgressReporter
from resolveflow.support.service import SupportRuntime
from tests.unit.test_support_agent import Reads, read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_grounding import FactReads
from tests.unit.test_support_staged import understand


@pytest.mark.parametrize("structured", [False, True])
def test_real_sdk_streams_after_reads_repairs_once_and_reuses_completed_run_without_new_http(
    agent_db, monkeypatch, structured,
):
    req = request()
    calls: list[dict[str, Any]] = []
    batches: list[dict[str, Any]] = []
    reporters: list[ProgressReporter] = []
    bad = parts(part('trace', '这条回答引用尚未读取的来源。', ['O99']))
    good = parts(part('trace', '根据本轮物流记录，需要进一步核验。', ['O1']))
    if structured:
        good['fact_rendering'] = 'fields-v1'
        good['parts'][0]['facts'] = [{'field': 'SHIPMENT_STATUS', 'source': 'O1'}]
    script = [understand(req), read(), bad, good]

    class Stream(httpx.SyncByteStream):
        def __init__(self, value: dict[str, Any]):
            self.text = json.dumps(value, ensure_ascii=False)

        def __iter__(self) -> Iterator[bytes]:
            for offset in range(0, len(self.text), 9):
                chunk = {"choices": [{"index": 0, "delta": {"content": self.text[offset:offset + 9]}}]}
                yield ("data: " + json.dumps(chunk) + "\n\n").encode()
            yield ("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 50}})
                   + "\n\ndata: [DONE]\n\n").encode()

    def provider(call: httpx.Request) -> httpx.Response:
        calls.append(json.loads(call.content))
        return httpx.Response(200, stream=Stream(script[len(calls) - 1]))

    def reporter(*args: Any) -> ProgressReporter:
        def respond(call: httpx.Request) -> httpx.Response:
            batches.append(json.loads(call.content))
            return httpx.Response(200)
        value = ProgressReporter(*args, transport=httpx.MockTransport(respond))
        reporters.append(value)
        return value

    monkeypatch.setattr('resolveflow.support.service.ProgressReporter', reporter)
    model = StreamingLiveModelClient(
        endpoint='http://synthetic.invalid', model_id='deepseek-flash', provider='deepseek',
        stream_transport=httpx.MockTransport(provider))
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode='live', provider='deepseek', model_id='deepseek-flash'),
                             architecture='staged-v1', model_factory=lambda: model,
                             sources_factory=lambda *args: FactReads() if structured else Reads())
    result = runtime.run(req, 'read-only', progress_token='progress-only')
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert len(calls) == model.calls == result['spend']['model_calls'] == 4
    assert all(call['stream'] for call in calls)
    assert reporters[0].failure is None
    events = [event for batch in batches for event in batch['events']]
    assert [e['kind'] for e in events[:2]] == ['activity.started', 'activity.completed']
    assert any(e['kind'] == 'answer.reset' for e in events)
    assert {e['attempt_id'] for e in events if e['kind'] == 'answer.started'} == {'model-3', 'model-4'}
    assert '根据本轮物流记录' in ''.join(e['payload']['text'] for e in events
                                   if e['kind'] == 'answer.delta' and e['attempt_id'] == 'model-4')
    assert not any(e['kind'] == 'answer.committed' for e in events)
    if structured:
        streamed = ''.join(e['payload']['text'] for e in events
                           if e['kind'] == 'answer.delta' and e['attempt_id'] == 'model-4')
        assert streamed == '根据本轮物流记录，需要进一步核验。'
        assert result['answer']['text'] == streamed + '\n\n物流状态：丢失。'
    assert runtime.run(req, 'fresh-read', progress_token='fresh-progress') == result
    assert len(calls) == 4 and len(reporters) == 1
    with agent_db.connection() as connection:
        rows = connection.execute(
            "SELECT kind,status FROM support_agent_call WHERE run_id=%s", (req.run_id,)).fetchall()
        assert len(rows) == 5 and all(row['status'] == 'COMPLETE' for row in rows)
        row = connection.execute('SELECT manifest_json,result_json FROM support_agent_run WHERE run_id=%s',
                                 (req.run_id,)).fetchone()
        assert row['manifest_json']['answer_fact_rendering'] == 'fields-v1'
        assert row['result_json'] == result


def test_unfinished_old_run_does_not_silently_adopt_new_fact_contract(agent_db):
    from resolveflow.harness.model import MockModelClient
    from resolveflow.support.protocol import SupportFailure
    from resolveflow.support.store import SupportStore

    req = request()
    SupportStore(agent_db).claim(req, {'version': 'old-frozen-manifest'})
    with agent_db.connection() as connection:
        connection.execute("UPDATE support_agent_run SET lease_until=now()-interval '1 second' WHERE run_id=%s",
                           (req.run_id,))
    model = MockModelClient(script=[])
    runtime = SupportRuntime(agent_db, DeploymentConfig(mode='mock'), architecture='staged-v1',
                             model_factory=lambda: model, sources_factory=lambda *args: Reads())
    with pytest.raises(SupportFailure, match='MANIFEST_MISMATCH'):
        runtime.run(req, 'read-only')
    assert model.calls == 0
