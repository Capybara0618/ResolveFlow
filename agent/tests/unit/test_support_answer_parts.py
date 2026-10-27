"""Single-source answer text and explicit per-task outcomes; no inferred completion."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import DECISION
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import GuideReads, Reads, answer, read, request
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_tasks import task


def parts(*values, **updates):
    return {'kind': 'ANSWER_PARTS', 'parts': list(values), **updates}


def part(key, text, citations=None, status='ANSWERED'):
    return {'task_id': key, 'text': text, 'status': status, 'citations': citations or []}


def test_three_tasks_answer_text_is_written_once_and_original_metadata_is_reused():
    req = request()
    pending = [task('shipping'), task('qualify', 'ELIGIBILITY'), task('apply', 'APPLICATION')]
    start = {**read(), 'tasks': pending,
             'dialogue_events': [group('ADD', ['shipping', 'qualify', 'apply'], req.context['current_request'])]}
    final = parts(part('shipping', '系统有签收记录。', ['O1']),
                  part('qualify', '退款条件需商家核验。', status='NEEDS_MERCHANT'),
                  part('apply', '正式退款申请入口为我的售后。', ['O2']))
    original = deepcopy(final)
    model = TokenizedScript(mode='live', script=[start, read('get_support_guide'), final])
    result = SupportAgent(req, model, GuideReads()).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert result['answer']['text'] == '\n\n'.join(p['text'] for p in final['parts'])
    saved = result['answer']['task_state']['tasks']
    assert [t['intent'] for t in saved] == ['LOGISTICS', 'ELIGIBILITY', 'APPLICATION']
    assert all(t['response_excerpt'] in result['answer']['text'] for t in saved)
    assert final == original and model.calls == 3


@pytest.mark.parametrize('bad_parts', [
    [part('a', '遗漏b')], [part('a', '重复'), part('a', '重复')],
    [part('a', '回答'), part('unknown', '未知')],
    [part('a', '回答', ['P99']), part('b', '回答')],
    [part('a', '未完成', status='PENDING'), part('b', '回答')],
])
def test_incomplete_duplicate_unknown_future_ref_or_pending_parts_do_not_publish(bad_parts):
    req = request()
    initial = {**read(), 'tasks': [task('a'), task('b')],
               'dialogue_events': [group('ADD', ['a', 'b'], req.context['current_request'])]}
    model = MockModelClient(mode='live', script=[initial, parts(*bad_parts), parts(*bad_parts)])
    result = SupportAgent(req, model, Reads()).run()
    assert result['status'] == 'FAILED' and result['reason'] == 'INVALID_DECISION'
    assert result['answer'] is None and model.calls == 3
    assert all(t['status'] == 'PENDING' for t in model.packets[2]['task_state']['tasks'])


def test_parts_cannot_invent_an_initial_task_or_silently_cancel_it():
    model = MockModelClient(mode='live', script=[parts(part('a', '随意完成')), parts(part('a', '随意完成'))])
    assert SupportAgent(request(), model, Reads()).run()['reason'] == 'INVALID_DECISION'
    req = request()
    initial = {**read(), 'tasks': [task('a')],
               'dialogue_events': [group('ADD', ['a'], req.context['current_request'])]}
    cancel = parts(part('a', '已撤回', status='CANCELLED'))
    result = SupportAgent(req, MockModelClient(mode='live', script=[initial, cancel, cancel]), Reads()).run()
    assert result['reason'] == 'INVALID_DECISION'


def test_long_part_is_not_duplicated_or_truncated_in_the_published_text():
    req = request()
    text = '答复' * 350
    initial = {**read(), 'tasks': [task('a')],
               'dialogue_events': [group('ADD', ['a'], req.context['current_request'])]}
    result = SupportAgent(req, MockModelClient(mode='live', script=[initial, parts(part('a', text))]), Reads()).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert result['answer']['text'] == text
    assert result['answer']['task_state']['tasks'][0]['response_excerpt'] == text[:400]


def test_combined_answer_still_obeys_public_length_limit_and_duplicate_initial_tasks_fail():
    req = request()
    initial = {**read(), 'tasks': [task('a'), task('b')],
               'dialogue_events': [group('ADD', ['a', 'b'], req.context['current_request'])]}
    overlong = parts(part('a', '字' * 2100), part('b', '字' * 2100))
    model = MockModelClient(mode='live', script=[initial, overlong, overlong])
    assert SupportAgent(req, model, Reads()).run()['reason'] == 'INVALID_DECISION'
    duplicate = parts(part('a', '回答'), tasks=[task('a'), task('a')],
                      dialogue_events=[group('ADD', ['a'], req.context['current_request'])])
    result = SupportAgent(req, MockModelClient(mode='live', script=[duplicate, duplicate]), Reads()).run()
    assert result['reason'] == 'INVALID_DECISION'


def test_saved_wrong_search_shape_is_now_an_explicit_valid_tool_contract():
    root = Path(__file__).resolve().parents[3]
    report = json.loads((root / 'agent/tests/fixtures/regressions/customer-agent-event-groups-v1/runtime-results.json').read_text(
        encoding='utf-8'))
    payload = deepcopy(report['rows'][1]['models'][2]['decision'])
    original = deepcopy(payload)
    DECISION.validate_python(payload)
    model = MockModelClient(script=[payload, answer(citations=['P1'])])
    sources = Reads()
    result = SupportAgent(request(), model, sources).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert model.calls == 2 and sources.calls[0][0] == 'search_policy'
    assert payload == original
    for arguments in [{}, {'query': '政策', 'merchant_id': 'OTHER'}, {'query': '政策', 'top_k': 9}]:
        with pytest.raises(ValidationError):
            DECISION.validate_python({'kind': 'READ_TOOL', 'tool_name': 'search_policy', 'arguments': arguments})
