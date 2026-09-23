#!/usr/bin/env python
"""C05.1c: the refund command over the real RocketMQ and the real MySQL.

What this runs is the core profile's refund path with no stand-ins on either side of the broker:

* the command is written by case-service's own outbox writer and signed with its own key
  (``EventOutbox.writeRefundCommand``);
* it leaves through the real RocketMQ client to the compose broker on ``127.0.0.1:9876``;
* a real ``commerce-service`` process consumes it and reserves the money in the real
  ``commerce_db`` — through C04.2's acceptance path, not a reimplementation.

The two things a broker makes possible and a fake publisher cannot show are then driven on purpose:
the same bytes delivered a second time, and a document whose signature no longer matches it. The first
must leave exactly one reservation; the second must be refused, filed, and move no money.

The writer half runs as a JUnit system test (``CoreEventTransportSystemTest``) rather than over HTTP,
because the only thing that decides *what* to send is an approved authorisation and that writer is C05.2.
Everything after the write is the real thing: the row, the loop, the publisher, the broker, the consumer.

Usage:
    python scripts/e2e_transport_refund.py [--line 7001] [--amount-minor 2599] [--keep-running]
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAVA_HOME = Path(r"C:\Users\hjn\.jdks\jdk-21.0.12.1+1")
MVNW = ROOT / "java" / "mvnw.cmd"
COMPOSE = ROOT / "infra" / "compose.yaml"
COMMERCE_JAR = ROOT / "java" / "commerce-service" / "target" / "commerce-service-0.1.0-SNAPSHOT.jar"
MYSQL_CONTAINER = "resolveflow-mysql-1"
COMMERCE_PORT = 8081
NAMESRV = "127.0.0.1:9876"
HEALTH = f"http://127.0.0.1:{COMMERCE_PORT}/actuator/health"
CONSUMER = "commerce-refund-command"
SYSTEM_TEST = "CoreEventTransportSystemTest"


# --------------------------------------------------------------------------- process plumbing


def child_env(**extra: str) -> dict:
    env = dict(os.environ)
    env["JAVA_HOME"] = str(JAVA_HOME)
    env["PATH"] = f"{JAVA_HOME / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env.update({key: str(value) for key, value in extra.items()})
    return env


def run(args, timeout=900, env=None, cwd=ROOT):
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=str(cwd),
        env=env or child_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def mysql_rows(statement: str) -> list[list[str]]:
    proc = subprocess.run(
        ["docker", "exec", MYSQL_CONTAINER, "mysql", "-uroot", "-proot", "-N", "-B", "-e", statement],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"mysql refused the statement: {proc.stderr.strip()}")
    return [line.split("\t") for line in proc.stdout.splitlines() if line.strip()]


def scalar(statement: str) -> str | None:
    rows = mysql_rows(statement)
    return rows[0][0] if rows and rows[0] else None


def tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def pids_on_port(port: int) -> list[str]:
    proc = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, errors="replace")
    pids: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            if parts[1].endswith(f":{port}") and parts[4] not in pids:
                pids.append(parts[4])
    return pids


def kill_port(port: int) -> list[str]:
    """Free a port by what is actually listening on it (C03.3b lesson), not by job bookkeeping."""
    killed = []
    for pid in pids_on_port(port):
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, text=True, errors="replace")
        killed.append(pid)
    return killed


def health_ok() -> bool:
    try:
        with urllib.request.urlopen(HEALTH, timeout=3) as response:
            return response.status == 200 and b'"UP"' in response.read()
    except Exception:
        return False


LINE_CANDIDATES = ["7001", "7002", "7101", "7201"]


def pick_line(preferred: str | None) -> tuple[str | None, str, str]:
    """Choose a demo line this run can ask for, and the amount that line was paid.

    The one thing that disqualifies a line here is a **stale command still pending**, which is a real hazard
    found by running this (C05.1c): a run that fails after writing its outbox row leaves a row that is delivered
    later, wins the line's single refund slot first, and makes every delivery of the next run's command be
    refused as "line held by operation ...". That is at-least-once durability doing its job on a row nobody
    meant to keep, so the e2e aims at a line nothing undelivered is pointed at.

    A line whose slot or whose order's ledger was left used by an earlier run is not disqualified: the driver
    resets exactly that, the same reset the module tests do in {@code @BeforeEach}.

    The amount comes back with the line for a third reason, learned the same way: a command must carry the
    <b>line's</b> own paid amount, which is not the order's. One order can hold several lines and its ledger
    totals them, so line 7001 is paid 2599 inside an order paid 4598 — a command carrying 4598, or 7101's 1299
    for that matter, is refused by the domain (correctly). Hardcoding any of the three was the bug.

    Returns (line, amount_minor, why) where a None line means no candidate is usable.
    """
    candidates = [preferred] if preferred else LINE_CANDIDATES
    rejected = []
    for line in candidates:
        slot = mysql_rows(
            "SELECT COALESCE(r.state, 'FREE'), p.refunded_amount, p.reserved_refund_amount, "
            "l.line_paid_amount, p.paid_amount "
            "FROM commerce_db.order_line l "
            "JOIN commerce_db.payment_ledger p ON p.order_id = l.order_id "
            "LEFT JOIN commerce_db.line_refund r ON r.line_id = l.line_id "
            f"WHERE l.line_id = '{line}'"
        )
        if not slot:
            rejected.append(f"{line}: no such demo line")
            continue
        state, refunded, reserved, line_paid, order_paid = slot[0]
        pending = scalar(
            "SELECT COUNT(*) FROM case_db.event_outbox "
            f"WHERE status <> 'PUBLISHED' AND envelope LIKE '%\"line_id\":\"{line}\"%'"
        )
        if pending != "0":
            rejected.append(f"{line}: {pending} undelivered command(s) still target it")
            continue
        note = (f"{line} is paid {line_paid} (its order {order_paid}), no undelivered command targets it"
                f" (before: slot {state}, order ledger refunded {refunded} reserved {reserved})")
        if rejected:
            note += " (skipped: " + "; ".join(rejected) + ")"
        return line, line_paid, note
    return None, "", "; ".join(rejected)


# --------------------------------------------------------------------------- reporting


class Report:
    """The report the ledger cites, written as the run goes rather than reconstructed afterwards."""

    def __init__(self, path: Path):
        self.path = path
        self.lines: list[str] = []
        self.failures: list[str] = []
        self.started = time.time()

    def head(self, text: str) -> None:
        self.lines.append(text)

    def section(self, text: str) -> None:
        self.lines.append(f"\n== {text}")

    def command(self, text: str) -> None:
        self.lines.append(f"     $ {text}")

    def step(self, name: str, ok: bool, seconds: float, detail: str = "") -> None:
        mark = "PASS" if ok else "FAIL"
        suffix = f"  {detail}" if detail else ""
        self.lines.append(f"  -- {name}\n     {mark} ({seconds:.1f}s){suffix}")
        if not ok:
            self.failures.append(name)

    def note(self, text: str) -> None:
        self.lines.append(f"     {text}")

    def check(self, label: str, observed: str, expected: str, ok: bool) -> None:
        mark = "PASS" if ok else "FAIL"
        self.lines.append(f"  -- {label}\n     {mark}  observed={observed}  expected={expected}")
        if not ok:
            self.failures.append(label)

    def finish(self, verdict: str) -> None:
        self.lines.append("")
        self.lines.append(f"RESULT: {verdict} ({time.time() - self.started:.1f}s)")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        print("\n".join(self.lines))


# --------------------------------------------------------------------------- the run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--line", default=None,
                        help="demo line to refund; by default the first one that is free and that no "
                             "undelivered command still targets")
    parser.add_argument("--amount-minor", default=None,
                        help="override the line's paid amount; by default the chosen line's own amount is used, "
                             "because a command carrying another line's amount is refused by the domain")
    parser.add_argument("--merchant", default="M-1001")
    parser.add_argument("--keep-running", action="store_true", help="leave commerce-service up for inspection")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "reports" / "c051c-transport"
    report = Report(out_dir / f"{stamp}-e2e-c051c.txt")
    commerce_log = out_dir / f"{stamp}-commerce-service.log"
    test_log = out_dir / f"{stamp}-case-service-test.log"

    report.head("ResolveFlow C05.1c — refund command over the real broker")
    report.head(f"  date    : {datetime.now().isoformat(timespec='seconds')}")
    report.head("  profile : core (real RocketMQ + real MySQL; no mocks, no Testcontainers)")
    requested_line = args.line or "chosen below"
    requested_amount = args.amount_minor or "the line's"
    report.head(f"  line    : {requested_line}   amount_minor: {requested_amount}   merchant: {args.merchant}")

    commerce_proc = None
    log_handle = None
    try:
        # ------------------------------------------------------------------ infra
        report.section("infra")
        started = time.time()
        states = run(["docker", "compose", "-f", COMPOSE, "ps", "--format", "{{.Name}}|{{.Status}}"], timeout=120)
        containers = {}
        for line in states.stdout.splitlines():
            if "|" in line:
                name, status = line.split("|", 1)
                containers[name.strip()] = status.strip()
        for name in sorted(containers):
            report.note(f"{name}: {containers[name]}")
        needed = ["resolveflow-mysql-1", "resolveflow-rocketmq-namesrv-1", "resolveflow-rocketmq-broker-1"]
        missing = [name for name in needed if name not in containers or "Up" not in containers[name]]
        report.step("infra-containers", not missing, time.time() - started,
                    "" if not missing else f"not up: {', '.join(missing)}")
        if missing:
            report.note("start them with: docker compose -f infra/compose.yaml up -d")
            raise SystemExit(report.finish("FAILED: infrastructure") or 1)

        started = time.time()
        broker_open = tcp_open("127.0.0.1", 9876)
        report.command(f"tcp 127.0.0.1:9876 -> {'open' if broker_open else 'closed'}")
        report.step("namesrv-reachable", broker_open, time.time() - started)

        # A second consumer in the same group would load-balance with the one this script starts, and half the
        # messages would go to a process nobody is watching. So the port is freed first, by port.
        started = time.time()
        squatters = pids_on_port(COMMERCE_PORT)
        if squatters:
            killed = kill_port(COMMERCE_PORT)
            report.note(f"freed port {COMMERCE_PORT} from pid(s) {', '.join(killed)}")
        free = not pids_on_port(COMMERCE_PORT)
        report.step("commerce-port-free", free, time.time() - started, f"{COMMERCE_PORT} -> {'free' if free else 'IN USE'}")

        # ------------------------------------------------------------------ build and start the consumer
        report.section("commerce-service (the consumer)")
        started = time.time()
        build = run(["cmd", "/c", str(MVNW), "-f", "java/pom.xml", "-B", "-ntp", "-DskipTests", "-pl", "commerce-service", "-am", "package"], timeout=1200)
        built = "BUILD SUCCESS" in build.stdout
        report.command("java\\mvnw.cmd -f java/pom.xml -B -ntp -DskipTests -pl commerce-service -am package")
        report.step("build-commerce-service", built, time.time() - started, "" if built else build.stdout[-400:])
        if not built or not COMMERCE_JAR.exists():
            raise SystemExit(report.finish("FAILED: the commerce-service jar was not built") or 1)

        started = time.time()
        out_dir.mkdir(parents=True, exist_ok=True)
        commerce_log.parent.mkdir(parents=True, exist_ok=True)
        log_handle = commerce_log.open("w", encoding="utf-8")
        commerce_proc = subprocess.Popen(
            [
                str(JAVA_HOME / "bin" / "java.exe"),
                "-jar",
                str(COMMERCE_JAR),
                f"--server.port={COMMERCE_PORT}",
                "--resolveflow.events.consumer.enabled=true",
                f"--resolveflow.events.namesrv={NAMESRV}",
            ],
            cwd=str(ROOT),
            env=child_env(),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        report.command(
            f"java -jar commerce-service.jar --server.port={COMMERCE_PORT} "
            "--resolveflow.events.consumer.enabled=true --resolveflow.events.namesrv=127.0.0.1:9876"
        )
        report.note(f"log: {commerce_log.relative_to(ROOT)}")
        healthy = False
        deadline = time.time() + 150
        while time.time() < deadline:
            if commerce_proc.poll() is not None:
                break
            if health_ok():
                healthy = True
                break
            time.sleep(1)
        report.step("commerce-service-healthy", healthy, time.time() - started, f"GET {HEALTH}")
        if not healthy:
            tail = "\n".join(commerce_log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:])
            report.note("last log lines:\n" + tail)
            raise SystemExit(report.finish("FAILED: commerce-service did not become healthy") or 1)

        # ------------------------------------------------------------------ the demo line's starting point
        report.section("the demo line before the command")
        started = time.time()
        line, paid, why = pick_line(args.line)
        report.note(why)
        if line is None:
            report.step("demo-line-ready", False, time.time() - started)
            report.note("nothing to run against: a line whose slot is free and which no undelivered command "
                        "targets. Check case_db.event_outbox for rows still PENDING.")
            raise SystemExit(report.finish("FAILED: no usable demo line") or 1)
        args.line = line
        args.amount_minor = args.amount_minor or paid
        if args.amount_minor != paid:
            report.note(f"amount_minor {args.amount_minor} overrides the line's paid amount {paid}: the domain "
                        "will refuse this command (AMOUNT_MISMATCH), which is a legitimate thing to test but is "
                        "not what a passing run looks like")
        before = mysql_rows(
            "SELECT r.state, IFNULL(r.operation_id, '-'), p.refunded_amount, p.reserved_refund_amount "
            "FROM commerce_db.order_line l "
            "JOIN commerce_db.payment_ledger p ON p.order_id = l.order_id "
            "LEFT JOIN commerce_db.line_refund r ON r.line_id = l.line_id "
            f"WHERE l.line_id = '{line}'"
        )
        report.note(f"line {line}: state/operation/refunded/reserved = {before[0] if before else 'no row'}")
        dirty = bool(before) and (before[0][0] != "FREE" or before[0][2:] != ["0", "0"])
        if dirty:
            # A one-refund-per-line system refuses a second run by design, and the ledger is per order, so a
            # line can be unusable because its sibling line was refunded. A repeat run has to put the demo line
            # back the way the module tests' @BeforeEach does. Scoped to this line and its order's ledger; the
            # run's own evidence (outbox, inbox, refusals, operations) is never touched.
            mysql_rows(
                f"UPDATE commerce_db.line_refund SET state = 'FREE', operation_id = NULL, version = 1 "
                f"WHERE line_id = '{line}'"
            )
            mysql_rows(
                "UPDATE commerce_db.payment_ledger SET refunded_amount = 0, reserved_refund_amount = 0, version = 1 "
                "WHERE order_id = (SELECT order_id FROM commerce_db.order_line "
                f"WHERE line_id = '{line}')"
            )
            report.note("the line, or its order's ledger, was left used by an earlier run, so it was reset "
                        "first: this line and this order only, the same reset the module tests do in @BeforeEach")
        report.step("demo-line-ready", True, time.time() - started)

        # ------------------------------------------------------------------ write, publish, duplicate, poison
        report.section("case-service (the writer, the outbox, the publisher)")
        operation_id = str(uuid.uuid4())
        case_id = str(uuid.uuid4())
        authorization_id = str(uuid.uuid4())
        poison_event_id = str(uuid.uuid4())
        started = time.time()
        test = run(
            ["cmd", "/c", str(MVNW), "-f", "java/pom.xml", "-B", "-ntp", "-pl", "case-service", "-am",
             f"-Dtest={SYSTEM_TEST}", "-Dsurefire.failIfNoSpecifiedTests=false", "test"],
            timeout=1800,
            env=child_env(
                RESOLVEFLOW_E2E_BROKER="true",
                RESOLVEFLOW_E2E_OPERATION_ID=operation_id,
                RESOLVEFLOW_E2E_CASE_ID=case_id,
                RESOLVEFLOW_E2E_AUTHORIZATION_ID=authorization_id,
                RESOLVEFLOW_E2E_POISON_EVENT_ID=poison_event_id,
                RESOLVEFLOW_E2E_LINE_ID=args.line,
                RESOLVEFLOW_E2E_MERCHANT=args.merchant,
                RESOLVEFLOW_E2E_AMOUNT_MINOR=args.amount_minor,
            ),
        )
        test_log.write_text(test.stdout + "\n" + test.stderr, encoding="utf-8")
        report.command(f"java\\mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am -Dtest={SYSTEM_TEST} test")
        report.note(f"log: {test_log.relative_to(ROOT)}")
        ran_one = "Tests run: 1, Failures: 0, Errors: 0" in test.stdout
        report.step("case-service-system-test", "BUILD SUCCESS" in test.stdout and ran_one, time.time() - started)
        if not ran_one:
            report.note("the -am reactor build is what puts the current shared-kernel on the test classpath; "
                        "a module-only run resolves whatever was last installed into ~/.m2 (found the hard way: "
                        "ClassNotFoundException com.resolveflow.shared.security.JwtCodec)")
        if "BUILD SUCCESS" not in test.stdout:
            report.note("last test lines:\n" + "\n".join(test.stdout.splitlines()[-20:]))
            raise SystemExit(report.finish("FAILED: the case-service system test did not pass") or 1)

        rows = mysql_rows(
            "SELECT event_id, status, attempts, IFNULL(last_error, '-') FROM case_db.event_outbox "
            f"WHERE envelope LIKE '%{operation_id}%'"
        )
        if len(rows) != 1:
            raise SystemExit(report.finish(f"FAILED: expected one outbox row for {operation_id}, found {len(rows)}") or 1)
        event_id, status, attempts, last_error = rows[0]
        report.note(f"event_id={event_id} operation_id={operation_id} poison_event_id={poison_event_id}")

        # ------------------------------------------------------------------ the consumer catches up
        report.section("the command crossing the broker")
        started = time.time()
        inbox_count = "0"
        deadline = time.time() + 180
        while time.time() < deadline:
            inbox_count = scalar(
                "SELECT COUNT(*) FROM commerce_db.event_inbox "
                f"WHERE consumer = '{CONSUMER}' AND event_id = '{event_id}'"
            ) or "0"
            if inbox_count != "0":
                break
            time.sleep(0.5)
        crossed = inbox_count == "1"
        report.step("consume-delivered", crossed, time.time() - started, f"inbox rows for the event: {inbox_count}")
        if not crossed:
            # The two ways this used to fail are worth naming in the report, because neither is a transport bug:
            # a stale command winning the line first, and the topic's route being discovered late.
            report.note("the line is held by: " + " / ".join(
                mysql_rows(f"SELECT state, IFNULL(operation_id, '-') FROM commerce_db.line_refund WHERE line_id = '{args.line}'")[0]))
            report.note("refusals filed for this event: " + (scalar(
                f"SELECT COUNT(*) FROM commerce_db.event_rejection WHERE event_id = '{event_id}'") or "0"))
            raise SystemExit(report.finish("FAILED: commerce-service never filed the event") or 1)

        # The duplicate and the poison were published by the test in the same pass. Rather than sleep and hope,
        # this waits for what they are supposed to leave behind: the duplicate marks the inbox row (the claim's
        # duplicate branch writes that marker) and the poison must be in the rejection log. A timer would let
        # "has not arrived yet" pass for "changed nothing", which is the difference between evidence and a guess.
        started = time.time()
        duplicate_marker = "0"
        poison_filed = "0"
        deadline = time.time() + 120
        while time.time() < deadline:
            duplicate_marker = scalar(
                "SELECT COUNT(*) FROM commerce_db.event_inbox "
                f"WHERE event_id = '{event_id}' AND detail = 'duplicate delivery ignored'"
            ) or "0"
            poison_filed = scalar(
                f"SELECT COUNT(*) FROM commerce_db.event_rejection WHERE event_id = '{poison_event_id}'"
            ) or "0"
            if duplicate_marker == "1" and poison_filed != "0":
                break
            time.sleep(0.5)
        report.step("duplicate-and-poison-consumed", duplicate_marker == "1" and poison_filed != "0",
                    time.time() - started, f"duplicate_marker={duplicate_marker} poison_rejections={poison_filed}")

        # ------------------------------------------------------------------ what the world looks like now
        report.section("checks")
        line = mysql_rows(
            f"SELECT state, IFNULL(operation_id, '-'), version FROM commerce_db.line_refund WHERE line_id = '{args.line}'"
        )[0]
        ledger = mysql_rows(
            "SELECT refunded_amount, reserved_refund_amount, version FROM commerce_db.payment_ledger "
            f"WHERE order_id = (SELECT order_id FROM commerce_db.order_line WHERE line_id = '{args.line}')"
        )[0]
        operations = scalar(f"SELECT COUNT(*) FROM commerce_db.refund_operation WHERE operation_id = '{operation_id}'")
        inbox = mysql_rows(
            f"SELECT COUNT(*), MAX(disposition), MAX(IFNULL(detail, '-')) FROM commerce_db.event_inbox "
            f"WHERE event_id = '{event_id}'"
        )[0]
        poison_inbox = scalar(f"SELECT COUNT(*) FROM commerce_db.event_inbox WHERE event_id = '{poison_event_id}'")
        rejections = mysql_rows(
            f"SELECT COUNT(*), MAX(reason), MAX(detail) FROM commerce_db.event_rejection WHERE event_id = '{poison_event_id}'"
        )[0]

        report.command("SELECT ... FROM case_db.event_outbox / commerce_db.line_refund / payment_ledger / event_inbox / event_rejection")
        report.check("outbox-published-twice-over-the-broker", f"{status}/{attempts}/{last_error}", "PUBLISHED/2/-",
                     status == "PUBLISHED" and attempts == "2" and last_error == "-")
        report.check("slot-reserved-once", "/".join(line), f"RESERVED/{operation_id}/2", line[0] == "RESERVED" and line[1] == operation_id and line[2] == "2")
        report.check("ledger-reserved", "/".join(ledger), f"0/{args.amount_minor}/2", ledger[0] == "0" and ledger[1] == args.amount_minor and ledger[2] == "2")
        report.check("one-refund-operation", operations or "-", "1", operations == "1")
        report.check("one-inbox-row-for-the-event", "/".join(inbox), "1/ACCEPTED/duplicate delivery ignored",
                     inbox[0] == "1" and inbox[1] == "ACCEPTED" and inbox[2] == "duplicate delivery ignored")
        report.check("duplicate-added-nothing", f"inbox={inbox[0]} operations={operations} reserved={ledger[1]}",
                     "inbox=1 operations=1 reserved=" + args.amount_minor,
                     inbox[0] == "1" and operations == "1" and ledger[1] == args.amount_minor)
        report.check("poison-refused-and-filed", f"{rejections[0]}/{rejections[1]}", ">=1/BAD_SIGNATURE",
                     int(rejections[0] or 0) >= 1 and rejections[1] == "BAD_SIGNATURE")
        report.check("poison-moved-no-money", f"poison_inbox={poison_inbox} reserved={ledger[1]}",
                     f"poison_inbox=0 reserved={args.amount_minor}",
                     poison_inbox == "0" and ledger[1] == args.amount_minor)
        report.note("rejection detail: " + (rejections[2] or "-")[:160])
        # The consumer's own log is evidence as well. With three copies of one event in the topic at once, the
        # earlier exception-driven claim deadlocked (three times) and the transport answered by redelivering a
        # duplicate eighteen times; the claim is an upsert now, so a deadlock here would mean the fix is not
        # doing its job. Redeliveries are only reported: a transient failure that gets retried is the design.
        consumer_log = commerce_log.read_text(encoding="utf-8", errors="replace")
        deadlocks = consumer_log.count("Deadlock found when trying to get lock")
        redeliveries = consumer_log.count("asking for redelivery")
        report.check("no-claim-deadlocks", f"deadlocks={deadlocks} redeliveries={redeliveries}", "deadlocks=0",
                     deadlocks == 0)
        report.note("CF1 (docs/evaluation.md:34, send happened but PUBLISHED was not recorded): attempts=2 is the "
                    "loop handing the identical bytes to the broker a second time")
        report.note("CF2 (docs/evaluation.md:35, redelivery after a lost acknowledgement): one inbox row, one "
                    "refund_operation, reserved unchanged — the duplicate reached the consumer and changed "
                    "nothing; the row's detail is the claim's own note that it did arrive")
        report.note("CF3 (provider succeeded but its response was lost) is C04.3's path, not the transport's")

        report.section("evidence")
        published_at = scalar(f"SELECT IFNULL(published_at, '-') FROM case_db.event_outbox WHERE event_id = '{event_id}'")
        report.note(f"case_db.event_outbox  event_id={event_id} status={status} attempts={attempts} published_at={published_at}")
        report.note(f"commerce_db.event_inbox  consumer={CONSUMER} event_id={event_id} count={inbox[0]} disposition={inbox[1]}")
        report.note(f"commerce_db.line_refund  line={args.line} state={line[0]} operation={line[1]} version={line[2]}")
        report.note(f"commerce_db.payment_ledger  refunded={ledger[0]} reserved={ledger[1]} version={ledger[2]}")
        report.note(f"commerce_db.event_rejection  event_id={poison_event_id} count={rejections[0]} reason={rejections[1]}")

        verdict = "PASSED" if not report.failures else "FAILED: " + ", ".join(report.failures)
        report.finish(verdict)
        return 0 if not report.failures else 1
    except SystemExit:
        raise
    except Exception as unexpected:  # a driver bug must still leave a report behind
        import traceback

        report.note("the driver itself failed:\n" + traceback.format_exc())
        report.finish(f"FAILED: {unexpected}")
        return 1
    finally:
        if log_handle is not None:
            log_handle.close()
        if commerce_proc is not None and not args.keep_running:
            commerce_proc.terminate()
            try:
                commerce_proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                commerce_proc.kill()
            # The port is the evidence that it is really gone (C03.3b lesson), not the exit of the process
            # this script happens to hold a handle on.
            if pids_on_port(COMMERCE_PORT):
                kill_port(COMMERCE_PORT)
        print(f"[driver] port {COMMERCE_PORT} -> {'free' if not pids_on_port(COMMERCE_PORT) else 'IN USE'}")


if __name__ == "__main__":
    sys.exit(main())