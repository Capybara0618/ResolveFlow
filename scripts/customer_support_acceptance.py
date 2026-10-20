"""Persistent synthetic support acceptance, no Agent or refund calls; reuses design sample lines."""

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import reviewer_demo as demo


def main():
    settings = demo.settings_from_environ()
    demo.guard(settings)
    root = Path(__file__).resolve().parents[1]
    directory = root / "tmp/customer-support-v1"
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / "acceptance-state.json"
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {}
    )
    results = []

    def call(method, path, token=None, body=None, key=None, expected=200):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = token
        if key:
            headers["Idempotency-Key"] = key
        req = urllib.request.Request(
            settings.case_url + path,
            method=method,
            headers=headers,
            data=json.dumps(body, ensure_ascii=False).encode()
            if body is not None
            else None,
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                status, data = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, data = error.code, error.read()
        if status != expected:
            raise RuntimeError(f"{method} {path}: expected {expected}, got {status}")
        results.append({"method": method, "path": path, "status": status})
        return json.loads(data)

    password = os.environ.get("RESOLVEFLOW_DEMO_PASSWORD", "123456")

    def login(user):
        return (
            "Bearer "
            + call(
                "POST",
                "/api/v1/auth/login",
                body={"username": user, "password": password},
            )["access_token"]
        )

    buyer, merchant, other_merchant, other_buyer = [
        login(user) for user in ["buyer01", "admin01", "admin02", "buyer02"]
    ]
    samples = {
        s["name"]: s
        for s in json.loads(
            (root / "reports/customer-agent-design-v1/runtime-samples.json").read_text(
                encoding="utf-8"
            )
        )["samples"]
    }
    base = "/api/v1/support"

    def step(name, path, token, body):
        if name not in state:
            state[name] = {"path": path, "body": body, "key": "support-v1-" + name}
            state_path.write_bytes(
                (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode()
            )
        frozen = state[name]
        assert frozen["path"] == path
        return call("POST", path, token, frozen["body"], frozen["key"])

    def open_sample(name):
        return call(
            "POST",
            base + "/conversations",
            buyer,
            {"line_id": samples[name]["line_id"]},
        )

    def path(c):
        return base + "/conversations/" + c["conversation_id"]

    a = open_sample("A-SIGNED")
    a = step(
        "a-private",
        path(a) + "/messages",
        buyer,
        {
            "expected_version": a["version"],
            "text": "演示个人备注：稍后自行确认，不共享给商家。",
            "recipient": "ASSISTANT",
        },
    )
    a = step(
        "a-statement",
        path(a) + "/messages",
        buyer,
        {
            "expected_version": a["version"],
            "text": "物流显示签收但没有收到，家人和代收点均未找到，只请求核查。",
            "recipient": "ASSISTANT",
        },
    )
    shared = a["messages"][-1]["message_id"]
    a = step(
        "a-handoff",
        path(a) + "/tickets",
        buyer,
        {
            "expected_version": a["version"],
            "summary": "核实签收争议，当前不申请退款。",
            "shared_message_ids": [shared],
        },
    )
    tid = a["ticket"]["ticket_id"]
    ticket_path = base + "/tickets/" + tid
    detail = call("GET", ticket_path, merchant)
    encoded = json.dumps(detail, ensure_ascii=False)
    assert "家人和代收点" in encoded and "演示个人备注" not in encoded
    first = state["a-handoff"]
    assert call("POST", first["path"], buyer, first["body"], first["key"]) == a
    call(
        "POST",
        first["path"],
        buyer,
        {**first["body"], "summary": "改变载荷"},
        first["key"],
        409,
    )
    call("GET", ticket_path, other_merchant, expected=404)
    call("GET", path(a), other_buyer, expected=404)
    call("GET", path(a), merchant, expected=403)
    detail = step(
        "a-question",
        ticket_path + "/messages",
        merchant,
        {
            "expected_version": a["version"],
            "text": "商家核查演示：请补充是否授权他人代收。",
            "kind": "REQUEST_INFO",
        },
    )
    a = step(
        "a-private-after",
        path(a) + "/messages",
        buyer,
        {
            "expected_version": detail["version"],
            "text": "这条个人补充也不共享。",
            "recipient": "ASSISTANT",
        },
    )
    for n in range(3):
        a = step(
            f"a-supplement-{n}",
            path(a) + "/messages",
            buyer,
            {
                "expected_version": a["version"],
                "text": f"核查补充{n + 1}：未授权他人代收，请继续核查。",
                "recipient": "MERCHANT",
            },
        )
    detail = call("GET", ticket_path, merchant)
    encoded = json.dumps(detail, ensure_ascii=False)
    assert sum(m["text"].startswith("核查补充") for m in detail["messages"]) == 3
    assert "个人补充" not in encoded and "演示个人备注" not in encoded
    detail = step(
        "a-reply",
        ticket_path + "/messages",
        merchant,
        {
            "expected_version": a["version"],
            "text": "商家核查演示：已记录你的补充，可继续核查；本回复未作退款审批。",
            "kind": "REPLY",
        },
    )
    a = step(
        "a-resolve",
        path(a) + "/resolve",
        buyer,
        {"expected_version": detail["version"]},
    )
    assert a["ticket"]["status"] == "RESOLVED"
    b = open_sample("B-SIGNED")
    b = step(
        "b-private",
        path(b) + "/messages",
        buyer,
        {
            "expected_version": b["version"],
            "text": "B店台灯的独立咨询记录。",
            "recipient": "ASSISTANT",
        },
    )
    assert (
        "签收争议" not in json.dumps(b, ensure_ascii=False)
        and b["merchant_id"] == "M-1002"
    )
    call("GET", path(b), other_buyer, expected=404)
    assert call("GET", ticket_path, merchant)["version"] == a["version"]
    from resolveflow.contracts._schemaio import component_validator

    for name, record in [
        ("SupportConversation", a),
        ("SupportConversation", b),
        ("SupportTicketDetail", detail),
    ]:
        v = component_validator("case", name, "contracts/core")
        assert v.accepts(record), v.error_messages(record)
    baseline = json.loads(
        (root / "tmp/customer-agent-design-v1/support-before.json").read_text()
    )
    preserved = {}
    for table, before in baseline.items():
        database, name = table.split(".")
        rows = sorted(
            demo.mysql_rows("SELECT * FROM " + name, settings, database=database)
        )
        after = {
            "count": len(rows),
            "sha256": hashlib.sha256(
                json.dumps(rows, ensure_ascii=False).encode()
            ).hexdigest(),
        }
        assert before == after, table
        preserved[table] = after
    result = {
        "synthetic": True,
        "model_calls": 0,
        "gateway_tested": False,
        "case_and_commerce_real": True,
        "conversation_a": a["conversation_id"],
        "conversation_b": b["conversation_id"],
        "ticket_id": tid,
        "final_ticket_status": a["ticket"]["status"],
        "originals_shared": 1,
        "customer_supplements": 3,
        "private_notes_hidden_from_merchant": True,
        "receipt_replay_identical": True,
        "schema_validated_responses": 3,
        "preserved_business_tables": preserved,
        "http": results,
    }
    report = root / "reports/customer-support-v1/runtime-check.json"
    report.write_bytes(
        (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    )
    print(
        f"{len(results)} HTTP calls verified, shared snapshot/replies/3 supplements/resolution, 8 business tables unchanged; 0 model calls"
    )


if __name__ == "__main__":
    main()
