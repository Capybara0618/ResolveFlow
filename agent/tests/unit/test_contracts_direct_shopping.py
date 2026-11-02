import pytest

from resolveflow.contracts._schemaio import load_openapi


@pytest.mark.parametrize("suffix,method", [
    ("cart", "get"), ("cart/{store_id}/items", "post"), ("cart/{store_id}/quote", "post"),
    ("cart/{store_id}/drafts", "post"), ("drafts", "post"), ("drafts/{draft_id}", "get"),
    ("drafts/{draft_id}/payment", "post"), ("drafts/{draft_id}/payment", "get"),
    ("drafts/{draft_id}/cancel", "post"), ("purchases", "get"), ("purchases/{purchase_id}", "get"),
])
def test_commerce_direct_shopping_keeps_shape_and_requires_user_identity(suffix, method):
    path = f"/api/v1/shop/{suffix}"
    old = load_openapi("case", "contracts/core")["paths"][path][method]
    new = load_openapi("commerce", "contracts/core")["paths"][path][method]
    assert new["security"] == [{"bearerAuth": []}]
    assert new.get("requestBody") == old.get("requestBody")
    assert new.get("parameters") == old.get("parameters")
    assert new["responses"] == old["responses"]


@pytest.mark.parametrize("path", [
    "/api/v1/merchant/orders", "/api/v1/merchant/orders/{order_id}",
    "/api/v1/merchant/orders/{order_id}/simulated-shipment",
    "/api/v1/shop/purchases/{purchase_id}/fulfillment", "/api/v1/shop/orders/lines/{line_id}/review",
    "/api/v1/merchant/reviews", "/api/v1/merchant/reviews/{review_id}/reply",
    "/api/v1/merchant/products", "/api/v1/merchant/products/{id}",
])
def test_direct_merchant_and_review_operations_preserve_existing_contracts(path):
    old = load_openapi("case", "contracts/core")["paths"][path]
    new = load_openapi("commerce", "contracts/core")["paths"][path]
    for method, operation in old.items():
        if method not in {"get", "post"}:
            continue
        assert new[method]["security"] == [{"bearerAuth": []}]
        for field in ["requestBody", "responses", "parameters"]:
            assert new[method].get(field) == operation.get(field)
