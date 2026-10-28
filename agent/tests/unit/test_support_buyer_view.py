"""Presentation is not an execution permission or a second model rewriting the answer."""

import json

import pytest

from resolveflow.support.grounding import GroundingError, check_amounts, ground_answer
from resolveflow.support.protocol import AnswerParts
from resolveflow.support.stream_projection import AnswerProjection
from tests.unit.test_support_agent import read, request
from tests.unit.test_support_orchestrated_engine import respond, run
from tests.unit.test_support_orchestration import plan, source_refs


def test_refund_body_is_separate_from_the_card_and_unsolicited_model_guidance():
    req = request()
    final = respond(parts=[{'task_id': 'trace', 'text': '商家还需要核实具体情况。',
                            'guidance': '核对金额和原因后确认提交，私聊不会自动共享。'}])
    result, agent, model, _ = run([plan(req).model_dump(), read('get_order_context'), final], req)
    assert result['status'] == 'SUCCEEDED', result['reason']
    answer = result['answer']
    assert answer['text'] == '商家还需要核实具体情况。'
    assert answer['buyer_view'] == {'version': 'buyer-view-v1', 'parts': [
        {'task_id': 'trace', 'text': answer['text'], 'action': 'REFUND_APPLICATION'}]}
    assert answer['refund_summary'] == req.context['current_request']
    assert model.calls == 3 and agent.repairs == 0


def test_explicit_application_question_keeps_its_guide_answer_without_an_action():
    req = request()
    opening = plan(req, intent='OTHER', goal='EXPLAIN', needs=['GUIDE']).model_dump()
    final = {'kind': 'RESPOND', 'parts': [{'task_id': 'trace', 'text': '可以请商家核查。',
             'guidance': '先核对要共享的内容，再确认转交。', 'citations': ['O1']}]}
    result, _, model, _ = run([opening, final], req)
    assert result['status'] == 'SUCCEEDED', result['reason']
    answer = result['answer']
    assert answer['text'] == '可以请商家核查。\n\n先核对要共享的内容，再确认转交。'
    assert answer['buyer_view']['parts'][0]['guidance'] == final['parts'][0]['guidance']
    assert 'action' not in answer['buyer_view']['parts'][0]
    assert not answer.get('refund_summary') and not answer['handoff_summary']
    assert model.calls == 2


def test_ordinary_logistics_does_not_publish_unsolicited_application_guidance():
    req = request()
    opening = plan(req, intent='LOGISTICS', goal='EXPLAIN', needs=['SHIPMENT']).model_dump()
    final = {'kind': 'RESPOND', 'parts': [{'task_id': 'trace', 'text': '具体签收情况仍需商家核实。',
             'guidance': '先选择共享原文，再确认转交。'}]}
    result, _, _, _ = run([opening, read(), final], req)
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert result['answer']['text'] == final['parts'][0]['text']
    assert result['answer']['buyer_view']['parts'] == [{'task_id': 'trace', 'text': final['parts'][0]['text']}]


def test_needed_customer_question_cannot_be_hidden_in_suppressed_guidance():
    req = request()
    opening = plan(req).model_dump()
    final = respond(parts=[{'task_id': 'trace', 'text': '还需要补充信息。', 'status': 'NEEDS_CUSTOMER',
             'guidance': '请问外包装是否破损？', 'blocker': {'kind': 'CUSTOMER_INFO',
             'detail': '缺少包装情况', 'question': '请问外包装是否破损？'}}])
    result, _, _, _ = run([opening, read('get_order_context'), final, final], req)
    assert result['status'] == 'FAILED' and result['answer'] is None


def test_visible_guidance_keeps_fact_grounding_and_money_validation():
    req = request()
    raw = AnswerParts.model_validate({'kind': 'ANSWER_PARTS', 'fact_rendering': 'fields-v1', 'parts': [
        {'task_id': 'trace', 'status': 'ANSWERED', 'text': '请查看申请。', 'guidance': '本件实付{{PAID_AMOUNT}}。',
         'facts': [{'field': 'PAID_AMOUNT', 'source': 'O3'}]}]})
    result = ground_answer(raw, req, source_refs(), buyer_view=True)
    assert result.parts[0].guidance == '本件实付123.45元。'
    forged = result.model_copy(update={'parts': [result.parts[0].model_copy(update={'guidance': '退款999.00元。'})]})
    with pytest.raises(GroundingError):
        check_amounts(forged, req, source_refs())


def test_stream_projects_only_body_and_never_card_reason_or_guidance():
    projection = AnswerProjection()
    decision = {'kind': 'RESPOND', 'parts': [{'task_id': 't1', 'guidance': '共享教程不可流出',
                'text': '商家还需要核实。'}], 'refund_reason': {'customer_refs': ['private-customer-ref']}}
    deltas = []
    for char in json.dumps(decision, ensure_ascii=False):
        deltas.extend(projection.feed(char))
    projection.finish()
    assert ''.join(delta.text for delta in deltas) == '商家还需要核实。'


def test_saved_legacy_text_is_not_cut_or_classified_by_keywords():
    text = '如果你问的是如何申请，可以核对后提交；仍需商家核实条件。'
    result, _, _, _ = run([plan(request()).model_dump(), read('get_order_context'),
                          respond(parts=[{'task_id': 'trace', 'text': text}])])
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert result['answer']['text'] == text


@pytest.mark.parametrize('life', ['PAUSED', 'CANCELLED', 'RESOLVED'])
def test_inactive_guide_task_does_not_expose_steps_or_an_action(life):
    from resolveflow.support.orchestration import Orchestration, Response

    req = request()
    p = plan(req, goal='EXPLAIN', intent='OTHER', needs=['GUIDE'])
    flow = Orchestration(req)
    flow.accept(p)
    result = flow.compose(Response.model_validate({'kind': 'RESPOND', 'parts': [
        {'task_id': 'trace', 'text': '收到，已停止。', 'guidance': '确认后提交。'}]}),
        p.meaning(), source_refs(), [], {'trace': life})
    assert result.parts[0].guidance is None and result.parts[0].next_steps == []


def test_source_failure_preserves_explanation_and_blocker_but_never_application_guidance():
    from resolveflow.support.orchestration import Orchestration, Response

    req = request()
    p = plan(req)
    flow = Orchestration(req)
    flow.accept(p)
    failed = [{'tool_name': 'get_order_context', 'error': 'SOURCE_UNAVAILABLE', 'retry_allowed': False}]
    result = flow.compose(Response.model_validate({'kind': 'RESPOND', 'parts': [
        {'task_id': 'trace', 'text': '暂时查不到订单情况。', 'guidance': '先确认提交。'}]}),
        p.meaning(), {'O1': source_refs()['O1']}, failed, {})
    part = result.parts[0]
    assert part.text == '暂时查不到订单情况。' and part.status == 'UNAVAILABLE'
    assert part.blocker.tool_name == 'get_order_context'
    assert part.guidance is None and not part.next_steps and not result.refund_summary


def test_multi_issue_refund_card_does_not_suppress_an_independent_explicit_guide_question():
    from resolveflow.support.orchestration import Orchestration, Response, TurnPlan
    from resolveflow.support.presentation import buyer_view

    req = request()
    value = plan(req).model_dump()
    value['focus'].append({'id': 'privacy', 'intent': 'OTHER', 'request': '如何共享原文',
                           'goal': 'EXPLAIN', 'needs': ['GUIDE'], 'context_refs': []})
    p = TurnPlan.model_validate(value)
    flow = Orchestration(req)
    flow.accept(p)
    result = flow.compose(Response.model_validate({'kind': 'RESPOND', 'parts': [
        {'task_id': 'trace', 'text': '还需要商家核实。', 'guidance': '重复退款教程'},
        {'task_id': 'privacy', 'text': '你可以选择共享范围。', 'guidance': '勾选本次要共享的原文再确认。'}],
        'refund_reason': {'customer_quotes': [req.context['current_request']]}}), p.meaning(), source_refs(), [], {})
    view = buyer_view(result)
    assert view['parts'][0] == {'task_id': 'trace', 'text': '还需要商家核实。', 'action': 'REFUND_APPLICATION'}
    assert view['parts'][1]['guidance'] == '勾选本次要共享的原文再确认。'
