"""Configure the selected showcase identities through existing versioned APIs.

Default is read-only preview. No order, consultation, policy or money writes.
Credentials and resumable upload identifiers remain under ignored tmp/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "fixtures/showcase/v1"
STATE = ROOT / "tmp/showcase-config/journal.json"
BASE = "http://127.0.0.1:8180"


def asset_path(value: str) -> Path:
    path = (PACK / value).resolve()
    if not path.is_relative_to(PACK.resolve()) or not path.is_file():
        raise ValueError("素材必须位于展示资料目录内")
    return path


def require_owned(label: str, current: dict, owned: dict | None) -> None:
    if owned is not None and current == (dict(owned, variant_images={}) if "variant_images" in current and "variant_images" not in owned else owned):
        return
    empty = current.get("version") == 0 and all(
        value in (None, "", [], 0)
        for key, value in current.items()
        if key not in ("version", "product_id", "store_id")
    )
    if owned is None and empty:
        return
    raise ValueError(f"{label}已有资料与本轮记录不同，请先核对，不自动覆盖")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_assets() -> dict:
    data = json.loads((PACK / "showcase.json").read_text(encoding="utf-8"))
    assets = json.loads((PACK / "assets.json").read_text(encoding="utf-8"))["assets"]
    known = {}
    for item in assets:
        path = (ROOT / item["file"].replace("\\", "/")).resolve()
        if not (
            path.is_relative_to(PACK.resolve())
            or path == ROOT / "web/public/identity/v1/assistant.webp"
        ):
            raise ValueError("素材清单路径超出范围")
        value = path.read_bytes()
        if digest(value) != item["sha256"] or len(value) >= 2 * 1024 * 1024:
            raise ValueError("素材哈希或体积不符合清单")
        known[path] = True
    files = [data["account"]["avatar"]]
    files.extend(s["logo"] for s in data["stores"])
    files.extend(image for p in data["products"] for image in p["images"])
    if any(asset_path(name) not in known for name in files):
        raise ValueError("资料引用了未登记图片")
    collection = json.loads(
        (ROOT / "fixtures/catalog/collection-v1.json").read_text(encoding="utf-8")
    )
    expected = {
        p["product_id"]: (p["store_id"], p["name"]) for p in collection["products"]
    }
    actual = {p["product_id"]: (p["store_id"], p["name"]) for p in data["products"]}
    if actual != expected or len(actual) != len(data["products"]):
        raise ValueError("只配置现有十二款精选商品")
    if len(data["stores"]) != 3 or {s["store_id"] for s in data["stores"]} != {
        "M-1001",
        "M-1002",
        "M-1003",
    }:
        raise ValueError("店铺身份不匹配")
    if data["account"]["username"] != "demo_showcase":
        raise ValueError("只配置专用展示买家")
    return data


class Configuration:
    def __init__(self, client: httpx.Client, data: dict, credentials: Path):
        self.client, self.data = client, data
        self.state = (
            json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
        )
        for key in ("media", "avatars", "presentations", "pending"):
            self.state.setdefault(key, {})
        self.tokens = {}
        buyer = json.loads(credentials.read_text(encoding="utf-8"))
        if buyer.get("username") != "demo_showcase":
            raise ValueError("买家凭据必须属于专用展示账号")
        self.login(buyer, "CUSTOMER", None)
        for store in data["stores"]:
            self.login(
                {"username": store["username"], "password": "123456"},
                "MERCHANT_ADMIN",
                store["store_id"],
            )
        self.current = {}
        self.current_profiles = {}

    def request(self, method: str, path: str, username: str | None = None, **kwargs):
        headers = (
            {"Authorization": "Bearer " + self.tokens[username]} if username else {}
        )
        response = self.client.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        return response

    def login(self, credentials: dict, role: str, merchant: str | None):
        value = self.request("POST", "/api/v1/auth/login", json=credentials).json()
        if value.get("role") != role or value.get("merchant_id") != merchant:
            raise ValueError("登录身份与资料归属不匹配")
        self.tokens[credentials["username"]] = value["access_token"]

    def save_state(self):
        STATE.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE.with_suffix(".new")
        temporary.write_bytes(
            (json.dumps(self.state, ensure_ascii=False, indent=2) + "\n").encode()
        )
        temporary.replace(STATE)

    @staticmethod
    def matches(current: dict, body: dict) -> bool:
        return current.get("version") == body["expected_version"] + 1 and all(
            current.get(key) == value
            for key, value in body.items()
            if key != "expected_version"
        )

    def preflight(self):
        account = self.data["account"]
        identities = [(account["username"], account["avatar"])] + [
            (s["username"], s["logo"]) for s in self.data["stores"]
        ]
        for username, image in identities:
            profile = self.request("GET", "/api/v1/account/profile", username).json()
            owned = self.state["avatars"].get(username)
            if (owned is None and profile.get("avatar_id")) or (
                owned is not None
                and (
                    profile != owned["profile"]
                    or owned["source"] != digest(asset_path(image).read_bytes())
                )
            ):
                raise ValueError("账号已有其他头像，请先核对，不自动覆盖")
            if (
                username == account["username"]
                and profile["display_name"] != account["display_name"]
            ):
                raise ValueError("展示账号昵称与既定资料不一致")
            self.current_profiles[username] = profile
        for store in self.data["stores"]:
            self.check_presentation(
                "/api/v1/merchant/store/presentation",
                store["username"],
                store["store_id"],
            )
        for product in self.data["products"]:
            username = next(
                s["username"]
                for s in self.data["stores"]
                if s["store_id"] == product["store_id"]
            )
            actual = self.request(
                "GET", f"/api/v1/shop/products/{product['product_id']}"
            ).json()
            if (actual["name"], actual["store_id"]) != (
                product["name"],
                product["store_id"],
            ):
                raise ValueError("商品身份发生变化，停止配置")
            self.check_presentation(
                f"/api/v1/merchant/products/{product['product_id']}/presentation",
                username,
                product["product_id"],
            )

    def check_presentation(self, path: str, username: str, key: str):
        current = self.request("GET", path, username).json()
        pending = self.state["pending"].get(key)
        if pending and self.matches(current, pending):
            self.state["presentations"][key] = current
            del self.state["pending"][key]
        require_owned(key, current, self.state["presentations"].get(key))
        self.current[key] = current

    def media(self, username: str, image: str) -> str:
        value = asset_path(image).read_bytes()
        key = username + ":" + digest(value)
        if key not in self.state["media"]:
            item = self.request(
                "POST",
                "/api/v1/merchant/media",
                username,
                files={"file": (Path(image).name, value, "image/jpeg")},
            ).json()
            self.state["media"][key] = item["media_id"]
            self.save_state()
        identity = self.state["media"][key]
        self.request("GET", f"/api/v1/merchant/media/{identity}", username)
        return identity

    def avatar(self, username: str, image: str):
        if username in self.state["avatars"]:
            return
        profile = self.current_profiles[username]
        value = asset_path(image).read_bytes()
        result = self.request(
            "POST",
            "/api/v1/account/avatar",
            username,
            data={"expected_version": str(profile["version"])},
            files={"file": (Path(image).name, value, "image/jpeg")},
        ).json()
        encoded = self.request("GET", "/api/v1/account/avatar", username).content
        self.state["avatars"][username] = {
            "source": digest(value),
            "profile": result,
            "encoded_sha256": digest(encoded),
        }
        self.save_state()

    def presentation(self, username: str, key: str, path: str, body: dict):
        current = self.current[key]
        if all(current.get(k) == value for k, value in body.items()):
            return
        body = {**body, "expected_version": current["version"]}
        self.state["pending"][key] = body
        self.save_state()
        self.state["presentations"][key] = self.request(
            "POST", path, username, json=body
        ).json()
        del self.state["pending"][key]
        self.save_state()

    def apply(self):
        account = self.data["account"]
        self.avatar(account["username"], account["avatar"])
        for store in self.data["stores"]:
            username = store["username"]
            self.avatar(username, store["logo"])
            self.presentation(
                username,
                store["store_id"],
                "/api/v1/merchant/store/presentation",
                {
                    **{
                        k: store[k]
                        for k in ("introduction", "contact_phone", "service_hours")
                    },
                    "logo_id": self.media(username, store["logo"]),
                },
            )
        for product in self.data["products"]:
            username = next(
                s["username"]
                for s in self.data["stores"]
                if s["store_id"] == product["store_id"]
            )
            self.presentation(
                username,
                product["product_id"],
                f"/api/v1/merchant/products/{product['product_id']}/presentation",
                {
                    **{
                        k: product[k]
                        for k in ("specifications", "shipping_note", "aftercare_note")
                    },
                    "images": [
                        self.media(username, image) for image in product["images"]
                    ],
                    "variant_images": { variant: self.media(username, image) for variant, image in product.get("variant_images", {}).items() },
                },
            )

    def verify(self):
        for username, entry in self.state["avatars"].items():
            current = self.request("GET", "/api/v1/account/profile", username).json()
            encoded = self.request("GET", "/api/v1/account/avatar", username).content
            if (
                current != entry["profile"]
                or digest(encoded) != entry["encoded_sha256"]
            ):
                raise ValueError("头像读回不一致")
            if (
                encoded[:8] != b"\x89PNG\r\n\x1a\n"
                or int.from_bytes(encoded[16:20], "big") != 256
                or int.from_bytes(encoded[20:24], "big") != 256
            ):
                raise ValueError("头像不是服务端标准256方图")
        if len(self.state["avatars"]) != 4 or len(self.state["presentations"]) != 15:
            raise ValueError("资料未配置完整")
        for store in self.data["stores"]:
            key = store["store_id"]
            current = self.request(
                "GET", f"/api/v1/shop/stores/{key}/presentation"
            ).json()
            if current != self.state["presentations"][key]:
                raise ValueError("公开店铺资料读回不一致")
            self.request("GET", f"/api/v1/shop/media/{current['logo_id']}")
        for product in self.data["products"]:
            key = product["product_id"]
            current = self.request(
                "GET", f"/api/v1/shop/products/{key}/presentation"
            ).json()
            if (
                current != self.state["presentations"][key]
                or len(current["images"]) != 2
            ):
                raise ValueError("公开商品资料读回不一致")
            cover = self.request("GET", f"/api/v1/shop/products/{key}").json()[
                "cover_image_id"
            ]
            if cover != current["images"][0]:
                raise ValueError("商品主图与图集不一致")
            for image in current["images"]:
                self.request("GET", f"/api/v1/shop/media/{image}")
        print(
            "读回通过：4个账号头像、3家店铺、12款商品、24张商品图，公开主图与图集一致。"
        )


def main():
    parser = argparse.ArgumentParser(description="展示资料配置；默认仅核对预览")
    parser.add_argument("--buyer-credentials", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    data = validate_assets()
    with httpx.Client(
        base_url=BASE, timeout=30, follow_redirects=False, trust_env=False
    ) as client:
        work = Configuration(client, data, args.buyer_credentials)
        work.preflight()
        if args.apply:
            work.apply()
        if args.apply or args.verify:
            work.verify()
        else:
            print(
                "预览通过：仅配置专用买家、三店商家头像及店铺资料、十二款精选商品资料。使用 --apply 保存。"
            )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, httpx.HTTPError) as exc:
        raise SystemExit(f"配置停止：{exc}") from None
