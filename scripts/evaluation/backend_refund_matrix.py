"""Owned real-MQ refund fault matrix. Frozen inputs, persistent provider and original operations."""

import argparse
import copy
import hashlib
import json
import re
import sqlite3
import sys
import time
import uuid
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend_resume_lab import healthy, start_java_services

from evaluation.backend_lab import (
    ROOT,
    Settings,
    child_env,
    freeze_file,
    run,
    sha256,
    wait,
)
from evaluation.backend_provider import Provider
from evaluation.backend_smoke import api, login
from evaluation.backend_trade import setup_cart
from evaluation.trade_request_journal import durable

sys.path.insert(0, str(ROOT / "agent/src"))
from resolveflow.contracts.canonical import canonical_bytes
from resolveflow.contracts.core_corpus import core_signing_keys, load_core_corpus
from resolveflow.contracts.events import sign_core_envelope


def validate_ledger(row):
    assert row["paid"] > 0 and row["refunded"] >= 0 and row["reserved"] >= 0
    assert row["refunded"] + row["reserved"] <= row["paid"]


def validate_unknown(row, amount):
    validate_ledger(row)
    assert row["refunded"] == 0 and row["reserved"] == amount
    assert row["operations"] and all(op["state"] == "UNKNOWN" and op["provider_key"] == op["operation_id"]
                                     for op in row["operations"])


def validate_final(row, lines, amount):
    validate_ledger(row)
    assert row["refunded"] == amount and row["reserved"] == 0 and row["operation_count"] == lines
    for field in ("provider_successes", "provider_attempts", "closed_events"):
        assert row[field] == [1] * lines
    for field, state in (("operation_states", "SUCCEEDED"), ("line_states", "CONSUMED"), ("case_states", "CLOSED_SUCCESS")):
        assert row[field] == [state] * lines


def restart(settings, role, delivery):
    state = settings.load()
    settings.stop_children({"pids": {role: state["pids"][role]}})
    start_java_services(settings, settings.load(), (role,), outbox_delivery=delivery)


def ids(values):
    if not values or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value) for value in values):
        raise ValueError("invalid owned entity identifiers")
    return ",".join("'" + value + "'" for value in values)


def event(settings, schema, operation, kind):
    assert schema in ("case_db", "commerce_db") and kind in ("RefundRequested", "RefundSucceeded")
    ids([operation])
    value = settings.sql(f"SELECT envelope FROM {schema}.event_outbox WHERE event_type='{kind}' "
                         f"AND JSON_UNQUOTE(JSON_EXTRACT(envelope,'$.payload.operation_id'))='{operation}';")
    return json.loads(value) if value else None


def ledger(settings, order, operations):
    values = settings.sql(f"SELECT paid_amount,refunded_amount,reserved_refund_amount FROM commerce_db.payment_ledger WHERE order_id={ids([order])};")
    paid, refunded, reserved = map(int, values.split("\t"))
    text = settings.sql("SELECT JSON_OBJECT('operation_id',operation_id,'provider_key',provider_key,'state',state,"
                        "'amount_minor',amount_minor,'retry_at',retry_at,'version',version) "
                        f"FROM commerce_db.refund_operation WHERE operation_id IN ({ids(operations)}) ORDER BY line_id;")
    row = {"paid": paid, "refunded": refunded, "reserved": reserved,
           "operations": [json.loads(line) for line in text.splitlines()]}
    validate_ledger(row)
    return row


def prepare(settings, buyer, admin, scenario, folder):
    from logistics_simulator import call_sql

    keys = {name: uuid.uuid4().hex for name in ("draft", "pay", "ship", "logistics")}
    durable(folder / "prepared.json", {"scenario": scenario, "keys": keys, "fixture": "actual shopping; synthetic manual evidence"})
    if scenario == "F03":
        body = setup_cart(settings, buyer)
        path = "/api/v1/shop/cart/M-1001/drafts"
    else:
        body = {"sku_id": "SKU-1001-BLACK", "quantity": 1, "expected_sku_version": 1}
        path = "/api/v1/shop/drafts"
    draft = api(settings, "POST", path, buyer, body, {"Idempotency-Key": keys["draft"]})["draft_id"]
    durable(folder / "draft.json", {"draft_id": draft})
    api(settings, "POST", f"/api/v1/shop/drafts/{draft}/payment", buyer, {}, {"Idempotency-Key": keys["pay"]})
    purchase = api(settings, "GET", "/api/v1/shop/purchases/draft:" + draft, buyer)
    assert purchase["status"] == "PAID"
    order = purchase["order_id"]
    lines = [line["line_id"] for line in purchase["lines"]]
    assert len(lines) == (2 if scenario == "F03" else 1)
    durable(folder / "purchase.json", purchase)
    api(settings, "POST", f"/api/v1/merchant/orders/{order}/simulated-shipment", admin,
        {"expected_version": 1}, {"Idempotency-Key": keys["ship"]})
    settings.sql("USE commerce_db;\n" + call_sql(order, "M-1001", 2, "LOST", keys["logistics"], None))
    cases, operations = [], []
    for index, line in enumerate(lines):
        case = api(settings, "POST", "/api/v1/cases", buyer,
                   {"line_id": line, "description": "合成退款故障实验：模拟承运商确认丢失，整行退款",
                    "requested_actions": ["REFUND"]}, {"Idempotency-Key": uuid.uuid4().hex}, expected=201)["case_id"]
        path = "/api/v1/cases/" + case
        view = api(settings, "GET", path, admin)
        collaboration = api(settings, "GET", path + "/collaboration", admin)
        if collaboration["version"] == 0:
            collaboration = api(settings, "POST", path + "/collaboration", admin,
                                {"action": "CLAIM", "reason": "合成故障实验显式领取"}, {"If-Collaboration-Match": '"0"'})
        values = settings.sql("SELECT b.bundle_id,b.version,r.position,r.rule_id,r.title,r.text "
            "FROM case_db.case_policy_bundle m JOIN case_db.policy_bundle b ON b.bundle_id=m.bundle_id "
            f"JOIN case_db.policy_rule r ON r.bundle_id=b.bundle_id WHERE m.case_id='{case}' AND r.rule_id='R-LOST-001';").split("\t")
        bundle, version, position, rule, title, text = values
        chunk = f"c-{int(position) + 1:02}"
        citation = {"bundle_id": bundle, "version": version, "rule_id": rule, "chunk_id": chunk,
                    "content_hash": hashlib.sha256(canonical_bytes(
                        {"bundle_id": bundle, "chunk_id": chunk, "title": title, "text": text})).hexdigest()}
        shipment_version = settings.sql(f"SELECT source_version FROM commerce_db.shipment WHERE line_id='{line}';")
        api(settings, "POST", path + "/manual-proposals", admin,
            {"action": "REFUND", "reason": "合成人工方案：核对模拟丢失事实及政策，整行退款",
             "policy_refs": [citation], "evidence_refs": [{"observation_id": str(uuid.uuid4()),
             "source_ref": f"line:{line}/shipment", "source_version": shipment_version, "content_hash": "1" * 64}]},
            {"If-Match": f'"{view["case"]["version"]}"', "If-Collaboration-Match": f'"{collaboration["version"]}"'})
        view = api(settings, "GET", path, admin)
        auth = view["authorization"]
        item = {"case_id": case, "line_id": line, "operation_id": auth["planned_operation_id"],
                "authorization_id": auth["authorization_id"], "input_revision": view["case"]["input_revision"],
                "case_version": view["case"]["version"], "collaboration_version": collaboration["version"],
                "authorization_version": auth["authorization_version"]}
        durable(folder / f"authorization-{index}.json", item)
        cases.append(case)
        operations.append(auth["planned_operation_id"])
    return {"order_id": order, "lines": lines, "cases": cases, "operations": operations,
            "amount": purchase["total_amount"]}


def approve(settings, admin, folder, count):
    for index in range(count):
        row = json.loads((folder / f"authorization-{index}.json").read_text(encoding="utf-8"))
        api(settings, "POST", "/api/v1/cases/" + row["case_id"] + "/reviews", admin,
            {"authorization_id": row["authorization_id"], "authorization_version": row["authorization_version"],
             "decision": "APPROVE", "reason": "合成故障实验确认版本及金额"},
            {"If-Match": f'"{row["case_version"]}"', "If-Collaboration-Match": f'"{row["collaboration_version"]}"'})


def mq_libraries(settings):
    target = settings.folder / "mq-libraries"
    target.mkdir(exist_ok=True)
    with zipfile.ZipFile(settings.folder / "baseline/commerce.jar") as jar:
        for name in jar.namelist():
            if name.startswith("BOOT-INF/lib/") and name.endswith(".jar"):
                path = target / Path(name).name
                data = jar.read(name)
                if path.exists():
                    assert path.read_bytes() == data
                else:
                    with path.open("xb") as output:
                        output.write(data)
    return target


def send(settings, envelopes, folder, label):
    settings.assert_owned("broker")
    values = [{"topic": e["topic"].replace(".", "-"), "event_id": e["event_id"],
               "envelope": json.dumps(e, ensure_ascii=False, separators=(",", ":"))} for e in envelopes]
    source = folder / (label + ".json")
    durable(source, values)
    java = Path.home() / ".jdks/jdk-21.0.12.1+1/bin/java.exe"
    result = run([str(java), "-cp", str(mq_libraries(settings) / "*"),
                  str(ROOT / "scripts/evaluation/BackendMqSender.java"), str(source),
                  f"127.0.0.1:{settings.load()['ports']['namesrv']}", settings.project], env=child_env(), timeout=60)
    acks = []
    for line in result.splitlines():
        if line.startswith("ACK "):
            _, event_id, status, message_id = line.split()
            assert status == "SEND_OK"
            acks.append({"event_id": event_id, "status": status, "message_id": message_id})
    assert len(acks) == len(envelopes)
    durable(folder / (label + "-acks.json"), acks)
    return acks


def consumed_acks(settings, acks):
    text = (settings.folder / "commerce.log").read_text(encoding="utf-8", errors="replace")
    found = {}
    for ack in acks:
        match = re.search(r"core event " + re.escape(ack["message_id"]) + r" -> ([A-Z_]+)", text)
        if match:
            found[ack["message_id"]] = match[1]
    return found


def final(settings, provider, entities):
    order, lines, cases, operations = (entities[key] for key in ("order_id", "lines", "cases", "operations"))
    row = ledger(settings, order, operations)
    def column(query):
        return settings.sql(query).splitlines()
    row.update(operation_count=int(settings.sql(f"SELECT COUNT(*) FROM commerce_db.refund_operation WHERE line_id IN ({ids(lines)});")),
               operation_states=[op["state"] for op in row["operations"]],
               line_states=column(f"SELECT state FROM commerce_db.line_refund WHERE line_id IN ({ids(lines)}) ORDER BY line_id;"),
               case_states=column(f"SELECT status FROM case_db.aftersale_case WHERE case_id IN ({ids(cases)}) ORDER BY case_id;"),
               closed_events=[int(settings.sql(f"SELECT COUNT(*) FROM case_db.case_timeline WHERE case_id='{case}' AND kind='CASE_CLOSED';")) for case in cases])
    with sqlite3.connect(provider.stub.path.as_uri() + "?mode=ro", uri=True) as db:
        row["provider_successes"] = [db.execute("SELECT COUNT(*) FROM refund_request WHERE line_id=? AND state='SUCCEEDED'", (line,)).fetchone()[0] for line in lines]
        row["provider_attempts"] = [db.execute("SELECT COUNT(*) FROM request_attempt WHERE operation_id=? AND outcome<>'REPEAT'", (op,)).fetchone()[0] for op in operations]
    validate_final(row, len(lines), entities["amount"])
    row["commands"] = [json.loads(settings.sql("SELECT JSON_OBJECT('event_id',event_id,'status',status,'attempts',attempts,'next_attempt_at',next_attempt_at,'last_error',last_error) "
                       "FROM case_db.event_outbox WHERE event_type='RefundRequested' "
                       f"AND JSON_UNQUOTE(JSON_EXTRACT(envelope,'$.payload.operation_id'))='{op}';")) for op in operations]
    row["results"] = [json.loads(settings.sql("SELECT JSON_OBJECT('event_id',event_id,'status',status,'attempts',attempts) "
                      "FROM commerce_db.event_outbox WHERE event_type='RefundSucceeded' "
                      f"AND JSON_UNQUOTE(JSON_EXTRACT(envelope,'$.payload.operation_id'))='{op}';")) for op in operations]
    for result in row["results"]:
        assert result["status"] == "PUBLISHED"
        assert settings.sql(f"SELECT COUNT(*) FROM case_db.case_result_inbox WHERE event_id='{result['event_id']}' AND projected_at IS NOT NULL;") == "1"
    row["provider_http"] = [r for r in provider.trace if r["operation_id"] in operations]
    return row


def broker_down(settings):
    settings.assert_owned("broker")
    run(["docker", "stop", "--time", "5", settings.container("broker")], timeout=20)
    assert run(["docker", "inspect", "--format", "{{.State.Running}}", settings.container("broker")]) == "false"


def broker_up(settings):
    settings.assert_owned("broker")
    run(["docker", "start", settings.container("broker")])
    port = settings.load()["ports"]["broker"]
    command = ("exec /home/rocketmq/rocketmq-*/bin/mqadmin updateTopic -n namesrv:9876 "
               f"-b 127.0.0.1:{port} -t rf-case-core-v2")
    wait("Broker available", lambda: "success" in run(
        ["docker", "exec", settings.container("broker"), "sh", "-c", command], timeout=10).lower())


def round_fault(settings, provider, buyer, admin, scenario, folder):
    started = time.monotonic()
    provider.gate.clear()
    broker_stopped = False
    try:
        entities = prepare(settings, buyer, admin, scenario, folder)
        durable(folder / "entities.json", entities)
        operations = entities["operations"]
        durable(folder / "before-approval.json", ledger(settings, entities["order_id"], operations))
        if scenario == "F04":
            provider.lose_response.update(operations)
        if scenario == "U00":
            provider.no_receipt.update(operations)
        if scenario == "F07":
            broker_down(settings)
            broker_stopped = True
            stopped_at = time.monotonic()
            durable(folder / "broker-stopped.json", {"monotonic": stopped_at, "pids": settings.load()["pids"]})
        approve(settings, admin, folder, len(operations))
        wait("real command outbox", lambda: all(event(settings, "case_db", op, "RefundRequested") for op in operations), seconds=20)
        commands = [event(settings, "case_db", op, "RefundRequested") for op in operations]
        durable(folder / "original-commands.json", commands)
        acks = None
        if scenario in ("F01", "F02"):
            envelopes = [copy.deepcopy(commands[0]) for _ in range(10)]
            if scenario == "F02":
                signing_key = core_signing_keys(load_core_corpus())[0]
                for envelope in envelopes:
                    envelope["event_id"] = str(uuid.uuid4())
                    envelope["signature"] = sign_core_envelope(envelope, signing_key)
                assert all(e["payload"] == commands[0]["payload"] for e in envelopes)
            acks = send(settings, envelopes, folder, "commands-sent")
        elif scenario == "F07":
            remaining = 10 - (time.monotonic() - stopped_at)
            if remaining > 0:
                time.sleep(remaining)
            pending = settings.sql(f"SELECT status FROM case_db.event_outbox WHERE event_id='{commands[0]['event_id']}';")
            assert pending == "PENDING"
            assert settings.sql(f"SELECT COUNT(*) FROM commerce_db.refund_operation WHERE operation_id IN ({ids(operations)});") == "0"
            durable(folder / "broker-window.json", {"stopped_seconds": time.monotonic() - stopped_at, "command_status": pending,
                                                   "pids": settings.load()["pids"], "no_operation_before_recovery": True})
            broker_up(settings)
            broker_stopped = False
            recovered_at = time.monotonic()
            durable(folder / "broker-recovered.json", {"monotonic": recovered_at})
        wait("money reserved", lambda: settings.sql(f"SELECT COUNT(*) FROM commerce_db.refund_operation WHERE operation_id IN ({ids(operations)});") == str(len(operations)))
        snapshot = ledger(settings, entities["order_id"], operations)
        assert snapshot["reserved"] == entities["amount"] and snapshot["refunded"] == 0
        durable(folder / "reserved.json", snapshot)
        provider.gate.set()
        if acks:
            wait("all sent commands consumed", lambda: len(consumed_acks(settings, acks)) == len(acks))
            durable(folder / "consumer-receipts.json", consumed_acks(settings, acks))
        if scenario in ("F04", "U00"):
            wait("UNKNOWN", lambda: settings.sql(f"SELECT state FROM commerce_db.refund_operation WHERE operation_id='{operations[0]}';") == "UNKNOWN")
            snapshot = ledger(settings, entities["order_id"], operations)
            validate_unknown(snapshot, entities["amount"])
            durable(folder / "unknown.json", snapshot)
            if scenario == "F04":
                visible = provider.hidden_until[operations[0]]
                remaining = visible - time.monotonic() + .02
                if remaining > 0:
                    time.sleep(remaining)
                held = ledger(settings, entities["order_id"], operations)
                validate_unknown(held, entities["amount"])
                durable(folder / "unknown-after-visibility-window.json", {**held, "monotonic": time.monotonic(),
                                                                         "visible_monotonic": visible})
            if scenario == "U00":
                time.sleep(10)
                later = ledger(settings, entities["order_id"], operations)
                validate_unknown(later, entities["amount"])
                assert provider.stub.query_refund(operations[0]).state == "NOT_FOUND"
                durable(folder / "unknown-control-final.json", later)
                return {"scenario": scenario, "status": "PASSED", "entities": entities,
                        "meaning": "no receipt; original reservation retained; not a converged success",
                        "provider_http": [r for r in provider.trace if r["operation_id"] in operations]}
        wait("refund settled", lambda: settings.sql(f"SELECT COUNT(*) FROM commerce_db.refund_operation WHERE operation_id IN ({ids(operations)}) AND state='SUCCEEDED';") == str(len(operations)))
        durable(folder / "settled.json", ledger(settings, entities["order_id"], operations))
        if scenario == "F05":
            result = event(settings, "commerce_db", operations[0], "RefundSucceeded")
            assert result
            assert settings.sql(f"SELECT status FROM commerce_db.event_outbox WHERE event_id='{result['event_id']}';") == "PENDING"
            old_pid = settings.load()["pids"]["commerce"]
            durable(folder / "unpublished-before-kill.json", {"pid": old_pid, "event_id": result["event_id"], "status": "PENDING"})
            restart(settings, "commerce", True)
            recovered_at = time.monotonic()
            durable(folder / "commerce-restarted.json", {"old_pid": old_pid, "new_pid": settings.load()["pids"]["commerce"], "ready_monotonic": recovered_at})
        wait("Case closed", lambda: settings.sql(f"SELECT COUNT(*) FROM case_db.aftersale_case WHERE case_id IN ({ids(entities['cases'])}) AND status='CLOSED_SUCCESS';") == str(len(entities["cases"])))
        closed_observed_at = time.monotonic()
        if scenario == "F06":
            result = event(settings, "commerce_db", operations[0], "RefundSucceeded")
            before = int(settings.sql(f"SELECT deliveries FROM case_db.case_result_inbox WHERE event_id='{result['event_id']}';"))
            send(settings, [result] * 9, folder, "results-sent")
            wait("ten result deliveries", lambda: int(settings.sql(f"SELECT deliveries FROM case_db.case_result_inbox WHERE event_id='{result['event_id']}';")) >= before + 9)
        result = final(settings, provider, entities)
        recovery = None
        if scenario in ("F05", "F07"):
            recovery = closed_observed_at - recovered_at
        elif scenario == "F04":
            visible = provider.hidden_until[operations[0]]
            assert any(r["stage"] == "query" and r["monotonic"] >= visible and r["state"] == "SUCCEEDED"
                       for r in result["provider_http"])
            recovery = closed_observed_at - visible
        return {"scenario": scenario, "status": "PASSED", "entities": entities, "final": result,
                "recovery_seconds": recovery, "elapsed_seconds": time.monotonic() - started}
    finally:
        provider.gate.set()
        if broker_stopped:
            broker_up(settings)


SOURCES = ["scripts/evaluation/" + name for name in (
    "backend_refund_matrix.py", "backend_provider.py", "backend_lab.py", "backend_smoke.py", "backend_trade.py",
    "BackendMqSender.java", "trade_request_journal.py")]
SOURCES += ["scripts/backend_resume_lab.py", "docs/backend-resume-evaluation-v1.md"]


def freeze(settings, folder, profile, scenarios=None):
    baseline = settings.freeze()
    folder.mkdir(parents=True, exist_ok=False)
    for name in SOURCES:
        freeze_file(ROOT / name, folder / "execution-sources" / name)
    repetitions = 10 if profile == "formal" else 1
    rows = [{"id": f"F{i:02d}-r{n + 1:02d}", "scenario": f"F{i:02d}"} for i in range(1, 8) for n in range(repetitions)]
    if profile == "wiring":
        rows = [{"id": "S00-smoke", "scenario": "S00"}, *rows, {"id": "U00-control", "scenario": "U00"}]
    if scenarios:
        if profile != "wiring" or not set(scenarios) <= {r["scenario"] for r in rows}:
            raise ValueError("scenario filter is only for explicit development wiring")
        rows = [r for r in rows if r["scenario"] in scenarios]
    durable(folder / "manifest.json", {"run_id": settings.identity, "profile": profile, "plan": rows,
            "sources": {name: sha256(ROOT / name) for name in SOURCES}, "jars": baseline["jars"],
            "provider": "persistent simulated refund; actual loopback HTTP/socket loss; no real money",
            "expected_success_lines": sum(2 if r["scenario"] == "F03" else 0 if r["scenario"] == "U00" else 1 for r in rows),
            "case_commands": "F01/F02 pause Case outbox and lab-send signed original; others automatic",
            "commerce_results": "F05 temporarily pause own result delivery, then real process exit; others automatic",
            "model_requests": 0})


def execute(settings, folder):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == settings.identity and manifest["jars"] == settings.freeze()["jars"]
    for name, digest in manifest["sources"].items():
        assert sha256(ROOT / name) == digest, name
    durable(folder / "execution-started.json", {"manifest_sha256": sha256(folder / "manifest.json")})
    settings.stop_children({"pids": {"provider": settings.load()["pids"]["provider"]}})
    provider = Provider(settings.folder / "provider.sqlite3", settings.load()["ports"]["provider"], trace_path=folder / "provider-http.jsonl")
    buyer, admin = login(settings, "demo-buyer", "demo-pass-4001"), login(settings, "demo-admin", "demo-pass-1100")
    results = []
    configuration = None
    try:
        for spec in manifest["plan"]:
            for name, digest in manifest["sources"].items():
                assert sha256(ROOT / name) == digest, name
            scenario = spec["scenario"]
            desired = (scenario not in ("F01", "F02"), scenario != "F05")
            if configuration != desired:
                restart(settings, "case", desired[0])
                restart(settings, "commerce", desired[1])
                configuration = desired
            output = folder / "rounds" / spec["id"]
            output.mkdir(parents=True)
            try:
                row = round_fault(settings, provider, buyer, admin, scenario, output)
            except Exception as error:
                durable(output / "failure.json", {**spec, "status": "FAILED", "error": type(error).__name__ + ": " + str(error)[:1200]})
                raise  # Uncertain money/window needs inspection; never blindly issue a fresh replacement.
            durable(output / "outcome.json", {**spec, **row, "evidence": {str(p.relative_to(output)): sha256(p) for p in output.rglob("*.json")}})
            results.append({**spec, **row})
            print(spec["id"] + " PASSED", flush=True)
    finally:
        provider.close()
        durable(folder / "summary.json", {"profile": manifest["profile"], "planned": len(manifest["plan"]),
                "completed": len(results), "passed": sum(r["status"] == "PASSED" for r in results), "rows": results,
                "manifest_sha256": sha256(folder / "manifest.json")})
        # Return the default owned provider process. UNKNOWN without receipt stays UNKNOWN on queries.
        env = child_env()
        env["PYTHONPATH"] = str(ROOT / "scripts")
        state = settings.load()
        settings.start_child("provider", [sys.executable, "-m", "evaluation.backend_provider", "--run-id=" + settings.identity], env, state)
        wait("provider restored", lambda: healthy(state["ports"]["provider"], "/health"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "execute"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--profile", choices=("wiring", "formal"), default="wiring")
    parser.add_argument("--scenarios", help="comma-separated explicit wiring subset; never changes formal denominator")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", args.experiment_id):
        raise ValueError("invalid experiment identifier")
    settings = Settings(args.run_id)
    with settings.operation_lock():
        folder = settings.report / "refund-matrices" / args.experiment_id
        scenarios = args.scenarios.split(",") if args.scenarios else None
        {"freeze": lambda: freeze(settings, folder, args.profile, scenarios), "execute": lambda: execute(settings, folder)}[args.action]()


if __name__ == "__main__":
    main()
