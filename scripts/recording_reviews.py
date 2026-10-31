"""Prepare three purchased-review examples in the selected filming stage only.

All purchases, shipment and review writes use business APIs. Carrier delivery uses
the existing controlled logistics simulator. Request identities persist before writes.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import uuid
from urllib.parse import quote

import httpx
import project_runtime
import recording_stage as stage
import reviewer_demo as runtime
from logistics_simulator import LocalMysql, call_sql, inspect


def require_stage():
    current = project_runtime.settings()
    if (
        current.project != stage.PROJECT
        or current.runtime_root != stage.STAGE
        or not (stage.STAGE / "imported.json").is_file()
    ):
        raise runtime.DemoRefused("只允许在已初始化的独立拍摄环境准备评价")
    return current


class Preparation:
    def __init__(self):
        self.settings = require_stage()
        self.path = stage.STAGE / "review-preparation.json"
        self.journal = (
            json.loads(self.path.read_text(encoding="utf-8"))
            if self.path.exists()
            else {"rows": {}}
        )
        self.client = httpx.Client(
            base_url=self.settings.gateway_url, timeout=30, trust_env=False
        )

    def save(self):
        stage.write_json(self.path, self.journal)

    def api(self, method, path, token=None, body=None, key=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        if key:
            headers["Idempotency-Key"] = key
        response = self.client.request(method, path, headers=headers, json=body)
        if not response.is_success:
            raise runtime.DemoRefused(
                f"{method} {path}: HTTP {response.status_code}；保留原请求记录"
            )
        return response.json() if response.content else None

    def login(self, username, password):
        return self.api(
            "POST",
            "/api/v1/auth/login",
            body={"username": username, "password": password},
        )["access_token"]

    def key(self, row, name):
        if name not in row:
            row[name] = str(uuid.uuid4())
            self.save()
        return row[name]

    def prepare(self):
        merchant = self.login("admin01", "123456")
        fixtures = json.loads(
            (runtime.ROOT / "fixtures/showcase/v1/reviews.json").read_text(
                encoding="utf-8"
            )
        )
        product = self.api("GET", "/api/v1/shop/products/P-1001")
        mysql = LocalMysql()
        for index, fixture in enumerate(fixtures["reviews"], 1):
            row = self.journal["rows"].setdefault(fixture["key"], {})
            if "credentials" not in row:
                row["credentials"] = {
                    "username": f"record_review_{index:02}",
                    "password": secrets.token_urlsafe(24),
                }
                self.save()
            creds = row["credentials"]
            if not row.get("registered"):
                result = self.client.post(
                    "/api/v1/auth/register",
                    json={**creds, "display_name": ["林然", "小满", "阿川"][index - 1]},
                )
                if result.status_code == 201:
                    row["registration_receipt"] = result.json()
                elif result.status_code != 409:
                    raise runtime.DemoRefused(
                        f"背景买家注册失败 HTTP {result.status_code}"
                    )
                self.login(**creds)
                row["registered"] = True
                self.save()
            token = self.login(**creds)
            addresses = self.api("GET", "/api/v1/account/addresses", token)["items"]
            address = (
                addresses[0]
                if addresses
                else self.api(
                    "POST",
                    "/api/v1/account/addresses",
                    token,
                    {
                        "recipient": ["林然", "小满", "阿川"][index - 1],
                        "phone": "13000000000",
                        "province": "浙江省",
                        "city": "杭州市",
                        "district": "西湖区",
                        "detail": "好物路88号",
                        "is_default": True,
                    },
                )
            )
            sku = next(s for s in product["skus"] if s["variant"] == fixture["variant"])
            if "draft_body" not in row:
                row["draft_body"] = {
                    "sku_id": sku["sku_id"],
                    "quantity": 1,
                    "expected_sku_version": sku["version"],
                    "shipping": {
                        "address_id": address["address_id"],
                        "expected_version": address["version"],
                    },
                }
                self.save()
            if "draft" not in row:
                row["draft"] = self.api(
                    "POST",
                    "/api/v1/shop/drafts",
                    token,
                    row["draft_body"],
                    self.key(row, "draft_key"),
                )
                self.save()
            draft = row["draft"]["draft_id"]
            if "payment" not in row:
                row["payment"] = self.api(
                    "POST",
                    f"/api/v1/shop/drafts/{draft}/payment",
                    token,
                    {},
                    self.key(row, "payment_key"),
                )
                self.save()
            assert row["payment"]["status"] == "SUCCEEDED"
            purchase = self.api(
                "GET",
                "/api/v1/shop/purchases/" + quote("draft:" + draft, safe=""),
                token,
            )
            assert purchase["status"] == "PAID" and len(purchase["lines"]) == 1
            row["order_id"], row["line_id"] = (
                purchase["order_id"],
                purchase["lines"][0]["line_id"],
            )
            self.save()
            order, line = row["order_id"], row["line_id"]
            trade = self.api("GET", f"/api/v1/merchant/orders/{order}", merchant)
            if trade["fulfillment"]["status"] == "NOT_SHIPPED":
                if "ship_body" not in row:
                    row["ship_body"] = {
                        "expected_version": trade["fulfillment"]["version"]
                    }
                    self.save()
                row["shipment"] = self.api(
                    "POST",
                    f"/api/v1/merchant/orders/{order}/simulated-shipment",
                    merchant,
                    row["ship_body"],
                    self.key(row, "ship_key"),
                )
                self.save()
            logistics = inspect(mysql, order, "M-1001")
            if logistics["status"] != "DELIVERED":
                assert logistics["status"] == "IN_TRANSIT"
                if "carrier_version" not in row:
                    row["carrier_version"] = logistics["fulfillment_version"]
                    self.save()
                mysql.execute(
                    call_sql(
                        order,
                        "M-1001",
                        row["carrier_version"],
                        "DELIVERED",
                        self.key(row, "carrier_key"),
                        None,
                    )
                )
            assert inspect(mysql, order, "M-1001")["status"] == "DELIVERED"
            own = self.api("GET", f"/api/v1/shop/orders/lines/{line}/review", token)
            review = own["review"]
            if review is None:
                assert own["can_review"]
                review = self.api(
                    "POST",
                    f"/api/v1/shop/orders/lines/{line}/review",
                    token,
                    {
                        "rating": fixture["rating"],
                        "body": fixture["body"],
                        "expected_version": 0,
                    },
                )
            assert (
                review["rating"] == fixture["rating"]
                and review["body"] == fixture["body"]
            )
            if fixture["reply"] and review["reply"] is None:
                review = self.api(
                    "POST",
                    f"/api/v1/merchant/reviews/{review['review_id']}/reply",
                    merchant,
                    {"body": fixture["reply"], "expected_version": review["version"]},
                )
            assert review["reply"] == fixture["reply"]
            row["review"] = review
            self.save()
            print(f"背景评价 {index}/3 已签收并保存", flush=True)
        self.verify()

    def verify(self):
        buyer = self.login("display01", "123456")
        merchant = self.login("admin01", "123456")
        platform = self.login("platform", "123456")
        profile = self.api("GET", "/api/v1/account/profile", buyer)
        assert profile["display_name"] == "卡皮巴拉" and profile["avatar_id"]
        assert self.api("GET", "/api/v1/account/addresses", buyer)["items"]
        avatar = self.client.get(
            "/api/v1/account/avatar", headers={"Authorization": "Bearer " + buyer}
        )
        assert avatar.status_code == 200 and avatar.content.startswith(b"\x89PNG")
        cart = self.api("GET", "/api/v1/shop/cart", buyer)
        assert all(not group["items"] for group in cart["stores"])
        for path in (
            "/api/v1/orders",
            "/api/v1/support/conversations",
            "/api/v1/customer/cases?view=ALL",
        ):
            assert self.api("GET", path, buyer)["items"] == [], path
        for token in (buyer, merchant):
            notifications = self.api("GET", "/api/v1/account/notifications", token)
            assert notifications["items"] == [] and notifications["unread_count"] == 0
        assert (
            self.api(
                "GET", "/api/v1/support/tickets?limit=8&status=ALL&query=", merchant
            )["items"]
            == []
        )
        assert (
            self.api(
                "GET",
                "/api/v1/review/cases?limit=8&scope=PUBLIC&view=ALL&query=",
                merchant,
            )["items"]
            == []
        )
        assert (
            self.api("GET", "/api/v1/platform/support-runs?limit=8", platform)["items"]
            == []
        )
        public = self.api("GET", "/api/v1/shop/products/P-1001/reviews?limit=10")
        assert (
            public["summary"]["count"] == 3
            and round(public["summary"]["average"], 1) == 4.7
        )
        assert sum(bool(r["reply"]) for r in public["items"]) == 2
        # Foreground buyer does not own the review purchases; every background order is delivered.
        trades = self.api("GET", "/api/v1/merchant/orders?limit=8", merchant)
        assert len(trades["items"]) == 3
        for row in self.journal["rows"].values():
            trade = self.api(
                "GET", f"/api/v1/merchant/orders/{row['order_id']}", merchant
            )
            assert trade["fulfillment"]["status"] == "DELIVERED"
        for table in (
            "support_agent_run",
            "support_agent_call",
            "agent_run",
            "agent_model_call",
        ):
            assert (
                runtime.postgres_scalar(f"SELECT COUNT(*) FROM {table}", self.settings)
                == "0"
            )
        counts = runtime.mysql_rows(
            "SELECT 'orders',COUNT(*) FROM commerce_db.orders UNION ALL "
            "SELECT 'delivered',COUNT(*) FROM commerce_db.order_fulfillment WHERE status='DELIVERED' UNION ALL "
            "SELECT 'cases',COUNT(*) FROM case_db.aftersale_case UNION ALL SELECT 'reviews',COUNT(*) FROM commerce_db.product_review "
            "UNION ALL SELECT 'refunds',COUNT(*) FROM commerce_db.refund_operation",
            self.settings,
        )
        assert dict(counts) == {
            "orders": "3",
            "delivered": "3",
            "cases": "0",
            "reviews": "3",
            "refunds": "0",
        }
        result = {
            "stage": stage.ENVIRONMENT,
            "buyer_login": "display01",
            "buyer_orders": 0,
            "buyer_conversations": 0,
            "buyer_cases": 0,
            "buyer_notifications": 0,
            "buyer_cart_items": 0,
            "merchant_cases": 0,
            "merchant_tickets": 0,
            "merchant_notifications": 0,
            "platform_support_runs": 0,
            "model_calls": 0,
            "background_delivered_orders": 3,
            "reviews": 3,
            "replies": 2,
            "rating": 4.7,
            "avatar_present": True,
            "address_present": True,
        }
        stage.write_json(stage.STAGE / "verified-initial-state.json", result)
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    work = Preparation()
    try:
        work.verify() if args.verify else work.prepare()
    finally:
        work.client.close()
