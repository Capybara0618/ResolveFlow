"""Keep the observed regressions and reject the original mixed routes under revised validation."""

from scripts.customer_agent_navigation_diagnose_v1 import diagnose


def test_saved_decisions_distinguish_overblocking_from_a_still_unread_guide():
    value = diagnose()
    assert value['new_provider_calls'] == value['business_writes'] == 0
    assert value['not_strict_replay']
    current = [r for r in value['rows'] if r['source_version'] == 'customer-agent-navigation-v1']
    assert [r['offline_status'] for r in current] == ['FAILED', *['SUCCEEDED'] * 5]
    assert current[0]['feedback'][0]['required_read']['tool_name'] == 'get_support_guide'
    assert sum(r['original_published'] for r in current) == 3
    old = [r for r in value['rows'] if r['source_version'] == 'customer-agent-correction-v1']
    assert len(old) == 2 and all(r['offline_status'] == 'FAILED' for r in old)
