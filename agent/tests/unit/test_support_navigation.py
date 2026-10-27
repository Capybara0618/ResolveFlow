"""Model selects a read-only next step; program owns stable application instructions."""

import pytest
from pydantic import ValidationError

from resolveflow.support.guide import guide_source
from resolveflow.support.protocol import AnswerParts
from tests.unit.test_support_answer_parts import part, parts


def decision(actions, text='可以按以下方式处理。'):
    piece = part('t1', text)
    piece['next_steps'] = [{'action': action, 'source': 'O1'} for action in actions]
    return AnswerParts.model_validate(parts(piece))


def test_review_and_refund_steps_are_generated_separately_from_current_guide():
    from resolveflow.support.navigation import render_navigation

    original = decision(['MERCHANT_REVIEW', 'REFUND_APPLICATION'])
    rendered = render_navigation(original, {'O1': guide_source()}, strict=True)
    text = rendered.parts[0].text
    assert '人工核查：打开“售后咨询”' in text
    assert '正式退款：在当前会话点击“申请退款”' in text
    assert '预览并编辑' in text and '确认后' in text
    assert '不会自动提交退款申请' in text
    assert rendered.parts[0].citations == ['O1']
    assert rendered.parts[0].next_steps == []
    assert original.parts[0].text == '可以按以下方式处理。'


@pytest.mark.parametrize('source', [None, {'source_type': 'POLICY'},
    {**guide_source(), 'version': 'old'},
    {**guide_source(), 'data': {**guide_source()['data'], 'knowledge_sha256': '0' * 64}}])
def test_only_observed_current_application_guide_can_support_navigation(source):
    from resolveflow.support.navigation import NavigationError, render_navigation

    with pytest.raises(NavigationError):
        render_navigation(decision(['MERCHANT_REVIEW']), {'O1': source} if source else {}, strict=True)


@pytest.mark.parametrize('actions', [
    ['MERCHANT_REVIEW', 'MERCHANT_REVIEW'], ['REFUND_APPLICATION', 'REFUND_APPLICATION']])
def test_duplicate_steps_are_rejected(actions):
    from resolveflow.support.navigation import NavigationError, render_navigation

    with pytest.raises(NavigationError):
        render_navigation(decision(actions), {'O1': guide_source()}, strict=True)


def test_free_navigation_is_rejected_in_staged_mode_without_rewriting_it():
    from resolveflow.support.navigation import NavigationError, render_navigation

    original = decision([], text='从我的售后点击请商家核查。')
    with pytest.raises(NavigationError):
        render_navigation(original, {'O1': guide_source()}, strict=True)
    assert render_navigation(original, {}, strict=False) == original


def test_unknown_actions_and_model_supplied_urls_are_not_part_of_protocol():
    with pytest.raises(ValidationError):
        decision(['EXECUTE_REFUND'])
    value = parts({**part('t1', '说明'), 'next_steps': [
        {'action': 'MERCHANT_REVIEW', 'source': 'O1', 'url': 'https://example.invalid'}]})
    with pytest.raises(ValidationError):
        AnswerParts.model_validate(value)


@pytest.mark.parametrize('status', ['CANCELLED', 'UNAVAILABLE', 'NEEDS_CUSTOMER'])
def test_non_actionable_parts_cannot_publish_application_steps(status):
    from resolveflow.support.navigation import NavigationError, render_navigation

    selected = decision(['MERCHANT_REVIEW'])
    selected.parts[0].status = status
    with pytest.raises(NavigationError):
        render_navigation(selected, {'O1': guide_source()}, strict=True)


def test_refund_step_cannot_satisfy_required_merchant_review():
    from resolveflow.support.navigation import NavigationError, render_navigation

    with pytest.raises(NavigationError):
        render_navigation(decision(['REFUND_APPLICATION']), {'O1': guide_source()},
                          strict=True, required={'t1': 'MERCHANT_REVIEW'})


def test_ordinary_review_explanation_is_allowed_without_free_page_routes():
    from resolveflow.support.navigation import render_navigation

    text = '请商家核查不会自动创建退款工单。'
    rendered = render_navigation(decision(['REFUND_APPLICATION'], text=text),
                                 {'O1': guide_source()}, strict=True)
    assert rendered.parts[0].text.startswith(text)
    assert '正式退款：在当前会话点击“申请退款”' in rendered.parts[0].text


def test_missing_navigation_source_feedback_requires_real_read_before_resubmission():
    import json

    from tests.unit.test_support_agent import GuideReads, read, request
    from tests.unit.test_support_staged import staged, understand

    req = request()
    bad = parts({**part('trace', '运输记录仍需进一步核验。', ['O1']),
                 'next_steps': [{'action': 'MERCHANT_REVIEW', 'source': 'O1'}]})
    fixed = parts({**part('trace', '运输记录仍需进一步核验。', ['O1']),
                   'next_steps': [{'action': 'MERCHANT_REVIEW', 'source': 'O2'}]})
    result, model, source, _ = staged(req, [understand(req), read(), bad,
        read('get_support_guide'), fixed], GuideReads())
    assert result['status'] == 'SUCCEEDED', result['reason']
    feedback = json.loads(model.packets[3]['feedback'])
    assert feedback['resubmit'] == 'READ_THEN_FULL_ANSWER'
    assert feedback['required_read'] == read('get_support_guide')
    assert '不能猜' in feedback['repair_note']
    assert source.calls == [('get_shipment_trace', {}), ('get_support_guide', {})]


def test_engine_rejects_mixed_entry_and_repairs_by_selecting_source_bound_step():
    import json

    from tests.unit.test_support_agent import GuideReads, read, request
    from tests.unit.test_support_staged import staged, understand

    req = request()
    bad = parts(part('trace', '从我的售后点击请商家核查。', ['O1']))
    fixed = parts({**part('trace', '可以先让商家协助核实。'),
                   'next_steps': [{'action': 'MERCHANT_REVIEW', 'source': 'O1'}]})
    result, model, source, _ = staged(req, [understand(req, needs=['GUIDE']),
        read('get_support_guide'), bad, fixed], GuideReads())
    assert result['status'] == 'SUCCEEDED', result['reason']
    text = result['answer']['text']
    assert '打开“售后咨询”' in text and '我的售后' not in text
    assert json.loads(model.packets[3]['feedback'])['field'] == 'next_steps'
    assert source.calls == [('get_support_guide', {})]


def test_handoff_requires_matching_step_but_a_resolved_issue_only_acknowledges_close():
    from tests.unit.test_support_agent import GuideReads, read, request
    from tests.unit.test_support_event_groups import group
    from tests.unit.test_support_staged import staged, understand

    req = request()
    bad = parts(part('trace', '可以联系商家。', ['O1']))
    fixed = parts({**part('trace', '可以先让商家协助核实。'),
                   'next_steps': [{'action': 'MERCHANT_REVIEW', 'source': 'O1'}]})
    result, model, _, _ = staged(req, [understand(req, intent='HANDOFF', needs=['GUIDE']),
        read('get_support_guide'), bad, fixed], GuideReads())
    assert result['status'] == 'SUCCEEDED' and model.calls == 4
    req.context.update(previous_tasks={'origin': 'MODEL_PREVIOUS_TURN', 'input_version': 1,
        'tasks': [{'id': 'trace', 'intent': 'HANDOFF', 'request': '核查', 'status': 'ANSWERED'}]})
    closed, _, source, _ = staged(req, [understand(req, intent='HANDOFF', needs=[],
        events=[group('RESOLVE', ['trace'], req.context['current_request'])]),
        parts(part('trace', '已结束此项咨询。'))], GuideReads())
    assert closed['status'] == 'SUCCEEDED', closed['reason']
    assert source.calls == [] and closed['answer']['text'] == '已结束此项咨询。'


@pytest.mark.parametrize('status', ['PENDING', 'WAITING_CUSTOMER', 'REPLIED', 'RESOLVED'])
def test_existing_ticket_uses_current_reply_control_once(status):
    from resolveflow.support.navigation import render_navigation

    # The model can repeat an obsolete generic route; the program owns pure guide instructions.
    original = decision(['MERCHANT_REVIEW'], text='打开售后咨询，点击请商家核查，选择共享原文并确认。')
    rendered = render_navigation(original, {'O1': guide_source()}, strict=True,
        required={'t1': 'MERCHANT_REVIEW'},
        conversation_state={'has_ticket': True, 'ticket_status': status, 'current_recipient': 'ASSISTANT'})
    text = rendered.parts[0].text
    assert text.count('补充给商家') == 1 and '请商家核查' not in text
    assert '发送' in text and '不会自动提交退款申请' in text
    assert rendered.parts[0].citations == ['O1'] and original.parts[0].next_steps


def test_new_ticket_pure_guide_keeps_confirmation_and_sharing_once():
    from resolveflow.support.navigation import render_navigation

    rendered = render_navigation(decision(['MERCHANT_REVIEW'], text='打开售后咨询，点击请商家核查并预览摘要。'),
        {'O1': guide_source()}, strict=True, required={'t1': 'MERCHANT_REVIEW'},
        conversation_state={'has_ticket': False, 'ticket_status': 'NONE'})
    text = rendered.parts[0].text
    assert text.count('请商家核查') == 1 and text.count('预览并编辑') == 1
    assert '确认后才转交商家' in text and '不会默认全部共享' in text


def test_investigation_explanation_with_business_evidence_is_preserved():
    from resolveflow.support.navigation import render_navigation

    selected = decision(['MERCHANT_REVIEW'], text='物流来源明确记录了运输延迟，需要商家核实原因。')
    selected.parts[0].citations.append('O2')
    text = render_navigation(selected, {'O1': guide_source(), 'O2': {'source_type': 'SHIPMENT'}},
        strict=True, required={'t1': 'MERCHANT_REVIEW'},
        conversation_state={'has_ticket': True, 'ticket_status': 'PENDING'}).parts[0].text
    assert text.startswith(selected.parts[0].text) and '补充给商家' in text


def test_saved_live_handoff_is_rendered_for_its_actual_existing_ticket():
    import json
    from pathlib import Path

    from resolveflow.support.navigation import render_navigation

    path = Path(__file__).resolve().parents[3] / 'agent/tests/fixtures/regressions/chat-stream-live-v3/runtime-results.json'
    run = json.loads(path.read_text(encoding='utf-8'))['runs'][0]
    reply = next(c['response_json']['decision'] for c in reversed(run['calls'])
                 if c['kind'] == 'model' and c['response_json']['decision']['kind'] == 'ANSWER_PARTS')
    state = run['run']['input_json']['context']['conversation_state']
    citations = {source['source_id']: source for source in run['run']['result_json']['answer']['citations']}
    from resolveflow.support.navigation import NavigationSourceError

    with pytest.raises(NavigationSourceError):
        render_navigation(AnswerParts.model_validate(reply), citations, strict=True,
                          required={'t3': 'MERCHANT_REVIEW'}, conversation_state=state)
    # Reuse saved model text with explicitly fresh guide evidence; never relabel the frozen run.
    citations = {key: guide_source() if value['source_type'] == 'KNOWLEDGE' else value
                 for key, value in citations.items()}
    rendered = render_navigation(AnswerParts.model_validate(reply), citations, strict=True,
        required={'t3': 'MERCHANT_REVIEW'}, conversation_state=state)
    text = rendered.parts[0].text
    assert state['has_ticket'] is True
    assert text.count('补充给商家') == 1 and '请商家核查' not in text


def test_engine_reuses_frozen_ticket_state_without_another_model_or_read():
    from tests.unit.test_support_agent import GuideReads, read, request
    from tests.unit.test_support_staged import staged, understand

    req = request()
    req.context['conversation_state'] = {'has_ticket': True, 'ticket_status': 'RESOLVED'}
    piece = part('trace', '打开售后咨询，点击请商家核查并确认。', ['O1'])
    piece['next_steps'] = [{'action': 'MERCHANT_REVIEW', 'source': 'O1'}]
    result, model, source, _ = staged(req, [understand(req, intent='HANDOFF', needs=['GUIDE']),
        read('get_support_guide'), parts(piece)], GuideReads())
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert '补充给商家' in result['answer']['text'] and '请商家核查' not in result['answer']['text']
    assert model.calls == 3 and source.calls == [('get_support_guide', {})]
