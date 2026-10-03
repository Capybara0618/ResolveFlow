"""Read-only HTTP checks for aftercare product identity/art; no model or transaction writes."""

from __future__ import annotations

import json
from pathlib import Path

import reviewer_demo as demo


def main() -> None:
    settings = demo.settings_from_environ()
    demo.guard(settings)
    results = []

    def read(path: str, token: str | None, expected: int = 200):
        status, value = demo.http("GET", settings.gateway_url + path, token=token)
        if status != expected:
            raise RuntimeError(f"GET {path}: {status}, expected {expected}")
        results.append({"path": path, "status": status})
        return value

    identities = ["buyer01", "buyer02", "admin01", "admin02", "admin03", "platform"]
    tokens = {name: demo.login(settings, name, "123456") for name in identities}
    items = read("/api/v1/customer/cases?view=ALL&limit=20", tokens["buyer01"])["items"]
    if len({item["merchant_id"] for item in items}) != 3:
        raise RuntimeError(
            "This verification requires existing buyer01 cases in the three stores"
        )
    products = read("/api/v1/shop/products?limit=48", None)["items"]
    for item in items:
        path = f"/api/v1/orders/lines/{item['line_id']}"
        buyer = read(path, tokens["buyer01"])
        if (
            buyer["line_id"] != item["line_id"]
            or buyer["merchant_id"] != item["merchant_id"]
        ):
            raise RuntimeError("The product did not match the visible application")
        admin = "admin0" + item["merchant_id"][-1]
        merchant = read(path, tokens[admin])
        for field in (
            "asset_key",
            "product_name",
            "variant_text",
            "quantity",
            "line_paid_amount",
        ):
            if buyer.get(field) != merchant.get(field):
                raise RuntimeError(f"Buyer/merchant product {field} differs")
        # Existing synthetic purchases have unchanged catalog values; this is a display check,
        # not the evidence that catalog changes cannot affect historical art (database tests).
        original = next(
            p for p in products if any(s["sku_id"] == buyer["sku"] for s in p["skus"])
        )
        if buyer.get("asset_key") != original["asset_key"] or not buyer.get(
            "merchant_name"
        ):
            raise RuntimeError("Existing purchase art/store name is missing")
        read(path, tokens["buyer02"], 404)
        other = "admin02" if admin != "admin02" else "admin01"
        read(path + "?merchant_id=" + item["merchant_id"], tokens[other], 404)
        read(path, tokens["platform"], 403)
        read(path, None, 401)
        read(path, demo.mint_service_token("case-service"), 401)
        detail = read(f"/api/v1/customer/cases/{item['case_id']}", tokens["buyer01"])
        eligibility = read(
            f"/api/v1/customer/order-lines/{item['line_id']}", tokens["buyer01"]
        )
        if detail["case"]["status"] != "CLOSED_SUCCESS" or eligibility["can_apply"]:
            raise RuntimeError("Existing refunded line became mutable/applicable")
        if eligibility["order_line"].get("asset_key") != buyer["asset_key"]:
            raise RuntimeError("Application product projection lost paid-snapshot art")
        trade = read(f"/api/v1/merchant/orders/{buyer['order_id']}", tokens[admin])
        if not any(
            row["line_id"] == item["line_id"] for row in trade["fulfillment"]["lines"]
        ):
            raise RuntimeError(
                "Fulfillment does not contain the exact case product line"
            )
    read("/api/v1/orders/lines/missing", tokens["buyer01"], 404)
    folder = Path("reports/aftercare-ui")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "http-verification.json").write_text(
        json.dumps(
            {
                "observed_at": demo.now_iso(),
                "read_only": True,
                "checks": results,
                "model_calls_started": 0,
                "orders_or_cases_created": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"{len(results)} read-only HTTP checks passed; no model/transaction writes")


if __name__ == "__main__":
    main()
