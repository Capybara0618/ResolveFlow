import json

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator, load_openapi


def test_identity_protocol_accepts_minimal_fixtures_and_rejects_client_scopes():
    fixtures = json.loads((REPO_ROOT / "contracts/core/fixtures/identity-access.json").read_text(encoding="utf-8"))
    for schema, value in fixtures.items():
        assert component_validator("case", schema, "contracts/core").accepts(value)
    validator = component_validator("case", "IdentityResolveRequest", "contracts/core")
    for name in ["merchant_id", "customer_id", "buyer_id", "role", "identity_version", "bindings"]:
        assert not validator.accepts({**fixtures["IdentityResolveRequest"], name: "forged"})


def test_identity_is_service_only_and_never_a_gateway_or_query_credential():
    operation = load_openapi("case", "contracts/core")["paths"]["/internal/v1/identity/resolve"]["post"]
    assert operation["security"] == [{"serviceToken": []}]
    assert not operation.get("parameters")
    assert {"401", "403", "404", "409"} <= set(operation["responses"])
    assert operation["responses"]["200"]["headers"]["Cache-Control"]["schema"]["const"] == "no-store"
