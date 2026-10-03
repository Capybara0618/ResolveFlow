import copy
import json

import pytest

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator, load_openapi

FIXTURES = json.loads((REPO_ROOT / 'contracts/core/fixtures/cart.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('name', sorted(FIXTURES))
def test_cart_wire_shared_and_strict(name):
    for service in ['case', 'commerce']:
        v = component_validator(service, name, 'contracts/core')
        assert v.accepts(FIXTURES[name]), v.error_messages(FIXTURES[name])
        assert not v.accepts({**FIXTURES[name], 'buyer_id': 'other'})
    assert load_openapi('case', 'contracts/core')['components']['schemas'][name] == (
        load_openapi('commerce', 'contracts/core')['components']['schemas'][name]
    )


def test_absolute_write_bounds_and_removal():
    v = component_validator('case', 'CartRequest', 'contracts/core')
    body = FIXTURES['CartRequest']
    assert v.accepts({**body, 'quantity': 0, 'expected_sku_version': None})
    for patch in [{'quantity': -1}, {'quantity': 101}, {'quantity': 1.5}, {'expected_revision': -1},
                  {'expected_revision': 9007199254740991}, {'expected_sku_version': None},
                  {'quantity': 0}, {'total_amount': 1}, {'customer_id': 'other'}]:
        assert not v.accepts({**body, **patch})
    delisted = copy.deepcopy(FIXTURES['CartItem'])
    delisted['availability'] = 'DELISTED'
    assert component_validator('case', 'CartItem', 'contracts/core').accepts(delisted)


def test_cart_never_anonymous_and_internal_customer_only_for_read():
    public = load_openapi('case', 'contracts/core')['paths']
    for path, method in [('/api/v1/shop/cart', 'get'), ('/api/v1/shop/cart/{store_id}/items', 'post')]:
        assert public[path][method].get('security') != []
        assert {'401', '403', '409', '503'} <= set(public[path][method]['responses'])
    private = load_openapi('commerce', 'contracts/core')['paths']
    op = private['/internal/v1/shop/cart/{store_id}']['get']
    assert any(p['name'] == 'customer_id' and p['required'] for p in op['parameters'])
