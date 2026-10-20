"""Explicit eight-turn live diagnostic on retained synthetic orders, through Gateway.

Requests are frozen before writes. Reruns reuse keys/results and never retry failed
turns as new model work. No refund, purchase, logistics or policy mutation routes.
"""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import reviewer_demo as demo
from resolveflow.runtime.db import Database

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/customer-agent-live-v1"
PRIVATE = ROOT / "tmp/customer-agent-live-v1"
PLAN = ROOT / "evals/customer-agent-live-v1/cases.json"
TABLES = [
    "case_db.aftersale_case",
    "case_db.case_authorization",
    "case_db.active_case_slot",
    "commerce_db.orders",
    "commerce_db.order_line",
    "commerce_db.payment_ledger",
    "commerce_db.line_refund",
    "commerce_db.refund_operation",
    "commerce_db.order_fulfillment",
    "commerce_db.shipment",
    "commerce_db.shipment_event",
]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode())


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def snapshot(settings):
    result = {}
    for table in TABLES:
        rows = sorted(demo.mysql_rows("SELECT * FROM " + table, settings))  # noqa: S608 - fixed local table allowlist
        result[table] = {"count": len(rows), "sha256": digest(rows)}
    db = Database(settings.agent_dsn)
    try:
        with db.connection() as conn:
            rows = conn.execute("SELECT * FROM agent_run ORDER BY run_id").fetchall()
        result["agent_db.agent_run"] = {"count": len(rows), "sha256": digest(rows)}
        with db.connection() as conn:
            rows = conn.execute("SELECT * FROM policy_index_generation ORDER BY generation_id").fetchall()
        result["agent_db.policy_index_generation"] = {
            "count": len(rows),
            "sha256": digest(rows),
        }
    finally:
        db.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preflight", "exercise", "collect"])
    args = parser.parse_args()
    settings = demo.settings_from_environ()
    demo.guard(settings)
    assert settings.ports == demo.DEFAULT_PORTS and settings.project == demo.PROJECT
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    PRIVATE.mkdir(parents=True, exist_ok=True)
    state_path = PRIVATE / "state.json"
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {"plan_sha256": digest(plan), "steps": {}, "turns": {}}
    )
    assert state["plan_sha256"] == digest(plan), "Frozen live plan changed"

    if args.command == "preflight":
        assert not demo.mysql_rows(
            "SELECT run_id FROM case_db.support_agent_turn WHERE status IN ('PENDING','RUNNING')",
            settings,
        )
        db = Database(settings.agent_dsn)
        assert not demo.mysql_rows("SELECT run_id FROM case_db.agent_binding WHERE dispatch_status='PENDING'", settings)
        try:
            with db.connection() as conn:
                assert not conn.execute("SELECT run_id FROM agent_run WHERE status IN ('QUEUED','RUNNING')").fetchall()
        finally:
            db.close()
        before = PRIVATE / "before.json"
        assert not before.exists(), "Preflight already recorded; do not replace baseline"
        baseline = snapshot(settings)
        save(before, baseline)
        save(state_path, state)
        print(
            json.dumps(
                {
                    "preflight": "passed",
                    "baseline_tables": len(baseline),
                    "new_model_calls": 0,
                }
            )
        )
        return

    samples = {
        v["name"]: v
        for v in json.loads(
            (ROOT / "reports/customer-agent-design-v1/runtime-samples.json").read_text(encoding="utf-8")
        )["samples"]
    }
    checks = []

    def call(method, path, token=None, body=None, key=None, expected=200):
        status, data = demo.http(
            method,
            settings.frontend_url + path,
            token=token,
            body=body,
            headers={"Idempotency-Key": key} if key else None,
            timeout=35,
        )
        assert status == expected, (method, path, status, str(data)[:300])
        checks.append({"method": method, "path": path, "status": status})
        return data

    def login(user):
        return call(
            "POST",
            "/api/v1/auth/login",
            body={
                "username": user,
                "password": os.environ.get("RESOLVEFLOW_DEMO_PASSWORD", "123456"),
            },
        )["access_token"]

    buyer = login("buyer01")

    def step(name, path, token, body):
        if name not in state["steps"]:
            state["steps"][name] = {
                "path": path,
                "body": body,
                "key": "customer-live-v1-" + name,
            }
            save(state_path, state)
        frozen = state["steps"][name]
        assert frozen["path"] == path
        return call("POST", path, token, frozen["body"], frozen["key"])

    def human_followup(c, answer):
        p = "/api/v1/support/conversations/" + c["conversation_id"]
        h = plan["human_followup"]
        original = next(
            m
            for m in reversed(c["messages"])
            if m["author"] == "CUSTOMER" and m["text"] == next(v["text"] for v in plan["cases"] if v["id"] == h["case"])
        )
        c = step(
            "handoff",
            p + "/tickets",
            buyer,
            {
                "expected_version": c["version"],
                "summary": h["summary"],
                "shared_message_ids": [original["message_id"]],
                "assistant_message_id": answer["message_id"],
            },
        )
        tid = c["ticket"]["ticket_id"]
        tp = "/api/v1/support/tickets/" + tid
        merchant, other, stranger = login("admin01"), login("admin02"), login("buyer02")
        shared = call("GET", tp, merchant)
        assert shared["ticket"]["summary"] == h["summary"]
        assert shared["ticket"]["report"] == answer["assistant"]
        assert [m["message_id"] for m in shared["ticket"]["shared_messages"]] == [original["message_id"]]
        assert not any(m["author"] == "ASSISTANT" for m in shared["messages"])
        call("GET", tp, other, expected=404)
        call("GET", p, stranger, expected=404)
        shared = step(
            "merchant-request",
            tp + "/messages",
            merchant,
            {
                "expected_version": shared["version"],
                "text": h["merchant_question"],
                "kind": "REQUEST_INFO",
            },
        )
        c = call("GET", p, buyer)
        c = step(
            "customer-more",
            p + "/messages",
            buyer,
            {
                "expected_version": c["version"],
                "text": h["customer_answer"],
                "recipient": "MERCHANT",
            },
        )
        shared = call("GET", tp, merchant)
        shared = step(
            "merchant-reply",
            tp + "/messages",
            merchant,
            {
                "expected_version": shared["version"],
                "text": h["merchant_reply"],
                "kind": "REPLY",
            },
        )
        c = call("GET", p, buyer)
        assert any(m["text"] == h["merchant_reply"] and m["author"] == "MERCHANT" for m in c["messages"])
        c = step(
            "customer-resolve",
            p + "/resolve",
            buyer,
            {"expected_version": c["version"]},
        )
        assert c["ticket"]["status"] == "RESOLVED"
        state["human"] = {
            "conversation_id": c["conversation_id"],
            "ticket_id": tid,
            "status": "RESOLVED",
            "checks": [
                "confirmed report snapshot",
                "selected original only",
                "merchant/customer isolation 404",
                "request info and reply visible",
                "customer resolved",
            ],
            "merchant_view": call("GET", tp, merchant),
        }
        save(state_path, state)

    if args.command == "exercise":
        assert (PRIVATE / "before.json").exists(), "Run preflight first"
        for case in plan["cases"]:
            name = case["id"]
            if name in state["turns"]:
                continue
            sample = samples[case["sample"]]
            c = call(
                "POST",
                "/api/v1/support/conversations",
                buyer,
                {"line_id": sample["line_id"]},
            )
            p = "/api/v1/support/conversations/" + c["conversation_id"]
            start = time.time()
            receipt = step(
                name,
                p + "/messages",
                buyer,
                {
                    "expected_version": c["version"],
                    "text": case["text"],
                    "recipient": "ASSISTANT",
                },
            )
            target_run = receipt["assistant_turn"]["run_id"]
            deadline = time.time() + 210
            while True:
                c = call("GET", p, buyer)
                turn = c.get("assistant_turn") or {}
                if turn.get("run_id") == target_run and turn.get("status") in ["SUCCEEDED", "FAILED", "STALE"]:
                    break
                if time.time() > deadline:
                    raise TimeoutError(f"{name} remains pending; resume with saved key, do not send another turn")
                time.sleep(1)
            answer = next(
                (
                    m
                    for m in reversed(c["messages"])
                    if m["author"] == "ASSISTANT" and m.get("assistant", {}).get("run_id") == turn["run_id"]
                ),
                None,
            )
            if answer:
                assert answer["assistant"]["mode"] == "live"
                assert all(
                    s["data"].get("merchant_id", sample["merchant_id"]) == sample["merchant_id"]
                    for s in answer["assistant"]["citations"]
                    if s["source_type"] == "POLICY"
                )
            state["turns"][name] = {
                "id": name,
                "sample": case["sample"],
                "text": case["text"],
                "conversation_id": c["conversation_id"],
                "line_id": c["line_id"],
                "merchant_id": c["merchant_id"],
                "turn": turn,
                "answer": answer,
                "elapsed_seconds": round(time.time() - start, 3),
                "history_at_result": c["messages"],
            }
            save(state_path, state)
            print(
                json.dumps(
                    {
                        "case": name,
                        "status": turn.get("status"),
                        "reason": turn.get("reason"),
                        "seconds": state["turns"][name]["elapsed_seconds"],
                    }
                ),
                flush=True,
            )
        human_case = state["turns"].get(plan["human_followup"]["case"])
        if human_case and human_case["answer"] and "human" not in state:
            c = call("GET", "/api/v1/support/conversations/" + human_case["conversation_id"], buyer)
            human_followup(c, human_case["answer"])
        save(PRIVATE / "http-checks.json", checks)

    db = Database(settings.agent_dsn)
    try:
        runs = []
        with db.connection() as conn:
            for v in state["turns"].values():
                rid = v["turn"]["run_id"]
                row = conn.execute("SELECT * FROM support_agent_run WHERE run_id=%s", (rid,)).fetchone()
                calls = conn.execute(
                    "SELECT kind,position,status,request_json,response_json "
                    "FROM support_agent_call WHERE run_id=%s ORDER BY kind,position",
                    (rid,),
                ).fetchall()
                assert "tool_token" not in row["input_json"]
                runs.append({"case": v["id"], "run": row, "calls": calls})
    finally:
        db.close()
    before = json.loads((PRIVATE / "before.json").read_text(encoding="utf-8"))
    after = snapshot(settings)
    save(
        OUT / "runtime-results.json",
        {
            "plan_sha256": digest(plan),
            "synthetic_business_data": True,
            "model_mode": "live",
            "not_holdout": True,
            "turns": list(state["turns"].values()),
            "runs": runs,
            "human": state.get("human"),
            "preservation": {
                t: {
                    "before": before[t],
                    "after": after[t],
                    "unchanged": before[t] == after[t],
                }
                for t in before
            },
        },
    )
    assert before == after, "Baseline business rows changed; inspect report"
    print(
        json.dumps(
            {
                "collected_turns": len(runs),
                "preserved_tables": len(before),
                "report": "reports/customer-agent-live-v1/runtime-results.json",
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
