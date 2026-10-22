"""Phase isolation, scoped evidence and actual SDK calls for the optional architecture."""

import json

import pytest

from resolveflow.harness.budget import RunBudget
from resolveflow.support.engine import SupportAgent
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import GuideReads, Reads, read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_event_groups import group


def understand(req, *, key='trace', intent='LOGISTICS', needs=None, events=None, memory=None):
    return {'kind': 'TURN_UNDERSTANDING', 'focus': [
        {'id': key, 'intent': intent, 'request': req.context['current_request'],
         'needs': ['SHIPMENT'] if needs is None else needs}],
        'dialogue_events': events or [group('ADD', [key], req.context['current_request'])],
        'memory_updates': memory or []}


def staged(req, script, sources=None, **kwargs):
    model = TokenizedScript(mode='live', script=script)
    source = sources or Reads()
    agent = SupportAgent(req, model, source, architecture='staged-v1', **kwargs)
    return agent.run(), model, source, agent


def test_understanding_is_separate_from_reads_and_final_answer_no_longer_repeats_annotations():
    req = request()
    result, model, source, agent = staged(req, [understand(req), read(),
        parts(part('trace', '根据本轮物流记录，需要进一步核验。', ['O1']))])
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert model.calls == 3 and result['spend']['model_calls'] == 3
    assert source.calls == [('get_shipment_trace', {})]
    assert model.packets[0]['stage']['phase'] == 'UNDERSTAND' and 'capabilities' not in model.packets[0]
    assert model.packets[1]['stage']['phase'] == 'INVESTIGATE_AND_ANSWER'
    systems = [''.join(b.text for b in c[0].get_content_blocks() if hasattr(b, 'text'))
               for c in model.conversations]
    assert systems[0] != systems[1] and 'TURN_UNDERSTANDING' in systems[0]
    assert 'memory_updates' not in systems[1]
    assert result['answer']['task_state']['focus_ids'] == ['trace']
    assert agent.stage.packet()['focus'][0]['needs'] == ['SHIPMENT']


@pytest.mark.parametrize('bad', ['read_first', 'redeclare', 'repeat_understanding'])
def test_illegal_phase_actions_have_one_feedback_and_never_execute_business_reads(bad):
    req = request()
    good = understand(req, intent='OTHER', needs=[])
    final = parts(part('trace', '已记录。'))
    if bad == 'read_first':
        script = [read(), good, final]
    elif bad == 'redeclare':
        script = [good, {**read(), 'tasks': [{'id': 'foreign', 'intent': 'OTHER', 'request': '换任务',
                                             'status': 'PENDING'}]}, final]
    else:
        script = [good, good, final]
    result, model, source, _ = staged(req, script)
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert source.calls == [] and model.calls == 3
    assert any(p['feedback'] and json.loads(p['feedback'])['field'] == 'stage' for p in model.packets)


def test_logistics_answer_with_attached_operation_requires_both_declared_sources():
    req = request()
    opening = understand(req, needs=['SHIPMENT', 'GUIDE'])
    final = parts(part('trace', '可以从售后咨询预览摘要后确认请商家核查。', ['O1', 'O2']))
    result, model, source, _ = staged(req, [opening, read(),
        parts(part('trace', '从售后咨询转交商家核查。', ['O1'])), read('get_support_guide'), final], GuideReads())
    assert result['status'] == 'SUCCEEDED', result['reason']
    feedback = json.loads(model.packets[3]['feedback'])
    assert feedback['field'] == 'stage_sources' and feedback['gaps'][0]['need'] == 'GUIDE'
    assert len(source.calls) == 2 and model.calls == 5


def test_closure_is_one_event_without_a_second_outcome_enum():
    req = request(input_version=3)
    req.context['previous_tasks'] = {'origin': 'MODEL_PREVIOUS_TURN', 'input_version': 1, 'tasks': [
        {'id': 'trace', 'intent': 'LOGISTICS', 'request': '调查签收', 'status': 'ANSWERED', 'lifecycle': 'OPEN'}]}
    opening = understand(req, needs=[], events=[group('RESOLVE', ['trace'], req.context['current_request'])])
    result, model, source, _ = staged(req, [opening, parts(part('trace', '已记录，结束核查。'))])
    assert result['status'] == 'SUCCEEDED' and source.calls == [] and model.calls == 2
    assert result['answer']['task_state']['tasks'][0]['lifecycle'] == 'RESOLVED'


def test_bad_understanding_quote_does_not_commit_memory_or_topics():
    req = request()
    bad = understand(req, needs=[])
    bad['dialogue_events'][0]['quote'] = '客户没有说过的话'
    result, model, source, agent = staged(req, [bad, bad])
    assert result['status'] == 'FAILED' and result['reason'] == 'INVALID_DECISION'
    assert source.calls == [] and agent.tasks.tasks == [] and agent.dialogue.lifecycles == {}
    assert model.calls == 2


def test_understanding_counts_toward_existing_budget_and_cannot_reset_it():
    req = request()
    result, model, source, _ = staged(req, [understand(req), read()], budget=RunBudget(model_calls=1))
    assert result['status'] == 'FAILED' and result['spend']['model_calls'] == 1
    assert model.calls == 1 and source.calls == []


def test_unknown_architecture_is_rejected_before_model_calls():
    model = TokenizedScript(mode='live', script=[])
    with pytest.raises(ValueError):
        SupportAgent(request(), model, Reads(), architecture='unknown')
    assert model.calls == 0


@pytest.mark.parametrize('prefix,utterance', [('a', '物流是否异常，能退吗，在哪申请？'),
                                         ('other_id', '我想同时知道运输结论、退款条件和办理入口。')])
def test_multiple_focus_questions_use_different_source_needs_and_dynamic_tool_order(prefix, utterance):
    req = request()
    req.context['current_request'] = utterance
    ids = [prefix + suffix for suffix in ['_shipping', '_policy', '_entry']]
    opening = {'kind': 'TURN_UNDERSTANDING', 'focus': [
        {'id': key, 'intent': intent, 'request': label, 'needs': [need]}
        for key, intent, label, need in zip(ids, ['LOGISTICS', 'ELIGIBILITY', 'APPLICATION'],
            ['运输结论', '退款条件', '办理入口'], ['SHIPMENT', 'POLICY', 'GUIDE'], strict=True)],
        'dialogue_events': [group('ADD', ids, utterance)]}
    # Guide first and policy before shipment: phase splitting does not preselect a full tool path.
    final = parts(part(ids[0], '物流有签收记录，不代表本人收到。', ['O2']),
                  part(ids[1], '签收争议须商家核验，不直接判定可退。', ['P1']),
                  part(ids[2], '正式退款入口为我的售后。', ['O1']))
    result, model, source, _ = staged(req, [opening, read('get_support_guide'),
        {'kind': 'SEARCH_POLICY', 'query': '签收争议核验条件', 'top_k': 3}, read(), final], GuideReads())
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert result['answer']['task_state']['focus_ids'] == ids
    assert [call[0] for call in source.calls] == ['get_support_guide', 'search_policy', 'get_shipment_trace']
    assert model.calls == 5


def test_stage_cannot_satisfy_source_requirement_with_a_reference_from_a_previous_run():
    req = request()
    bad = parts(part('trace', '复述旧回答的状态。', ['O9']))
    result, model, source, _ = staged(req, [understand(req), bad, bad])
    assert result['status'] == 'FAILED' and result['reason'] == 'INVALID_DECISION'
    assert source.calls == [] and model.calls == 3
