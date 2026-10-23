import json

import pytest

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator

FIXTURES = json.loads((REPO_ROOT / 'contracts/core/fixtures/support-refund.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('name', sorted(FIXTURES))
def test_customer_refund_wires_are_closed(name):
    validator = component_validator('case', 'SupportRefund' + name, 'contracts/core')
    assert validator.accepts(FIXTURES[name]), validator.error_messages(FIXTURES[name])
    for key in ['buyer_id', 'merchant_id', 'refund_amount', 'approved']:
        assert not validator.accepts({**FIXTURES[name], key: 'forged'})


def test_prepare_cannot_override_the_order_amount():
    validator = component_validator('case', 'SupportRefundPrepare', 'contracts/core')
    assert not validator.accepts({**FIXTURES['Prepare'], 'amount_minor': 1})
    assert not validator.accepts({**FIXTURES['Prepare'], 'expected_version': 0})


def test_optional_final_assistant_summary_has_no_authority_fields():
    value = json.loads((REPO_ROOT / 'contracts/core/fixtures/support-refund-offer.json').read_text(encoding='utf-8'))
    validator = component_validator('case', 'SupportAssistant', 'contracts/core')
    assert validator.accepts(value), validator.error_messages(value)
    assert not validator.accepts({**value, 'refund_amount': 32900})
    assert not validator.accepts({**value, 'refund_summary': ''})
