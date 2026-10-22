"""Finite business completion checks, using actual sources rather than answer keyword matching."""

import datetime as dt
import json
from copy import deepcopy
from pathlib import Path

import pytest

from resolveflow.harness.model import MockModelClient
from resolveflow.support.engine import SupportAgent
from resolveflow.support.guide import guide_source
from resolveflow.support.protocol import SupportInput, SupportTask
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import Reads, answer, read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_event_groups import group
from tests.unit.test_support_tasks import task


class GuideReads(Reads):
    def read(self, name, arguments):
        if name == 'get_support_guide':
            self.calls.append((name, arguments))
            return guide_source()
        return super().read(name, arguments)


def first(req, tasks, *values):
    return parts(*values, tasks=tasks,
                 dialogue_events=[group('ADD', [t['id'] for t in tasks], req.context['current_request'])])


@pytest.mark.parametrize('case_id', ['U02', 'U03'])
def test_saved_incomplete_process_answers_do_not_publish_and_can_read_guide_after_feedback(case_id):
    report = json.loads((Path(__file__).resolve().parents[3]
                         / 'reports/customer-agent-experience-v1/runtime-results.json').read_text(encoding='utf-8'))
    row = next(r for r in report['rows'] if r['id'] == case_id)
    req = SupportInput.model_validate({**row['input'],
                                      'deadline_at': dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120)})
    final = deepcopy(row['models'][-1]['decision'])

    class Saved(GuideReads):
        def read(self, name, arguments):
            if name == 'get_support_guide':
                return super().read(name, arguments)
            self.calls.append((name, arguments))
            return next(t['result'] for t in row['tools'] if t['name'] == name)

        def search(self, query, top_k):
            return row['tools'][-1]['result']

    script = [m['decision'] for m in row['models']]
    guide_ref = 'O3' if case_id == 'U02' else 'O1'
    fixed = deepcopy(final)
    if case_id == 'U03':
        fixed['tasks'][0]['intent'] = 'HANDOFF'
    for p, t in zip(fixed['parts'], fixed['tasks'], strict=True):
        if t['intent'] == 'APPLICATION' or case_id == 'U03':
            p.update(status='ANSWERED', text='正式退款去我的售后；独立核查可请商家核查，预览共享摘要并确认。',
                     citations=[guide_ref])
    model = TokenizedScript(mode='live', script=[*script, read('get_support_guide'), fixed])
    result = SupportAgent(req, model, Saved()).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    rejected = model.packets[len(script)]
    assert rejected['task_state']['tasks'] == []
    feedback = json.loads(rejected['feedback'])
    assert feedback['code'] == 'TASK_COMPLETION_INCOMPLETE'
    assert any(g['code'] == 'SOURCE_REQUIRED' and g['tool_name'] == 'get_support_guide'
               for g in feedback['gaps'])
    assert result['answer']['text'] != row['result']['answer']['text']


def test_customer_wait_requires_explicit_question_in_this_answer_and_stays_a_customer_claim():
    req = request()
    missing = first(req, [task('proof')], part('proof', '请提供外包装照片。', status='NEEDS_CUSTOMER'))
    fixed = deepcopy(missing)
    fixed['parts'][0]['blocker'] = {'kind': 'CUSTOMER_INFO', 'detail': '缺少客户材料', 'question': '请提供外包装照片。'}
    model = MockModelClient(mode='live', script=[missing, fixed])
    result = SupportAgent(req, model, Reads()).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert json.loads(model.packets[1]['feedback'])['gaps'][0]['code'] == 'CUSTOMER_QUESTION_REQUIRED'
    assert result['answer']['task_state']['tasks'][0]['blocker'] == fixed['parts'][0]['blocker']
    assert result['answer']['customer_memory']['entries'] == []
    absent = deepcopy(fixed)
    absent['parts'][0]['blocker']['question'] = '正文没有这个问题'
    bad = SupportAgent(req, MockModelClient(mode='live', script=[absent, absent]), Reads()).run()
    assert bad['reason'] == 'INVALID_DECISION'


@pytest.mark.parametrize('actual_tool', ['get_shipment_trace', 'get_support_guide'])
def test_unavailable_must_match_actual_relevant_failure_and_can_explain_guide_outage(actual_tool):
    class Outage(Reads):
        def read(self, name, arguments):
            self.calls.append((name, arguments))
            return {'error': 'SOURCE_UNAVAILABLE', 'retryable': True}

    req = request()
    p = {**part('entry', '入口指南暂时不可用。', status='UNAVAILABLE'),
         'blocker': {'kind': 'SOURCE_FAILURE', 'detail': '工具无法取得指南', 'tool_name': actual_tool}}
    final = first(req, [task('entry', 'APPLICATION')], p)
    model = MockModelClient(mode='live', script=[read(actual_tool), final, final])
    result = SupportAgent(req, model, Outage()).run()
    if actual_tool == 'get_support_guide':
        assert result['status'] == 'SUCCEEDED', result['reason']
    else:
        assert result['reason'] == 'INVALID_DECISION'


def test_recovered_source_failure_cannot_remain_a_blocker_and_answer_cannot_bypass_with_legacy_kind():
    class Recovers(GuideReads):
        def read(self, name, arguments):
            if not self.calls:
                self.calls.append((name, arguments))
                return {'error': 'SOURCE_UNAVAILABLE', 'retryable': True}
            return super().read(name, arguments)

    req = request()
    blocked = task('entry', 'APPLICATION', 'UNAVAILABLE', response_excerpt='指南不可用',
                   blocker={'kind': 'SOURCE_FAILURE', 'detail': '失败', 'tool_name': 'get_support_guide'})
    final = answer(text='指南不可用', citations=[], tasks=[blocked],
                   dialogue_events=[group('ADD', ['entry'], req.context['current_request'])])
    model = TokenizedScript(mode='live', script=[read('get_support_guide'), read('get_support_guide'), final, final])
    assert SupportAgent(req, model, Recovers()).run()['reason'] == 'INVALID_DECISION'


def test_eligibility_needs_policy_but_plain_logistics_and_cancellation_do_not_force_guide():
    req = request()
    final = first(req, [task('refund', 'ELIGIBILITY')], part('refund', '可以退款', ['O1']))
    model = MockModelClient(mode='live', script=[read(), final, final])
    result = SupportAgent(req, model, Reads()).run()
    assert result['reason'] == 'INVALID_DECISION'
    assert json.loads(model.packets[2]['feedback'])['gaps'][0]['tool_name'] == 'search_policy'
    simple = first(req, [task('trace')], part('trace', '系统有签收记录。', ['O1']))
    source = Reads()
    result = SupportAgent(req, MockModelClient(mode='live', script=[read(), simple]), source).run()
    assert result['status'] == 'SUCCEEDED'
    assert source.calls == [('get_shipment_trace', {})]
    req.context['previous_tasks'] = {'origin': 'MODEL_PREVIOUS_TURN', 'input_version': 1,
                                      'tasks': [task('review', 'HANDOFF', 'NEEDS_MERCHANT')]}
    cancel = parts(part('review', '停止核查。', status='CANCELLED'), tasks=[task('review', 'HANDOFF')],
                   dialogue_events=[group('CANCEL', ['review'], req.context['current_request'])])
    source = Reads()
    assert SupportAgent(req, MockModelClient(mode='live', script=[cancel]), source).run()['status'] == 'SUCCEEDED'
    assert source.calls == []


def test_declared_pending_task_exposes_completion_requirements_without_forcing_the_next_read():
    req = request()
    start = {**read(), 'tasks': [task('entry', 'APPLICATION')],
             'dialogue_events': [group('ADD', ['entry'], req.context['current_request'])]}
    final = parts(part('entry', '正式退款请到我的售后。', ['O2']))
    model = TokenizedScript(mode='live', script=[start, read('get_support_guide'), final])
    result = SupportAgent(req, model, GuideReads()).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    rules = model.packets[1]['answer_requirements']
    assert rules['unresolved'] == [{'task_id': 'entry', 'status': 'PENDING'}]
    assert rules['completion']['APPLICATION/HANDOFF'] == 'get_support_guide引用'
    assert rules['available_sources'] == {'O1': 'SHIPMENT'}
    assert SupportTask.model_validate(task('old')).model_dump() == task('old')


def test_guide_elsewhere_in_answer_does_not_support_an_unbound_application_task():
    req = request()
    final = first(req, [task('entry', 'APPLICATION'), task('other', 'OTHER')],
                  part('entry', '正式申请请到我的售后。'), part('other', '另一个回答。', ['O1']))
    model = TokenizedScript(mode='live', script=[read('get_support_guide'), final, final])
    assert SupportAgent(req, model, GuideReads()).run()['reason'] == 'INVALID_DECISION'


def test_empty_policy_result_is_not_a_source_failure():
    class Empty(Reads):
        def search(self, query, top_k):
            return []

    req = request()
    value = {**part('refund', '政策来源不可用。', status='UNAVAILABLE'), 'blocker': {
        'kind': 'SOURCE_FAILURE', 'detail': '没有结果', 'tool_name': 'search_policy'}}
    final = first(req, [task('refund', 'ELIGIBILITY')], value)
    model = TokenizedScript(mode='live', script=[read('search_policy', query='退款资格'), final, final])
    assert SupportAgent(req, model, Empty()).run()['reason'] == 'INVALID_DECISION'


def test_legacy_answer_without_task_field_checks_the_actual_accepted_tasks():
    req = request()
    initial = {**read(), 'tasks': [task('entry', 'APPLICATION', 'ANSWERED', response_excerpt='入口已说明')],
               'dialogue_events': [group('ADD', ['entry'], req.context['current_request'])]}
    final = answer(text='入口已说明', citations=[])
    model = TokenizedScript(mode='live', script=[initial, final, final])
    result = SupportAgent(req, model, Reads()).run()
    assert result['reason'] == 'INVALID_DECISION'
    assert json.loads(model.packets[2]['feedback'])['gaps'][0]['task_id'] == 'entry'


def test_customer_question_at_end_of_long_part_remains_bound_to_that_part():
    req = request()
    question = '您方便提供外包装照片吗？'
    value = {**part('photo', '说明。' * 160 + question, status='NEEDS_CUSTOMER'), 'blocker': {
        'kind': 'CUSTOMER_INFO', 'detail': '缺少材料', 'question': question}}
    final = first(req, [task('photo')], value)
    result = SupportAgent(req, TokenizedScript(mode='live', script=[final]), Reads()).run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert result['answer']['task_state']['tasks'][0]['response_excerpt'] == question
    wrong = first(req, [task('photo'), task('other', 'OTHER')],
                  {**value, 'text': '需要补充材料。'}, part('other', question))
    model = TokenizedScript(mode='live', script=[wrong, wrong])
    assert SupportAgent(req, model, Reads()).run()['reason'] == 'INVALID_DECISION'
