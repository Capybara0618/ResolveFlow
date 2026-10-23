"""Historical v2 diagnostic profile; current v3 rejects v2 evidence in navigation tests."""

import hashlib
import json
from importlib.resources import files

from scripts.customer_agent_navigation_diagnose_v1 import diagnose


def test_saved_decisions_distinguish_overblocking_from_a_still_unread_guide(monkeypatch):
    from resolveflow.support import navigation

    raw = files('resolveflow.assets').joinpath('support-guide-v2.json').read_bytes()
    guide = json.loads(raw)
    source = {'source_type': 'KNOWLEDGE', 'version': guide['version'], 'title': '售后咨询使用指南',
              'data': {**{k: v for k, v in guide.items() if k != 'version'},
                       'knowledge_sha256': hashlib.sha256(raw).hexdigest()}}
    # Preserve the frozen diagnostic's historical UI rules explicitly, never upgrade its source version.
    monkeypatch.setattr(navigation, 'guide_source', lambda: source)
    monkeypatch.setattr(navigation, 'PAGE_ACTIONS', {
        '售后咨询': {'MERCHANT_REVIEW'}, '我的售后': {'REFUND_APPLICATION'}})
    monkeypatch.setitem(navigation.INSTRUCTIONS, 'REFUND_APPLICATION',
        '正式退款：打开“我的售后”，选择对应订单商品，核对申请内容后自行提交。'
        '聊天表达退款意愿或转交人工核查不会自动创建退款工单；助手没有替你提交申请。')
    monkeypatch.setattr(navigation, 'DIRECT_CROSSED_ROUTES', navigation.DIRECT_CROSSED_ROUTES + (
        r'售后咨询[”」"\']?(?:页面)?[中里内的]?\s*[，,:：→-]*\s*(?:提交|发起)(?:正式)?退款(?:申请|工单)?',))
    value = diagnose()
    assert value['new_provider_calls'] == value['business_writes'] == 0
    assert value['not_strict_replay']
    current = [r for r in value['rows'] if r['source_version'] == 'customer-agent-navigation-v1']
    assert [r['offline_status'] for r in current] == ['FAILED', *['SUCCEEDED'] * 5]
    assert current[0]['feedback'][0]['required_read']['tool_name'] == 'get_support_guide'
    assert sum(r['original_published'] for r in current) == 3
    old = [r for r in value['rows'] if r['source_version'] == 'customer-agent-correction-v1']
    assert len(old) == 2 and all(r['offline_status'] == 'FAILED' for r in old)
