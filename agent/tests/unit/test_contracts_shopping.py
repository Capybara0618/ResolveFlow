"""Public commerce projections stay identical across the facade/service boundary."""
import copy
import json

import pytest

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator, load_openapi

FIXTURES = json.loads((REPO_ROOT / "contracts/core/fixtures/shopping.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_shopping_fixtures_and_wire_equality(name: str) -> None:
    for service in ["case", "commerce"]:
        validator = component_validator(service, name, "contracts/core")
        assert validator.accepts(FIXTURES[name]), validator.error_messages(FIXTURES[name])
    assert load_openapi("case", "contracts/core")["components"]["schemas"][name] == (
        load_openapi("commerce", "contracts/core")["components"]["schemas"][name]
    )


def test_money_scope_and_draft_state_cannot_be_forged() -> None:
    validator = component_validator("case", "ShopDraftRequest", "contracts/core")
    for field in ["buyer_id", "merchant_id", "buyer_id", "total_amount", "unit_amount"]:
        assert not validator.accepts({**FIXTURES["ShopDraftRequest"], field: "forged"})
    for quantity in [0, 101, 1.5]:
        assert not validator.accepts({**FIXTURES["ShopDraftRequest"], "quantity": quantity})
    draft = component_validator("case", "ShopDraft", "contracts/core")
    for field in ["paid_at", "buyer_id", "idempotency_key"]:
        assert not draft.accepts({**FIXTURES["ShopDraft"], field: "private"})
    invalid = copy.deepcopy(FIXTURES["ShopDraft"])
    invalid["status"] = "SHIPPED"
    assert not draft.accepts(invalid)


def test_only_catalog_is_anonymous_and_drafts_require_buyer() -> None:
    paths = load_openapi("case", "contracts/core")["paths"]
    for suffix in ["products", "products/{product_id}", "stores", "stores/{store_id}", "quote"]:
        method = "post" if suffix == "quote" else "get"
        assert paths[f"/api/v1/shop/{suffix}"][method]["security"] == []
    for suffix, method in [("drafts", "post"), ("drafts/{draft_id}", "get")]:
        op = paths[f"/api/v1/shop/{suffix}"][method]
        assert "security" not in op
        assert {"401", "403", "404", "409", "503"} <= set(op["responses"])
