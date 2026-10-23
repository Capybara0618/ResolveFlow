"""Accept correct source-bound UI explanations and reject mismatched application routes."""

import json

import pytest

from resolveflow.support.guide import guide_source
from tests.unit.test_support_agent import GuideReads, read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_navigation import decision
from tests.unit.test_support_staged import staged, understand


@pytest.mark.parametrize('actions,text', [
    (['REFUND_APPLICATION'], '正式退款可在售后咨询核对后提交。'),
    (['REFUND_APPLICATION'], '正式退款到售后咨询提交。'),
    (['MERCHANT_REVIEW', 'REFUND_APPLICATION'], '在售后咨询中提交退款申请。'),
    (['REFUND_APPLICATION'], '正式退款申请请到“我的售后”选择对应商品，不会替您提交。'),
    (['MERCHANT_REVIEW'], '在售后咨询中选择商品，点击“请商家核查”，确认后转交。'),
    (['MERCHANT_REVIEW'], '在售后咨询中选择商品核查，不会自动提交退款申请。'),
    (['REFUND_APPLICATION'], '我的售后用于正式申请；请商家核查不会自动建退款工单。'),
    (['MERCHANT_REVIEW', 'REFUND_APPLICATION'], '核查在售后咨询办理；正式退款到我的售后。'),
])
def test_matching_page_mentions_are_published_without_rewriting_explanation(actions, text):
    from resolveflow.support.navigation import render_navigation

    result = render_navigation(decision(actions, text), {'O1': guide_source()}, strict=True)
    assert result.parts[0].text.startswith(text + '\n\n')
    assert result.parts[0].citations == ['O1']


@pytest.mark.parametrize('actions,text', [
    (['MERCHANT_REVIEW'], '打开我的售后，请商家核查。'),
    ([], '打开我的售后申请。'),
    (['MERCHANT_REVIEW', 'REFUND_APPLICATION'], '在我的售后点击请商家核查。'),
    (['MERCHANT_REVIEW', 'REFUND_APPLICATION'], '到“我的售后”页面选择“请商家核查”。'),
])
def test_pages_need_matching_steps_and_direct_crossed_routes_remain_rejected(actions, text):
    from resolveflow.support.navigation import NavigationError, render_navigation

    with pytest.raises(NavigationError):
        render_navigation(decision(actions, text), {'O1': guide_source()}, strict=True)


def test_correct_page_does_not_authorize_unobserved_guide():
    from resolveflow.support.navigation import NavigationSourceError, render_navigation

    with pytest.raises(NavigationSourceError):
        render_navigation(decision(['REFUND_APPLICATION'], '请到我的售后提交。'), {}, strict=True)


def test_wrong_route_feedback_does_not_report_an_already_observed_step_source_as_missing():
    req = request()
    bad = {**part('trace', '请在我的售后点击请商家核查。'),
           'next_steps': [{'action': 'MERCHANT_REVIEW', 'source': 'O1'}]}
    fixed = {**part('trace', '请在售后咨询选择商品并确认核查。'), 'next_steps': bad['next_steps']}
    result, model, source, _ = staged(req, [understand(req, intent='HANDOFF', needs=['GUIDE']),
        read('get_support_guide'), parts(bad), parts(fixed)], GuideReads())
    assert result['status'] == 'SUCCEEDED', result['reason']
    feedback = json.loads(model.packets[3]['feedback'])
    assert feedback['field'] == 'next_steps' and 'source_gaps' not in feedback
    assert source.calls == [('get_support_guide', {})]
