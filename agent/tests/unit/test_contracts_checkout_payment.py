"""Simulated purchase schemas share the Java facade's exact state/null/privacy boundary."""
import copy
import json

import pytest

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator, load_openapi

FIXTURES = json.loads((REPO_ROOT / "contracts/core/fixtures/checkout-payment.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_both_services_share_checkout_fixture_and_schema(name: str) -> None:
    for service in ["case", "commerce"]:
        validator = component_validator(service, name, "contracts/core")
        assert validator.accepts(FIXTURES[name]), validator.error_messages(FIXTURES[name])
    assert load_openapi("case", "contracts/core")["components"]["schemas"][name] == (
        load_openapi("commerce", "contracts/core")["components"]["schemas"][name]
    )


def test_public_payment_accepts_no_scope_amount_or_result_fields() -> None:
    validator = component_validator("case", "CheckoutEmptyRequest", "contracts/core")
    for field in ["merchant_id", "customer_id", "total_amount", "status", "attempt_id"]:
        assert not validator.accepts({field: "forged"})
    for path, method in [("drafts/{draft_id}/payment", "post"), ("drafts/{draft_id}/payment", "get"),
                         ("drafts/{draft_id}/cancel", "post"), ("purchases", "get"),
                         ("purchases/{purchase_id}", "get")]:
        op = load_openapi("case", "contracts/core")["paths"][f"/api/v1/shop/{path}"][method]
        assert "security" not in op
        assert {"401", "403", "404", "409", "503"} <= set(op["responses"])


def test_unknown_or_failed_payment_cannot_claim_paid_publication() -> None:
    validator = component_validator("case", "CheckoutPayment", "contracts/core")
    for state in ["UNKNOWN", "FAILED"]:
        payment = copy.deepcopy(FIXTURES["CheckoutPayment"])
        payment["status"] = state
        assert not validator.accepts(payment)
        for field in ["order_id", "line_id", "paid_at"]:
            payment[field] = None
        if state == "UNKNOWN":
            payment["finished_at"] = None
        assert validator.accepts(payment)
    purchase = copy.deepcopy(FIXTURES["CheckoutPurchase"])
    purchase["status"] = "WAITING_PAYMENT"
    assert not component_validator("case", "CheckoutPurchase", "contracts/core").accepts(purchase)
    lookup = component_validator("case", "CheckoutPaymentLookup", "contracts/core")
    assert lookup.accepts({"payment": None})


def test_private_checkout_keys_are_never_public_fields() -> None:
    for schema in ["CheckoutPayment", "CheckoutPurchase"]:
        validator = component_validator("case", schema, "contracts/core")
        for field in ["idempotency_key", "customer_id", "provider_secret"]:
            assert not validator.accepts({**FIXTURES[schema], field: "private"})
