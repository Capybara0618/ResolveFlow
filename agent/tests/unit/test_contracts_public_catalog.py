"""Direct Commerce entry keeps existing public shapes and excludes private commands."""
import pytest

from resolveflow.contracts._schemaio import load_openapi


@pytest.mark.parametrize("suffix,method", [
    ("stores", "get"), ("stores/{store_id}", "get"), ("products", "get"),
    ("products/{product_id}", "get"), ("quote", "post"),
    ("products/{product_id}/reviews", "get"),
])
def test_direct_catalog_retains_request_response_and_anonymous_security(suffix, method):
    case = load_openapi("case", "contracts/core")
    commerce = load_openapi("commerce", "contracts/core")
    path = f"/api/v1/shop/{suffix}"
    old, new = case["paths"][path][method], commerce["paths"][path][method]
    assert new["security"] == []
    assert new["responses"] == old["responses"]
    assert new.get("parameters") == old.get("parameters")
    assert new.get("requestBody") == old.get("requestBody")


def test_commerce_does_not_publish_internal_commands_or_private_media():
    doc = load_openapi("commerce", "contracts/core")
    public = {p: v for p, v in doc["paths"].items() if p.startswith("/api/")
              and all(op.get("security") == [] for method, op in v.items() if method in {"get", "post"})}
    assert len(public) == 8
    assert all(set(item) <= {"get", "post", "parameters"} for item in public.values())
    assert [p for p,item in public.items() if "post" in item] == ["/api/v1/shop/quote"]
