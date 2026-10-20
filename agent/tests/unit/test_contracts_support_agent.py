import json

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator


def test_consultation_wire_is_independent_from_case_permissions_and_closed():
    fixtures = json.loads((REPO_ROOT / "contracts/core/fixtures/support-agent.json").read_text(encoding="utf-8"))
    for name, value in fixtures.items():
        validator = component_validator("agent", name, "contracts/core")
        assert validator.accepts(value), validator.error_messages(value)
        assert not validator.accepts({**value, "case_id": "fake"})
    assert fixtures["SupportAgentRequest"]["context"]["policy_manifest"]["merchant_id"] == "M-A"
