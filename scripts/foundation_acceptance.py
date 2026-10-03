"""Concentrated real-HTTP foundation and three-store refund verification (explicit mock decisions).

Run only on the clean fixed demo. Creates temporary verification transactions; the human-authorized
reset restores the empty baseline afterwards. Does not call a paid model or drain unrelated runs.
"""

from __future__ import annotations

import json
import sys
import uuid
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reviewer_demo as demo
from demo_foundation import checked_settings, verify
from foundation_data import accounts
from product_flow_acceptance import queued_run
from resolveflow.harness.model import MockModelClient
from resolveflow.policies import PolicyIndex, embedder
from resolveflow.runtime.db import Database
from resolveflow.runtime.factory import DeploymentConfig, build_investigation
from resolveflow.runtime.leases import RunLease
from resolveflow.runtime.worker import RunWorker


def main() -> None:
    settings = checked_settings()
    verify(settings)
    results = []

    def check(method, path, token=None, body=None, status=200, headers=None):
        code, value = demo.http(
            method, settings.gateway_url + path, token=token, body=body, headers=headers
        )
        assert code == status, f"{method} {path}: {code}, expected {status}: {value}"
        results.append({"method": method, "path": path, "status": code})
        return value

    tokens = {}
    for account in accounts():
        tokens[account["username"]] = check(
            "POST",
            "/api/v1/auth/login",
            body={"username": account["username"], "password": "123456"},
        )["access_token"]
    platform, buyer, other = tokens["platform"], tokens["buyer01"], tokens["buyer02"]
    assert len(check("GET", "/api/v1/shop/stores")) == 3
    products = check("GET", "/api/v1/shop/products?limit=48")["items"]
    assert len(products) == 30 and sum(len(p["skus"]) for p in products) == 45
    assert (
        len(check("GET", "/api/v1/shop/products?category=outdoor&limit=48")["items"])
        == 10
    )
    for path in ("/api/v1/review/cases", "/api/v1/orders", "/api/v1/merchant/products"):
        check("GET", path, platform, status=403)
    for actor in (buyer, tokens["admin01"], tokens["staff01"]):
        check("GET", "/api/v1/platform/merchants", actor, status=403)
    for i in range(1, 4):
        rows = check(
            "GET", "/api/v1/merchant/products?limit=48", tokens[f"admin{i:02d}"]
        )["items"]
        assert len(rows) == 10 and all(p["store_id"] == f"M-100{i}" for p in rows)
    check("GET", "/api/v1/merchant/products/P-2001", tokens["admin01"], status=404)
    created = check(
        "POST",
        "/api/v1/platform/buyers",
        platform,
        {
            "username": "checkbuyer",
            "display_name": "验证买家",
            "password": "123456",
            "reason": "集中验收",
        },
        201,
    )
    temp = check(
        "POST",
        "/api/v1/auth/login",
        body={"username": "checkbuyer", "password": "123456"},
    )["access_token"]
    check(
        "POST",
        "/api/v1/platform/buyers/checkbuyer",
        platform,
        {
            "display_name": created["display_name"],
            "enabled": False,
            "expected_version": created["version"],
            "reason": "集中停用验收",
        },
    )
    check("GET", "/api/v1/auth/me", temp, status=401)
    check(
        "POST",
        "/api/v1/platform/buyers/checkbuyer",
        platform,
        {
            "display_name": created["display_name"],
            "enabled": True,
            "expected_version": 2,
            "password": "654321",
            "reason": "集中重置验收",
        },
    )
    check(
        "POST",
        "/api/v1/auth/login",
        body={"username": "checkbuyer", "password": "123456"},
        status=401,
    )
    check(
        "POST",
        "/api/v1/auth/login",
        body={"username": "checkbuyer", "password": "654321"},
    )
    store_body = {
        "merchant_id": "M-VERIFY",
        "name": "集中验证商家",
        "description": "验证创建与原请求恢复",
        "username": "checkadmin",
        "display_name": "验证管理员",
        "password": "123456",
        "reason": "集中验收",
    }
    store = check("POST", "/api/v1/platform/merchants", platform, store_body, 201)
    check("POST", "/api/v1/platform/merchants", platform, store_body, 201)
    assert not store["policy_ready"]
    temp_admin = check(
        "POST",
        "/api/v1/auth/login",
        body={"username": "checkadmin", "password": "123456"},
    )["access_token"]
    new_product = check(
        "POST",
        "/api/v1/merchant/products",
        temp_admin,
        {
            "name": "验证收纳袋",
            "description": "验证商品维护",
            "category": "outdoor",
            "asset_key": "bag",
            "listed": True,
            "skus": [
                {
                    "variant": "标准款",
                    "unit_amount": 1234,
                    "max_quantity": 10,
                    "listed": True,
                }
            ],
        },
        201,
    )
    assert (
        check("GET", "/api/v1/shop/products/" + new_product["product_id"])[
            "from_amount"
        ]
        == 1234
    )
    check(
        "POST",
        "/api/v1/platform/merchants/M-VERIFY",
        platform,
        {
            "name": store["name"],
            "description": store["description"],
            "enabled": False,
            "expected_version": store["version"],
            "reason": "集中停用验收",
        },
    )
    check("GET", "/api/v1/auth/me", temp_admin, status=401)
    check("GET", "/api/v1/shop/products/" + new_product["product_id"], status=404)
    flows = []
    with closing(Database(settings.agent_dsn)) as database:
        for i in range(1, 4):
            merchant = f"M-100{i}"
            product = next(p for p in products if p["store_id"] == merchant)
            sku = product["skus"][0]
            draft = check(
                "POST",
                "/api/v1/shop/drafts",
                buyer,
                {
                    "sku_id": sku["sku_id"],
                    "quantity": 1,
                    "expected_sku_version": sku["version"],
                },
                200,
                {"Idempotency-Key": str(uuid.uuid4())},
            )
            check("GET", "/api/v1/shop/drafts/" + draft["draft_id"], other, status=404)
            if i == 1:
                row = check(
                    "GET",
                    "/api/v1/merchant/products/" + product["product_id"],
                    tokens["admin01"],
                )
                write = {
                    k: row[k]
                    for k in ("name", "description", "category", "asset_key", "listed")
                }
                write.update(
                    expected_version=row["version"],
                    skus=[
                        {
                            k: s[k]
                            for k in (
                                "sku_id",
                                "variant",
                                "unit_amount",
                                "max_quantity",
                                "listed",
                            )
                        }
                        for s in row["skus"]
                    ],
                )
                for s in write["skus"]:
                    s["unit_amount"] += 100
                check(
                    "POST",
                    "/api/v1/merchant/products/" + row["product_id"],
                    tokens["admin01"],
                    write,
                )
                check(
                    "POST",
                    "/api/v1/shop/drafts",
                    buyer,
                    {
                        "sku_id": sku["sku_id"],
                        "quantity": 1,
                        "expected_sku_version": sku["version"],
                    },
                    409,
                    {"Idempotency-Key": str(uuid.uuid4())},
                )
                assert (
                    check("GET", "/api/v1/shop/drafts/" + draft["draft_id"], buyer)[
                        "total_amount"
                    ]
                    == draft["total_amount"]
                )
            payment = check(
                "POST",
                "/api/v1/shop/drafts/" + draft["draft_id"] + "/payment",
                buyer,
                {},
                200,
                {"Idempotency-Key": str(uuid.uuid4())},
            )
            assert (
                payment["status"] == "SUCCEEDED"
                and payment["total_amount"] == draft["total_amount"]
            )
            case = check(
                "POST",
                "/api/v1/cases",
                buyer,
                {
                    "line_id": payment["line_id"],
                    "description": "已付款未发货，申请整行退款。合成集中验收。",
                    "requested_actions": ["REFUND"],
                },
                201,
                {"Idempotency-Key": str(uuid.uuid4())},
            )["case_id"]
            check("GET", "/api/v1/customer/cases/" + case, other, status=404)
            staff = tokens[f"staff{i * 2 - 1:02d}"]
            collab = check("GET", "/api/v1/cases/" + case + "/collaboration", staff)
            collab = check(
                "POST",
                "/api/v1/cases/" + case + "/collaboration",
                staff,
                {"action": "CLAIM", "reason": "集中验收领取"},
                200,
                {"If-Collaboration-Match": f'"{collab["version"]}"'},
            )
            assert demo.wait_for(
                "dispatched run",
                lambda case=case: (
                    demo.postgres_scalar(
                        "SELECT COUNT(*) FROM agent_run WHERE run_id='"
                        + demo.agent_run_id(case, 1)
                        + "'",
                        settings,
                    )
                    == "1"
                ),
                timeout=30,
            )
            run = queued_run(database, {"case_id": case}, 1)
            refs = demo.preflight(
                settings,
                case_id=case,
                run_id=run,
                input_revision=1,
                line_id=payment["line_id"],
                tool_calls=(
                    (demo.TOOL_GET_SHIPMENT, {"limit": 3}),
                    (demo.TOOL_GET_EVIDENCE, {}),
                ),
            )
            bundle, digest = demo.pinned_bundle(settings, case)
            assert bundle == f"policy-foundation-m100{i}-2026.10"
            index = PolicyIndex(database)
            encoder = embedder(str(demo.EMBEDDING_PATH))
            hits = index.search(
                merchant_id=merchant,
                bundle_ids=[bundle],
                manifest_hash=digest,
                query="已付款未发货 NOT_SHIPPED ORDER_PAID",
                path="dense",
                top_k=5,
                embedder=encoder,
            )
            rule = next(h for h in hits if h.rule_id == "R-UNSHIPPED-001")
            citation = {
                k: getattr(rule, k)
                for k in ("bundle_id", "version", "rule_id", "chunk_id", "content_hash")
            }
            script = [
                {
                    "kind": "READ_TOOL",
                    "tool_name": demo.TOOL_GET_SHIPMENT,
                    "arguments": {"limit": 3},
                },
                {
                    "kind": "READ_TOOL",
                    "tool_name": demo.TOOL_GET_EVIDENCE,
                    "arguments": {},
                },
                {
                    "kind": "SEARCH_POLICY",
                    "query": rule.text,
                    "arguments": {"top_k": 1},
                },
                {
                    "kind": "PROPOSE",
                    "case_type": "LOGISTICS",
                    "recommended_action": "REFUND",
                    "reason_codes": ["ORDER_NOT_SHIPPED"],
                    "summary": "合成mock建议：已付款未发货，建议本行全额模拟退款，由专员最终决定。",
                    "evidence_refs": [
                        refs[demo.TOOL_GET_SHIPMENT],
                        refs[demo.TOOL_GET_EVIDENCE],
                    ],
                    "policy_refs": [citation],
                },
            ]
            action = build_investigation(
                database=database,
                config=DeploymentConfig(
                    mode="mock",
                    context_window_tokens=32768,
                    case_base_url=settings.case_url,
                    commerce_base_url=settings.commerce_url,
                    policy_index=True,
                    embedding_path=str(demo.EMBEDDING_PATH),
                ),
                model=MockModelClient(script=script),
                service_identity_source=lambda: demo.mint_service_token(
                    "agent-service"
                ),
            )
            with RunLease(database, owner="foundation-acceptance").acquire(
                run_id=run
            ) as claimed:
                assert claimed is not None and not claimed.legacy
                outcome = RunWorker(
                    database, investigate=action, recoverable=True
                ).finish(claimed, action(claimed.facts))
                assert outcome.status == "CALLBACK_PENDING", (
                    outcome.status,
                    outcome.result.reason_code,
                )
            assert demo.wait_for(
                "proposal callback",
                lambda case=case: (
                    demo.case_state(settings, case)
                    .get("authorization", {})
                    .get("status")
                    == "PENDING_REVIEW"
                ),
                timeout=30,
            )
            with database.connection() as connection:
                assert (
                    connection.execute(
                        "SELECT status FROM agent_run WHERE run_id=%s", (run,)
                    ).fetchone()["status"]
                    == "COMPLETED"
                )
            snapshot = check("GET", "/api/v1/cases/" + case, staff)
            authorization = snapshot["authorization"]
            body = {
                "authorization_id": authorization["authorization_id"],
                "authorization_version": authorization["authorization_version"],
                "decision": "APPROVE",
                "reason": "人工核对本行实付和当前政策后批准",
            }
            headers = {
                "If-Match": f'"{snapshot["case"]["version"]}"',
                "If-Collaboration-Match": f'"{collab["version"]}"',
            }
            check(
                "POST", "/api/v1/cases/" + case + "/reviews", staff, body, 200, headers
            )
            assert demo.wait_for(
                "refund settled",
                lambda case=case: (
                    demo.case_state(settings, case)["status"] == "CLOSED_SUCCESS"
                ),
                timeout=45,
            )
            row = demo.mysql_rows(
                f"SELECT paid_amount,refunded_amount,reserved_refund_amount FROM commerce_db.payment_ledger WHERE order_id='{payment['order_id']}'",
                settings,
            )[0]
            assert row == [str(draft["total_amount"]), str(draft["total_amount"]), "0"]
            assert (
                demo.mysql_scalar(
                    f"SELECT COUNT(*) FROM commerce_db.refund_operation WHERE line_id='{payment['line_id']}' AND state='SUCCEEDED'",
                    settings,
                )
                == "1"
            )
            check("GET", "/api/v1/customer/cases/" + case, buyer)
            flows.append(
                {
                    "merchant_id": merchant,
                    "case_id": case,
                    "run_id": run,
                    "status": "CLOSED_SUCCESS",
                    "amount_minor": draft["total_amount"],
                    "reserved_minor": 0,
                    "model_mode": "mock",
                }
            )
        with database.connection() as connection:
            calls = connection.execute(
                "SELECT COUNT(*) AS n FROM agent_model_call"
            ).fetchone()["n"]
            tools = connection.execute(
                "SELECT COUNT(*) AS n FROM agent_tool_call WHERE observation IS NOT NULL"
            ).fetchone()["n"]
    report = {
        "verified_at": demo.now_iso(),
        "http_checks": len(results),
        "checks": results,
        "flows": flows,
        "model_mode": "mock",
        "model_calls": calls,
        "tool_observations": tools,
        "live_calls": 0,
    }
    path = demo.ROOT / "reports/foundation/verification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "checks"},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
