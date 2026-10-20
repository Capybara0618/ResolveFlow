"""Resumable, explicit mock-model consultation check on the retained local demo.

Requires the separately started support-only stack. Never starts a worker or changes
logistics/refunds; one existing synthetic order line is used, with frozen request keys.
"""

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import reviewer_demo as demo
from resolveflow.api.identity import mint_service_token
from resolveflow.runtime.db import Database


def main():
    settings = demo.settings_from_environ()
    demo.guard(settings)
    assert demo.owns_port(settings, "design-support-agent", settings.ports["agent"]), (
        "This check requires the explicitly started support-only mock verification process"
    )
    root = Path(__file__).resolve().parents[1]
    directory = root / "tmp/customer-agent-v1"
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / "acceptance-state.json"
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {}
    )
    checks = []

    def call(method, path, token=None, body=None, key=None, expected=200, base=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if key:
            headers["Idempotency-Key"] = key
        request = urllib.request.Request(
            (base or settings.case_url) + path,
            method=method,
            headers=headers,
            data=json.dumps(body, ensure_ascii=False).encode()
            if body is not None
            else None,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        assert status == expected, (method, path, status, raw[:180])
        checks.append({"method": method, "path": path, "status": status})
        return json.loads(raw)

    def login(user):
        return call(
            "POST", "/api/v1/auth/login", body={"username": user, "password": "123456"}
        )["access_token"]

    buyer, merchant, other_merchant, other_buyer = [
        login(u) for u in ["buyer01", "admin01", "admin02", "buyer02"]
    ]
    samples = json.loads(
        (root / "reports/customer-agent-design-v1/runtime-samples.json").read_text(
            encoding="utf-8"
        )
    )
    sample = next(s for s in samples["samples"] if s["name"] == "A-TRANSIT")
    c = call(
        "POST", "/api/v1/support/conversations", buyer, {"line_id": sample["line_id"]}
    )
    path = "/api/v1/support/conversations/" + c["conversation_id"]

    def step(name, endpoint, body):
        if name not in state:
            state[name] = {
                "path": endpoint,
                "body": body,
                "key": "customer-agent-v1-" + name,
            }
            state_path.write_bytes(
                (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode()
            )
        frozen = state[name]
        assert frozen["path"] == endpoint
        return call("POST", endpoint, buyer, frozen["body"], frozen["key"])

    receipt = step(
        "ask-rag-enabled-v2",
        path + "/messages",
        {
            "expected_version": c["version"],
            "text": "演示私人备注-客服Agent：请核查在途商品的物流和适用政策，暂不申请退款。",
            "recipient": "ASSISTANT",
        },
    )
    for _ in range(45):
        c = call("GET", path, buyer)
        turn = c.get("assistant_turn", {})
        if turn.get("status") in ["SUCCEEDED", "FAILED", "STALE"]:
            break
        time.sleep(1)
    assert turn.get("status") == "SUCCEEDED", turn
    answer = next(m for m in c["messages"] if m["author"] == "ASSISTANT")
    metadata = answer["assistant"]
    assert metadata["mode"] == "mock", "This driver must never use a real model"
    assert {c["source_type"] for c in metadata["citations"]} == {"SHIPMENT", "POLICY"}
    policy = next(c for c in metadata["citations"] if c["source_type"] == "POLICY")
    assert policy["data"]["merchant_id"] == sample["merchant_id"]
    assert "IN_TRANSIT" in json.dumps(
        next(c for c in metadata["citations"] if c["source_type"] == "SHIPMENT")
    )
    assert step("ask-rag-enabled-v2", path + "/messages", {}) == receipt
    call("GET", path, other_buyer, expected=404)

    database = Database(settings.agent_dsn)
    with database.connection() as conn:
        row = conn.execute(
            "SELECT * FROM support_agent_run WHERE run_id=%s", (metadata["run_id"],)
        ).fetchone()
        calls = conn.execute(
            "SELECT kind,status,count(*) AS count FROM support_agent_call WHERE run_id=%s GROUP BY kind,status ORDER BY kind",
            (metadata["run_id"],),
        ).fetchall()
        original_runs = conn.execute(
            "SELECT count(*) AS count FROM agent_run"
        ).fetchone()
    assert row["result_json"]["status"] == "SUCCEEDED"
    assert "tool_token" not in row["input_json"]
    assert row["generations_json"], "Actual dense search must pin its generation"
    assert calls == [
        {"kind": "model", "status": "COMPLETE", "count": 3},
        {"kind": "tool", "status": "COMPLETE", "count": 2},
    ], calls
    # The cached route must not require a usable tool credential or touch business facts.
    dispatch = mint_service_token(
        "case-service",
        demo.JWT_SECRET,
        scope="support:run",
        merchant_id=sample["merchant_id"],
        customer_id=row["input_json"]["customer_id"],
    )
    repeated = call(
        "POST",
        "/internal/v1/support-runs",
        dispatch,
        {**row["input_json"], "tool_token": "unused-on-completed-run"},
        base=settings.agent_url,
    )
    assert repeated == row["result_json"]
    with database.connection() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM support_agent_call WHERE run_id=%s",
                (metadata["run_id"],),
            ).fetchone()["n"]
            == 5
        )
    database.close()

    c = step(
        "handoff",
        path + "/tickets",
        {
            "expected_version": c["version"],
            "summary": "客户确认：核查在途商品运输进度，不申请退款。",
            "shared_message_ids": [],
            "assistant_message_id": answer["message_id"],
        },
    )
    ticket = c["ticket"]["ticket_id"]
    shared = call("GET", "/api/v1/support/tickets/" + ticket, merchant)
    assert shared["ticket"]["report"]["citations"] == metadata["citations"]
    assert shared["ticket"]["shared_messages"] == []
    assert "演示私人备注" not in json.dumps(shared, ensure_ascii=False)
    assert not any(m["author"] == "ASSISTANT" for m in shared["messages"])
    call("GET", "/api/v1/support/tickets/" + ticket, other_merchant, expected=404)
    baseline = json.loads(
        (root / "tmp/customer-agent-design-v1/assistant-before.json").read_text(
            encoding="utf-8"
        )
    )
    preservation = {}
    for full_name, expected in baseline.items():
        db, table = full_name.split(".")
        if table.startswith("support_"):
            old_support = json.loads(
                (root / "reports/customer-support-v1/runtime-check.json").read_text(
                    encoding="utf-8"
                )
            )
            # Compare the original columns/rows across the additive V28 migration.
            columns = [
                r[0]
                for r in demo.mysql_rows(
                    "SHOW COLUMNS FROM " + table, settings, database=db
                )
                if r[0] not in ["assistant_json", "report_json"]
            ]
            ids = [old_support["conversation_a"], old_support["conversation_b"]]
            assert all(
                len(value) == 36 and all(ch in "0123456789abcdef-" for ch in value)
                for value in ids
            )
            query = (
                "SELECT "
                + ",".join("`" + name + "`" for name in columns)
                + " FROM "
                + table
                + " WHERE conversation_id IN ('"
                + "','".join(ids)
                + "')"
            )
        else:
            query = "SELECT * FROM " + table
        rows = sorted(demo.mysql_rows(query, settings, database=db))
        actual = {
            "count": len(rows),
            "sha256": hashlib.sha256(
                json.dumps(rows, ensure_ascii=False).encode()
            ).hexdigest(),
        }
        assert actual == expected, full_name
        preservation[full_name] = actual
    old_pg = json.loads(
        (root / "tmp/customer-agent-design-v1/assistant-pg-before.json").read_text(
            encoding="utf-8"
        )
    )
    assert original_runs == old_pg
    result = {
        "synthetic": True,
        "model_mode": "mock",
        "live_model_calls": 0,
        "retrieval": "existing local BGE dense / retained READY generation",
        "conversation_id": c["conversation_id"],
        "ticket_id": ticket,
        "run_id": metadata["run_id"],
        "line_id": sample["line_id"],
        "input_version": row["input_json"]["input_version"],
        "spend": row["result_json"]["spend"],
        "calls": calls,
        "generation_ids": row["generations_json"],
        "citations": [
            {
                k: cite[k]
                for k in ["source_id", "source_type", "version", "content_hash"]
            }
            for cite in metadata["citations"]
        ],
        "checks": checks,
        "preserved_business_tables": preservation,
        "old_agent_run_count": original_runs["count"],
        "cached_repeat_extra_calls": 0,
    }
    target = root / "reports/customer-agent-v1/runtime-check.json"
    target.write_bytes(
        (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    )
    print(
        json.dumps(
            {
                "http_checks": len(checks),
                "conversation_id": c["conversation_id"],
                "run_id": metadata["run_id"],
                "mode": "mock",
                "dense": "real local",
                "business_tables_preserved": len(preservation),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
