"""Exclusive platform identity and additive, public ownership labels; existing fixtures remain valid."""

import json

import pytest

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator, load_openapi

FIXTURES = json.loads((REPO_ROOT / "contracts/core/fixtures/platform-buyer.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", FIXTURES)
def test_platform_buyer_wire_fixtures(name: str) -> None:
    validator = component_validator("case", name, "contracts/core").validator
    assert not list(validator.iter_errors(FIXTURES[name]))


@pytest.mark.parametrize("name", ["LoginResponse", "UserProfile"])
def test_buyer_identity_cannot_become_a_merchant_or_claim_legacy_customer(name: str) -> None:
    validator = component_validator("case", name, "contracts/core").validator
    for field in ("merchant_id", "customer_id", "merchant_name"):
        assert list(validator.iter_errors({**FIXTURES[name], field: "foreign"}))
    for role in ("REVIEWER", "MERCHANT_ADMIN", "OPERATOR"):
        assert list(validator.iter_errors({**FIXTURES[name], "role": role}))
    for buyer in (None, "", 123):
        assert list(validator.iter_errors({**FIXTURES[name], "buyer_id": buyer}))
    missing = {key: value for key, value in FIXTURES[name].items() if key != "buyer_id"}
    assert list(validator.iter_errors(missing))


def test_private_customer_id_and_credentials_are_not_public_order_members() -> None:
    validator = component_validator("case", "BuyerOrderLineSummary", "contracts/core").validator
    line = FIXTURES["BuyerOrderLinePage"]["items"][0]
    for field in ("customer_id", "buyer_id", "password_hash", "reserved_refund_amount"):
        assert list(validator.iter_errors({**line, field: "private"}))


def test_empty_orders_are_valid_without_guessing_a_merchant_for_the_buyer() -> None:
    document = load_openapi("case", "contracts/core")
    schema = document["paths"]["/api/v1/orders"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert {item["$ref"] for item in schema["anyOf"]} == {
        "#/components/schemas/OrderLinePage", "#/components/schemas/BuyerOrderLinePage",
    }
    for name in ("OrderLinePage", "BuyerOrderLinePage"):
        empty = {"items": [], "page": {"limit": 20}}
        assert not component_validator("case", name, "contracts/core").error_messages(empty)
