import json

import httpx
import pytest
from scripts.confirm_policy_focus_live_v1 import RecordedStreamingModel, build_fixture, frozen_transport

from resolveflow.harness.sdk_adapter import raw_text_message
from resolveflow.support.protocol import SupportInput


def test_counter_saves_before_send_and_hard_bound_never_sends_an_extra_request():
    saved, transmitted = [], []
    usage = {'used': 7, 'save': lambda: saved.append('ledger')}

    def respond(request):
        assert saved[:2] == ['ledger', 'record']
        transmitted.append(request)
        answer = json.dumps({'kind': 'ANSWER_PARTS', 'parts': [
            {'task_id': 't1', 'status': 'ANSWERED', 'text': '仅解释假设条件。', 'citations': []}]}, ensure_ascii=False)
        events = [{'choices': [{'delta': {'content': answer}}]},
                  {'choices': [{'delta': {}, 'finish_reason': 'stop'}],
                   'usage': {'prompt_tokens': 3, 'completion_tokens': 2}}]
        raw = ''.join('data: ' + json.dumps(e, ensure_ascii=False) + '\n\n' for e in events) + 'data: [DONE]\n\n'
        return httpx.Response(200, content=raw.encode('utf-8'))

    model = RecordedStreamingModel(usage=usage, limit=1, on_record=lambda _: saved.append('record'),
        endpoint='https://synthetic-provider.invalid/chat', model_id='synthetic-model', provider='deepseek',
        stream_transport=httpx.MockTransport(respond))
    arguments = {'system': '', 'messages': [raw_text_message('合成测试', role='user')], 'max_output_tokens': 128}
    reply = model.decide(**arguments)
    assert reply.decision['kind'] == 'ANSWER_PARTS' and model.records[0]['deltas']
    assert usage['used'] == 8 and model.records[0]['usage']['estimated'] is False
    with pytest.raises(ValueError, match='bound'):
        model.decide(**arguments)
    assert len(transmitted) == 1 and usage['used'] == 8


def test_frozen_facade_is_bound_and_never_invents_missing_business_reads():
    fixture = build_fixture()
    req = SupportInput.model_validate(fixture['original_input'])
    paths = []
    shipment = frozen_transport(httpx.Request('GET', f'http://frozen/internal/{req.run_id}/facts/shipment'),
                                fixture, req, paths)
    assert shipment.json() == fixture['shipment']
    assert frozen_transport(httpx.Request('GET', f'http://frozen/internal/{req.run_id}/unsupported'),
                            fixture, req, paths).status_code == 404
    with pytest.raises(AssertionError, match='run-bound'):
        frozen_transport(httpx.Request('GET', 'http://frozen/internal/other/facts/order'), fixture, req, paths)
