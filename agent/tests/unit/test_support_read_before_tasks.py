"""Read-only investigation may precede annotations; publication remains fully checked."""

import json
from pathlib import Path

import pytest

from resolveflow.harness.budget import RunBudget
from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from tests.unit.test_support_agent import Reads, answer, read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_dialogue import previous
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_tasks import task


def final(req, values=None, **updates):
    values = values or [task('a')]
    return parts(*[part(t['id'], '依据已读，仍须人工核验。', ['O1'], 'NEEDS_MERCHANT') for t in values],
                 tasks=values, dialogue_events=[group('ADD', [t['id'] for t in values],
                                                       req.context['current_request'])], **updates)


def test_live_unannotated_read_executes_without_repair_then_final_declares_tasks_and_sources():
    req = request()
    model = MockModelClient(mode='live', script=[read(), final(req)])
    sources = Reads()
    result = SupportAgent(req, model, sources).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert model.calls == 2 and sources.calls == [('get_shipment_trace', {})]
    assert model.packets[1]['feedback'] is None
    assert model.packets[1]['task_state']['tasks'] == []
    assert model.packets[1]['dialogue_state']['events'] == []
    assert result['answer']['task_state']['tasks'][0]['status'] == 'NEEDS_MERCHANT'
    assert result['answer']['citations'][0]['source_id'] == 'O1'
    assert 'first_action_annotations' not in model.packets[0]
    assert 'annotation_example_note' not in model.packets[0]


def test_saved_extra_field_is_rejected_but_valid_read_after_feedback_needs_no_annotations():
    root = Path(__file__).resolve().parents[3]
    old = json.loads((root / 'reports/customer-agent-answer-parts-v1/runtime-results.json').read_text(
        encoding='utf-8'))['rows'][1]['models'][0]['decision']
    req = request()
    model = MockModelClient(mode='live', script=[old, read(), final(req)])
    sources = Reads()
    result = SupportAgent(req, model, sources).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert model.calls == 3 and sources.calls == [('get_shipment_trace', {})]
    assert json.loads(model.packets[1]['feedback'])['field'] == 'schema'


@pytest.mark.parametrize('terminal', ['no_tasks', 'missing_events', 'pending', 'future_ref'])
def test_read_does_not_grant_permission_to_publish_incomplete_or_ungrounded_answer(terminal):
    req = request()
    invalid = {
        'no_tasks': answer(citations=['O1']),
        'missing_events': parts(part('a', '已查到', ['O1']), tasks=[task('a')]),
        'pending': answer(text='尚待处理', citations=['O1'], tasks=[task('a')],
                          dialogue_events=[group('ADD', ['a'], req.context['current_request'])]),
        'future_ref': parts(part('a', '依据不存在', ['P99']), tasks=[task('a')],
                            dialogue_events=[group('ADD', ['a'], req.context['current_request'])]),
    }[terminal]
    model = MockModelClient(mode='live', script=[read(), invalid, invalid])
    source = Reads()
    result = SupportAgent(req, model, source).run()
    assert result['reason'] == 'INVALID_DECISION' and result['answer'] is None
    assert source.calls == [('get_shipment_trace', {})] and model.calls == 3
    assert model.packets[2]['task_state']['tasks'] == []


@pytest.mark.parametrize('change', ['drop', 'cancel', 'resume', 'old_quote'])
def test_unannotated_reads_preserve_prior_tasks_and_do_not_authorize_state_changes(change):
    req = request(input_version=5)
    previous(req, [task('existing', status='SUSPENDED' if change == 'resume' else 'NEEDS_MERCHANT')])
    status = 'CANCELLED' if change == 'cancel' else 'NEEDS_MERCHANT'
    ids = ['new'] if change == 'drop' else ['existing']
    values = [task(ids[0])]
    events = [group('ADD' if change == 'drop' else 'CONTINUE', ids, req.context['current_request'])]
    if change == 'old_quote':
        events = [group('CANCEL', ids, '以前不查了', reference='H1')]
        status = 'CANCELLED'
    invalid = parts(part(ids[0], '已处理', ['O1'], status), tasks=values, dialogue_events=events)
    model = MockModelClient(mode='live', script=[read(), invalid, invalid])
    result = SupportAgent(req, model, Reads()).run()
    if change == 'drop':
        assert result['status'] == 'SUCCEEDED'
        state = result['answer']['task_state']
        assert state['focus_ids'] == ['new']
        assert [t['id'] for t in state['tasks']] == ['existing', 'new']
        assert state['tasks'][0]['lifecycle'] == 'OPEN'
    else:
        assert result['reason'] == 'INVALID_DECISION'
    assert model.packets[1]['dialogue_state']['carried_tasks'] == {
        'existing': 'SUSPENDED' if change == 'resume' else 'NEEDS_MERCHANT'}


def test_supplied_invalid_annotations_still_block_the_whole_action_atomically():
    req = request()
    invalid = {**read(), 'tasks': [task('a'), task('b')],
               'dialogue_events': [group('ADD', ['a'], req.context['current_request'])]}
    model = MockModelClient(mode='live', script=[invalid, read(), final(req)])
    source = Reads()
    result = SupportAgent(req, model, source).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert model.packets[1]['task_state']['tasks'] == []
    assert result['answer']['task_state']['tasks'][0]['id'] == 'a'
    assert len(result['answer']['task_state']['tasks']) == 1
    assert source.calls == [('get_shipment_trace', {})]


@pytest.mark.parametrize('bad', [
    {'kind': 'READ_TOOL', 'tool_name': 'refund', 'arguments': {}},
    {'kind': 'READ_TOOL', 'tool_name': 'get_order_context', 'arguments': {'customer_id': 'OTHER'}},
])
def test_tool_permission_and_identity_arguments_remain_closed_without_annotations(bad):
    source = Reads()
    result = SupportAgent(request(), MockModelClient(mode='live', script=[bad, bad]), source).run()
    assert result['reason'] == 'INVALID_DECISION' and source.calls == []


def test_read_before_tasks_still_consumes_original_tool_budget():
    source = Reads()
    model = MockModelClient(mode='live', script=[read()])
    result = SupportAgent(request(), model, source, budget=RunBudget(tool_attempts=0)).run()
    assert result['reason'] == 'BUDGET_TOOL_ATTEMPTS' and source.calls == []
    assert model.calls == 1 and model.packets[0]['task_state']['tasks'] == []
