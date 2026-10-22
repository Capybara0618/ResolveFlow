"""Regress saved missing-task answers without rewriting outputs or granting extra repairs."""

import json
import re
from copy import deepcopy
from pathlib import Path

import pytest

from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from resolveflow.support.guidance import decision_feedback
from resolveflow.support.protocol import Answer, AnswerParts, SupportTask
from resolveflow.support.tasks import TaskStateError, TaskTracker
from tests.unit.test_support_agent import Reads, answer, read, request
from tests.unit.test_support_dialogue import event
from tests.unit.test_support_tasks import task


def saved_row():
    root = Path(__file__).resolve().parents[3]
    return json.loads((root / 'reports/customer-agent-annotation-check-v1/runtime-results.json').read_text(
        encoding='utf-8'))['rows'][1]


@pytest.mark.parametrize('position', [3, 4])
def test_saved_answers_get_specific_pending_ids_without_mutating_accepted_state(position):
    row = saved_row()
    tracker = TaskTracker()
    tracker.accept([SupportTask.model_validate(t) for t in row['models'][1]['decision']['tasks']], {'O1'})
    payload = deepcopy(row['models'][position]['decision'])
    original = deepcopy(payload)
    with pytest.raises(TaskStateError) as error:
        tracker.accept(None, {'O1', 'O2', 'P1', 'P2', 'P3'}, answer=Answer.model_validate(payload))
    feedback = json.loads(decision_feedback(error.value, payload, ['O1', 'O2', 'P1', 'P2', 'P3']))
    assert feedback['issue'] == 'ANSWER_TASKS_PENDING'
    assert feedback['task_ids'] == ['t1'] and feedback['field'] == 'tasks'
    assert feedback['required_on_answer'] == ['tasks']
    assert 'response_excerpt' in feedback['repair_note']
    assert 'NEEDS_MERCHANT' in feedback['status_choices'] and 'PENDING' not in feedback['status_choices']
    assert payload == original and tracker.tasks[0].status == 'PENDING'


def test_sent_answer_example_is_complete_and_packet_keeps_all_required_task_ids():
    initial = [task('shipping'), task('entry', 'APPLICATION', request='申请入口')]
    model = MockModelClient(script=[{**read(), 'tasks': initial}, answer(citations=['O1']),
                                   answer(citations=['O1'])])
    SupportAgent(request(), model, Reads()).run()
    system = ''.join(b.text for b in model.conversations[0][0].get_content_blocks() if hasattr(b, 'text'))
    examples = [json.loads(s) for s in re.findall(r'^\{"kind":.*\}$', system, re.MULTILINE)]
    example = next(e for e in examples if e['kind'] == 'ANSWER_PARTS')
    parsed = AnswerParts.model_validate(example)
    assert parsed.parts[0].task_id == 't1' and parsed.parts[0].text
    assert '独立事项分任务' in system
    requirements = model.packets[1]['answer_requirements']
    assert requirements['task_ids'] == ['shipping', 'entry']
    assert model.packets[2]['answer_requirements'] == requirements
    assert model.packets[2]['task_state']['tasks'] == initial


def test_model_repairs_saved_answer_with_full_task_updates_and_one_repair_only():
    req = request()
    initial = [task('shipping'), task('eligibility', 'ELIGIBILITY'), task('entry', 'APPLICATION')]
    pending = {**read(), 'tasks': initial, 'dialogue_events': [
        event('ADD', t['id'], req.context['current_request']) for t in initial]}
    saved = deepcopy(saved_row()['models'][3]['decision'])
    saved['citations'] = ['O1']  # Script source only provides O1; original report stays untouched.
    text = '系统有签收记录；退款须商家核验；入口尚未核实。'
    complete = [task('shipping', status='ANSWERED', evidence_refs=['O1'], response_excerpt='系统有签收记录'),
                task('eligibility', 'ELIGIBILITY', 'NEEDS_MERCHANT', response_excerpt='退款须商家核验'),
                task('entry', 'APPLICATION', 'UNAVAILABLE', response_excerpt='入口尚未核实')]
    model = MockModelClient(mode='live', script=[pending, saved, answer(text=text, citations=['O1'], tasks=complete)])
    sources = Reads()
    result = SupportAgent(req, model, sources).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    feedback = json.loads(model.packets[2]['feedback'])
    assert feedback['task_ids'] == ['shipping', 'eligibility', 'entry']
    assert result['answer']['task_state']['tasks'] == complete
    assert sources.calls == [('get_shipment_trace', {})] and model.calls == 3
    repeated = MockModelClient(mode='live', script=[pending, saved, saved])
    failed = SupportAgent(req, repeated, Reads()).run()
    assert failed['reason'] == 'INVALID_DECISION' and failed['answer'] is None


def test_removed_task_feedback_identifies_the_task_instead_of_allowing_silent_deletion():
    tracker = TaskTracker()
    tracker.accept([SupportTask.model_validate(task('a')), SupportTask.model_validate(task('b'))], set())
    payload = answer(citations=[], tasks=[task('a', status='UNAVAILABLE', response_excerpt='无法查询')],
                     text='无法查询')
    with pytest.raises(TaskStateError) as error:
        tracker.accept(Answer.model_validate(payload).tasks, set(), answer=Answer.model_validate(payload))
    feedback = json.loads(decision_feedback(error.value, payload, []))
    assert feedback['issue'] == 'TASKS_REMOVED' and feedback['task_ids'] == ['b']
    assert [t.status for t in tracker.tasks] == ['PENDING', 'PENDING']
