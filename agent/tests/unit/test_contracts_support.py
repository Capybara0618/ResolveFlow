import json

import pytest

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator, load_openapi

FIXTURES = json.loads((REPO_ROOT / 'contracts/core/fixtures/support.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('name', sorted(FIXTURES))
def test_support_wires_are_closed_and_match_shared_fixture(name):
    validator = component_validator('case', 'Support' + name, 'contracts/core')
    assert validator.accepts(FIXTURES[name]), validator.error_messages(FIXTURES[name])
    assert not validator.accepts({**FIXTURES[name], 'buyer_id': 'foreign'})


@pytest.mark.parametrize('name', ['Handoff', 'Conversation', 'TicketDetail'])
def test_assistant_and_confirmed_report_wires(name):
    fixtures = json.loads((REPO_ROOT / 'contracts/core/fixtures/support-assistant.json').read_text(encoding='utf-8'))
    validator = component_validator('case', 'Support' + name, 'contracts/core')
    assert validator.accepts(fixtures[name]), validator.error_messages(fixtures[name])


@pytest.mark.parametrize('name', ['Send', 'Handoff', 'Reply', 'Resolve'])
def test_support_writes_refuse_invalid_versions_and_user_authority(name):
    validator = component_validator('case', 'Support' + name, 'contracts/core')
    for version in [None, 0, -1, 1.5]:
        assert not validator.accepts({**FIXTURES[name], 'expected_version': version})
    for field in ['merchant_id', 'customer_id', 'run_id', 'refund_amount', 'author']:
        assert not validator.accepts({**FIXTURES[name], field: 'forged'})


def test_support_routes_are_authenticated_and_keyed_with_no_refund_execution():
    doc = load_openapi('case', 'contracts/core')
    paths = {p: item for p, item in doc['paths'].items() if p.startswith('/api/v1/support/')}
    assert len(paths) == 14
    assert sum(len(item) for item in paths.values()) == 15
    for path, item in paths.items():
        for method, operation in item.items():
            assert operation['security'] == [{'bearerAuth': []}]
            if path.endswith('/events'):
                assert method == 'get'
                assert {'200', '401', '404'} <= operation['responses'].keys()
                assert 'text/event-stream' in operation['responses']['200']['content']
                assert any(p['name'] == 'Last-Event-ID' for p in operation['parameters'])
            else:
                assert {'400', '401', '403', '404', '409', '503'} <= operation['responses'].keys()
            if method == 'post' and path != '/api/v1/support/conversations':
                assert any(p['name'] == 'Idempotency-Key' and p['required'] for p in operation['parameters'])
    assert all('execute' not in path and 'approve' not in path for path in paths)


def test_private_stream_envelope_matches_shared_fixture_and_has_no_write_authority():
    fixtures = json.loads((REPO_ROOT / 'contracts/core/fixtures/support-stream.json').read_text(encoding='utf-8'))
    validator = component_validator('case', 'SupportStreamEvent', 'contracts/core')
    for event in fixtures.values():
        assert validator.accepts(event), validator.error_messages(event)
        assert not validator.accepts({**event, 'refund_amount': 123})
        assert not validator.accepts({**event, 'event_id': -1})
        assert not validator.accepts({**event, 'kind': 'REFUND_EXECUTE'})
    conversation = component_validator('case', 'SupportConversation', 'contracts/core')
    assert conversation.accepts(fixtures['snapshot']['payload']['conversation'])
