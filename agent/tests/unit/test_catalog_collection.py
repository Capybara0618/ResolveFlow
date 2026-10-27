"""Curated catalog keeps stable identities and never deletes historical rows."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from foundation_data import catalog


def test_collection_has_four_products_per_store_and_only_three_dual_variants():
    data = catalog()
    assert len(data["products"]) == 12
    assert len(data["skus"]) == 15
    for store in data["stores"]:
        assert sum(p["store_id"] == store["store_id"] for p in data["products"]) == 4
    assert "P-1008" in {p["product_id"] for p in data["products"]}
    assert "P-1003" not in {p["product_id"] for p in data["products"]}


def managed_rows():
    old = catalog(curated=False)
    return [
        dict(
            p,
            listed=True,
            version=3,
            skus=[dict(s, listed=True, version=5) for s in old["skus"] if s["product_id"] == p["product_id"]],
        )
        for p in old["products"]
    ]


def test_refresh_preserves_all_skus_current_prices_and_unknown_products():
    from catalog_collection import build_changes

    rows = managed_rows()
    rows[0]["skus"][0]["unit_amount"] = 12345
    custom = dict(rows[0], product_id="P-custom", name="用户商品")
    original = copy.deepcopy(rows + [custom])
    changes = build_changes(rows + [custom])
    assert rows + [custom] == original
    assert len(changes) == 30
    assert sum(body["listed"] for _, body in changes) == 12
    assert sum(s["listed"] for _, body in changes for s in body["skus"]) == 15
    assert changes[0][1]["skus"][0]["unit_amount"] == 12345
    for before, body in changes:
        assert body["expected_version"] == before["version"]
        assert {s["sku_id"] for s in body["skus"]} == {s["sku_id"] for s in before["skus"]}
        assert before["product_id"] != "P-custom"


@pytest.mark.parametrize("change", ["name", "store", "missing", "sku"])
def test_refresh_refuses_customized_or_missing_seed_before_any_write(change):
    from catalog_collection import build_changes

    rows = managed_rows()
    if change == "name":
        rows[0]["name"] = "用户改名"
    elif change == "store":
        rows[0]["store_id"] = "M-other"
    elif change == "missing":
        rows.pop(0)
    else:
        rows[0]["skus"][0]["variant"] = "用户规格"
    with pytest.raises(ValueError):
        build_changes(rows)


def test_refresh_is_idempotent_without_extra_version_bumps():
    from catalog_collection import build_changes

    rows = managed_rows()
    for before, body in build_changes(rows):
        before.update({k: v for k, v in body.items() if k != "expected_version"})
    assert build_changes(rows) == []
