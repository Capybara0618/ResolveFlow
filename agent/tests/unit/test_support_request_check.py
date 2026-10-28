"""Request intent is checked separately from the planner's goal and literal quote provenance."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from resolveflow.harness.budget import RunBudget
from resolveflow.support.engine import SupportAgent
from resolveflow.support.orchestration import Orchestration, Response, TurnPlan
from resolveflow.support.progress import ProgressReporter
from resolveflow.support.protocol import SupportInput
from tests.integration.test_support_dialogue_api import TokenizedScript
from tests.unit.test_support_agent import request
from tests.unit.test_support_orchestrated_engine import Sources
from tests.unit.test_support_orchestration import plan, source_refs


def saved_failure():
    path = Path(__file__).parents[1] / 'fixtures/regressions/buyer-view-live-v1/signed-overeager-review.json'
    row = json.loads(path.read_text(encoding='utf-8'))
    req = SupportInput.model_validate({**row['input'], 'deadline_at': request().deadline_at})
    return req, deepcopy(row['decisions'])


def check(purpose='INFORMATION', quote='现在应该找谁帮我', task_id='t1'):
    return {'kind': 'CHECK_REQUEST', 'assessments': [{'task_id': task_id, 'purpose': purpose,
            'quote': quote, 'reason': '核对本轮原话所表达的用途。'}]}


class MatchingSources(Sources):
    def __init__(self, req):
        super().__init__()
        self.req = req

    def read(self, name, arguments):
        result = super().read(name, arguments)
        data = result.get('data', {})
        if 'order_line' in data:
            data['order_line']['line_id'] = self.req.line_id
        if 'line_id' in data:
            data['line_id'] = self.req.line_id
        return result


def test_recorded_overeager_plan_cannot_go_straight_to_artifact_or_fact_reads():
    req, decisions = saved_failure()
    model = TokenizedScript(mode='live', script=decisions)
    sources = Sources()
    agent = SupportAgent(req, model, sources, architecture='orchestrated-v1')
    result = agent.run()
    assert model.packets[1]['orchestration']['phase'] == 'CHECK_REQUEST'
    assert result['answer'] is None
    assert sources.calls == [('get_support_guide', {})]


def test_original_literal_quote_checked_as_information_removes_the_operation_goal():
    req, decisions = saved_failure()
    # Facts and final language are scripted here; only the original mistaken plan is replayed.
    # This is an offline gate regression, not a new live semantic-quality claim.
    final = {'kind': 'RESPOND', 'parts': [{'task_id': 't1',
             'text': '你可以先联系商家，让商家协助核实具体签收情况。', 'citations': ['P1']}]}
    model = TokenizedScript(mode='live', script=[decisions[0], check(), decisions[1], final])
    agent = SupportAgent(req, model, MatchingSources(req), architecture='orchestrated-v1')
    result = agent.run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert agent.orchestration.goals == {'t1': 'EXPLAIN'}
    assert result['answer']['handoff_summary'] is None
    assert 'refund_summary' not in result['answer']
    assert 'action' not in result['answer']['buyer_view']['parts'][0]
    assert result['spend']['model_calls'] == 4
    packet = model.packets[1]
    assert 'stage' not in packet and 'observations' not in packet and 'summary_candidates' not in packet
    assert 'goal' not in packet['orchestration']['request_check']['tasks'][0]


@pytest.mark.parametrize('text,goal,intent,purpose,action', [
    ('耳机没收到，能帮我整理给商家的情况吗？先别发。', 'MERCHANT_REVIEW', 'HANDOFF',
     'MERCHANT_REVIEW', 'MERCHANT_REVIEW'),
    ('耳机没收到，能帮我整理退款原因吗？先不要提交。', 'PREPARE_REFUND', 'APPLICATION',
     'PREPARE_REFUND', 'REFUND_APPLICATION'),
    ('耳机没收到，帮我申请退款。', 'PREPARE_REFUND', 'APPLICATION',
     'PREPARE_REFUND', 'REFUND_APPLICATION'),
    ('如果耳机没收到，我应该找谁帮忙？', 'MERCHANT_REVIEW', 'HANDOFF', 'INFORMATION', None),
    ('昨天说要核查，今天先不办，只问一下入口。', 'MERCHANT_REVIEW', 'HANDOFF', 'DECLINED', None),
    ('耳机没收到，帮我处理一下。', 'MERCHANT_REVIEW', 'HANDOFF', 'UNCLEAR', None),
    ('耳机没收到，帮我整理退款原因。', 'MERCHANT_REVIEW', 'HANDOFF', 'PREPARE_REFUND', None),
])
def test_assessed_purpose_gates_artifacts_without_question_mark_or_keyword_rules(text, goal, intent, purpose, action):
    req = request()
    req.context['current_request'] = text
    opening = plan(req, intent=intent, goal=goal).model_dump()
    final = {'kind': 'RESPOND', 'parts': [{'task_id': 'trace', 'text': '具体情况还需要商家核实。'}]}
    if action:
        field = 'refund_reason' if action == 'REFUND_APPLICATION' else 'handoff_reason'
        final[field] = {'customer_quotes': ['耳机没收到']}
    script = [opening, check(purpose, text, 'trace')]
    if goal == 'PREPARE_REFUND':
        script.append({'kind': 'READ_TOOL', 'tool_name': 'get_order_context', 'arguments': {}})
    model = TokenizedScript(mode='live', script=[*script, final])
    agent = SupportAgent(req, model, Sources(), architecture='orchestrated-v1')
    result = agent.run()
    assert result['status'] == 'SUCCEEDED', result['reason']
    part = result['answer']['buyer_view']['parts'][0]
    assert part.get('action') == action
    assert bool(result['answer'].get('refund_summary') or result['answer']['handoff_summary']) == bool(action)
    assert agent.repairs == 0


def test_batch_check_is_atomic_complete_and_bound_to_current_customer_text():
    req = request()
    p = plan(req).model_dump()
    p['focus'].append({'id': 'merchant', 'intent': 'HANDOFF', 'request': '准备商家核查',
                       'goal': 'MERCHANT_REVIEW', 'operation_request': req.context['current_request'], 'needs': []})
    p['dialogue_events'][0]['task_ids'].append('merchant')
    p = TurnPlan.model_validate(p)
    flow = Orchestration(req)
    flow.accept(p)
    a = check('PREPARE_REFUND', req.context['current_request'], 'trace')['assessments'][0]
    b = {**a, 'task_id': 'merchant', 'purpose': 'MERCHANT_REVIEW'}
    for items in [[a], [a, a], [a, {**b, 'task_id': 'other'}], [a, {**b, 'quote': '历史助手建议退款'}]]:
        with pytest.raises(ValueError):
            flow.check_requests({'kind': 'CHECK_REQUEST', 'assessments': items}, p.meaning(), {})
        assert not flow.checked_requests and not flow.request_checks and flow.request_check_rounds == 0
    flow.check_requests({'kind': 'CHECK_REQUEST', 'assessments': [a, {**b, 'purpose': 'INFORMATION'}]},
                         p.meaning(), {})
    assert flow.goals == {'trace': 'PREPARE_REFUND', 'merchant': 'EXPLAIN'}
    assert flow.required_actions({}) == {'trace': 'REFUND_APPLICATION'}


def test_unchecked_compilation_and_actions_are_blocked_even_with_all_evidence_ready():
    req = request()
    p = plan(req)
    flow = Orchestration(req)
    flow.accept(p)
    assert flow.required_actions({}) == {}
    assert flow.snapshot(p.meaning(), source_refs(), [], {})['phase'] == 'CHECK_REQUEST'
    with pytest.raises(ValueError, match='not ready'):
        flow.compose(Response.model_validate({'kind': 'RESPOND', 'parts': [{'task_id': 'trace', 'text': '待核对。'}],
                     'refund_reason': {'customer_quotes': [req.context['current_request']]}}),
                     p.meaning(), source_refs(), [], {})


def test_goal_correction_cannot_bypass_recheck_or_reuse_approval_for_a_different_action():
    req = request()
    p = plan(req)
    flow = Orchestration(req)
    flow.accept(p)
    flow.check_requests(check('PREPARE_REFUND', req.context['current_request'], 'trace'), p.meaning(), {})
    from resolveflow.support.orchestration import GoalConflict

    with pytest.raises(GoalConflict):
        flow.compose(Response.model_validate({'kind': 'RESPOND', 'parts': [{'task_id': 'trace', 'text': '待核对。'}],
                     'handoff_reason': {'customer_quotes': [req.context['current_request']]}}),
                     p.meaning(), source_refs(), [], {})
    meaning = flow.review_goal({'kind': 'REVIEW_GOAL', 'task_id': 'trace', 'previous_goal': 'PREPARE_REFUND',
        'goal': 'MERCHANT_REVIEW', 'operation_request': req.context['current_request'], 'reason': '核对用途。'},
        p.meaning(), {})
    assert flow.snapshot(meaning, source_refs(), [], {})['phase'] == 'CHECK_REQUEST'
    assert flow.required_actions({}) == {}
    flow.check_requests(check('INFORMATION', req.context['current_request'], 'trace'), meaning, {})
    assert flow.goals == {'trace': 'EXPLAIN'} and flow.request_check_rounds == 2


def test_purpose_check_uses_existing_model_budget_and_never_resets_it():
    req = request()
    model = TokenizedScript(mode='live', script=[plan(req).model_dump()])
    sources = Sources()
    result = SupportAgent(req, model, sources, architecture='orchestrated-v1', budget=RunBudget(model_calls=1)).run()
    assert result['reason'] == 'BUDGET_MODEL_CALLS' and result['answer'] is None
    assert model.calls == result['spend']['model_calls'] == 1
    assert sources.calls == [('get_support_guide', {})]


def test_check_reason_is_private_and_only_ready_reply_is_streamed():
    batches = []
    reporter = ProgressReporter('http://synthetic.invalid', 'run', 'test', transport=httpx.MockTransport(
        lambda r: (batches.append(json.loads(r.content)) or httpx.Response(200))))

    class Stream(TokenizedScript):
        def decide(self, **kwargs):
            reply = super().decide(**kwargs)
            reporter.content(json.dumps(reply.decision, ensure_ascii=False))
            return reply

    req, decisions = saved_failure()
    final = {'kind': 'RESPOND', 'parts': [{'task_id': 't1', 'text': '你可以先请商家协助核实。'}]}
    model = Stream(mode='live', script=[decisions[0], check(), decisions[1], final])
    try:
        result = SupportAgent(req, model, MatchingSources(req), architecture='orchestrated-v1',
                              progress=reporter).run()
    finally:
        reporter.close()
    assert result['status'] == 'SUCCEEDED', result['reason']
    events = [event for batch in batches for event in batch['events']]
    assert ''.join(e['payload']['text'] for e in events if e['kind'] == 'answer.delta') == final['parts'][0]['text']
    assert {e['attempt_id'] for e in events if e['kind'] == 'answer.delta'} == {'model-4'}


def test_mock_script_loader_checks_request_assessment_schema(monkeypatch, tmp_path):
    from resolveflow.runtime.factory import DeploymentConfig
    from resolveflow.support.service import SupportRuntime

    script = [check()]
    path = tmp_path / 'script.json'
    path.write_text(json.dumps(script, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setenv('RESOLVEFLOW_SUPPORT_MOCK_SCRIPT', str(path))
    runtime = SupportRuntime(None, DeploymentConfig(mode='mock'), architecture='orchestrated-v1')
    assert runtime._model().script == script
