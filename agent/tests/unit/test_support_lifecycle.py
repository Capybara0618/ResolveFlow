import json
from copy import deepcopy
from pathlib import Path

import pytest

from resolveflow.support.dialogue import DialogueState, DialogueStateError
from resolveflow.support.engine import SupportAgent
from resolveflow.support.protocol import DECISION, DialogueEvent, SupportInput, SupportTask
from resolveflow.support.tasks import render_answer
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import Reads, read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_tasks import task


def carry(req, result):
    req.context['previous_tasks'] = {'origin': 'MODEL_PREVIOUS_TURN', 'input_version': result['input_version'],
                                      'tasks': result['answer']['task_state']['tasks']}
    req.context['previous_customer_memory'] = result['answer']['customer_memory']
    return req


@pytest.mark.parametrize('turn,expected', [(2, 'PAUSED'), (4, 'CANCELLED')])
def test_saved_answered_topic_can_be_paused_or_cancelled_without_editing_the_saved_decision(turn, expected):
    raw = json.loads((Path(__file__).resolve().parents[3]
                      / 'reports/customer-agent-experience-v2/runtime-results.json').read_text(encoding='utf-8'))
    row = next(r for r in raw['rows'] if r['id'] == 'U05' and r['turn'] == turn)
    decision = deepcopy(row['models'][0]['decision'])
    original = deepcopy(decision)
    req = SupportInput.model_validate(row['input'])
    state = DialogueState(req)
    answer = render_answer(DECISION.validate_python(decision), [])
    state.apply(answer.dialogue_events, answer.tasks, [], require=True)
    assert state.packet()['lifecycles']['t1'] == expected
    assert decision == original


def test_answered_response_remains_open_then_pauses_resumes_with_correction_and_cancels():
    req = request(input_version=1)
    text = req.context['current_request']
    initial = parts(part('trace', '已读签收记录，事项尚待核查。', ['O1']), tasks=[task('trace')],
                    dialogue_events=[group('ADD', ['trace'], text)])
    result = SupportAgent(req, TokenizedScript(mode='live', script=[read(), initial]), Reads()).run()
    assert result['status'] == 'SUCCEEDED'
    assert result['answer']['task_state']['tasks'][0]['status'] == 'ANSWERED'
    assert result['answer']['task_state']['tasks'][0]['lifecycle'] == 'OPEN'
    for version, change, status, expected, current in [
        (3, 'PAUSE', 'SUSPENDED', 'PAUSED', '签收问题先暂停。'),
        (5, 'RESUME', 'ANSWERED', 'OPEN', '继续核查。补充：家人和代收点都没代收。'),
        (7, 'CANCEL', 'CANCELLED', 'CANCELLED', '找到了，不再核查。'),
    ]:
        req = carry(request(input_version=version), result)
        req.context['current_request'] = current
        extra = {'memory_updates': [{'id': 'checked', 'topic': 'CHECKS', 'reference': 'CURRENT',
                                    'quote': '家人和代收点都没代收。'}]} if change == 'RESUME' else {}
        final = parts(part('trace', '已按本轮要求记录。', status=status), tasks=[task('trace')],
                      dialogue_events=[group(change, ['trace'], current)], **extra)
        result = SupportAgent(req, TokenizedScript(mode='live', script=[final]), Reads()).run()
        assert result['status'] == 'SUCCEEDED', result['reason']
        assert result['answer']['task_state']['tasks'][0]['lifecycle'] == expected
    claim = result['answer']['customer_memory']['entries'][0]
    assert claim['quote'] == '家人和代收点都没代收。' and claim['source']['offset'] == 8


@pytest.mark.parametrize('old_lifecycle', ['RESOLVED', 'CANCELLED'])
def test_explicitly_closed_topic_needs_reopen_and_cannot_silently_continue(old_lifecycle):
    req = request(input_version=3)
    req.context['previous_tasks'] = {'origin': 'MODEL_PREVIOUS_TURN', 'input_version': 1, 'tasks': [
        {**task('trace', status='ANSWERED'), 'lifecycle': old_lifecycle}]}
    state = DialogueState(req)
    values = [SupportTask.model_validate(task('trace', status='ANSWERED'))]
    with pytest.raises(DialogueStateError):
        state.apply([DialogueEvent.model_validate(group('CONTINUE', ['trace'], req.context['current_request']))],
                    values, [], require=True)
    state.apply([DialogueEvent.model_validate(group('REOPEN', ['trace'], req.context['current_request']))],
                values, [], require=True)
    assert state.packet()['lifecycles']['trace'] == 'OPEN'


def test_resolve_is_explicit_and_lifecycle_cannot_be_forged_in_task_metadata():
    req = request(input_version=3)
    req.context['previous_tasks'] = {'origin': 'MODEL_PREVIOUS_TURN', 'input_version': 1,
                                      'tasks': [task('review', 'HANDOFF', 'ANSWERED')]}
    req.context['current_request'] = '事情解决了，结束。'
    final = parts(part('review', '已记录事项结束。'), tasks=[task('review', 'HANDOFF')],
                  dialogue_events=[group('RESOLVE', ['review'], req.context['current_request'])])
    result = SupportAgent(req, TokenizedScript(mode='live', script=[final]), Reads()).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert result['answer']['task_state']['tasks'][0]['lifecycle'] == 'RESOLVED'
    fake = SupportTask.model_validate({**task('new'), 'lifecycle': 'RESOLVED'})
    with pytest.raises(DialogueStateError, match='lifecycle'):
        DialogueState(request()).apply([DialogueEvent.model_validate(group('ADD', ['new'],
            request().context['current_request']))], [fake], [], require=True)


def test_answered_faq_can_be_omitted_but_unfinished_issue_cannot_disappear():
    for old_status in ['ANSWERED', 'NEEDS_MERCHANT']:
        req = request(input_version=3)
        req.context['previous_tasks'] = {'origin': 'MODEL_PREVIOUS_TURN', 'input_version': 1,
                                          'tasks': [task('old', status=old_status)]}
        state = DialogueState(req)
        event = DialogueEvent.model_validate(group('ADD', ['new'], req.context['current_request']))
        values = [SupportTask.model_validate(task('new', status='ANSWERED'))]
        if old_status == 'ANSWERED':
            state.apply([event], values, [], require=True)
            assert state.packet()['lifecycles']['new'] == 'OPEN'
        else:
            with pytest.raises(DialogueStateError):
                state.apply([event], values, [], require=True)
