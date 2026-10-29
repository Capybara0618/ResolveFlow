import copy
import json
import pytest
from resolveflow.contracts._schemaio import REPO_ROOT, component_validator, load_openapi

FIXTURES = json.loads((REPO_ROOT / 'contracts/core/fixtures/presentation.json').read_text(encoding='utf-8'))

@pytest.mark.parametrize('name', sorted(FIXTURES))
def test_presentation_fixtures(name):
    validator = component_validator('presentation', name, 'contracts/core')
    assert validator.accepts(FIXTURES[name]), validator.error_messages(FIXTURES[name])

def test_publication_writes_reject_foreign_scope_and_duplicate_or_unbounded_gallery():
    body = copy.deepcopy(FIXTURES['ProductPresentation'])
    body.pop('product_id')
    body['expected_version'] = body.pop('version')
    validator = component_validator('presentation', 'ProductPresentationWrite', 'contracts/core')
    assert validator.accepts(body)
    assert not validator.accepts({**body, 'merchant_id': 'other'})
    assert not validator.accepts({**body, 'images': body['images'] * 2})
    assert not validator.accepts({**body, 'specifications': body['specifications'] * 21})

def test_registration_and_recovery_do_not_accept_a_role_or_return_a_login_token():
    register = component_validator('account', 'RegistrationRequest', 'contracts/core')
    body = {'username': 'test-buyer', 'display_name': '测试买家', 'password': 'test-password'}
    assert register.accepts(body)
    assert not register.accepts({**body, 'role': 'PLATFORM_ADMIN'})
    receipt = component_validator('account', 'RecoveryReceipt', 'contracts/core')
    assert receipt.accepts({'username': 'test-buyer', 'recovery_key': 'a' * 64})
    assert not receipt.accepts({'username': 'test-buyer', 'recovery_key': 'a' * 64, 'access_token': 'secret'})
    paths = load_openapi('account', 'contracts/core')['paths']
    assert paths['/api/v1/auth/register']['post']['security'] == []
    assert paths['/api/v1/auth/recover']['post']['security'] == []
