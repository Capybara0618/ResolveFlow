import json

import pytest

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator

FIXTURES = json.loads((REPO_ROOT / 'contracts/core/fixtures/support-buyer-view.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('name', sorted(FIXTURES))
def test_buyer_view_is_closed_and_carries_no_execution_or_internal_fields(name):
    validator = component_validator('case', 'SupportBuyerView', 'contracts/core')
    value = FIXTURES[name]
    assert validator.accepts(value), validator.error_messages(value)
    for field in ['approved', 'amount_minor', 'tool_name', 'private_prompt']:
        assert not validator.accepts({**value, field: 'forged'})
        assert not validator.accepts({**value, 'parts': [{**value['parts'][0], field: 'forged'}]})
    assert not validator.accepts({**value, 'parts': []})
    assert not validator.accepts({**value, 'version': 'unknown'})


def test_action_and_model_guidance_cannot_compete_on_the_same_buyer_part():
    validator = component_validator('case', 'SupportBuyerView', 'contracts/core')
    value = FIXTURES['Refund']
    assert not validator.accepts({**value, 'parts': [{**value['parts'][0], 'guidance': '重复办理说明'}]})
    assert not validator.accepts({**value, 'parts': [{**value['parts'][0], 'action': 'EXECUTE_REFUND'}]})
