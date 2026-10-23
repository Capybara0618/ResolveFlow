"""One actual browser refund conversation, retained data, explicit provider usage accounting."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "agent/src")]

import logistics_simulator as simulator
import reviewer_demo as demo
from product_flow_acceptance import baseline_state
from resolveflow.runtime.db import Database

from scripts.agent_eval import allowance, persist
from scripts.evaluation.models import live_guard

OUT = ROOT / "reports/chat-refund-live-v1"
PRIVATE = ROOT / "tmp/chat-refund-live-v1"
LEDGER = ROOT / "tmp/evaluation-live-budget.json"
TURNS = [
    "这件商品一直没收到，请帮我查一下最新物流状态，先不要申请退款。",
    "我确实没有收到这件商品，想申请整件退款。请把申请原因整理成可编辑的摘要，由我核对后再确认提交。",
]


def normalize(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(normalize(value), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def connect():
    settings = demo.settings_from_environ()
    demo.guard(settings)
    assert settings.ports == demo.DEFAULT_PORTS
    return settings, Database(settings.agent_dsn)


def prepare():
    assert not (OUT / "plan.json").exists(), "frozen plan exists"
    settings, db = connect()
    try:
        assert not demo.mysql_rows(
            "SELECT run_id FROM case_db.support_agent_turn WHERE status IN ('PENDING','RUNNING')",
            settings,
        )
        assert not demo.mysql_rows(
            "SELECT run_id FROM case_db.agent_binding WHERE dispatch_status='PENDING'",
            settings,
        )
        with db.connection() as c:
            assert not c.execute(
                "SELECT run_id FROM agent_run WHERE status IN ('QUEUED','RUNNING')"
            ).fetchall()
            assert not c.execute(
                "SELECT run_id FROM support_agent_run WHERE status='RUNNING'"
            ).fetchall()
            old_support = c.execute(
                "SELECT * FROM support_agent_run ORDER BY run_id"
            ).fetchall()
            indexes = c.execute(
                "SELECT * FROM policy_index_generation ORDER BY generation_id"
            ).fetchall()
        if not (PRIVATE / "before.json").exists():
            persist(
                PRIVATE / "before.json",
                {
                    "business": baseline_state(settings, db),
                    "support_runs": old_support,
                    "indexes": indexes,
                },
            )
        state = (
            json.loads((PRIVATE / "sample.json").read_text(encoding="utf-8"))
            if (PRIVATE / "sample.json").exists()
            else {
                "keys": {
                    k: str(uuid.uuid4()) for k in ["draft", "pay", "ship", "scenario"]
                }
            }
        )
        persist(PRIVATE / "sample.json", state)

        def api(method, path, token=None, body=None, key=None):
            code, result = demo.http(
                method,
                settings.gateway_url + path,
                token=token,
                body=body,
                headers={"Idempotency-Key": key} if key else None,
            )
            assert code in {200, 201}, (path, code, str(result)[:300])
            return result

        buyer = demo.login(
            settings, "buyer10", os.environ.get("RESOLVEFLOW_DEMO_PASSWORD", "123456")
        )
        merchant = demo.login(
            settings, "admin01", os.environ.get("RESOLVEFLOW_DEMO_PASSWORD", "123456")
        )
        if "draft" not in state:
            products = api("GET", "/api/v1/shop/products?store_id=M-1001&limit=48")[
                "items"
            ]
            product = next(p for p in products if p["asset_key"] == "headphones")
            sku = api("GET", "/api/v1/shop/products/" + product["product_id"])["skus"][
                0
            ]
            state["draft"] = api(
                "POST",
                "/api/v1/shop/drafts",
                buyer,
                {
                    "sku_id": sku["sku_id"],
                    "quantity": 1,
                    "expected_sku_version": sku["version"],
                },
                state["keys"]["draft"],
            )
            persist(PRIVATE / "sample.json", state)
        if "payment" not in state:
            state["payment"] = api(
                "POST",
                "/api/v1/shop/drafts/" + state["draft"]["draft_id"] + "/payment",
                buyer,
                {},
                state["keys"]["pay"],
            )
            persist(PRIVATE / "sample.json", state)
        payment = state["payment"]
        assert payment["status"] == "SUCCEEDED"
        if "shipment" not in state:
            state["shipment"] = api(
                "POST",
                "/api/v1/merchant/orders/"
                + payment["order_id"]
                + "/simulated-shipment",
                merchant,
                {"expected_version": 1},
                state["keys"]["ship"],
            )
            persist(PRIVATE / "sample.json", state)
        mysql = simulator.LocalMysql()
        mysql.execute(
            simulator.call_sql(
                payment["order_id"],
                "M-1001",
                2,
                "LOST",
                state["keys"]["scenario"],
                None,
            )
        )
        state["logistics"] = simulator.inspect(mysql, payment["order_id"], "M-1001")
        conversation = api(
            "POST",
            "/api/v1/support/conversations",
            buyer,
            {"line_id": payment["line_id"]},
        )
        persist(PRIVATE / "sample.json", state)
        files = [
            "scripts/accept_chat_refund_live_v1.py",
            "scripts/check_chat_refund_live_v1.cjs",
        ]
        persist(
            OUT / "plan.json",
            {
                "synthetic_business": True,
                "provider": "deepseek-flash",
                "resume_metrics": False,
                "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True
                ).strip(),
                "turns": TURNS,
                "turn_limit": 2,
                "automatic_retry": False,
                "customer": "buyer10",
                "merchant": "admin01",
                "line_id": payment["line_id"],
                "order_id": payment["order_id"],
                "amount_minor": payment["total_amount"],
                "conversation_id": conversation["conversation_id"],
                "model_bound": "two support runs plus one original Case run; existing per-run budgets unchanged",
                "files": {
                    p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                    for p in files
                },
            },
        )
        print(
            "Prepared one new synthetic LOST order and two live turns; model requests: 0"
        )
    finally:
        db.close()


def execute():
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    for path, expected in plan["files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
    with (PRIVATE / "execution-started.json").open("x", encoding="utf-8") as f:
        json.dump({"started": True}, f)
    settings, db = connect()
    before = json.loads((PRIVATE / "before.json").read_text(encoding="utf-8"))
    report = {
        "scope": "real browser + Java/Python/DeepSeek, synthetic transaction",
        "success": False,
    }
    try:
        with live_guard(LEDGER):
            usage = allowance(LEDGER)
            report["ledger_before"] = usage["used"]
            try:
                runtime = (
                    Path.home()
                    / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
                )
                result = subprocess.run(
                    [
                        str(runtime / "bin/node.exe"),
                        "scripts/check_chat_refund_live_v1.cjs",
                    ],
                    cwd=ROOT,
                    env={**os.environ, "NODE_PATH": str(runtime / "node_modules")},
                    timeout=420,
                    check=False,
                )
                report["browser_exit_code"] = result.returncode
            finally:
                old_support = {str(r["run_id"]) for r in before["support_runs"]}
                old_general = {str(r["run_id"]) for r in before["business"]["runs"]}
                # A browser failure must not hide model requests still completing server-side.
                deadline = time.monotonic() + 190
                while True:
                    with db.connection() as c:
                        pending = [
                            r
                            for r in c.execute(
                                "SELECT run_id FROM support_agent_run WHERE status='RUNNING'"
                            ).fetchall()
                            if str(r["run_id"]) not in old_support
                        ] + [
                            r
                            for r in c.execute(
                                "SELECT run_id FROM agent_run WHERE status IN ('QUEUED','RUNNING')"
                            ).fetchall()
                            if str(r["run_id"]) not in old_general
                        ]
                    if not pending or time.monotonic() >= deadline:
                        report["pending_at_accounting"] = normalize(pending)
                        break
                    time.sleep(1)
                with db.connection() as c:
                    support = [
                        r
                        for r in c.execute(
                            "SELECT * FROM support_agent_run ORDER BY created_at"
                        ).fetchall()
                        if str(r["run_id"]) not in old_support
                    ]
                    general = [
                        r
                        for r in c.execute(
                            "SELECT * FROM agent_run ORDER BY created_at"
                        ).fetchall()
                        if str(r["run_id"]) not in old_general
                    ]
                    for r in support:
                        r["calls"] = c.execute(
                            "SELECT * FROM support_agent_call WHERE run_id=%s ORDER BY created_at,kind,position",
                            (r["run_id"],),
                        ).fetchall()
                    for r in general:
                        r["attempts"] = c.execute(
                            "SELECT * FROM agent_model_attempt WHERE run_id=%s ORDER BY created_at",
                            (r["run_id"],),
                        ).fetchall()
                    current_support = c.execute(
                        "SELECT * FROM support_agent_run ORDER BY run_id"
                    ).fetchall()
                    current_indexes = c.execute(
                        "SELECT * FROM policy_index_generation ORDER BY generation_id"
                    ).fetchall()
                sm = [
                    call
                    for r in support
                    for call in r["calls"]
                    if call["kind"] == "model"
                ]
                gm = [a for r in general for a in r["attempts"]]
                usages = [(m.get("response_json") or {}).get("usage") for m in sm] + [
                    (m.get("response") or {}).get("usage") for m in gm
                ]
                known = [u for u in usages if u]
                count = len(sm) + len(gm)
                usage["used"] += count
                usage["save"]()
                current = normalize(baseline_state(settings, db))
                preserved = {}
                for name, old in before["business"].items():
                    ids = {str(r["run_id"]) if name == "runs" else r[0] for r in old}
                    actual = [
                        r
                        for r in current[name]
                        if (str(r["run_id"]) if name == "runs" else r[0]) in ids
                    ]
                    preserved[name] = {
                        "unchanged": actual == old,
                        "count": len(old),
                        "sha256_before": fingerprint(old),
                        "sha256_after": fingerprint(actual),
                    }
                old_current = [
                    r for r in current_support if str(r["run_id"]) in old_support
                ]
                # Calls are attached only to new rows above; old rows remain byte-equivalent after normalization.
                preserved["support_runs"] = {
                    "unchanged": normalize(old_current) == before["support_runs"]
                }
                preserved["policy_indexes"] = {
                    "unchanged": normalize(current_indexes) == before["indexes"]
                }
                report.update(
                    support_runs=support,
                    general_runs=general,
                    model_attempts=count,
                    provider_known_usage_count=len(known),
                    unknown_usage=count - len(known),
                    input_tokens=sum(u["input_tokens"] for u in known),
                    output_tokens=sum(u["output_tokens"] for u in known),
                    estimated=any(u.get("estimated", True) for u in known),
                    ledger_after=usage["used"],
                    preservation=preserved,
                )
                order = demo._sql_text(plan["order_id"])
                line = demo._sql_text(plan["line_id"])
                report["payment_ledger"] = demo.mysql_rows(
                    "SELECT paid_amount,refunded_amount,reserved_refund_amount FROM commerce_db.payment_ledger WHERE order_id="
                    + order,
                    settings,
                )
                report["refund_operations"] = demo.mysql_rows(
                    "SELECT operation_id,state,amount_minor FROM commerce_db.refund_operation WHERE line_id="
                    + line,
                    settings,
                )
                report["success"] = (
                    report.get("browser_exit_code") == 0
                    and len(support) == 2
                    and len(general) == 1
                    and all(r["status"] == "SUCCEEDED" for r in support)
                    and all(p["unchanged"] for p in preserved.values())
                    and report["payment_ledger"]
                    == [[str(plan["amount_minor"]), str(plan["amount_minor"]), "0"]]
                    and len(report["refund_operations"]) == 1
                    and report["refund_operations"][0][1] == "SUCCEEDED"
                    and not report["unknown_usage"]
                    and not report["pending_at_accounting"]
                )
                persist(OUT / "runtime-results.json", report)
    finally:
        db.close()
    print(
        json.dumps(
            {
                k: report[k]
                for k in ["success", "model_attempts", "ledger_before", "ledger_after"]
            }
        )
    )
    if not report["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["prepare", "execute"])
    prepare() if p.parse_args().command == "prepare" else execute()
