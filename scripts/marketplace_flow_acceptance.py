"""Browser-owned shopping cases, exact-run mock investigation and preserved-data verification.

Only investigation writes through the existing fenced production runtime. All shopping,
Case input and human decisions are performed in the real product. Never drains a queue.
Raw baseline stays in ignored tmp; no tokens or original keys are exported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent/src"))
import reviewer_demo as demo
from merchant_fulfillment_acceptance import snapshot
from product_flow_acceptance import queued_run
from resolveflow.contracts._schemaio import component_validator
from resolveflow.harness.model import MockModelClient
from resolveflow.policies.index import PolicyIndex
from resolveflow.policies.retrieval import embedder
from resolveflow.runtime.db import Database
from resolveflow.runtime.factory import DeploymentConfig, build_investigation
from resolveflow.runtime.leases import RunLease
from resolveflow.runtime.worker import RunWorker

LOCAL = ROOT / "tmp/marketplace-flow"
PUBLIC = ROOT / "reports/marketplace-flow/verification.json"


def save(path, value):
    demo.atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def buyer(settings):
    return demo.login(settings, "demo-buyer", "demo-pass-4001")


def inspect(settings, document):
    token = buyer(settings)
    details = {}
    for purchase in document["purchases"]:
        for line in purchase["lines"]:
            page = demo.api(
                settings,
                "/api/v1/customer/cases?line_id=" + line["line_id"],
                token=token,
            )
            if len(page["items"]) > 1:
                raise demo.DemoRefused(
                    "multiple cases on dedicated new line; never rebind"
                )
            if page["items"]:
                case = page["items"][0]["case_id"]
                assert line.get("case_id") in (None, case)
                line["case_id"] = case
                details[case] = demo.api(
                    settings, "/api/v1/customer/cases/" + case, token=token
                )
    return details


def investigate(settings, database, document, line_id):
    matches = [
        (p, line)
        for p in document["purchases"]
        for line in p["lines"]
        if line["line_id"] == line_id
    ]
    if len(matches) != 1:
        raise demo.DemoRefused(
            "only one registered new shopping line may be investigated"
        )
    purchase, line = matches[0]
    detail = inspect(settings, document)[line["case_id"]]
    assert detail["case"]["status"] == "QUEUED", (
        "no reset or repeated terminal investigation"
    )
    revision = detail["input_revision"]
    run_id = queued_run(database, line, revision)
    citations = demo.preflight(
        settings,
        case_id=line["case_id"],
        run_id=run_id,
        input_revision=revision,
        line_id=line_id,
        tool_calls=(
            (demo.TOOL_GET_SHIPMENT, {"limit": 3}),
            (demo.TOOL_GET_EVIDENCE, {}),
        ),
    )
    bundle, digest = demo.pinned_bundle(settings, line["case_id"])
    expected_bundle = (
        "policy-logistics-2026.10"
        if purchase["store_id"] == "M-1001"
        else "policy-demo-m1002-logistics-2026.10"
    )
    assert bundle == expected_bundle
    encoder = embedder(str(demo.EMBEDDING_PATH))
    index = PolicyIndex(database)
    hits = index.search(
        merchant_id=purchase["store_id"],
        bundle_ids=[bundle],
        manifest_hash=digest,
        query="已付款未发货 NOT_SHIPPED ORDER_PAID",
        path="dense",
        top_k=5,
        embedder=encoder,
    )
    rule = next(hit for hit in hits if hit.rule_id == "R-UNSHIPPED-001")
    narrow = index.search(
        merchant_id=purchase["store_id"],
        bundle_ids=[bundle],
        manifest_hash=digest,
        query=rule.text,
        path="dense",
        top_k=1,
        embedder=encoder,
    )
    assert narrow and narrow[0].rule_id == rule.rule_id
    citation = {
        k: getattr(rule, k)
        for k in ("bundle_id", "version", "rule_id", "chunk_id", "content_hash")
    }
    shipment = citations[demo.TOOL_GET_SHIPMENT]
    evidence = citations[demo.TOOL_GET_EVIDENCE]
    script = [
        {
            "kind": "READ_TOOL",
            "tool_name": demo.TOOL_GET_SHIPMENT,
            "arguments": {"limit": 3},
        },
        {"kind": "READ_TOOL", "tool_name": demo.TOOL_GET_EVIDENCE, "arguments": {}},
        {"kind": "SEARCH_POLICY", "query": rule.text, "arguments": {"top_k": 1}},
        {
            "kind": "PROPOSE",
            "case_type": "LOGISTICS",
            "recommended_action": "REFUND",
            "reason_codes": ["ORDER_NOT_SHIPPED"],
            "summary": "合成验收mock：持久物流为NOT_SHIPPED且有付款事件；按绑定政策建议该行全额退款，由工作人员最终审批。",
            "evidence_refs": [shipment, evidence],
            "policy_refs": [citation],
            "review_findings": [
                {
                    "kind": "FACT",
                    "text": "已保存物流记录为待发货，包含付款完成事件。",
                    "observation_ids": [shipment["observation_id"]],
                },
                {
                    "kind": "FACT",
                    "text": "已读取本版提交材料、补证问题及回答和核验记录；客户陈述不自动等于真实事实。",
                    "observation_ids": [evidence["observation_id"]],
                },
            ],
        },
    ]
    config = DeploymentConfig(
        mode="mock",
        context_window_tokens=32768,
        case_base_url=settings.case_url,
        commerce_base_url=settings.commerce_url,
        policy_index=True,
        embedding_path=str(demo.EMBEDDING_PATH),
    )
    action = build_investigation(
        database=database,
        config=config,
        model=MockModelClient(script=script),
        service_identity_source=lambda: demo.mint_service_token("agent-service"),
    )
    with RunLease(database, owner="marketplace-browser-acceptance").acquire(
        run_id=run_id
    ) as claimed:
        if claimed is None or claimed.legacy:
            raise demo.DemoRefused(
                "target cannot be claimed; no fallback to another run"
            )
        outcome = RunWorker(database, investigate=action, recoverable=True).finish(
            claimed, action(claimed.facts)
        )
    result = {
        "case_id": line["case_id"],
        "run_id": run_id,
        "input_revision": revision,
        "status": outcome.status,
        "callback_kind": outcome.callback_kind,
        "reason_code": outcome.result.reason_code,
        "model_mode": "mock",
    }
    document["investigations"].append(result)
    return result


def verify(settings, database, document):
    before = json.loads((LOCAL / "before.json").read_text(encoding="utf-8"))
    details = inspect(settings, document)
    assert len(document["purchases"]) == 2 and len(details) == 4
    accounts = {
        u: demo.login(settings, u, p)
        for u, p in [
            ("demo-buyer", "demo-pass-4001"),
            ("demo-customer", "demo-pass-1001"),
            ("demo-customer-m2", "demo-pass-2001"),
            ("demo-reviewer", "demo-pass-1003"),
            ("demo-reviewer-m2", "demo-pass-2002"),
            ("demo-admin", "demo-pass-1100"),
            ("demo-admin-m2", "demo-pass-2100"),
        ]
    }
    checks, purchases = [], []

    def check(label, path, account, expected=200, body=None, headers=None):
        status, value = demo.http(
            "GET" if body is None else "POST",
            settings.gateway_url + path,
            token=accounts.get(account),
            body=body,
            headers=headers,
        )
        assert status == expected, (label, path, status, expected)
        checks.append({"check": label, "status": status, "passed": True})
        return value

    def schema(name, value):
        validator = component_validator("case", name, "contracts/core")
        assert validator.accepts(value), validator.error_messages(value)

    check("anonymous purchases denied", "/api/v1/shop/purchases", None, 401)
    for account in ["demo-buyer", "demo-reviewer"]:
        check("non-admin trade access denied", "/api/v1/merchant/orders", account, 403)
    for purchase in document["purchases"]:
        merchant, order = purchase["store_id"], str(uuid.UUID(purchase["order_id"]))
        first = merchant == "M-1001"
        admin, foreign_admin = (
            ("demo-admin", "demo-admin-m2")
            if first
            else ("demo-admin-m2", "demo-admin")
        )
        staff, foreign_staff = (
            ("demo-reviewer", "demo-reviewer-m2")
            if first
            else ("demo-reviewer-m2", "demo-reviewer")
        )
        current = check(
            "buyer final purchase",
            "/api/v1/shop/purchases/" + purchase["purchase_id"],
            "demo-buyer",
        )
        assert current["refund_status"] == (
            "REFUNDED" if first else "PARTIALLY_REFUNDED"
        )
        trade = check(
            "own merchant per-line aftercare", "/api/v1/merchant/orders/" + order, admin
        )
        schema("MerchantTrade", trade)
        assert not trade["can_ship"] and trade["fulfillment"]["status"] == "NOT_SHIPPED"
        check(
            "foreign merchant trade denied",
            "/api/v1/merchant/orders/" + order,
            foreign_admin,
            404,
        )
        check(
            "refunded order cannot be shipped",
            "/api/v1/merchant/orders/" + order + "/simulated-shipment",
            admin,
            409,
            {"expected_version": 1},
            {"Idempotency-Key": str(uuid.uuid4())},
        )
        fulfillment = check(
            "buyer persistent fulfillment",
            "/api/v1/shop/purchases/" + purchase["purchase_id"] + "/fulfillment",
            "demo-buyer",
        )
        schema("OrderFulfillment", fulfillment)
        assert fulfillment == trade["fulfillment"] and fulfillment["version"] == 1
        assert all(
            [e["code"] for e in line["events"]] == ["ORDER_PAID"]
            for line in fulfillment["lines"]
        )
        ledger = demo.mysql_rows(
            "SELECT paid_amount,refunded_amount,reserved_refund_amount FROM payment_ledger "
            f"WHERE order_id='{order}'",
            settings,
            database="commerce_db",
        )
        expected_paid, expected_refund = (72700, 72700) if first else (21800, 12900)
        assert list(map(int, ledger[0])) == [expected_paid, expected_refund, 0]
        outcomes = []
        slots = {line["line_id"]: line for line in trade["line_aftercare"]}
        for line in purchase["lines"]:
            case = str(uuid.UUID(line["case_id"]))
            detail = details[case]
            cancelled = line["sku"] == "SKU-2002-SILVER"
            assert detail["case"]["status"] == (
                "CANCELLED" if cancelled else "CLOSED_SUCCESS"
            )
            assert detail["allowed_actions"] == []
            expected_amount = int(line["line_amount"])
            rows = demo.mysql_rows(
                "SELECT state,amount_minor,operation_id FROM refund_operation "
                f"WHERE line_id='{line['line_id']}'",
                settings,
                database="commerce_db",
            )
            assert (
                (rows == [])
                if cancelled
                else (
                    len(rows) == 1
                    and rows[0][0] == "SUCCEEDED"
                    and int(rows[0][1]) == expected_amount
                )
            )
            assert slots[line["line_id"]]["state"] == (
                "FREE" if cancelled else "CONSUMED"
            )
            eligibility = check(
                "line eligibility matches terminal result",
                "/api/v1/customer/order-lines/" + line["line_id"],
                "demo-buyer",
            )
            assert eligibility["can_apply"] == cancelled
            for account in ["demo-customer", "demo-customer-m2"]:
                check(
                    "other customer cannot read new case",
                    "/api/v1/customer/cases/" + case,
                    account,
                    404,
                )
                check(
                    "other customer cannot read new line",
                    "/api/v1/customer/order-lines/" + line["line_id"],
                    account,
                    404,
                )
            for suffix in ["", "/collaboration", "/review-context", "/investigation"]:
                check(
                    "foreign staff cannot read case",
                    "/api/v1/cases/" + case + suffix,
                    foreign_staff,
                    404,
                )
            check(
                "buyer cannot read private investigation",
                "/api/v1/cases/" + case + "/investigation",
                "demo-buyer",
                403,
            )
            if not cancelled:
                for suffix, body in [
                    (
                        "/evidence",
                        {
                            "text": "消费后禁止追加的合成材料",
                            "evidence_kind": "CUSTOMER_STATEMENT",
                        },
                    ),
                    ("/cancel", {"reason": "消费后撤销必须拒绝"}),
                ]:
                    check(
                        "consumed case rejects mutation",
                        "/api/v1/cases/" + case + suffix,
                        "demo-buyer",
                        409,
                        body,
                    )
                snapshot_case = check(
                    "own staff terminal snapshot", "/api/v1/cases/" + case, staff
                )
                assert snapshot_case["authorization"]["status"] == "CONSUMED"
                assert (
                    snapshot_case["authorization"]["input_revision"]
                    == detail["input_revision"]
                )
                assert (
                    snapshot_case["proposal"]["input_revision"]
                    == detail["input_revision"]
                )
                collaboration = check(
                    "terminal owner retained",
                    "/api/v1/cases/" + case + "/collaboration",
                    staff,
                )
                expected_owner = (
                    "demo-reviewer-2" if line["sku"] == "SKU-1002-WHITE" else staff
                )
                assert collaboration["owner"]["username"] == expected_owner
            if line["sku"] == "SKU-2001-CREAM":
                assert detail["input_revision"] == 4 and len(detail["questions"]) == 1
                assert detail["questions"][0]["status"] == "ANSWERED"
                assert (
                    detail["questions"][0]["answers"][0]["verification_result"]
                    == "CONFIRMED"
                )
                assert len(detail["materials"]) == 2
            outcomes.append(
                {
                    "line_id": line["line_id"],
                    "case_id": case,
                    "status": detail["case"]["status"],
                    "revision": detail["input_revision"],
                    "line_paid_minor": expected_amount,
                    "refund_operation_count": len(rows),
                    "refund": rows,
                }
            )
        purchases.append(
            {
                "order_id": order,
                "store_id": merchant,
                "paid_minor": expected_paid,
                "refunded_minor": expected_refund,
                "reserved_minor": 0,
                "refund_status": current["refund_status"],
                "lines": outcomes,
            }
        )
    unknown = "ce263102-965d-4dee-974f-351c9800b5cb"
    for suffix, body in [
        (
            "/evidence",
            {"text": "禁止写入UNKNOWN", "evidence_kind": "CUSTOMER_STATEMENT"},
        ),
        ("/cancel", {"reason": "UNKNOWN不能撤销"}),
    ]:
        check(
            "original UNKNOWN rejects mutation",
            "/api/v1/cases/" + unknown + suffix,
            "demo-customer",
            409,
            body,
        )
    after = snapshot(settings, database)
    after["fulfillment_heads"] = demo.mysql_rows(
        "SELECT order_id,status,version,updated_at,shipment_key,shipment_actor,expected_version FROM order_fulfillment ORDER BY order_id",
        settings,
        database="commerce_db",
    )
    preserved = {}
    canonical = lambda row: json.dumps(row, sort_keys=True)
    for name, rows in before.items():
        if name == "cart_heads":
            assert len(rows) == len(after[name])
            assert all(
                a[:2] == b[:2] and int(b[2]) >= int(a[2])
                for a, b in zip(rows, after[name], strict=True)
            )
            preserved[name] = {
                "rows": len(rows),
                "unchanged": False,
                "revisions_before": [r[2] for r in rows],
                "revisions_after": [r[2] for r in after[name]],
                "reason": "normal browser cart operations",
            }
            continue
        old, new = Counter(map(canonical, rows)), Counter(map(canonical, after[name]))
        assert not (old - new), "original rows changed: " + name
        preserved[name] = {
            "rows": len(rows),
            "unchanged": True,
            "sha256": hashlib.sha256(canonical(rows).encode()).hexdigest(),
        }
    assert len(after["cases"]) == len(before["cases"]) + 4
    assert len(after["orders"]) == len(before["orders"]) + 2
    assert len(after["operations"]) == len(before["operations"]) + 3
    assert len(after["cart_items"]) == len(before["cart_items"])
    with database.connection() as connection:
        runs = connection.execute(
            "SELECT run_id,case_id,input_revision,status,budget_spent FROM agent_run WHERE case_id=ANY(%s::uuid[]) ORDER BY case_id,input_revision",
            (list(details),),
        ).fetchall()
        models = connection.execute(
            "SELECT run_id,COUNT(*) AS calls FROM agent_model_call WHERE run_id=ANY(%s::uuid[]) GROUP BY run_id",
            ([str(r["run_id"]) for r in runs],),
        ).fetchall()
        tool_rows = connection.execute(
            "SELECT run_id,observation FROM agent_tool_call WHERE run_id=ANY(%s::uuid[]) AND observation IS NOT NULL",
            ([i["run_id"] for i in document["investigations"]],),
        ).fetchall()
        manifests = connection.execute(
            "SELECT run_id,manifest FROM agent_run_model_budget WHERE run_id=ANY(%s::uuid[])",
            ([i["run_id"] for i in document["investigations"]],),
        ).fetchall()
        lamp = next(
            line
            for p in document["purchases"]
            for line in p["lines"]
            if line["sku"] == "SKU-2001-CREAM"
        )
        context = connection.execute(
            "SELECT review_context FROM agent_run WHERE run_id=%s",
            (demo.agent_run_id(lamp["case_id"], 4),),
        ).fetchone()["review_context"]
        requests = connection.execute(
            "SELECT request_body FROM agent_model_call WHERE run_id=%s",
            (demo.agent_run_id(lamp["case_id"], 4),),
        ).fetchall()
    executed = {i["run_id"] for i in document["investigations"]}
    assert len(executed) == 5 and len(models) == 5
    assert {str(row["run_id"]) for row in models} == executed
    cancelled_case = next(
        line["case_id"]
        for p in document["purchases"]
        for line in p["lines"]
        if line["sku"] == "SKU-2002-SILVER"
    )
    for run in runs:
        expected = (
            "COMPLETED"
            if str(run["run_id"]) in executed
            else ("QUEUED" if str(run["case_id"]) == cancelled_case else "STALE")
        )
        assert run["status"] == expected
        if expected != "COMPLETED":
            assert run["budget_spent"] == {}, "unused revisions must not spend"
    assert len(manifests) == 5 and all(
        m["manifest"]["model"]["provider"] == "mock"
        and m["manifest"]["model"]["model_id"] == "mock-scripted"
        for m in manifests
    )
    assert len(context["materials"]) == 3 and len(context["questions"]) == 1
    verification = next(
        m for m in context["materials"] if m["source_type"] == "REVIEWER_VERIFICATION"
    )
    assert verification["verification_result"] == "CONFIRMED"
    assert any(
        m.get("question_id")
        and m["evidence_id"] == verification["reviewed_evidence_id"]
        for m in context["materials"]
    )
    serialized_requests = json.dumps(requests, ensure_ascii=False)
    assert all(m["content"] in serialized_requests for m in context["materials"]), (
        "actual model requests lost current material"
    )
    lamp_authorizations = demo.mysql_rows(
        "SELECT status,input_revision FROM case_authorization "
        f"WHERE case_id='{uuid.UUID(lamp['case_id'])}' ORDER BY input_revision",
        settings,
        database="case_db",
    )
    assert lamp_authorizations == [
        ["EXPIRED", "2"],
        ["REVOKED", "3"],
        ["CONSUMED", "4"],
    ]
    observations = []
    for item in document["investigations"]:
        obs = [
            r["observation"] for r in tool_rows if str(r["run_id"]) == item["run_id"]
        ]
        expected_tools = {demo.TOOL_GET_SHIPMENT, "search_policy"}
        if item["case_id"] == lamp["case_id"]:
            expected_tools.add(demo.TOOL_GET_EVIDENCE)
        assert {o["tool_name"] for o in obs} == expected_tools
        policy = next(o for o in obs if o["tool_name"] == "search_policy")
        assert (
            policy["result"]["hit_count"] == 1
            and policy["result"]["hits"][0]["rule_id"] == "R-UNSHIPPED-001"
        )
        assert all(
            o["content_hash"]
            and o["source_ref"]
            and o["source_version"]
            and o["observation_id"]
            for o in obs
        )
        observations.append(
            {
                "run_id": item["run_id"],
                "tools": sorted(expected_tools),
                "policy_rule": "R-UNSHIPPED-001",
            }
        )
    assert len(after["runs"]) == len(before["runs"]) + len(runs)
    report = {
        "date": "2026-10-03",
        "synthetic": True,
        "model_mode": "mock",
        "paid_model_calls": 0,
        "purchases": purchases,
        "checks": checks,
        "preserved": preserved,
        "investigations": document["investigations"],
        "run_audit": [
            {**r, "run_id": str(r["run_id"]), "case_id": str(r["case_id"])}
            for r in runs
        ],
        "model_call_counts": [{**r, "run_id": str(r["run_id"])} for r in models],
        "persisted_tool_observations": len(tool_rows),
        "observation_audit": observations,
        "lamp_authorization_audit": lamp_authorizations,
        "latest_context": {
            "revision": 4,
            "materials": 3,
            "questions": 1,
            "answer_verification": "CONFIRMED",
            "actual_model_request_contains_all_materials": True,
        },
        "outcomes_verified": True,
    }
    save(PUBLIC, report)
    print(
        f"{len(checks)} HTTP checks passed; 3 exact per-line refunds; original data preserved"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["snapshot", "register", "inspect", "investigate", "verify"]
    )
    parser.add_argument("--draft-id")
    parser.add_argument("--line-id")
    args = parser.parse_args()
    settings = demo.settings_from_environ()
    demo.guard(settings)
    database = Database(settings.agent_dsn)
    LOCAL.mkdir(parents=True, exist_ok=True)
    file = LOCAL / "samples.json"
    try:
        if args.command == "snapshot":
            if (LOCAL / "before.json").exists():
                raise demo.DemoRefused("baseline already exists; refusing to overwrite")
            state = snapshot(settings, database)
            state["fulfillment_heads"] = demo.mysql_rows(
                "SELECT order_id,status,version,updated_at,shipment_key,shipment_actor,expected_version FROM order_fulfillment ORDER BY order_id",
                settings,
                database="commerce_db",
            )
            save(LOCAL / "before.json", state)
            save(
                file,
                {
                    "synthetic": True,
                    "model_mode": "mock",
                    "purchases": [],
                    "investigations": [],
                },
            )
            print({k: len(v) for k, v in state.items()})
            return
        document = json.loads(file.read_text(encoding="utf-8"))
        if args.command == "register":
            draft = str(uuid.UUID(args.draft_id))
            p = demo.api(
                settings,
                "/api/v1/shop/purchases/draft%3A" + draft,
                token=buyer(settings),
            )
            before = json.loads((LOCAL / "before.json").read_text(encoding="utf-8"))
            assert p["status"] == "PAID" and len(p["lines"]) == 2
            assert p["order_id"] not in {row[0] for row in before["orders"]}, (
                "old purchase cannot become a new fixture"
            )
            assert not any(
                o["store_id"] == p["store_id"] for o in document["purchases"]
            ), "one new purchase per store"
            document["purchases"].append(p)
            print(json.dumps(p, ensure_ascii=False))
        elif args.command == "inspect":
            details = inspect(settings, document)
            print(
                json.dumps(
                    {
                        case: {
                            "status": d["case"]["status"],
                            "revision": d["input_revision"],
                        }
                        for case, d in details.items()
                    }
                )
            )
        elif args.command == "verify":
            verify(settings, database, document)
        else:
            print(json.dumps(investigate(settings, database, document, args.line_id)))
        save(file, document)
    finally:
        database.close()


if __name__ == "__main__":
    main()
