"""D1 development faults over frozen Java services. No production fault switches."""

import argparse
import hashlib
import http.client
import json
import queue
import re
import socket
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend_resume_lab import start_java_services

from evaluation.backend_lab import Settings, sha256, wait
from evaluation.backend_smoke import api, login
from evaluation.backend_trade import burst, payment_counts, setup_cart, validate_payment


def save(folder, name, value):
    with (folder / (name + ".json")).open("xb") as output:
        output.write((json.dumps(value, indent=2) + "\n").encode())


def validate_crash_window(state):
    assert state["attempt_id"] and state["planned_order_id"]
    assert state["attempts"] == state["receipts"] == 1 and state["orders"] == 0
    assert state["draft_status"] == "PAYMENT_PENDING" and state["attempt_status"] == "UNKNOWN"


def validate_loss(evidence):
    assert evidence["upstream_status"] == 200 and evidence["client_status"] == 0
    assert evidence["discarded_bytes"] > 0 and evidence["client_error"] == "RemoteDisconnected"


class MysqlSession:
    """A labelled lab-only persistent connection; close rolls back and releases locks."""

    def __init__(self, settings):
        settings.assert_owned("mysql")
        self.process = subprocess.Popen(
            ["docker", "exec", "-i", settings.container("mysql"), "mysql", "-uroot", "-proot",
             "--batch", "--raw", "--skip-column-names", "--unbuffered", "--skip-reconnect", "commerce_db"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.output = queue.Queue()
        def read():
            for line in self.process.stdout:
                self.output.put(line.rstrip("\r\n"))
            self.output.put(None)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        self.execute("SET SESSION innodb_lock_wait_timeout=40; SET SESSION lock_wait_timeout=40")

    def execute(self, sql, timeout=45):
        sentinel = "done_" + uuid.uuid4().hex
        self.process.stdin.write(sql.rstrip(";") + f"; SELECT '{sentinel}';\n")
        self.process.stdin.flush()
        result = []
        while True:
            try:
                line = self.output.get(timeout=timeout)
            except queue.Empty as error:
                raise TimeoutError("lab SQL gate did not acknowledge") from error
            if line is None:
                raise RuntimeError("lab SQL session closed: " + "\n".join(result))
            if line == sentinel:
                if any(row.startswith("ERROR") for row in result):
                    raise RuntimeError("\n".join(result))
                return result
            result.append(line)

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.process.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def crash_snapshot(settings, draft):
    return json.loads(settings.sql(f"""SELECT JSON_OBJECT(
      'attempt_id',a.attempt_id,'planned_order_id',a.order_id,
      'attempt_status',a.status,'draft_status',d.status,
      'attempts',(SELECT COUNT(*) FROM commerce_db.checkout_payment_attempt WHERE draft_id=d.draft_id),
      'receipts',(SELECT COUNT(*) FROM commerce_db.simulated_checkout_receipt WHERE attempt_id=a.attempt_id),
      'orders',(SELECT COUNT(*) FROM commerce_db.orders WHERE order_id=a.order_id))
      FROM commerce_db.checkout_draft d JOIN commerce_db.checkout_payment_attempt a USING(draft_id)
      WHERE d.draft_id='{draft}';"""))


def discard_payment_response(settings, token, path, key):
    evidence = {}
    port = settings.load()["ports"]["gateway"]

    class Drop(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            upstream = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
            try:
                upstream.request("POST", self.path, body, {"Authorization": self.headers["Authorization"],
                                 "Content-Type": "application/json", "Idempotency-Key": self.headers["Idempotency-Key"]})
                reply = upstream.getresponse()
                content = reply.read()
                evidence.update(upstream_status=reply.status, discarded_bytes=len(content),
                                response_sha256=hashlib.sha256(content).hexdigest(),
                                attempt_id=json.loads(content).get("attempt_id"))
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
            finally:
                upstream.close()

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Drop)
    server.timeout = 25
    worker = threading.Thread(target=server.handle_request)
    worker.start()
    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=25)
    journal = getattr(settings, "request_journal", None)
    ticket = journal.prepare(path, journal.actor(token), [({}, key)])[0] if journal else None
    if ticket:
        journal.start(ticket)
    try:
        client.request("POST", path, b"{}", {"Authorization": "Bearer " + token,
                       "Content-Type": "application/json", "Idempotency-Key": key})
        evidence["client_status"] = client.getresponse().status
    except http.client.RemoteDisconnected as error:
        evidence.update(client_status=0, client_error=type(error).__name__)
    finally:
        client.close()
        worker.join(timeout=30)
        server.server_close()
    if ticket:
        journal.finish(ticket, {"status": evidence.get("client_status", 0), "body": evidence,
                                "phase": "intentional first response loss"})
    validate_loss(evidence)
    return evidence


def crash_after_receipt(settings, token, path, key, draft, folder):
    state = settings.load()
    stopped = False
    try:
        with MysqlSession(settings) as receipt, MysqlSession(settings) as publication:
            receipt.execute("LOCK TABLES simulated_checkout_receipt WRITE")
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(burst, settings, path, token, [({}, key)])
                wait("payment reservation", lambda: settings.sql(
                    f"SELECT COUNT(*) FROM commerce_db.checkout_payment_attempt WHERE draft_id='{draft}';") == "1", seconds=15)
                publication.execute(f"START TRANSACTION; SELECT draft_id FROM checkout_draft WHERE draft_id='{draft}' FOR UPDATE")
                receipt.execute("UNLOCK TABLES")
                wait("committed payment receipt", lambda: int(settings.sql(
                    "SELECT COUNT(*) FROM commerce_db.simulated_checkout_receipt WHERE attempt_id IN "
                    f"(SELECT attempt_id FROM commerce_db.checkout_payment_attempt WHERE draft_id='{draft}');")) == 1, seconds=15)
                snapshot = crash_snapshot(settings, draft)
                validate_crash_window(snapshot)
                save(folder, "before-crash", snapshot)
                settings.stop_children({"pids": {"commerce": state["pids"]["commerce"]}})
                stopped = True
                def gone():
                    with socket.socket() as probe:
                        return probe.connect_ex(("127.0.0.1", state["ports"]["commerce"])) != 0
                wait("Commerce process exit", gone, seconds=10)
                save(folder, "process-exit", {"pid": state["pids"]["commerce"], "port_closed": True})
                publication.execute("ROLLBACK")
                interrupted = pending.result(timeout=25)
                save(folder, "interrupted-request", interrupted)
                assert interrupted[0]["status"] in (0, 502, 503), interrupted
    finally:
        if stopped:
            start_java_services(settings, settings.load(), ("commerce",))
    save(folder, "restart", {"pid": settings.load()["pids"]["commerce"], "previous_pid": state["pids"]["commerce"]})
    return snapshot


def fault_round(settings, token, scenario, concurrency, folder):
    # No automatic retries: STARTED without a result requires inspection of these original identifiers.
    body = setup_cart(settings, token)
    draft_key, pay_key = uuid.uuid4().hex, uuid.uuid4().hex
    save(folder, "prepared", {"scenario": scenario, "concurrency": concurrency, "draft_key": draft_key,
                             "pay_key": pay_key, "draft_body": body, "phase": "development probe"})
    draft = api(settings, "POST", "/api/v1/shop/cart/M-1001/drafts", token, body, {"Idempotency-Key": draft_key})["draft_id"]
    path = f"/api/v1/shop/drafts/{draft}/payment"
    save(folder, "draft", {"draft_id": draft, "path": path})
    if scenario == "T06":
        evidence = discard_payment_response(settings, token, path, pay_key)
        save(folder, "response-loss", evidence)
    else:
        evidence = crash_after_receipt(settings, token, path, pay_key, draft, folder)
    rows = burst(settings, path, token, [({}, pay_key) for _ in range(concurrency)])
    save(folder, "recovery-requests", rows)
    payment = api(settings, "GET", path, token)["payment"]
    counts = payment_counts(settings, draft)
    validate_payment(rows, payment["attempt_id"], counts, 2)
    assert payment["attempt_id"] == evidence["attempt_id"] and payment["status"] == "SUCCEEDED"
    if scenario == "T07":
        assert payment["order_id"] == evidence["planned_order_id"]
    result = {"scenario": scenario, "concurrency": concurrency, "status": "PASSED", "draft_id": draft,
              "attempt_id": payment["attempt_id"], "order_id": payment["order_id"], "counts": counts,
              "artifacts": {p.name: sha256(p) for p in folder.glob("*.json")}}
    save(folder, "result", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--probe-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", args.probe_id):
        raise ValueError("invalid probe identifier")
    settings = Settings(args.run_id)
    with settings.operation_lock():
        settings.freeze()
        output = settings.report / "trade-faults" / args.probe_id
        output.mkdir(parents=True, exist_ok=False)
        token = login(settings, "demo-buyer", "demo-pass-4001")
        rows = []
        try:
            for scenario in ("T06", "T07"):
                for concurrency in (10, 30):
                    folder = output / f"{scenario}-c{concurrency}"
                    folder.mkdir()
                    rows.append(fault_round(settings, token, scenario, concurrency, folder))
                    print(f"{scenario} c{concurrency} passed", flush=True)
        finally:
            save(output, "summary", {"run_id": settings.identity, "completed_rounds": len(rows),
                                    "planned_rounds": 4, "phase": "development, not formal matrix", "rows": rows,
                                    "source_sha256": {str(p): sha256(p) for p in
                                                      (Path(__file__), Path(__file__).parents[1] / "backend_resume_lab.py")}})


if __name__ == "__main__":
    main()
