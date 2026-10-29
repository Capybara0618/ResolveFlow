import json
import pytest
from resolveflow.contracts._schemaio import REPO_ROOT, component_validator

FIXTURES = json.loads((REPO_ROOT / 'contracts/core/fixtures/account.json').read_text(encoding='utf-8'))

@pytest.mark.parametrize('name', sorted(FIXTURES))
def test_account_fixtures(name):
    validator = component_validator('account', name, 'contracts/core')
    assert validator.accepts(FIXTURES[name]), validator.error_messages(FIXTURES[name])

def test_shopping_stage_does_not_change_payment_state():
    purchase = json.loads((REPO_ROOT / 'contracts/core/fixtures/checkout-payment.json').read_text(encoding='utf-8'))['CheckoutPurchase']
    for owner in ['case', 'commerce']:
        validator = component_validator(owner, 'CheckoutPurchase', 'contracts/core')
        assert validator.accepts({**purchase, 'shopping_stage': 'AWAITING_SHIPMENT'})
        assert not validator.accepts({**purchase, 'status': 'AWAITING_SHIPMENT'})
