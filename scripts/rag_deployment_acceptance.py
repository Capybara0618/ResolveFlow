"""One retained-data live deployment check; no reset, mock or queue replay.

Run snapshot before deployment, then exercise after normal start.ps1. Requests use
persisted idempotency keys; exercise resumes the same synthetic order/case. A
non-refund model outcome fails this check and is never replaced with a mock.
Private snapshots stay in tmp; only audited aggregate evidence is publishable.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reviewer_demo as demo
from product_flow_acceptance import baseline_state, fingerprint
from resolveflow.runtime.db import Database

LOCAL = demo.ROOT / "tmp/rag-docker-delivery"


def save(name, value):
    LOCAL.mkdir(exist_ok=True)
    demo.atomic_write(
        LOCAL / name,
        json.dumps(value, ensure_ascii=False, default=str, indent=2) + "\n",
    )


def snapshot(settings, database):
    if (LOCAL / "before.json").exists():
        raise demo.DemoRefused("baseline already exists; do not overwrite")
    state = baseline_state(settings, database)
    with database.connection() as connection:
        state["index_generations"] = connection.execute(
            "SELECT * FROM policy_index_generation ORDER BY generation_id"
        ).fetchall()
        state["model_calls"] = connection.execute(
            "SELECT count(*) n FROM agent_model_call"
        ).fetchone()["n"]
        state["pending_runs"] = connection.execute(
            "SELECT count(*) n FROM agent_run WHERE status NOT IN ('COMPLETED','FAILED','STALE')"
        ).fetchone()["n"]
    assert state["pending_runs"] == 0, (
        "inspect historical pending runs before enabling the live worker"
    )
    save("before.json", state)


def exercise(settings, database):
    before = json.loads((LOCAL / "before.json").read_text(encoding="utf-8"))
    assert before["pending_runs"] == 0
    path = LOCAL / "sample.json"
    sample = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {
            "synthetic": True,
            "draft_key": str(uuid.uuid4()),
            "payment_key": str(uuid.uuid4()),
            "case_key": str(uuid.uuid4()),
            "checks": [],
        }
    )
    save("sample.json", sample)
    checks = sample["checks"]

    def check(method, route, token=None, body=None, status=200, headers=None):
        code, value = demo.http(
            method,
            settings.gateway_url + route,
            token=token,
            body=body,
            headers=headers,
        )
        checks.append(
            {"method": method, "path": route, "status": code, "expected": status}
        )
        save("sample.json", sample)
        assert code == status, f"{method} {route}: status {code}, expected {status}"
        return value

    buyer = demo.login(settings, "buyer01", "123456")
    other_buyer = demo.login(settings, "buyer02", "123456")
    merchant = demo.login(settings, "admin01", "123456")
    other_merchant = demo.login(settings, "admin02", "123456")
    platform = demo.login(settings, "platform", "123456")
    if "draft" not in sample:
        products = check("GET", "/api/v1/shop/products?limit=48")["items"]
        product = next(p for p in products if p["store_id"] == "M-1001")
        sku = product["skus"][0]
        sample["draft"] = check(
            "POST",
            "/api/v1/shop/drafts",
            buyer,
            {
                "sku_id": sku["sku_id"],
                "quantity": 1,
                "expected_sku_version": sku["version"],
            },
            headers={"Idempotency-Key": sample["draft_key"]},
        )
        sample["product"] = {
            "product_id": product["product_id"],
            "sku_id": sku["sku_id"],
        }
        save("sample.json", sample)
    if "payment" not in sample:
        sample["payment"] = check(
            "POST",
            "/api/v1/shop/drafts/" + sample["draft"]["draft_id"] + "/payment",
            buyer,
            {},
            headers={"Idempotency-Key": sample["payment_key"]},
        )
        assert sample["payment"]["status"] == "SUCCEEDED"
        save("sample.json", sample)
    payment = sample["payment"]
    if "case_id" not in sample:
        sample["case_id"] = check(
            "POST",
            "/api/v1/cases",
            buyer,
            {
                "line_id": payment["line_id"],
                "description": "尚未发货，想取消购买，请退还这一件商品的全部实付款。",
                "requested_actions": ["REFUND"],
            },
            status=201,
            headers={"Idempotency-Key": sample["case_key"]},
        )["case_id"]
        save("sample.json", sample)
    case = str(uuid.UUID(sample["case_id"]))
    run = demo.agent_run_id(case, 1)
    check("GET", "/api/v1/customer/cases/" + case, other_buyer, status=404)
    check("GET", "/api/v1/cases/" + case, other_merchant, status=404)

    # Poll persisted outcome rather than deciding tools, queries or actions for the model.
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        detail = demo.api(settings, "/api/v1/cases/" + case, token=merchant)
        state = detail["case"]["status"]
        if state not in ("QUEUED", "ANALYZING"):
            break
        time.sleep(2)
    else:
        raise TimeoutError("live investigation has not produced a reviewable outcome")
    sample["investigation_state"] = state
    save("sample.json", sample)
    auth = detail.get("authorization") or {}
    if state != "CLOSED_SUCCESS":
        assert auth.get("status") == "PENDING_REVIEW", (
            f"live outcome {state}; no usable refund authorization"
        )
        collab = check("GET", "/api/v1/cases/" + case + "/collaboration", merchant)
        assert collab["is_owner"]
        body = {
            "authorization_id": auth["authorization_id"],
            "authorization_version": auth["authorization_version"],
            "decision": "APPROVE",
            "reason": "合成部署验收：商家核对当前未发货、实付金额及所引用政策后批准模拟退款。",
        }
        headers = {
            "If-Match": f'"{detail["case"]["version"]}"',
            "If-Collaboration-Match": f'"{collab["version"]}"',
        }
        check("POST", "/api/v1/cases/" + case + "/reviews", buyer, body, 403, headers)
        check(
            "POST", "/api/v1/cases/" + case + "/reviews", platform, body, 403, headers
        )
        check(
            "POST",
            "/api/v1/cases/" + case + "/reviews",
            merchant,
            body,
            409,
            {**headers, "If-Collaboration-Match": '"0"'},
        )
        # Record the original review request before sending; retries never change its identity.
        sample["review"] = {"body": body, "headers": headers}
        save("sample.json", sample)
        check(
            "POST", "/api/v1/cases/" + case + "/reviews", merchant, body, 200, headers
        )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if demo.case_state(settings, case)["status"] == "CLOSED_SUCCESS":
            break
        time.sleep(1)
    else:
        raise TimeoutError("simulated refund has not settled")
    view = check("GET", "/api/v1/customer/cases/" + case, buyer)
    assert view["case"]["status"] == "CLOSED_SUCCESS" and view["allowed_actions"] == []
    original = sample["review"]
    check(
        "POST",
        "/api/v1/cases/" + case + "/reviews",
        merchant,
        original["body"],
        409,
        original["headers"],
    )
    ledger = demo.mysql_rows(
        f"SELECT paid_amount,refunded_amount,reserved_refund_amount FROM commerce_db.payment_ledger WHERE order_id='{uuid.UUID(payment['order_id'])}'",
        settings,
    )[0]
    assert list(map(int, ledger)) == [
        payment["total_amount"],
        payment["total_amount"],
        0,
    ]
    operations = demo.mysql_rows(
        "SELECT operation_id,state,amount_minor FROM commerce_db.refund_operation WHERE line_id="
        + demo._sql_text(payment["line_id"]),
        settings,
    )
    assert len(operations) == 1 and operations[0][1:] == [
        "SUCCEEDED",
        str(payment["total_amount"]),
    ]
    after = baseline_state(settings, database)
    preserved = {}
    for name in (
        "cases",
        "owners",
        "pins",
        "policies",
        "authorizations",
        "operations",
        "payments",
        "runs",
    ):
        old = before[name]
        ids = {str(r["run_id"]) if name == "runs" else r[0] for r in old}
        current = [
            r
            for r in after[name]
            if (str(r["run_id"]) if name == "runs" else r[0]) in ids
        ]
        assert old == current, f"historical {name} changed"
        preserved[name] = {
            "rows": len(old),
            "sha256": fingerprint(old),
            "unchanged": True,
        }
    with database.connection() as connection:
        models = connection.execute(
            "SELECT state,response FROM agent_model_call WHERE run_id=%s ORDER BY call_id",
            (run,),
        ).fetchall()
        tools = connection.execute(
            "SELECT observation FROM agent_tool_call WHERE run_id=%s AND observation IS NOT NULL ORDER BY call_id",
            (run,),
        ).fetchall()
        manifest = connection.execute(
            "SELECT manifest FROM agent_run_model_budget WHERE run_id=%s", (run,)
        ).fetchone()["manifest"]
        callbacks = connection.execute(
            "SELECT kind,status,disposition FROM agent_callback_outbox WHERE run_id=%s ORDER BY created_at",
            (run,),
        ).fetchall()
        generations = connection.execute(
            "SELECT bundle_id,generation_id,retrieval_layout,child_count FROM policy_index_generation WHERE status='READY' ORDER BY bundle_id"
        ).fetchall()
        all_generations = connection.execute(
            "SELECT * FROM policy_index_generation ORDER BY generation_id"
        ).fetchall()
        version = connection.execute(
            "SELECT version() v, current_setting('fsync') fsync, current_setting('synchronous_commit') synchronous_commit"
        ).fetchone()
        model_total = connection.execute(
            "SELECT count(*) n FROM agent_model_call"
        ).fetchone()["n"]
    assert manifest["model"]["provider"] == "deepseek"
    assert len(models) > 0 and all(
        m["state"] == "SAVED" and m["response"].get("mode") == "live" for m in models
    )
    assert model_total == before["model_calls"] + len(models), (
        "unexpected other model calls"
    )
    policy = [
        t["observation"]
        for t in tools
        if t["observation"]["tool_name"] == "search_policy"
    ]
    assert policy and any(o["result"]["hit_count"] > 0 for o in policy)
    assert all(c["status"] == "DELIVERED" for c in callbacks)
    assert all(
        g["retrieval_layout"] == "token-children-v1" and g["child_count"] > 0
        for g in generations
    )
    # Deployment may retire READY generations; original identities/lineage stay intact.
    by_id = {g["generation_id"]: g for g in all_generations}
    retired = []
    for old in before["index_generations"]:
        current = by_id[old["generation_id"]]
        for field, value in old.items():
            if field != "status":
                # Baseline JSON serialises PG timestamps and dates explicitly.
                assert json.loads(json.dumps(current[field], default=str)) == value
        if old["status"] != current["status"]:
            assert old["status"] == "READY" and current["status"] == "BUILDING"
            retired.append(old["generation_id"])
    proposal = demo.mysql_rows(
        f"SELECT origin,payload FROM case_db.case_proposal WHERE case_id='{case}'",
        settings,
    )
    assert len(proposal) == 1 and proposal[0][0] == "AGENT"
    payload = json.loads(proposal[0][1])
    assert payload["recommended_action"] == "REFUND" and payload["policy_refs"]
    assert len(generations) == 3
    assert manifest["index_generation"] == next(
        g["generation_id"]
        for g in generations
        if g["bundle_id"] == payload["policy_refs"][0]["bundle_id"]
    )
    usages = [m["response"].get("usage") for m in models]
    assert all(u and u.get("estimated") is False for u in usages)
    report = {
        "verified_at": demo.now_iso(),
        "synthetic": True,
        "model_mode": "live",
        "case_id": case,
        "run_id": run,
        "order_id": payment["order_id"],
        "line_id": payment["line_id"],
        "model": manifest["model"],
        "run_index_generation": manifest["index_generation"],
        "model_calls": len(models),
        "provider_usage": usages,
        "tool_names": [t["observation"]["tool_name"] for t in tools],
        "policy_queries": [
            m["response"]["decision"]["query"]
            for m in models
            if m["response"].get("decision", {}).get("kind") == "SEARCH_POLICY"
        ],
        "policy_refs": payload["policy_refs"],
        "recommended_action": payload["recommended_action"],
        "callbacks": callbacks,
        "generations": generations,
        "index_history": {
            "original_rows_retained": len(before["index_generations"]),
            "retired_generation_ids": retired,
            "current_rows": len(all_generations),
        },
        "postgres": version,
        "refund": {
            "status": "SUCCEEDED",
            "amount_minor": payment["total_amount"],
            "operation_count": 1,
            "reserved_minor": 0,
        },
        "buyer_outcome": "CLOSED_SUCCESS",
        "preserved": preserved,
        "http_checks": len(checks),
        "checks": checks,
    }
    save("verification.json", report)
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "case_id",
                    "model_calls",
                    "tool_names",
                    "refund",
                    "http_checks",
                )
            },
            ensure_ascii=False,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["snapshot", "exercise"])
    args = parser.parse_args()
    settings = demo.settings_from_environ()
    demo.guard(settings)
    assert (
        settings.project == demo.PROJECT
        and settings.ports == demo.DEFAULT_PORTS
        and settings.runtime_root.resolve() == demo.RUNTIME_ROOT.resolve()
    )
    database = Database(settings.agent_dsn)
    try:
        if args.command == "snapshot":
            snapshot(settings, database)
        else:
            exercise(settings, database)
    finally:
        database.close()


if __name__ == "__main__":
    main()
