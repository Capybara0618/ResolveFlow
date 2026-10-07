"""Real Case/Commerce/MySQL/MQ fault matrix with a durable simulated provider."""

import argparse
import copy
import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]
from resolveflow.contracts.canonical import canonical_bytes
from resolveflow.contracts.core_corpus import core_signing_keys, load_core_corpus
from resolveflow.contracts.events import sign_core_envelope
from resolveflow.provider_stub import RefundProviderStub

from scripts.c11_review_load import login
from scripts.evaluation.resume_lab import JAVA, mysql, start_java, stop

CASE = "resume_refund_case_20261007c"
COMMERCE = "resume_refund_commerce_20261007c"
BASE = "http://127.0.0.1:18084"


def http(path, body=None, token=None, headers=None):
    req = Request(
        BASE + path,
        data=json.dumps(body, ensure_ascii=False).encode()
        if body is not None
        else None,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
            **(headers or {}),
        },
    )
    try:
        with urlopen(req, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except HTTPError as error:
        return error.code, error.read().decode()


def sqlrow(sql):
    text = mysql(sql)
    return text.split("\t") if text else []


def wait(label, fn, expected, timeout=120):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = fn()
        if last == expected:
            return last
        time.sleep(0.2)
    raise TimeoutError(f"{label}: last={last!r}, expected={expected!r}")


class Provider:
    def __init__(self, path):
        self.stub = RefundProviderStub(path)
        self.gate = threading.Event()
        self.gate.set()
        self.lost = set()
        self.hidden_until = {}
        self.reads = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def answer(self, status, result):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result, default=str).encode())

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                op = body["operation_id"]
                owner.reads.append({"method": "POST", "operation_id": op})
                if not owner.gate.wait(120):
                    self.answer(
                        503, {"detail": "lab reservation observation timed out"}
                    )
                    return
                result = owner.stub.request_refund(**body)
                if op in owner.lost:
                    owner.hidden_until[op] = time.monotonic() + 10
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                self.answer(200, asdict(result))

            def do_GET(self):
                op = self.path.rsplit("/", 1)[-1]
                owner.reads.append({"method": "GET", "operation_id": op})
                if time.monotonic() < owner.hidden_until.get(op, 0):
                    self.answer(
                        404, {"detail": "controlled delayed provider visibility"}
                    )
                    return
                result = owner.stub.query_refund(op)
                self.answer(200 if result.state != "NOT_FOUND" else 404, asdict(result))

        self.server = ThreadingHTTPServer(("127.0.0.1", 18090), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.gate.set()
        self.server.shutdown()
        self.server.server_close()
        self.stub.close()


def commerce_process(label, *, publish=True):
    return start_java(
        "commerce",
        COMMERCE,
        18081,
        label,
        extra=[
            "--resolveflow.provider.base-url=http://127.0.0.1:18090",
            "--resolveflow.events.namesrv=127.0.0.1:9879",
            "--resolveflow.events.consumer.enabled=true",
            "--resolveflow.events.consumer.group=resume-refund-commerce-20261007c",
            "--resolveflow.events.producer.group=resume-refund-commerce-outbox-20261007a",
            "--resolveflow.events.publisher.enabled=true",
            f"--resolveflow.events.outbox.delivery-enabled={str(publish).lower()}",
            "--resolveflow.events.outbox.poll-interval-ms=300",
            "--resolveflow.refund.dispatch-enabled=true",
            "--resolveflow.refund.reconcile-enabled=true",
            "--resolveflow.refund.poll-interval-ms=1000",
        ],
    )


def mint(lines):
    order = str(uuid.uuid4())
    ids = ["9" + str(uuid.uuid4().int)[:15] for _ in range(lines)]
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    sql = f"START TRANSACTION; INSERT INTO {COMMERCE}.orders (order_id,merchant_id,customer_id,order_status,currency,paid_at,created_at) VALUES ('{order}','M-1001','C-2002','PAID','CNY','{now}','{now}');"
    for line in ids:
        sql += f"INSERT INTO {COMMERCE}.order_line (line_id,order_id,merchant_id,customer_id,sku,category,quantity,line_paid_amount,currency,paid_at,order_status,version) VALUES ('{line}','{order}','M-1001','C-2002','RESUME-{line}','electronics',1,2599,'CNY','{now}','PAID',1);"
        sql += f"INSERT INTO {COMMERCE}.line_refund (line_id,state,operation_id,version,updated_at) VALUES ('{line}','FREE',NULL,1,'{now}');"
        sql += f"INSERT INTO {COMMERCE}.shipment (line_id,status,carrier_conclusion,source_version) VALUES ('{line}','LOST','LOST',1);"
        sql += f"INSERT INTO {COMMERCE}.shipment_event (line_id,code,occurred_at,source_version) VALUES ('{line}','CARRIER_LOST','{now}',1);"
    sql += f"INSERT INTO {COMMERCE}.payment_ledger (order_id,paid_amount,refunded_amount,reserved_refund_amount,version) VALUES ('{order}',{2599 * lines},0,0,1); COMMIT;"
    mysql(sql)
    return order, ids


def case_approve(line, customer, reviewer):
    status, opened = http(
        "/api/v1/cases",
        {
            "line_id": line,
            "description": "合成故障实验：承运商确认丢失，申请全额退款",
            "requested_actions": ["REFUND"],
        },
        customer,
        {"Idempotency-Key": str(uuid.uuid4())},
    )
    assert status == 201, (status, opened)
    case_id = opened["case_id"]
    path = f"/api/v1/cases/{case_id}"
    status, claim = http(
        path + "/collaboration",
        {"action": "CLAIM", "reason": "合成实验领取"},
        reviewer,
        {"If-Collaboration-Match": '"0"'},
    )
    assert status == 200, (status, claim)
    bundle, version, position, rule_id, title, text = sqlrow(
        f"SELECT b.bundle_id,b.version,r.position,r.rule_id,r.title,r.text FROM {CASE}.case_policy_bundle m JOIN {CASE}.policy_bundle b ON b.bundle_id=m.bundle_id JOIN {CASE}.policy_rule r ON r.bundle_id=b.bundle_id WHERE m.case_id='{case_id}' AND r.rule_id='R-LOST-001' LIMIT 1;"
    )
    chunk = f"c-{int(position) + 1:02}"
    citation = {
        "bundle_id": bundle,
        "version": version,
        "rule_id": rule_id,
        "chunk_id": chunk,
        "content_hash": hashlib.sha256(
            canonical_bytes(
                {"bundle_id": bundle, "chunk_id": chunk, "title": title, "text": text}
            )
        ).hexdigest(),
    }
    _, view = http(path, token=reviewer)
    headers = {
        "If-Match": f'"{view["case"]["version"]}"',
        "If-Collaboration-Match": f'"{claim["version"]}"',
    }
    status, proposal = http(
        path + "/manual-proposals",
        {
            "action": "REFUND",
            "reason": "人工核查合成承运结论后确认退款",
            "policy_refs": [citation],
            "evidence_refs": [
                {
                    "observation_id": str(uuid.uuid4()),
                    "source_ref": f"line:{line}/shipment",
                    "source_version": "1",
                    "content_hash": "1" * 64,
                }
            ],
        },
        reviewer,
        headers,
    )
    assert status == 200, (status, proposal)
    _, view = http(path, token=reviewer)
    auth = view["authorization"]
    headers["If-Match"] = f'"{view["case"]["version"]}"'
    status, answer = http(
        path + "/reviews",
        {
            "authorization_id": auth["authorization_id"],
            "authorization_version": auth["authorization_version"],
            "decision": "APPROVE",
            "reason": "合成退款故障实验确认金额及政策",
        },
        reviewer,
        headers,
    )
    assert status == 200, (status, answer)
    return case_id


def command_for(case_id):
    wait(
        "Case outbox",
        lambda: mysql(
            f"SELECT count(*) FROM {CASE}.event_outbox WHERE envelope LIKE '%{case_id}%' AND event_type='RefundRequested';"
        ),
        "1",
    )
    envelope = json.loads(
        mysql(
            f"SELECT envelope FROM {CASE}.event_outbox WHERE envelope LIKE '%{case_id}%' AND event_type='RefundRequested';"
        )
    )
    return envelope


def send(rows, file):
    file.write_text(
        json.dumps(
            [
                {
                    "topic": row["topic"].replace(".", "-"),
                    "event_id": row["event_id"],
                    "envelope": json.dumps(
                        row, ensure_ascii=False, separators=(",", ":")
                    ),
                }
                for row in rows
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    log = (ROOT / "tmp/resume/processes" / (file.stem + "-sender.log")).open(
        "w", encoding="utf-8"
    )
    process = subprocess.Popen(
        [
            str(JAVA),
            "-cp",
            str(ROOT / "tmp/resume/mq/lib/*"),
            str(ROOT / "scripts/evaluation/ResumeMqSender.java"),
            str(file),
        ],
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    log.close()
    return process


def ledger(order):
    paid, refunded, reserved, version = map(
        int,
        sqlrow(
            f"SELECT paid_amount,refunded_amount,reserved_refund_amount,version FROM {COMMERCE}.payment_ledger WHERE order_id='{order}';"
        ),
    )
    return {
        "paid": paid,
        "refunded": refunded,
        "reserved": reserved,
        "version": version,
        "excess": max(0, refunded + reserved - paid),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trial", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    provider = Provider(ROOT / f"tmp/resume/{args.output.name}-provider.sqlite3")
    commerce = case = None
    results = []
    metadata = {
        "case_schema": CASE,
        "commerce_schema": COMMERCE,
        "namesrv": "127.0.0.1:9879",
        "provider": "durable simulated SQLite provider; real loopback HTTP",
        "source_sha256": {
            str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in [
                Path(__file__),
                ROOT / "scripts/evaluation/ResumeMqSender.java",
                ROOT / "scripts/evaluation/resume_lab.py",
                ROOT
                / "java/commerce-service/target/commerce-service-0.1.0-SNAPSHOT.jar",
                ROOT / "java/case-service/target/case-service-0.1.0-SNAPSHOT.jar",
            ]
        },
        "command_delivery": "Case HTTP approval/consumption writes real signed outbox; lab sender controls MQ delivery count",
    }
    (args.output / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    try:
        commerce = commerce_process(f"{args.output.name}-commerce")
        case = start_java(
            "case",
            CASE,
            18084,
            f"{args.output.name}-case",
            extra=[
                "--resolveflow.commerce.base-url=http://127.0.0.1:18081",
                "--resolveflow.dispatch.enabled=true",
                "--resolveflow.dispatch.poll-interval-ms=500",
                "--resolveflow.events.namesrv=127.0.0.1:9879",
                "--resolveflow.events.consumer.enabled=true",
                "--resolveflow.events.consumer.group=resume-refund-case-20261007c",
                "--resolveflow.events.publisher.enabled=true",
                "--resolveflow.events.producer.group=resume-refund-case-outbox-20261007a",
                "--resolveflow.events.outbox.delivery-enabled=false",
                "--resolveflow.events.outbox.poll-interval-ms=300",
            ],
        )
        customer = login(BASE, "demo-customer", "demo-pass-1001")
        reviewer = login(BASE, "demo-reviewer", "demo-pass-1003")
        key = core_signing_keys(load_core_corpus())[0]
        for scenario in range(1, 7):
            for repeat in range(1 if args.trial else 10):
                started = time.monotonic()
                row = {
                    "scenario": f"F{scenario}",
                    "repeat": repeat,
                    "status": "RUNNING",
                    "snapshots": [],
                }
                results.append(row)
                provider.gate.clear()
                if scenario == 5:
                    stop(commerce)
                    commerce = commerce_process(f"f5-{repeat}-before", publish=False)
                try:
                    order, lines = mint(2 if scenario == 3 else 1)
                    cases = [case_approve(line, customer, reviewer) for line in lines]
                    envelopes = [command_for(c) for c in cases]
                    ops = [e["payload"]["operation_id"] for e in envelopes]
                    row.update(order_id=order, lines=lines, cases=cases, operations=ops)
                    if scenario == 1:
                        # Ten identical deliveries of the authoritative Case document.
                        sender = send(
                            [envelopes[0]] * 10,
                            args.output / f"F1-{repeat}-messages.json",
                        )
                    elif scenario == 2:
                        # Ten concurrent deliveries, distinct events and the same approved operation.
                        conflicting = []
                        for _ in range(10):
                            event = copy.deepcopy(envelopes[0])
                            event["event_id"] = str(uuid.uuid4())
                            event["signature"] = sign_core_envelope(event, key)
                            conflicting.append(event)
                        sender = send(
                            conflicting, args.output / f"F2-{repeat}-messages.json"
                        )
                        row["concurrent_same_line_deliveries"] = 10
                    elif scenario == 4:
                        provider.lost.add(ops[0])
                        sender = send(
                            envelopes, args.output / f"F4-{repeat}-messages.json"
                        )
                    else:
                        sender = send(
                            envelopes,
                            args.output / f"F{scenario}-{repeat}-messages.json",
                        )
                    wait(
                        "reserved",
                        lambda ops=ops, cases=cases: mysql(
                            f"SELECT count(*) FROM {COMMERCE}.refund_operation WHERE operation_id IN ({','.join(repr(o) for o in ops)});"
                        ),
                        str(len(ops)),
                    )
                    row["snapshots"].append(
                        {"stage": "reserved_before_provider", **ledger(order)}
                    )
                    provider.gate.set()
                    assert sender.wait(timeout=60) == 0, (
                        "MQ sender failed; inspect sender log"
                    )
                    if scenario == 4:
                        wait(
                            "UNKNOWN",
                            lambda ops=ops, cases=cases: mysql(
                                f"SELECT state FROM {COMMERCE}.refund_operation WHERE operation_id='{ops[0]}';"
                            ),
                            "UNKNOWN",
                        )
                        row["snapshots"].append({"stage": "UNKNOWN", **ledger(order)})
                        row["unknown_observed"] = True
                    wait(
                        "settled",
                        lambda ops=ops, cases=cases: mysql(
                            f"SELECT count(*) FROM {COMMERCE}.refund_operation WHERE operation_id IN ({','.join(repr(o) for o in ops)}) AND state='SUCCEEDED';"
                        ),
                        str(len(ops)),
                    )
                    row["snapshots"].append({"stage": "settled", **ledger(order)})
                    if scenario == 5:
                        pending = mysql(
                            f"SELECT count(*) FROM {COMMERCE}.event_outbox WHERE envelope LIKE '%{ops[0]}%' AND status='PENDING';"
                        )
                        assert pending == "1", pending
                        row["settled_unpublished_before_kill"] = True
                        commerce.kill()
                        commerce.wait(timeout=10)
                        commerce = commerce_process(f"f5-{repeat}-after")
                    wait(
                        "Case closed",
                        lambda ops=ops, cases=cases: mysql(
                            f"SELECT count(*) FROM {CASE}.aftersale_case WHERE case_id IN ({','.join(repr(c) for c in cases)}) AND status='CLOSED_SUCCESS';"
                        ),
                        str(len(cases)),
                    )
                    if scenario == 6:
                        event = json.loads(
                            mysql(
                                f"SELECT envelope FROM {COMMERCE}.event_outbox WHERE event_type='RefundSucceeded' AND envelope LIKE '%{ops[0]}%';"
                            )
                        )
                        repeated = send(
                            [event] * 9, args.output / f"F6-{repeat}-messages.json"
                        )
                        assert repeated.wait(timeout=60) == 0, (
                            "result redelivery sender failed"
                        )
                        wait(
                            "ten result deliveries",
                            lambda ops=ops, cases=cases: mysql(
                                f"SELECT deliveries FROM {CASE}.case_result_inbox WHERE operation_id='{ops[0]}' AND state='SUCCEEDED';"
                            ),
                            "10",
                        )
                    row["snapshots"].append({"stage": "final", **ledger(order)})
                    with sqlite3.connect(provider.stub.path) as db:
                        success_counts = {
                            line: db.execute(
                                "SELECT count(*) FROM refund_request WHERE line_id=? AND state='SUCCEEDED'",
                                (line,),
                            ).fetchone()[0]
                            for line in lines
                        }
                    row["provider_successes_per_line"] = success_counts
                    row["duplicate_successes"] = sum(
                        max(0, n - 1) for n in success_counts.values()
                    )
                    row["closed_events"] = {
                        c: int(
                            mysql(
                                f"SELECT count(*) FROM {CASE}.case_timeline WHERE case_id='{c}' AND kind='CASE_CLOSED';"
                            )
                        )
                        for c in cases
                    }
                    row["provider_http"] = [
                        r for r in provider.reads if r["operation_id"] in ops
                    ]
                    row["domain_failed_results"] = int(
                        mysql(
                            f"SELECT count(*) FROM {COMMERCE}.event_outbox WHERE event_type='RefundFailed' AND ("
                            + " OR ".join(f"envelope LIKE '%{op}%'" for op in ops)
                            + ");"
                        )
                    )
                    assert row["domain_failed_results"] == 0
                    assert all(n == 1 for n in success_counts.values()) and all(
                        n == 1 for n in row["closed_events"].values()
                    )
                    assert all(s["excess"] == 0 for s in row["snapshots"])
                    assert (
                        row["snapshots"][-1]["refunded"] == 2599 * len(lines)
                        and row["snapshots"][-1]["reserved"] == 0
                    )
                    row["status"] = "PASSED"
                except Exception as error:  # noqa: BLE001 - retain measured failures
                    row.update(
                        status="FAILED", error=f"{type(error).__name__}: {error}"
                    )
                finally:
                    provider.gate.set()
                    row["elapsed_seconds"] = time.monotonic() - started
                    (args.output / "results.json").write_text(
                        json.dumps(
                            {
                                "state": "RUNNING",
                                "trial": args.trial,
                                "results": results,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    print(
                        json.dumps(
                            {
                                k: row.get(k)
                                for k in ("scenario", "repeat", "status", "error")
                            }
                        ),
                        flush=True,
                    )
                if args.trial and row["status"] == "FAILED":
                    return 1
    finally:
        stop(case)
        stop(commerce)
        provider.close()
    (args.output / "results.json").write_text(
        json.dumps(
            {"state": "COMPLETED", "trial": args.trial, "results": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return int(any(r["status"] != "PASSED" for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
