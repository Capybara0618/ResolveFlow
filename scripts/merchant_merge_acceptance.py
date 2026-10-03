"""Three-store single-merchant verification; adds synthetic transactions without resetting existing data.

Only mock decisions, real production AgentScope/MCP/dense/HTTP and human approvals.
"""

from __future__ import annotations

import json
import sys
import uuid
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reviewer_demo as demo
from demo_foundation import checked_settings
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
    assert (
        json.loads(
            (demo.RUNTIME_ROOT / "foundation.json").read_text(encoding="utf-8")
        ).get("role_profile")
        == "merchant-single-v1"
    )
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
        profile = check(
            "POST",
            "/api/v1/auth/login",
            body={"username": account["username"], "password": "123456"},
        )
        if account["role"] == "MERCHANT_ADMIN":
            assert profile.get("single_operator") is True
        tokens[account["username"]] = profile["access_token"]
    for i in range(1, 7):
        check(
            "POST",
            "/api/v1/auth/login",
            body={"username": f"staff{i:02d}", "password": "123456"},
            status=401,
        )
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
    for actor in (buyer, tokens["admin01"]):
        check("GET", "/api/v1/platform/merchants", actor, status=403)
    for i in range(1, 4):
        rows = check(
            "GET", "/api/v1/merchant/products?limit=48", tokens[f"admin{i:02d}"]
        )["items"]
        assert len(rows) == 10 and all(p["store_id"] == f"M-100{i}" for p in rows)
    check("GET", "/api/v1/merchant/products/P-2001", tokens["admin01"], status=404)
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
            staff = tokens[f"admin{i:02d}"]
            collab = check("GET", "/api/v1/cases/" + case + "/collaboration", staff)
            assert collab["is_owner"] and collab["owner"]["username"] == f"admin{i:02d}"
            assert collab["version"] == 1 and collab["allowed_actions"] == []
            assert (
                collab["history"][0]["action"] == "AUTO_ASSIGN"
                and collab["history"][0]["actor_username"] == "SYSTEM"
            )
            check(
                "GET",
                "/api/v1/cases/" + case,
                tokens[f"admin{(i % 3) + 1:02d}"],
                status=404,
            )
            check(
                "POST",
                "/api/v1/cases/" + case + "/collaboration",
                staff,
                {"action": "RELEASE", "reason": "单账号不允许释放"},
                403,
                {"If-Collaboration-Match": '"1"'},
            )
            check(
                "POST",
                "/api/v1/admin/accounts",
                staff,
                {
                    "username": "should-not-exist",
                    "display_name": "禁止新增人员",
                    "role": "REVIEWER",
                    "password": "123456",
                    "reason": "单账号守卫",
                },
                403,
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
                    "summary": "合成mock建议：已付款未发货，建议本行全额模拟退款，由商家人工最终决定。",
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
            with RunLease(database, owner="merchant-merge-acceptance").acquire(
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
            for token in (buyer, platform):
                check(
                    "POST",
                    "/api/v1/cases/" + case + "/reviews",
                    token,
                    body,
                    403,
                    headers,
                )
            check(
                "POST",
                "/api/v1/cases/" + case + "/reviews",
                staff,
                body,
                409,
                {**headers, "If-Collaboration-Match": '"0"'},
            )
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
                "SELECT COUNT(*) AS n FROM agent_model_call WHERE run_id=ANY(%s)",
                ([f["run_id"] for f in flows],),
            ).fetchone()["n"]
            tools = connection.execute(
                "SELECT COUNT(*) AS n FROM agent_tool_call WHERE observation IS NOT NULL AND run_id=ANY(%s)",
                ([f["run_id"] for f in flows],),
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
    path = demo.ROOT / "reports/merchant-merge/verification.json"
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
