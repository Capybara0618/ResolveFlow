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
    assert '正式退款：打开“我的售后”' in text
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
