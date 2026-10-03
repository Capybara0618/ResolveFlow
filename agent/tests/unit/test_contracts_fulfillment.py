import copy
import json

import pytest

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator, load_openapi

FIXTURES = json.loads((REPO_ROOT / 'contracts/core/fixtures/fulfillment.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('name', sorted(FIXTURES))
def test_fulfillment_shared_closed_protocol(name):
    for owner in ['case', 'commerce']:
        validator = component_validator(owner, name, 'contracts/core')
        assert validator.accepts(FIXTURES[name]), validator.error_messages(FIXTURES[name])
        assert not validator.accepts({**FIXTURES[name], 'customer_id': 'foreign'})
    assert load_openapi('case', 'contracts/core')['components']['schemas'][name] == (
        load_openapi('commerce', 'contracts/core')['components']['schemas'][name])


def test_local_unshipped_is_not_a_carrier_delivery_or_missing_history():
    v = component_validator('case', 'OrderFulfillment', 'contracts/core')
    original = FIXTURES['OrderFulfillment']
    assert not v.accepts({**original, 'synthetic': False})
    assert not v.accepts({**original, 'status': 'PAID'})
    assert not v.accepts({**original, 'version': 0})
    missing = copy.deepcopy(original)
    missing.update(status='UNKNOWN', version=None, updated_at=None)
    missing['lines'][0].update(status='UNKNOWN', source_version=None, events=[])
    assert v.accepts(missing)
    shipped = copy.deepcopy(original)
    shipped.update(status='IN_TRANSIT', version=2)
    shipped['lines'][0].update(status='IN_TRANSIT', carrier_conclusion='IN_TRANSIT', source_version=2)
    shipped['lines'][0]['events'].append({
        **shipped['lines'][0]['events'][0], 'code': 'SIMULATED_SHIPPED', 'source_version': 2})
    assert v.accepts(shipped)


def test_public_shipment_only_accepts_observed_version():
    v = component_validator('case', 'SimulatedShipmentRequest', 'contracts/core')
    for extra in ['merchant_id', 'actor', 'customer_id', 'status', 'occurred_at', 'template']:
        assert not v.accepts({'expected_version': 1, extra: 'forged'})
    for version in [0, -1, None, 1.5, 9223372036854775808]:
        assert not v.accepts({'expected_version': version})


def test_new_shipping_routes_require_admin_or_trusted_case_and_original_key():
    for owner, prefix in [('case', '/api/v1'), ('commerce', '/internal/v1')]:
        doc = load_openapi(owner, 'contracts/core')
        for suffix in ['', '/{order_id}', '/{order_id}/simulated-shipment']:
            operations = doc['paths'][prefix + '/merchant/orders' + suffix]
            operation = operations['post' if suffix.endswith('simulated-shipment') else 'get']
            assert operation['security']
            assert {'401', '403', '404', '503'} <= set(operation['responses'])
        ship = doc['paths'][prefix + '/merchant/orders/{order_id}/simulated-shipment']['post']
        assert '409' in ship['responses']
        if owner == 'case':
            assert any(p['name'] == 'Idempotency-Key' and p['required'] for p in ship['parameters'])
