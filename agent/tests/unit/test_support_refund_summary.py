"""An accepted application answer can offer a reason, but never create or authorize a refund."""

from tests.unit.test_support_agent import GuideReads, read, request
from tests.unit.test_support_answer_parts import part, parts
from tests.unit.test_support_staged import staged, understand


def test_application_summary_survives_publication_without_an_extra_model_round():
    req = request()
    value = parts({**part('trace', '可核对申请摘要后自行确认。', ['O1']),
                   'next_steps': [{'action': 'REFUND_APPLICATION', 'source': 'O1'}]})
    value['refund_summary'] = '客户反馈商品未收到，希望核实签收后退款。'
    result, model, sources, _ = staged(req, [understand(req, intent='APPLICATION', needs=['GUIDE']),
        read('get_support_guide'), value], GuideReads())
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert result['answer']['refund_summary'] == value['refund_summary']
    assert result['answer']['handoff_summary'] is None
    assert model.calls == 3 and sources.calls == [('get_support_guide', {})]
    assert '确认提交申请' in result['answer']['text']


def test_unselected_application_summary_is_rejected_then_repaired_not_silently_published():
    req = request()
    bad = {**parts(part('trace', '先核实情况。')), 'refund_summary': '请立即退款'}
    result, model, sources, agent = staged(req, [understand(req, intent='OTHER', needs=[]),
        bad, parts(part('trace', '请补充你需要了解的问题。'))], GuideReads())
    assert result['status'] == 'SUCCEEDED', result['reason']
    assert 'refund_summary' not in result['answer']
    assert model.calls == 3 and agent.repairs == 1 and sources.calls == []


def test_invalid_application_result_never_exposes_a_summary():
    req = request()
    bad = {**parts(part('trace', '先核实情况。')), 'refund_summary': '请立即退款'}
    result, _, _, _ = staged(req, [understand(req, intent='OTHER', needs=[]), bad, bad], GuideReads())
    assert result['status'] == 'FAILED' and result['answer'] is None
