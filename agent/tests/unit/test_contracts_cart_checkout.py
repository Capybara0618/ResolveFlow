import json

import pytest

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator, load_openapi

FIXTURES = json.loads((REPO_ROOT / 'contracts/core/fixtures/cart-checkout.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('name', sorted(FIXTURES))
def test_multiline_wire_shared_and_strict(name):
    for service in ['case', 'commerce']:
        v = component_validator(service, name, 'contracts/core')
        assert v.accepts(FIXTURES[name]), v.error_messages(FIXTURES[name])
        assert not v.accepts({**FIXTURES[name], 'paid_at': 'forged'})
    assert load_openapi('case', 'contracts/core')['components']['schemas'][name] == (
        load_openapi('commerce', 'contracts/core')['components']['schemas'][name]
    )


def test_checkout_rejects_empty_duplicate_overflow_and_private_body():
    for name in ['CartQuoteRequest', 'CartDraftRequest']:
        v = component_validator('case', name, 'contracts/core')
        field = 'sku_ids' if name == 'CartQuoteRequest' else 'lines'
        body = FIXTURES[name]
        for values in [[], [body[field][0]] * 2, [body[field][0]] * 21]:
            assert not v.accepts({**body, field: values})
        for extra in ['merchant_id', 'buyer_id', 'total_amount', 'buyer_id']:
            assert not v.accepts({**body, extra: 'private'})
    q = component_validator('case', 'CartQuote', 'contracts/core')
    assert not q.accepts({**FIXTURES['CartQuote'], 'total_amount': 1000000001})


def test_both_cart_checkout_routes_require_authenticated_buyer():
    for owner, prefix in [('case', '/api/v1'), ('commerce', '/internal/v1')]:
        paths = load_openapi(owner, 'contracts/core')['paths']
        for suffix in ['quote', 'drafts']:
            op = paths[f'{prefix}/shop/cart/{{store_id}}/{suffix}']['post']
            assert op.get('security') != []
            assert {'401', '403', '409', '503'} <= set(op['responses'])


def test_refund_projection_is_optional_but_only_on_paid_purchase():
    purchase = json.loads((REPO_ROOT / 'contracts/core/fixtures/checkout-payment.json').read_text(
        encoding='utf-8'))['CheckoutPurchase']
    for owner in ['case', 'commerce']:
        v = component_validator(owner, 'CheckoutPurchase', 'contracts/core')
        assert v.accepts(purchase)
        for state in ['NONE', 'IN_PROGRESS', 'PARTIALLY_REFUNDED', 'REFUNDED']:
            assert v.accepts({**purchase, 'refund_status': state})
        assert not v.accepts({**purchase, 'refund_status': 'PAID'})
        assert not v.accepts({**purchase, 'status': 'WAITING_PAYMENT', 'order_id': None,
                              'paid_at': None, 'refund_status': 'NONE'})
