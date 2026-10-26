"""One real Gateway -> purchase -> manual authorization -> MQ -> refund smoke."""

import hashlib
import json
import sqlite3
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime

from evaluation.backend_lab import ROOT, sha256, wait

sys.path.insert(0, str(ROOT / "agent/src"))
from resolveflow.contracts.canonical import canonical_bytes


def api(settings, method, path, token=None, body=None, headers=None, expected=200):
    state = settings.load()
    request = urllib.request.Request(
        f"http://127.0.0.1:{state['ports']['gateway']}{path}",
        data=None if body is None else json.dumps(body).encode(), method=method,
        headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {}),
                 **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status, content = response.status, response.read()
    except urllib.error.HTTPError as response:
        status, content = response.code, response.read()
    entry = {"at": datetime.now(UTC).isoformat(), "method": method, "path": path,
             "gateway_port": state["ports"]["gateway"], "status": status,
             "response_sha256": hashlib.sha256(content).hexdigest()}
    with (settings.folder / "http.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps(entry) + "\n")
    if status != expected:
        raise AssertionError(f"{method} {path}: expected {expected}, got {status}: {content.decode()[:400]}")
    return json.loads(content)


def login(settings, username, password):
    return api(settings, "POST", "/api/v1/auth/login", body={"username": username, "password": password})["access_token"]


def save(settings, smoke):
    state = settings.load()
    state["smoke"] = smoke
    settings.save(state)


def exercise(settings):
    from logistics_simulator import call_sql

    state = settings.load()
    smoke = state.setdefault("smoke", {})
    for name in ("draft_key", "pay_key", "ship_key", "logistics_key", "case_key"):
        smoke.setdefault(name, uuid.uuid4().hex)
    save(settings, smoke)
    buyer = login(settings, "demo-buyer", "demo-pass-4001")
    admin = login(settings, "demo-admin", "demo-pass-1100")
    if "draft" not in smoke:
        product = api(settings, "GET", "/api/v1/shop/products/P-1001")
        sku = product["skus"][0]
        draft = api(settings, "POST", "/api/v1/shop/drafts", buyer,
                    {"sku_id": sku["sku_id"], "quantity": 1, "expected_sku_version": sku["version"]},
                    {"Idempotency-Key": smoke["draft_key"]})
        smoke["draft"] = draft["draft_id"]
        save(settings, smoke)
    if "order" not in smoke:
        api(settings, "POST", f"/api/v1/shop/drafts/{smoke['draft']}/payment", buyer, {},
            {"Idempotency-Key": smoke["pay_key"]})
        purchase = api(settings, "GET", "/api/v1/shop/purchases/draft:" + smoke["draft"], buyer)
        assert purchase["status"] == "PAID"
        smoke.update(order=purchase["order_id"], line=purchase["lines"][0]["line_id"], paid=purchase["total_amount"])
        save(settings, smoke)
    if not smoke.get("logistics"):
        api(settings, "POST", f"/api/v1/merchant/orders/{smoke['order']}/simulated-shipment", admin,
            {"expected_version": 1}, {"Idempotency-Key": smoke["ship_key"]})
        settings.sql("USE commerce_db;\n" + call_sql(smoke["order"], "M-1001", 2, "LOST", smoke["logistics_key"], None))
        smoke["logistics"] = True
        save(settings, smoke)
    if "case" not in smoke:
        opened = api(settings, "POST", "/api/v1/cases", buyer,
                     {"line_id": smoke["line"], "description": "独立后端冒烟：承运商模拟确认丢失，申请整行退款",
                      "requested_actions": ["REFUND"]}, {"Idempotency-Key": smoke["case_key"]}, expected=201)
        smoke["case"] = opened["case_id"]
        save(settings, smoke)
    case_path = "/api/v1/cases/" + smoke["case"]
    view = api(settings, "GET", case_path, admin)
    if view["case"]["status"] != "CLOSED_SUCCESS":
        collaboration = api(settings, "GET", case_path + "/collaboration", admin)
        if collaboration["version"] == 0:
            collaboration = api(settings, "POST", case_path + "/collaboration", admin,
                                {"action": "CLAIM", "reason": "独立后端冒烟人工处理"},
                                {"If-Collaboration-Match": '"0"'})
        if not view.get("authorization"):
            values = settings.sql(
                "SELECT b.bundle_id,b.version,r.position,r.rule_id,r.title,r.text FROM case_db.case_policy_bundle m "
                "JOIN case_db.policy_bundle b ON b.bundle_id=m.bundle_id JOIN case_db.policy_rule r ON r.bundle_id=b.bundle_id "
                f"WHERE m.case_id='{smoke['case']}' AND r.rule_id='R-LOST-001' LIMIT 1;").split("\t")
            bundle, version, position, rule, title, text = values
            chunk = f"c-{int(position) + 1:02}"
            citation = {"bundle_id": bundle, "version": version, "rule_id": rule, "chunk_id": chunk,
                        "content_hash": hashlib.sha256(canonical_bytes(
                            {"bundle_id": bundle, "chunk_id": chunk, "title": title, "text": text})).hexdigest()}
            shipment_version = settings.sql(f"SELECT source_version FROM commerce_db.shipment WHERE line_id='{smoke['line']}';")
            headers = {"If-Match": f'"{view["case"]["version"]}"',
                       "If-Collaboration-Match": f'"{collaboration["version"]}"'}
            api(settings, "POST", case_path + "/manual-proposals", admin,
                {"action": "REFUND", "reason": "合成人工核查：模拟承运商确认丢失，按绑定政策退款",
                 "policy_refs": [citation], "evidence_refs": [{"observation_id": str(uuid.uuid4()),
                    "source_ref": f"line:{smoke['line']}/shipment", "source_version": shipment_version,
                    "content_hash": "1" * 64}]}, headers)
            view = api(settings, "GET", case_path, admin)
        authorization = view["authorization"]
        smoke["operation"] = authorization["planned_operation_id"]
        save(settings, smoke)
        if authorization["status"] == "PENDING_REVIEW":
            api(settings, "POST", case_path + "/reviews", admin,
                {"authorization_id": authorization["authorization_id"],
                 "authorization_version": authorization["authorization_version"],
                 "decision": "APPROVE", "reason": "独立后端冒烟确认政策及整行金额"},
                {"If-Match": f'"{view["case"]["version"]}"',
                 "If-Collaboration-Match": f'"{collaboration["version"]}"'})
        wait("refund Case closed", lambda: settings.sql(
            f"SELECT status FROM case_db.aftersale_case WHERE case_id='{smoke['case']}';") == "CLOSED_SUCCESS", 120)
    verify(settings)


def verify(settings):
    state = settings.load()
    smoke = state["smoke"]
    case, order, line, operation = (smoke[k] for k in ("case", "order", "line", "operation"))
    paid, refunded, reserved = map(int, settings.sql(
        f"SELECT paid_amount,refunded_amount,reserved_refund_amount FROM commerce_db.payment_ledger WHERE order_id='{order}';").split("\t"))
    assert paid == smoke["paid"] == refunded and reserved == 0
    assert settings.sql(f"SELECT status FROM case_db.aftersale_case WHERE case_id='{case}';") == "CLOSED_SUCCESS"
    assert settings.sql(f"SELECT state FROM commerce_db.refund_operation WHERE operation_id='{operation}';") == "SUCCEEDED"
    assert settings.sql(f"SELECT COUNT(*) FROM commerce_db.refund_operation WHERE line_id='{line}';") == "1"
    assert settings.sql(f"SELECT state FROM commerce_db.line_refund WHERE line_id='{line}';") == "CONSUMED"
    command = settings.sql(f"SELECT event_id,status FROM case_db.event_outbox WHERE event_type='RefundRequested' AND envelope LIKE '%{operation}%';").split("\t")
    result = settings.sql(f"SELECT event_id,status FROM commerce_db.event_outbox WHERE event_type='RefundSucceeded' AND envelope LIKE '%{operation}%';").split("\t")
    assert command[1] == result[1] == "PUBLISHED"
    assert settings.sql(f"SELECT disposition FROM commerce_db.event_inbox WHERE event_id='{command[0]}';") == "ACCEPTED"
    assert settings.sql(f"SELECT COUNT(*) FROM case_db.case_result_inbox WHERE event_id='{result[0]}' AND projected_at IS NOT NULL;") == "1"
    assert settings.sql(f"SELECT COUNT(*) FROM case_db.case_timeline WHERE case_id='{case}' AND kind='CASE_CLOSED';") == "1"
    with sqlite3.connect((settings.folder / "provider.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        provider = db.execute("SELECT operation_id,amount_minor,state FROM refund_request WHERE line_id=?", (line,)).fetchall()
        assert provider == [(operation, paid, "SUCCEEDED")]
        assert db.execute("SELECT COUNT(*) FROM request_attempt WHERE operation_id=?", (operation,)).fetchone()[0] == 1
    buyer = login(settings, "demo-buyer", "demo-pass-4001")
    purchases = api(settings, "GET", "/api/v1/shop/purchases?limit=24", buyer)
    assert any(p.get("order_id") == order for p in purchases["items"])
    report = {"run_id": settings.identity, "phase": "D0 real-service smoke, not formal evaluation",
              "model_requests": 0, "money": {"paid": paid, "refunded": refunded, "reserved": reserved},
              "fixture": "actual purchase/payment/shipment, controlled logistics LOST; explicit synthetic manual evidence/proposal",
              "ids": {"case": case, "order": order, "line": line, "operation": operation,
                      "command_event": command[0], "result_event": result[0]},
              "checks": {name: True for name in ("gateway_public_http", "purchase_paid", "controlled_shipment_lost",
                         "manual_authorization", "automatic_command_outbox", "mq_command_inbox", "single_provider_success",
                         "single_provider_attempt", "single_refund_operation", "ledger_balanced", "line_consumed",
                         "automatic_result_outbox", "mq_result_projected", "single_case_close", "buyer_order_visible")},
              "runtime_source_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p) for p in
                  (ROOT / "scripts/backend_resume_lab.py", ROOT / "scripts/evaluation/backend_lab.py",
                   ROOT / "scripts/evaluation/backend_smoke.py", ROOT / "scripts/evaluation/backend_provider.py")}}
    settings.report.mkdir(parents=True, exist_ok=True)
    (settings.report / "smoke.json").write_bytes((json.dumps(report, indent=2) + "\n").encode())
    print(json.dumps(report, ensure_ascii=False))
