"""Dedicated v2 browser fixtures and single-run mock support, never a queue drainer.

Cases, answers, ownership and decisions are created through the product. This helper only
seeds new synthetic Commerce orders, reads evidence, and investigates a manifest-owned run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "agent" / "src"))

import reviewer_demo as demo
from customer_workspace_acceptance import protected_runs
from resolveflow.harness.budget import RunSpend
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.runner import RunResult
from resolveflow.policies.index import PolicyIndex
from resolveflow.policies.retrieval import embedder
from resolveflow.runtime.db import Database
from resolveflow.runtime.factory import DeploymentConfig, build_investigation
from resolveflow.runtime.leases import RunLease
from resolveflow.runtime.worker import RunWorker

MANIFEST = ROOT / "reports" / "product-flow" / "acceptance.json"
BASELINE = ROOT / "tmp" / "product-flow-baseline.json"
SPECS = {
    "supplement-approve": ("demo-customer", "demo-pass-1001", "M-1001", "CLOSED_SUCCESS"),
    "takeover-reject": ("demo-customer-2", "demo-pass-1002", "M-1001", "CLOSED_REJECTED"),
    "merchant-two-approve": ("demo-customer-m2", "demo-pass-2001", "M-1002", "CLOSED_SUCCESS"),
    "cancel": ("demo-customer", "demo-pass-1001", "M-1001", "CANCELLED"),
    "failed-manual-approve": ("demo-customer-2", "demo-pass-1002", "M-1001", "CLOSED_SUCCESS"),
}


def save(document: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    demo.atomic_write(MANIFEST, json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def fingerprint(rows: list) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def baseline_state(settings: demo.Settings, database: Database) -> dict:
    tables = {
        "cases": "SELECT case_id,status,version,input_revision,updated_at FROM aftersale_case",
        "owners": "SELECT case_id,owner_username,version FROM case_collaboration",
        "pins": "SELECT case_id,manifest_hash,safety_epoch FROM case_policy_manifest",
        "policies": "SELECT bundle_id,merchant_id,manifest_hash FROM policy_bundle",
        "authorizations": "SELECT authorization_id,status,authorization_version FROM case_authorization",
        "operations": "SELECT operation_id,state FROM commerce_db.refund_operation",
        "payments": "SELECT order_id,paid_amount,refunded_amount,reserved_refund_amount,version "
        "FROM commerce_db.payment_ledger",
    }
    state = {name: sorted(demo.mysql_rows(sql, settings, database="case_db"))
             for name, sql in tables.items()}
    state["runs"] = protected_runs(database)
    return state


def select_target(document: dict, case_id: str) -> dict:
    target_id = str(uuid.UUID(case_id))
    matches = [item for item in document["orders"] if item.get("case_id") == target_id]
    if len(matches) != 1:
        raise demo.DemoRefused("only one manifest-owned browser case may be investigated")
    return matches[0]


def queued_run(database: Database, item: dict, revision: int) -> str:
    run_id = demo.agent_run_id(item["case_id"], revision)
    with database.connection() as connection:
        row = connection.execute(
            "SELECT status FROM agent_run WHERE run_id=%s AND case_id=%s AND input_revision=%s",
            (run_id, item["case_id"], revision),
        ).fetchone()
    if row is None or row["status"] != "QUEUED":
        raise demo.DemoRefused("only the already-dispatched QUEUED revision is eligible; no reset")
    return run_id


def inspect(settings: demo.Settings, document: dict) -> dict[str, dict]:
    details = {}
    for item in document["orders"]:
        username, password, _, _ = SPECS[item["purpose"]]
        token = demo.login(settings, username, password)
        page = demo.api(settings, f"/api/v1/customer/cases?line_id={item['line_id']}&limit=100",
                        token=token)
        if len(page["items"]) > 1:
            raise demo.DemoRefused("more than one case on dedicated line; inspect manually")
        if page["items"]:
            found = page["items"][0]["case_id"]
            if item.get("case_id") not in (None, found):
                raise demo.DemoRefused("case identity changed; never rebind a used fixture")
            item["case_id"] = found
            details[found] = demo.api(settings, f"/api/v1/customer/cases/{found}", token=token)
    return details


def investigate(settings: demo.Settings, database: Database, item: dict, detail: dict) -> dict:
    if detail["case"]["status"] != "QUEUED":
        raise demo.DemoRefused("case must still be queued; cancelled/ended cases are never investigated")
    revision = detail["input_revision"]
    run_id = queued_run(database, item, revision)
    username, password, merchant, _ = SPECS[item["purpose"]]
    scenario = replace(demo.SCENARIOS["lost-review"], merchant_id=merchant,
                       customer_username=username, customer_password=password)
    bundle, digest = demo.pinned_bundle(settings, item["case_id"])
    citations = demo.preflight(settings, case_id=item["case_id"], run_id=run_id,
                              input_revision=revision, line_id=item["line_id"],
                              tool_calls=demo._tool_calls_for(scenario))
    policies = demo._policies_for(settings, scenario, bundle_id=bundle, manifest_hash=digest)
    script = demo.build_script(scenario, citations=citations, policies=policies)
    encoder = embedder(str(demo.EMBEDDING_PATH))
    index = PolicyIndex(database)
    hits = index.search(merchant_id=merchant, bundle_ids=[bundle], manifest_hash=digest,
                        query="物流丢失 全额退款", path="dense", top_k=5, embedder=encoder)
    rule = next(hit for hit in hits if hit.rule_id == "R-LOST-001")
    narrow = index.search(merchant_id=merchant, bundle_ids=[bundle], manifest_hash=digest,
                          query=rule.text, path="dense", top_k=1, embedder=encoder)
    if not narrow or narrow[0].rule_id != rule.rule_id:
        raise demo.DemoRefused("explicit mock must retrieve its actual pinned rule")
    next(step for step in script if step["kind"] == "SEARCH_POLICY").update(
        query=rule.text, arguments={"top_k": 1})
    if item["purpose"] == "failed-manual-approve":
        # Explicit lab failure: the mock reads the genuine shipment, then exhausts.
        # No fabricated callback, SQL case mutation or live provider fault is involved.
        script = script[:1]
    config = DeploymentConfig(mode="mock", context_window_tokens=32768,
                              case_base_url=settings.case_url, commerce_base_url=settings.commerce_url,
                              policy_index=True, embedding_path=str(demo.EMBEDDING_PATH))
    action = build_investigation(database=database, config=config,
                                 model=MockModelClient(script=script),
                                 service_identity_source=lambda: demo.mint_service_token("agent-service"))
    with RunLease(database, owner="product-browser-acceptance").acquire(run_id=run_id) as claimed:
        if claimed is None or claimed.legacy:
            raise demo.DemoRefused("target cannot be claimed; no fallback to another run")
        outcome = RunWorker(database, investigate=action, recoverable=True).finish(
            claimed, action(claimed.facts))
    return {"case_id": item["case_id"], "run_id": run_id, "input_revision": revision,
            "callback_kind": outcome.callback_kind, "status": outcome.status,
            "reason_code": outcome.result.reason_code, "model_mode": "mock"}


def verify(settings: demo.Settings, database: Database, document: dict, details: dict) -> None:
    before = json.loads(BASELINE.read_text(encoding="utf-8"))
    after = baseline_state(settings, database)
    preserved = {}
    for name, rows in before.items():
        if name == "runs":
            current = protected_runs(database, [row["run_id"] for row in rows])
        else:
            ids = {row[0] for row in rows}
            current = [row for row in after[name] if row[0] in ids]
        assert rows == current, f"Historical {name} changed; do not reset to obtain a pass"
        preserved[name] = {"rows": len(rows), "sha256": fingerprint(rows), "unchanged": True}
    for item in document["orders"]:
        detail = details[item["case_id"]]
        expected = SPECS[item["purpose"]][3]
        assert detail["case"]["status"] == expected and detail["allowed_actions"] == []
        item["outcome"] = expected
        item["input_revision"] = detail["input_revision"]
        item["public_result"] = detail["result"]
        ledger = demo.mysql_rows(
            "SELECT paid_amount,refunded_amount,reserved_refund_amount FROM commerce_db.payment_ledger "
            f"WHERE order_id='{uuid.UUID(detail['case']['order_id'])!s}'", settings)
        assert len(ledger) == 1
        paid, refunded, reserved = map(int, ledger[0])
        assert paid == item["amount_minor"] and refunded + reserved <= paid and reserved == 0
        assert refunded == (paid if expected == "CLOSED_SUCCESS" else 0)
        item["payment"] = {"paid_minor": paid, "refunded_minor": refunded, "reserved_minor": reserved}
        if item["purpose"] == "supplement-approve":
            assert len(detail["questions"]) == 1
            assert detail["questions"][0]["status"] == "ANSWERED"
            assert detail["questions"][0]["answers"] and detail["input_revision"] == 4
        if expected == "CLOSED_SUCCESS":
            rows = demo.mysql_rows(
                "SELECT state,amount_minor,operation_id FROM commerce_db.refund_operation "
                f"WHERE line_id='{item['line_id']}'", settings)
            assert len(rows) == 1 and rows[0][0] == "SUCCEEDED", rows
            assert int(rows[0][1]) == item["amount_minor"]
            item["refund"] = {"state": rows[0][0], "amount_minor": int(rows[0][1]),
                              "operation_id": rows[0][2], "operation_count": 1}
    document["preserved"] = preserved
    document["outcomes_verified"] = True
    document["paid_model_calls"] = 0
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT run_id,case_id,input_revision,status,budget_spent FROM agent_run "
            "WHERE case_id=ANY(%s::uuid[]) ORDER BY case_id,input_revision",
            ([item["case_id"] for item in document["orders"]],),
        ).fetchall()
    document["run_audit"] = [{**row, "run_id": str(row["run_id"]), "case_id": str(row["case_id"])}
                             for row in rows]


def boundaries(settings: demo.Settings, document: dict) -> None:
    accounts = {username: demo.login(settings, username, password)
                for username, password in [("demo-customer", "demo-pass-1001"),
                                            ("demo-customer-2", "demo-pass-1002"),
                                            ("demo-customer-m2", "demo-pass-2001"),
                                            ("demo-reviewer", "demo-pass-1003"),
                                            ("demo-reviewer-m2", "demo-pass-2002")]}
    checks = []

    def check(account: str, path: str, expected: int, body: dict | None = None) -> None:
        code, _ = demo.http("POST" if body is not None else "GET",
                            settings.gateway_url + path, token=accounts[account], body=body)
        checks.append({"account": account, "path": path, "status": code,
                       "method": "POST" if body is not None else "GET"})
        assert code == expected, f"{account}: {path} returned {code}, expected {expected}"

    for item in document["orders"]:
        case_id = item["case_id"]
        for username in ["demo-customer", "demo-customer-2", "demo-customer-m2"]:
            if username != item["account"]:
                check(username, f"/api/v1/customer/cases/{case_id}", 404)
                check(username, f"/api/v1/customer/order-lines/{item['line_id']}", 404)
        other_staff = "demo-reviewer-m2" if item["merchant_id"] == "M-1001" else "demo-reviewer"
        for suffix in ["", "/collaboration", "/review-context", "/investigation"]:
            check(other_staff, f"/api/v1/cases/{case_id}{suffix}", 404)
        if SPECS[item["purpose"]][3] == "CLOSED_SUCCESS":
            check(item["account"], f"/api/v1/cases/{case_id}/evidence", 409,
                  {"text": "不得写入的消费后材料", "evidence_kind": "CUSTOMER_STATEMENT"})
            check(item["account"], f"/api/v1/cases/{case_id}/cancel", 409,
                  {"reason": "消费后撤销必须拒绝"})
    # Existing UNKNOWN remains consumed, same operation/reservation; no simulated re-payment.
    unknown = "ce263102-965d-4dee-974f-351c9800b5cb"
    for suffix, body in [("/evidence", {"text": "不得写入的UNKNOWN材料",
                                        "evidence_kind": "CUSTOMER_STATEMENT"}),
                         ("/cancel", {"reason": "UNKNOWN不能取消"})]:
        check("demo-customer", f"/api/v1/cases/{unknown}{suffix}", 409, body)
    disabled = demo.http("POST", settings.gateway_url + "/api/v1/auth/login",
                         body={"username": "synthetic-people-1002180836", "password": "invalid"})[0]
    assert disabled == 401
    document["boundary_checks"] = checks
    document["disabled_login_status"] = disabled
    print(f"Boundary requests verified: {len(checks)}; disabled login: {disabled}")


def recover_failure(database: Database, item: dict, detail: dict) -> dict:
    if item["purpose"] != "failed-manual-approve" or detail["case"]["status"] != "ANALYZING":
        raise demo.DemoRefused("only the crashed dedicated failure fixture may be recovered")
    revision = detail["input_revision"]
    run_id = demo.agent_run_id(item["case_id"], revision)
    with database.connection() as connection:
        row = connection.execute(
            "SELECT status,active_deadline_at,budget_spent FROM agent_run "
            "WHERE run_id=%s AND case_id=%s AND input_revision=%s",
            (run_id, item["case_id"], revision),
        ).fetchone()
    if (row is None or row["status"] != "RUNNING"
            or not isinstance(row["active_deadline_at"], datetime)
            or row["active_deadline_at"] > datetime.now(UTC)):
        raise demo.DemoRefused("wait for the real active deadline; never extend or reset a run")
    # The same deadline branch used by RunWorker._recoverable_once, scoped to this exact run.
    with RunLease(database, owner="product-failure-recovery").acquire(run_id=run_id) as claimed:
        if claimed is None or claimed.legacy:
            raise demo.DemoRefused("failure fixture lease is still held; no other run is taken")
        result = RunResult(False, "BUDGET_DEADLINE", None, (), RunSpend(**row["budget_spent"]))
        outcome = RunWorker(database, investigate=lambda _: result, recoverable=True).finish(claimed, result)
    return {"case_id": item["case_id"], "run_id": run_id, "input_revision": revision,
            "callback_kind": outcome.callback_kind, "status": outcome.status,
            "reason_code": outcome.result.reason_code, "model_mode": "mock",
            "injection": "mock script exhausted; same run expired and recovered without model calls"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["seed", "seed-failure", "inspect", "investigate", "recover-failure",
                                            "boundaries", "verify"])
    parser.add_argument("--case-id")
    args = parser.parse_args()
    settings = demo.settings_from_environ()
    demo.guard(settings)
    database = Database(settings.agent_dsn)
    try:
        if args.command == "seed":
            if MANIFEST.exists():
                print("Existing manifest retained; no reseeding")
                return 0
            BASELINE.parent.mkdir(parents=True, exist_ok=True)
            demo.atomic_write(BASELINE, json.dumps(baseline_state(settings, database)))
            document = {"environment": settings.environment, "synthetic": True, "model_mode": "mock",
                        "orders": [], "investigations": []}
            save(document)
            for i, (purpose, (username, password, merchant, _)) in enumerate(SPECS.items()):
                if purpose == "failed-manual-approve":
                    continue
                scenario = replace(demo.SCENARIOS["lost-review"], merchant_id=merchant,
                                   customer_username=username, customer_password=password,
                                   product_name=f"第五批合成 · {purpose}")
                line = demo.seed_line(settings, scenario, 90 + i)
                document["orders"].append({"purpose": purpose, "account": username,
                                           "merchant_id": merchant, "line_id": line, "case_id": None,
                                           "amount_minor": scenario.amount_minor})
                save(document)
        else:
            document = json.loads(MANIFEST.read_text(encoding="utf-8"))
            if document["environment"] != settings.environment:
                raise demo.DemoRefused("manifest belongs to another environment")
            details = inspect(settings, document)
            save(document)
            if args.command == "seed-failure":
                purpose = "failed-manual-approve"
                if any(item["purpose"] == purpose for item in document["orders"]):
                    raise demo.DemoRefused("failure fixture already allocated; no reseeding")
                scenario = replace(demo.SCENARIOS["lost-review"],
                                   customer_username="demo-customer-2", customer_password="demo-pass-1002",
                                   product_name="第五批合成 · failed-manual-approve")
                line = demo.seed_line(settings, scenario, 94)
                document["orders"].append({"purpose": purpose, "account": scenario.customer_username,
                                           "merchant_id": scenario.merchant_id, "line_id": line,
                                           "case_id": None, "amount_minor": scenario.amount_minor})
                save(document)
            if args.command == "investigate":
                item = select_target(document, args.case_id or "")
                result = investigate(settings, database, item, details[item["case_id"]])
                document["investigations"].append(result)
                save(document)
                print(json.dumps(result))
                expected = "FAILED" if item["purpose"] == "failed-manual-approve" else "PROPOSAL"
                return 0 if result["callback_kind"] == expected else 1
            if args.command == "recover-failure":
                item = select_target(document, args.case_id or "")
                result = recover_failure(database, item, details[item["case_id"]])
                document["investigations"].append(result)
                save(document)
                print(json.dumps(result))
                return 0 if result["callback_kind"] == "FAILED" else 1
            if args.command == "verify":
                verify(settings, database, document, details)
                save(document)
            if args.command == "boundaries":
                boundaries(settings, document)
                save(document)
        print(json.dumps(document["orders"], ensure_ascii=False))
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
