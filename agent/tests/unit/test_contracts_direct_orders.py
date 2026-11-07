import copy
import json

import pytest

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator, load_openapi


@pytest.mark.parametrize("path", ["/api/v1/orders", "/api/v1/orders/{order_id}", "/api/v1/orders/lines/{line_id}"])
def test_direct_order_parameters_preserve_public_location_and_cursor_capacity(path):
    case = load_openapi("case", "contracts/core")
    commerce = load_openapi("commerce", "contracts/core")
    def parameters(doc):
        result = []
        for value in doc["paths"][path]["get"].get("parameters", []):
            if "$ref" in value:
                value = doc["components"]["parameters"][value["$ref"].rsplit("/", 1)[1]]
            result.append(value)
        return result
    assert parameters(case) == parameters(commerce)
    assert commerce["paths"][path]["get"]["security"] == [{"bearerAuth": []}]


def test_direct_buyer_and_legacy_order_shapes_stay_distinct_and_private_fields_are_refused():
    fixture = json.loads((REPO_ROOT / "contracts/core/fixtures/platform-buyer.json").read_text(encoding="utf-8"))["BuyerOrderLinePage"]
    assert component_validator("commerce", "BuyerOrderLinePage", "contracts/core").accepts(fixture)
    legacy = copy.deepcopy(fixture)
    for item in legacy["items"]:
        item.pop("merchant_id")
        item.pop("merchant_name")
    assert component_validator("commerce", "OrderLinePage", "contracts/core").accepts(legacy)
    assert not component_validator("commerce", "OrderLinePage", "contracts/core").accepts(fixture)
    private = copy.deepcopy(fixture)
    private["items"][0]["buyer_id"] = "other"
    assert not component_validator("commerce", "BuyerOrderLinePage", "contracts/core").accepts(private)
