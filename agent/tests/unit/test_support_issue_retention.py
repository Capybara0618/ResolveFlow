"""A response covers its focus; omission must never delete a conversation issue."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from resolveflow.support.dialogue import DialogueState, DialogueStateError
from resolveflow.support.protocol import DECISION, DialogueEvent, SupportInput, SupportTask
from resolveflow.support.tasks import render_answer
from tests.unit.test_support_agent import request
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_tasks import task


def saved(turn):
    raw = Path(__file__).resolve().parents[3] / 'agent/tests/fixtures/regressions/customer-agent-experience-v3/runtime-results.json'
    rows = json.loads(raw.read_text(encoding='utf-8'))['rows']
    return next(r for r in rows if r['id'] == 'U05' and r['turn'] == turn)


def test_actual_published_interruption_keeps_unmentioned_open_issue_and_only_answers_entry():
    row = saved(2)
    original = deepcopy(row['models'][-1]['decision'])
    answer = render_answer(DECISION.validate_python(original), [])
    state = DialogueState(SupportInput.model_validate(row['input']))
    state.apply(answer.dialogue_events, answer.tasks, [], require=True)
    assert state.lifecycles == {'t1': 'OPEN', 't2': 'OPEN'}
    packet = state.task_snapshot(answer.tasks)
    assert packet['focus_ids'] == ['t2']
    assert [t['id'] for t in packet['tasks']] == ['t1', 't2']
    old = packet['tasks'][0]
    assert old['evidence_refs'] == [] and old['response_excerpt'] is None
    assert row['models'][-1]['decision'] == original


def test_event_can_pause_nonfocus_issue_then_resume_original_id_after_a_faq():
    req = request(input_version=3)
    req.context['previous_tasks'] = {'origin': 'MODEL_PREVIOUS_TURN', 'input_version': 1,
                                    'tasks': [{**task('trace', status='ANSWERED'), 'lifecycle': 'OPEN'}]}
    state = DialogueState(req)
    entry = SupportTask.model_validate(task('faq', 'OTHER', 'ANSWERED'))
    events = [DialogueEvent.model_validate(group(change, [key], req.context['current_request']))
              for change, key in [('PAUSE', 'trace'), ('ADD', 'faq')]]
    state.apply(events, [entry], [], require=True)
    snapshot = state.task_snapshot([entry])
    assert state.lifecycles == {'trace': 'PAUSED', 'faq': 'OPEN'}
    next_req = request(input_version=5)
    next_req.context['previous_tasks'] = {'origin': 'MODEL_PREVIOUS_TURN', 'input_version': 3,
                                         'tasks': snapshot['tasks']}
    resumed = DialogueState(next_req)
    trace = SupportTask.model_validate(task('trace', status='ANSWERED'))
    resumed.apply([DialogueEvent.model_validate(group('RESUME', ['trace'],
                   next_req.context['current_request']))], [trace], [], require=True)
    assert resumed.lifecycles['trace'] == 'OPEN'
    assert [t['id'] for t in resumed.task_snapshot([trace])['tasks']] == ['trace', 'faq']


def test_issue_capacity_refuses_without_losing_previously_accepted_state():
    req = request(input_version=3)
    req.context['previous_tasks'] = {'origin': 'MODEL_PREVIOUS_TURN', 'input_version': 1,
                                    'tasks': [task('t' + str(i), status='ANSWERED') for i in range(8)]}
    state = DialogueState(req)
    before = deepcopy(state.packet())
    with pytest.raises(DialogueStateError, match='8'):
        state.apply([DialogueEvent.model_validate(group('ADD', ['extra'], req.context['current_request']))],
                    [SupportTask.model_validate(task('extra', status='ANSWERED'))], [], require=True)
    assert state.packet() == before
