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
