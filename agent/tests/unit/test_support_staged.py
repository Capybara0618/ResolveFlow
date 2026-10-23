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


def test_optional_branch_queries_are_one_sdk_action_without_an_extra_model_round():
    class Branches(Reads):
        def search(self, query, top_k, *, sub_queries=None):
            self.calls.append(('search_policy', {'query': query, 'top_k': top_k, 'sub_queries': sub_queries}))
            return [{'source_type': 'POLICY', 'version': 'v1', 'data': {'text': text}}
                    for text in ['当前状态不足以认定丢失。', '假设确认丢失后仍须人工核验。']]

    req = request()
    queries = ['当前在途的适用条件', '假如以后确认丢失的条件']
    action = read('search_policy', query='当前与假设两类条件', sub_queries=queries, top_k=3)
    result, model, source, _ = staged(req, [understand(req, intent='OTHER', needs=['POLICY']),
        action, parts(part('trace', '目前与假设条件分别说明，尚未认定退款资格。', ['P1', 'P2']))], Branches())
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert model.calls == 3 and source.calls == [('search_policy', {
        'query': '当前与假设两类条件', 'sub_queries': queries, 'top_k': 3})]
    assert model.packets[-1]['stage']['policy_scope'] == {'trace': 'CONDITIONS'}


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


def test_followup_carries_explicit_history_scope_without_making_it_a_business_fact():
    req = request()
    req.context['history'] = [{'sequence': 1, 'author': 'ASSISTANT', 'text': '上一轮讨论运输延迟。'}]
    opening = understand(req, intent='OTHER', needs=['POLICY'])
    opening['focus'][0]['context_refs'] = ['H1']
    result, model, _, _ = staged(req, [opening, read('search_policy', query='相关条件'),
        parts(part('trace', '沿用上轮讨论，只解释条件。', ['P1']))])
    assert result['status'] == 'SUCCEEDED', result['reason']
    packet = model.packets[-1]
    assert packet['stage']['focus'][0]['context_refs'] == ['H1']
    assert packet['recent_messages'][0]['read_ref'] == 'H1' and packet['fact_view'] == []


def test_unknown_history_scope_is_rejected_before_any_meaning_state_is_committed():
    req = request()
    opening = understand(req, needs=['POLICY'])
    opening['focus'][0]['context_refs'] = ['H999']
    result, _, source, agent = staged(req, [opening, opening])
    assert result['status'] == 'FAILED' and result['reason'] == 'INVALID_DECISION'
    assert agent.tasks.tasks == [] and source.calls == [] and agent.stage.understanding is None


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
    fixed = part('trace', '可以进一步由商家核验。', ['O1', 'O2'])
    fixed['next_steps'] = [{'action': 'MERCHANT_REVIEW', 'source': 'O2'}]
    final = parts(fixed)
    result, model, source, _ = staged(req, [opening, read(),
        parts(part('trace', '物流记录已查看，可进一步核查。', ['O1'])), read('get_support_guide'), final], GuideReads())
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
    entry = part(ids[2], '正式申请需要你核对后自行提交。', ['O1'])
    entry['next_steps'] = [{'action': 'REFUND_APPLICATION', 'source': 'O1'}]
    final = parts(part(ids[0], '物流有签收记录，不代表本人收到。', ['O2']),
                  part(ids[1], '签收争议须商家核验，不直接判定可退。', ['P1']),
                  entry)
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
