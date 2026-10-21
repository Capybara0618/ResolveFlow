"""Explicit groups share an anchor; never infer missing task changes from statuses."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from resolveflow.harness.model import MockModelClient
from resolveflow.support.dialogue import DialogueState, DialogueStateError
from resolveflow.support.engine import SupportAgent
from resolveflow.support.guidance import decision_feedback
from resolveflow.support.protocol import DECISION, DialogueEvent, SupportTask
from tests.unit.test_support_agent import Reads, answer, read, request
from tests.unit.test_support_dialogue import event, previous
from tests.unit.test_support_tasks import task


def group(change, ids, text, **kwargs):
    return {'change': change, 'task_ids': ids, 'reference': 'CURRENT', 'offset': 0, 'quote': text, **kwargs}


def tasks(values):
    return [SupportTask.model_validate(t) for t in values]


def test_saved_three_task_failure_reports_exact_missing_ids_and_does_not_commit():
    root = Path(__file__).resolve().parents[3]
    report = json.loads((root / 'reports/customer-agent-answer-tasks-v1/runtime-results.json').read_text(
        encoding='utf-8'))
    raw = deepcopy(report['rows'][1]['models'][0]['decision'])
    original = deepcopy(raw)
    decision = DECISION.validate_python(raw)
    state = DialogueState(request())
    with pytest.raises(DialogueStateError) as error:
        state.apply(decision.dialogue_events, decision.tasks, [], require=True)
    feedback = json.loads(decision_feedback(error.value, raw, []))
    assert feedback['issue'] == 'DIALOGUE_COVERAGE'
    assert feedback['missing_task_ids'] == ['t2', 't3']
    assert feedback['required_on_action'] == ['tasks', 'dialogue_events']
    assert 'task_ids' in feedback['repair_note']
    assert raw == original and state.before == {} and state.events == [] and not state.started


def test_grouped_additions_are_explicitly_expanded_to_per_task_source_records():
    req = request()
    ids = ['delivery', 'eligibility', 'entry']
    state = DialogueState(req)
    proposed = group('ADD', ids, req.context['current_request'])
    state.apply([DialogueEvent.model_validate(proposed)], tasks([task(i) for i in ids]), [], require=True)
    assert [e['task_id'] for e in state.events] == ids
    assert all(e['source']['quote'] == req.context['current_request'] for e in state.events)
    assert all(e['source']['sequence'] == req.input_version for e in state.events)


@pytest.mark.parametrize('updates', [
    {'task_ids': []}, {'task_ids': ['a', 'a']}, {'task_ids': ['invalid id']},
    {'task_ids': ['a'], 'task_id': 'a'}, {'task_ids': None}, {'task_ids': [str(i) for i in range(9)]},
])
def test_group_target_shape_rejects_ambiguous_duplicate_empty_or_excessive_ids(updates):
    payload = group('ADD', ['a'], '原文')
    payload.update(updates)
    with pytest.raises(ValidationError):
        DialogueEvent.model_validate(payload)


def test_overlapping_groups_and_unknown_tasks_cannot_silently_merge():
    req = request()
    quote = req.context['current_request']
    state = DialogueState(req)
    with pytest.raises(DialogueStateError):
        state.apply([DialogueEvent.model_validate(group('ADD', ['a', 'b'], quote)),
                     DialogueEvent.model_validate(event('ADD', 'b', quote))], tasks([task('a'), task('b')]), [],
                    require=True)
    with pytest.raises(DialogueStateError):
        state.apply([DialogueEvent.model_validate(group('ADD', ['a', 'unknown'], quote))], tasks([task('a')]), [],
                    require=True)
    assert not state.started and state.events == []


def test_invalid_member_of_group_blocks_all_changes_and_current_source_is_still_required():
    req = request(input_version=5)
    quote = req.context['current_request']
    previous(req, [task('paused', status='SUSPENDED'), task('active', status='NEEDS_MERCHANT')])
    state = DialogueState(req)
    before = state.packet()
    with pytest.raises(DialogueStateError):
        state.apply([DialogueEvent.model_validate(group('RESUME', ['paused', 'active'], quote))],
                    tasks([task('paused'), task('active')]), [], require=True)
    assert state.packet() == before
    with pytest.raises(DialogueStateError):
        state.apply([DialogueEvent.model_validate(group('CONTINUE', ['paused', 'active'], quote, reference='H1'))],
                    tasks([task('paused', status='SUSPENDED'), task('active')]), [], require=True)
    assert state.packet() == before


def test_model_can_reissue_complete_three_task_group_after_one_repair_then_answer():
    req = request()
    quote = req.context['current_request']
    initial = [task('a'), task('b', 'ELIGIBILITY'), task('c', 'APPLICATION')]
    incomplete = {**read(), 'tasks': initial, 'dialogue_events': [event('ADD', 'a', quote)]}
    corrected = {**read(), 'tasks': initial, 'dialogue_events': [group('ADD', ['a', 'b', 'c'], quote)]}
    final = [task('a', status='ANSWERED', evidence_refs=['O1'], response_excerpt='系统有签收记录'),
             task('b', 'ELIGIBILITY', 'NEEDS_MERCHANT', response_excerpt='可以请商家核验'),
             task('c', 'APPLICATION', 'UNAVAILABLE', response_excerpt='入口暂未核实')]
    model = MockModelClient(mode='live', script=[incomplete, corrected,
        answer(text='系统有签收记录，可以请商家核验。入口暂未核实。', citations=['O1'], tasks=final)])
    sources = Reads()
    result = SupportAgent(req, model, sources).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert model.packets[1]['task_state']['tasks'] == []
    assert json.loads(model.packets[1]['feedback'])['missing_task_ids'] == ['b', 'c']
    assert [e['task_id'] for e in result['answer']['dialogue_state']['events']] == ['a', 'b', 'c']
    assert sources.calls == [('get_shipment_trace', {})] and model.calls == 3
