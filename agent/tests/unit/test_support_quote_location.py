import json
from copy import deepcopy
from pathlib import Path

import pytest

from resolveflow.support.memory import CustomerMemory, MemoryStateError, customer_source
from resolveflow.support.protocol import DialogueEvent, MemoryUpdate
from tests.recorded_sources import ProjectedSupportInput as SupportInput
from tests.unit.test_support_agent import request
from tests.unit.test_support_context import message


def test_saved_actual_quotes_are_located_without_changing_the_model_outputs():
    raw = json.loads((Path(__file__).resolve().parents[3]
                      / 'agent/tests/fixtures/regressions/customer-agent-experience-v2/runtime-results.json').read_text(encoding='utf-8'))
    original = deepcopy(raw)
    positions = []
    for row in raw['rows']:
        if row['id'] != 'U05' or row['turn'] not in (2, 3):
            continue
        req = SupportInput.model_validate(row['input'])
        for m in row['models']:
            for key, schema in [('dialogue_events', DialogueEvent), ('memory_updates', MemoryUpdate)]:
                for value in m['decision'].get(key, []):
                    if value.get('reference') != 'CURRENT':
                        continue
                    source = customer_source(schema.model_validate(value), req, [], current_only=True)
                    assert req.context['current_request'][source['offset']:].startswith(value['quote'])
                    positions.append(source['offset'])
    assert {9, 10, 15} <= set(positions)
    assert raw == original


@pytest.mark.parametrize('offset', [None, 0, 999])
def test_unique_unicode_quote_is_located_and_canonical_offset_is_saved(offset):
    req = request()
    req.context['current_request'] = '🙂先补充：家人没代收。'
    value = {'id': 'check', 'topic': 'CHECKS', 'reference': 'CURRENT', 'quote': '家人没代收。'}
    if offset is not None:
        value['offset'] = offset
    claim = MemoryUpdate.model_validate(value)
    memory = CustomerMemory(req)
    memory.apply([claim], [])
    assert memory.snapshot()['entries'][0]['source']['offset'] == 5
    assert memory.snapshot()['entries'][0]['source']['quote'] == value['quote']
    assert claim.model_dump()['offset'] == (offset or 0)


def test_ambiguous_quote_needs_matching_explicit_offset_not_a_default_zero():
    req = request()
    req.context['current_request'] = '没收到。后来仍没收到。'
    value = {'id': 'check', 'topic': 'RECEIPT', 'reference': 'CURRENT', 'quote': '没收到。'}
    with pytest.raises(MemoryStateError, match='歧义'):
        customer_source(MemoryUpdate.model_validate(value), req, [])
    with pytest.raises(MemoryStateError, match='歧义'):
        customer_source(MemoryUpdate.model_validate({**value, 'offset': 999}), req, [])
    source = customer_source(MemoryUpdate.model_validate({**value, 'offset': 7}), req, [])
    assert source['offset'] == 7


def test_location_never_changes_author_message_scope_or_allows_fake_current_events():
    req = request(input_version=5)
    req.context.update(current_request='今天没有收到', history=[
        message(1, '昨天收到过'), message(2, '助手说已经退款', 'ASSISTANT'), message(9, '未来消息')])
    for ref, quote, current_only in [('H1', '昨天收到过', True), ('H2', '助手说已经退款', False),
                                     ('H9', '未来消息', False), ('H999', '不存在', False),
                                     ('CURRENT', '已经退款', False)]:
        value = MemoryUpdate(id='x', topic='OTHER', reference=ref, quote=quote)
        with pytest.raises(MemoryStateError):
            customer_source(value, req, [], current_only=current_only)
