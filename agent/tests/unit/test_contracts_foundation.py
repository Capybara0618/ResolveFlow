"""New admin boundaries have fixture evidence and retain merchant/buyer exclusivity."""

import copy
import json

import pytest
from jsonschema import ValidationError

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator, load_openapi


def test_automatic_ownership_is_audit_only_and_single_profile_is_merchant_only():
    fixtures = json.loads((REPO_ROOT / "contracts/core/fixtures/foundation.json").read_text(encoding="utf-8"))
    profile = fixtures["SingleMerchantProfile"]
    validator = component_validator("case", "UserProfile", "contracts/core").validator
    validator.validate(profile)
    for role in ("REVIEWER", "PLATFORM_ADMIN", "CUSTOMER"):
        with pytest.raises(ValidationError):
            validator.validate({**profile, "role": role})
    component_validator("case", "CaseCollaborationEvent", "contracts/core").validator.validate(fixtures["AutomaticAssignment"])
    with pytest.raises(ValidationError):
        component_validator("case", "CaseCollaborationAction", "contracts/core").validator.validate(
            {"action": "AUTO_ASSIGN", "reason": "不能由客户端指定自动分配"}
        )


@pytest.mark.parametrize("name", ["PlatformMerchant", "PlatformBuyer", "ManagedProduct", "PlatformMerchants", "PlatformBuyers"])
def test_management_fixture_matches_both_services(name):
    fixture = json.loads((REPO_ROOT / "contracts/core/fixtures/foundation.json").read_text(encoding="utf-8"))[name]
    for owner in ("case", "commerce"):
        component_validator(owner, name, "contracts/core").validator.validate(fixture)
    assert (
        load_openapi("case", "contracts/core")["components"]["schemas"][name]
        == load_openapi("commerce", "contracts/core")["components"]["schemas"][name]
    )


def test_platform_identity_contract_rejects_tenant_or_buyer_claims():
    profile = {"username": "platform", "role": "PLATFORM_ADMIN", "display_name": "平台管理员"}
    validator = component_validator("case", "UserProfile", "contracts/core")
    validator.validator.validate(profile)
    for fields in ({"buyer_id": "B-1"}, {"merchant_id": "M-1", "merchant_name": "其他商家"}, {"buyer_id": "C-1"}):
        with pytest.raises(ValidationError):
            validator.validator.validate({**profile, **fields})


def test_product_write_refuses_fractional_cents_and_empty_skus():
    product = json.loads((REPO_ROOT / "contracts/core/fixtures/foundation.json").read_text(encoding="utf-8"))[
        "ManagedProduct"
    ]
    body = {k: product[k] for k in ("name", "description", "category", "asset_key", "listed")}
    body["skus"] = [{k: product["skus"][0][k] for k in ("variant", "unit_amount", "max_quantity", "listed")}]
    validator = component_validator("case", "ManagedProductWrite", "contracts/core")
    validator.validator.validate(body)
    wrong = copy.deepcopy(body)
    wrong["skus"][0]["unit_amount"] = 16900.5
    with pytest.raises(ValidationError):
        validator.validator.validate(wrong)
    with pytest.raises(ValidationError):
        validator.validator.validate({**body, "skus": []})


def test_platform_lists_offer_server_search_and_pagination():
    doc = load_openapi("case", "contracts/core")
    for name in ("merchants", "buyers"):
        operation = doc["paths"][f"/api/v1/platform/{name}"]["get"]
        params = {p["name"]: p for p in operation["parameters"]}
        assert {"after", "query", "limit"} <= params.keys()
        assert params["limit"]["schema"]["maximum"] == 50
