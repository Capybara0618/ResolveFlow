"""Apply the curated collection through versioned merchant APIs; never reset data.

Only known foundation identities can be changed. Custom products, current prices,
SKU identities, orders and historical snapshots remain untouched. Default is preview.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from foundation_data import catalog


def build_changes(rows: list[dict]) -> list[tuple[dict, dict]]:
    legacy = catalog(curated=False)
    targets = {p["product_id"]: p for p in catalog()["products"]}
    chosen_skus = {s["sku_id"] for s in catalog()["skus"]}
    known = {p["product_id"]: p for p in legacy["products"]}
    old_skus = {s["sku_id"]: s for s in legacy["skus"]}
    found = {p["product_id"] for p in rows}
    if not targets.keys() <= found:
        raise ValueError("精选商品缺失；拒绝自动创建替代身份")
    changes = []
    for row in rows:
        product_id = row["product_id"]
        baseline = known.get(product_id)
        if baseline is None:
            continue  # A merchant-created product is never silently delisted.
        if any(
            row[k] != baseline[k] for k in ("store_id", "name", "category", "asset_key")
        ):
            raise ValueError(f"基础商品身份已修改，需人工核对：{product_id}")
        expected = {
            s["sku_id"] for s in legacy["skus"] if s["product_id"] == product_id
        }
        current = {s["sku_id"] for s in row["skus"]}
        required = expected & chosen_skus
        if (
            not required <= current
            or not current <= expected
            or len(current) != len(row["skus"])
        ):
            raise ValueError(f"基础规格身份已修改，需人工核对：{product_id}")
        for sku in row["skus"]:
            if sku["variant"] != old_skus[sku["sku_id"]]["variant"]:
                raise ValueError(f"基础规格名称已修改，需人工核对：{sku['sku_id']}")
        target = targets.get(product_id)
        description = row["description"]
        if target and description == baseline["description"]:
            description = target["description"]
        body = {k: row[k] for k in ("name", "category", "asset_key")}
        body.update(
            description=description,
            listed=target is not None,
            expected_version=row["version"],
        )
        body["skus"] = [
            dict(
                {k: s[k] for k in ("sku_id", "variant", "unit_amount", "max_quantity")},
                listed=target is not None and s["sku_id"] in chosen_skus,
            )
            for s in row["skus"]
        ]
        if any(body[k] != row[k] for k in ("description", "listed")) or any(
            s["listed"] != before["listed"]
            for s, before in zip(body["skus"], row["skus"], strict=True)
        ):
            changes.append((row, body))
    return changes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="本机精选商品更新（默认只预览，不清库）"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--base-url", choices=["http://127.0.0.1:8180"], default="http://127.0.0.1:8180"
    )
    args = parser.parse_args()
    # Fixed existing local demo credentials. Tokens never enter logs or backups.
    with httpx.Client(
        base_url=args.base_url, timeout=30, follow_redirects=False, trust_env=False
    ) as client:
        tokens, rows = {}, []
        for i in range(1, 4):
            response = client.post(
                "/api/v1/auth/login",
                json={"username": f"admin{i:02d}", "password": "123456"},
            )
            response.raise_for_status()
            identity = response.json()
            merchant = f"M-100{i}"
            if (
                identity.get("merchant_id") != merchant
                or identity.get("role") != "MERCHANT_ADMIN"
            ):
                raise ValueError("商家身份不匹配，拒绝更新")
            token = identity["access_token"]
            tokens[merchant] = token
            after = None
            while True:
                response = client.get(
                    "/api/v1/merchant/products",
                    params={"limit": 48, **({"after": after} if after else {})},
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                page = response.json()
                if any(p["store_id"] != merchant for p in page["items"]):
                    raise ValueError("商家返回了跨主体商品，拒绝更新")
                rows.extend(page["items"])
                after = page["next_after"]
                if not after:
                    break
        changes = build_changes(
            rows
        )  # Validate the entire plan before the first write.
        print(
            f"需更新 {len(changes)} 个基础商品；目标12个商品/15个在售规格；自建商品保持。"
        )
        if not args.apply:
            print("仅预览；使用 --apply 执行经版本校验的商家API更新。")
            return
        folder = Path(__file__).resolve().parents[1] / "tmp/catalog-collection"
        folder.mkdir(parents=True, exist_ok=True)
        backup = folder / (
            datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f") + "-before.json"
        )
        backup.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for before, body in changes:
            response = client.post(
                f"/api/v1/merchant/products/{before['product_id']}",
                json=body,
                headers={"Authorization": f"Bearer {tokens[before['store_id']]}"},
            )
            response.raise_for_status()  # Stop on conflict/unknown result; never invent a new identity.
            print(f"已更新 {before['product_id']}，版本 {response.json()['version']}")
        print(f"更新完成；原商品快照保存在 {backup}。重跑仅更新剩余差异。")


if __name__ == "__main__":
    main()
