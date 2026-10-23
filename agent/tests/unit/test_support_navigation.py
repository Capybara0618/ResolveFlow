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
