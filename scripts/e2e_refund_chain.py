#!/usr/bin/env python
"""C05.2c: the whole refund chain, over real RocketMQ and the real MySQL.

What this runs is the core profile's refund path end to end, with no stand-ins anywhere:

* a case is opened through case-service's public API, a proposal is delivered the way the Agent would,
  and a reviewer approves it — all three through their real entry points, over HTTP;
* case-service's dispatch loop consumes the approved authorisation and writes the signed command
  (C05.2a), its outbox hands the bytes to the real broker on ``127.0.0.1:9876``;
* a real ``commerce-service`` consumes it, reserves the money, and its dispatch loop sends the refund to
  the real provider process (the C04.1 stub, started here on its own port and its own SQLite file);
* the settlement writes a signed result (C05.2b-1), the result outbox hands *that* to the broker, and a
  real case-service result listener (C05.2c-1) consumes it and the projection closes the case.

The assertions live in the JUnit system test (``RefundChainSystemTest``) rather than here, because the
interesting facts are cross-service and the test can read both schemas and mint the demo tokens with the
same code the services use. What this script owns is the environment: three processes, the switches that
are off by default, and a report of what happened.

Usage:
    python scripts/e2e_refund_chain.py [--line 7101] [--keep-running]
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The C05.1c driver's plumbing is imported rather than copied: its process handling, MySQL reads and report
# format were each bought with a failure (see tasks/todo.md C05.1c), and a second copy would drift.
sys.path.insert(0, str(HERE))
import e2e_transport_refund as base  # noqa: E402

ROOT = base.ROOT
JAVA_HOME = base.JAVA_HOME
MVNW = base.MVNW
MYSQL_CONTAINER = base.MYSQL_CONTAINER
NAMESRV = base.NAMESRV
COMMERCE_JAR = base.COMMERCE_JAR
CASE_JAR = ROOT / "java" / "case-service" / "target" / "case-service-0.1.0-SNAPSHOT.jar"
PROVIDER_PYTHON = ROOT / "agent" / ".venv" / "Scripts" / "python.exe"

CASE_PORT = 8083
COMMERCE_PORT = 8081
SYSTEM_TEST = "RefundChainSystemTest"

# Line 7001 is not a candidate for a whole-chain run. The live commerce_db holds four orphaned RECEIVED
# operations on it from the C05.1c runs (recorded in the ledger, C05.2c-2b); with the dispatch loop now
# enabled they are swept, refuse to settle and retry for as long as any commerce-service is up. That is
# honest background noise, not this run's subject, so this driver mints a line of its own instead.
DEFAULT_LINE = None


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status == 200 and b'"UP"' in response.read()
    except Exception:
        return False


def reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            response.read()
            return True
    except urllib.error.HTTPError:
        # A 404 is an answer: the process is up and something is listening.
        return True
    except Exception:
        return False


def start(name: str, args: list, env: dict, report: "base.Report", log_dir: Path):
    """Start a long-running process, with its output going to a file rather than a pipe.

    A pipe nobody reads can block the child, and a driver that has to keep reading three processes to stop
    them deadlocking is a driver that will eventually stop reading. The files are the evidence too.
    """
    log = (log_dir / f"{name}.log").open("w", encoding="utf-8", errors="replace")
    report.note(f"{name}: {' '.join(str(a) for a in args)}  (log {log.name})")
    return subprocess.Popen(
        [str(a) for a in args],
        cwd=str(ROOT),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )


def wait_reachable(name: str, url: str, proc, report: "base.Report", timeout: float = 60.0) -> bool:
    """Wait for something to answer, without the /actuator/health contract Spring Boot has."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if reachable(url):
            return True
        if proc.poll() is not None:
            report.note(f"{name} exited early with code {proc.returncode}; see its log")
            return False
        time.sleep(0.5)
    report.note(f"{name} did not answer {url} within {timeout:.0f}s")
    return False


def wait_health(name: str, url: str, proc, report: "base.Report", timeout: float = 180.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if health(url):
            return True
        if proc.poll() is not None:
            report.note(f"{name} exited early with code {proc.returncode}; see its log")
            return False
        time.sleep(0.5)
    report.note(f"{name} did not answer {url} within {timeout:.0f}s")
    return False


def create_demo_line(amount_minor: int, report: "base.Report", slot: bool = True) -> tuple[str, str, str]:
    """Mint this run's own demo order, line and ledger row; return (line_id, merchant, customer).

    Every seeded fixture line already carries an open case from the 2026-09-19 sessions, and opening a second
    case for a line is refused with ``CASE_ALREADY_OPEN`` — correctly. So a chain run has two honest options:
    cancel somebody else's case, or bring its own line. This brings its own. It is also what makes the run
    repeatable: a fresh line_id per run means the next run does not have to reason about this one's leftovers.

    ``slot=False`` mints the line *without* its ``line_refund`` row, which is the state that makes the domain
    refuse a command with ``LINE_NOT_FOUND``. That is not a contrived fixture: it is exactly the failure this
    driver produced by accident in C05.2c-3 (the mint was missing the slot row), and it is the cheapest honest
    way to reach a domain refusal end to end — a real line, a real case, a real command, refused by the real
    acceptance path for a reason the world gives rather than one the test injects.

    The line_id starts with 9 so that a look at the database later can tell a driver-minted line from a seeded
    one. The merchant and customer are the fixture demo pair, so the case-service's order visibility and the
    demo identity agree without any special casing.
    """
    order_id = str(uuid.uuid4())
    line_id = f"9{datetime.now().strftime('%H%M%S')}"
    while base.scalar(f"SELECT COUNT(*) FROM commerce_db.order_line WHERE line_id = '{line_id}'") != "0":
        line_id += "1"
    # The sku and category are copied from a seeded line rather than invented: category is what policy
    # applicability is written against, and a made-up one could silently fall outside every rule.
    sku, category = base.mysql_rows("SELECT sku, category FROM commerce_db.order_line WHERE line_id = '7001'")[0]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    # One transaction for the four rows. A half-minted line is worse than no line: an order that exists with a
    # line that has no slot row is exactly the state that reads as "no order line in this service".
    base.mysql_rows(
        "START TRANSACTION;"
        " INSERT INTO commerce_db.orders (order_id, merchant_id, buyer_id, order_status, currency, paid_at,"
        f" created_at) VALUES ('{order_id}', 'M-1001', 'B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80', 'PAID', 'CNY', '{now}', '{now}');"
        " INSERT INTO commerce_db.order_line (line_id, order_id, merchant_id, buyer_id, sku, category, quantity,"
        " line_paid_amount, currency, paid_at, order_status, version) VALUES"
        f" ('{line_id}', '{order_id}', 'M-1001', 'B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80', '{sku}-DRV-{line_id}', '{category}', 1, {amount_minor},"
        f" 'CNY', '{now}', 'PAID', 1);"
        " INSERT INTO commerce_db.payment_ledger (order_id, paid_amount, refunded_amount, reserved_refund_amount,"
        f" version) VALUES ('{order_id}', {amount_minor}, 0, 0, 1);"
        # The line's refund slot. This is not decoration: RefundMoneyRepository.slotForUpdate reads
        # "FROM line_refund r JOIN order_line l ON l.line_id = r.line_id", so a line that exists in order_line
        # but has no slot row is reported as "no order line ... in this service" — found by running this
        # (C05.2c-3), and worth stating because the message points at the wrong table. updated_at has no
        # default, and live_marker is a generated column, so neither can be supplied: only MySQL decides it.
        # slot=False leaves exactly this row out, on purpose (C05.3b): the refusal test needs a line the
        # acceptance path will refuse, and this is the real one.
        + ("" if not slot else
           " INSERT INTO commerce_db.line_refund (line_id, state, operation_id, version, updated_at)"
           f" VALUES ('{line_id}', 'FREE', NULL, 1, '{now}');")
        + "COMMIT;")
    report.note(f"minted order {order_id} line {line_id} for {amount_minor} minor (sku {sku}-DRV-{line_id},"
                f" category {category}{'' if slot else ', deliberately WITHOUT its line_refund slot row'})")
    return line_id, "M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80"


def java_ports_available(report: base.Report) -> bool:
    for port in (CASE_PORT, COMMERCE_PORT):
        owners = base.pids_on_port(port)
        if owners:
            report.note(f"port {port} is occupied by PID(s) {', '.join(owners)}; leaving them untouched")
            return False
    return True


def stop(proc, port: int) -> None:
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
    # An unrelated listener may have taken the port after our child exited. Observe it, but never kill it.
    if base.pids_on_port(port):
        print(f"[driver] port {port} remains occupied after our child exited; owner left untouched")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--line", default=DEFAULT_LINE,
                        help="refund a specific existing demo line instead of minting one; every seeded line"
                             " already has an open case from the 2026-09-19 sessions, so this is mainly for"
                             " re-running against a line a previous run of this driver minted")
    parser.add_argument("--keep-running", action="store_true",
                        help="leave case-service, commerce-service and the provider running afterwards")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir = ROOT / "reports" / "c052c-chain"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = base.Report(report_dir / f"{stamp}-e2e-refund-chain.txt")

    case_proc = commerce_proc = provider_proc = None
    try:
        report.head("# C05.2c 全链路端到端：建单 → 人工通过 → 命令 → Commerce → provider → 结果事件 → Case 关单")
        report.head(f"run {stamp}  line {args.line}")
        report.section("environment")

        started = time.time()
        mysql_up = base.mysql_rows("SELECT 1") == [["1"]]
        report.step("compose MySQL answers", mysql_up, time.time() - started)
        if not mysql_up:
            report.finish("FAILED: MySQL is not reachable")
            return 1

        started = time.time()
        broker_up = base.tcp_open("127.0.0.1", 9876)
        report.step("RocketMQ name server listens on 9876", broker_up, time.time() - started)
        if not broker_up:
            report.finish("FAILED: no broker; this test is meaningless without one")
            return 1

        if not java_ports_available(report):
            report.finish("FAILED: a Java service port is already in use")
            return 1

        if args.line:
            line, amount, why = base.pick_line(args.line)
            report.step(f"line {line} is usable", line is not None, 0.0, why)
        else:
            # The default: bring this run's own line, because every seeded line already has an open case.
            started = time.time()
            amount = base.scalar(
                "SELECT line_paid_amount FROM commerce_db.order_line WHERE line_id = '7001'")
            line, _merchant, _customer = create_demo_line(int(amount), report)
            report.step(f"minted a fresh line for this run: {line}", True, time.time() - started,
                        f"paid {amount} minor, no case on it and none of the 7001 orphans touch it")
        if line is None:
            report.finish("FAILED: no usable demo line")
            return 1

        # CF3 needs a line of its own as well: it arms a fault for the operation id that line produces, and two
        # tests sharing one line would be two tests sharing one refund slot.
        cf3_line = ""
        if args.line is None:
            cf3_amount = base.scalar("SELECT line_paid_amount FROM commerce_db.order_line WHERE line_id = '7001'")
            cf3_line, _m2, _c2 = create_demo_line(int(cf3_amount), report)
            report.step(f"minted a second line for the CF3 run: {cf3_line}", True, 0.0,
                        f"paid {cf3_amount} minor; the lost-response test must not share a slot with the happy path")

        # And a third for the refusal run (C05.3b): a line the acceptance path will refuse with LINE_NOT_FOUND,
        # so the end-to-end question "does the case hear about a refusal" is asked of the real chain rather than
        # of a test double.
        refused_line = ""
        if args.line is None:
            refused_amount = base.scalar(
                "SELECT line_paid_amount FROM commerce_db.order_line WHERE line_id = '7001'")
            refused_line, _m3, _c3 = create_demo_line(int(refused_amount), report, slot=False)
            report.step(f"minted a third line for the refusal run: {refused_line}", True, 0.0,
                        f"paid {refused_amount} minor, no line_refund slot row: commerce must refuse the command")

        report.section("build")
        started = time.time()
        built = base.run([MVNW, "-f", "java/pom.xml", "-B", "-ntp", "-DskipTests", "-pl",
                          "case-service,commerce-service", "-am", "package"], timeout=1800)
        (report_dir / f"{stamp}-build.txt").write_text(built.stdout + built.stderr, encoding="utf-8",
                                                      errors="replace")
        report.step("mvnw package (skipTests)", built.returncode == 0, time.time() - started,
                    f"log {stamp}-build.txt")
        if built.returncode != 0 or not CASE_JAR.exists() or not COMMERCE_JAR.exists():
            report.finish("FAILED: the jars were not built")
            return 1

        report.section("three processes")
        provider_port = free_port()
        provider_proc = start(
            "provider",
            [PROVIDER_PYTHON, "-m", "uvicorn", "resolveflow.api.app:app", "--host", "127.0.0.1",
             "--port", str(provider_port), "--log-level", "warning"],
            base.child_env(
                RESOLVEFLOW_PROVIDER_DB=str(report_dir / f"{stamp}-provider.sqlite3"),
                # The lab fault surface is on because this is the lab context, and C05.2c's CF3 (a provider
                # that settles but loses the response) is armed through it. It is off in any deployed process.
                RESOLVEFLOW_LAB_ROUTES="1",
                # This process runs the Agent app, so C06.3b's callback delivery worker starts with it. The
                # loop is off in no configuration (an outbox nobody drains is a callback that never
                # arrives), so it must be told where Case is rather than left to guess: the default is the
                # same address, and stating it here means a port change in this script cannot silently
                # leave the worker delivering into nothing.
                RESOLVEFLOW_CASE_BASE_URL=f"http://127.0.0.1:{CASE_PORT}",
            ),
            report, report_dir)

        case_proc = start(
            "case-service",
            [JAVA_HOME / "bin" / "java", "-jar", CASE_JAR,
             f"--resolveflow.commerce.base-url=http://127.0.0.1:{COMMERCE_PORT}",
             "--resolveflow.dispatch.enabled=true",
             "--resolveflow.dispatch.poll-interval-ms=500",
             "--resolveflow.events.namesrv=" + NAMESRV,
             "--resolveflow.events.publisher.enabled=true",
             "--resolveflow.events.outbox.delivery-enabled=true",
             "--resolveflow.events.outbox.poll-interval-ms=300",
             # C05.2c-1: the result listener. This line is the whole point of the run — with it absent the
             # case stays EXECUTING while Commerce has already paid.
             "--resolveflow.events.consumer.enabled=true"],
            base.child_env(), report, report_dir)

        commerce_proc = start(
            "commerce-service",
            [JAVA_HOME / "bin" / "java", "-jar", COMMERCE_JAR,
             f"--resolveflow.provider.base-url=http://127.0.0.1:{provider_port}",
             "--resolveflow.events.namesrv=" + NAMESRV,
             "--resolveflow.events.consumer.enabled=true",
             "--resolveflow.events.publisher.enabled=true",
             "--resolveflow.events.outbox.delivery-enabled=true",
             "--resolveflow.events.outbox.poll-interval-ms=300",
             # C05.2c-2: the two loops that make a reservation become a refund without anybody calling
             # dispatch(id). Without them the operation stays RECEIVED and no result is ever written.
             "--resolveflow.refund.dispatch-enabled=true",
             "--resolveflow.refund.reconcile-enabled=true",
             # Deliberately slow. The CF3 run has to arm a fault for the operation the reservation creates, and
             # with a half-second tick that is a race the test would sometimes lose (the dispatch is the very next
             # tick). Eight seconds makes the window deterministic, and costs the happy path nothing but seconds.
             "--resolveflow.refund.poll-interval-ms=8000"],
            base.child_env(), report, report_dir)

        started = time.time()
        provider_ok = wait_reachable("provider", f"http://127.0.0.1:{provider_port}/health",
                                     provider_proc, report)
        commerce_ok = wait_health("commerce-service", f"http://127.0.0.1:{COMMERCE_PORT}/actuator/health",
                                  commerce_proc, report)
        case_ok = wait_health("case-service", f"http://127.0.0.1:{CASE_PORT}/actuator/health",
                              case_proc, report)
        report.step("the three processes are up", provider_ok and commerce_ok and case_ok,
                    time.time() - started,
                    f"provider={provider_ok} commerce={commerce_ok} case={case_ok}")
        if not (provider_ok and commerce_ok and case_ok):
            report.finish("FAILED: not every process came up")
            return 1

        report.section("the chain")
        report.command(f"mvnw -Dtest={SYSTEM_TEST} with RESOLVEFLOW_E2E_CHAIN=true LINE={line}")
        started = time.time()
        chain = base.run(
            [MVNW, "-f", "java/pom.xml", "-B", "-ntp", "-pl", "case-service", "-am", "test",
             f"-Dtest={SYSTEM_TEST}", "-Dsurefire.failIfNoSpecifiedTests=false"],
            timeout=1200,
            env=base.child_env(
                RESOLVEFLOW_E2E_CHAIN="true",
                RESOLVEFLOW_E2E_LINE=line,
                RESOLVEFLOW_E2E_LINE_UNKNOWN=cf3_line,
                RESOLVEFLOW_E2E_LINE_REFUSED=refused_line,
                RESOLVEFLOW_E2E_PROVIDER_BASE=f"http://127.0.0.1:{provider_port}",
                RESOLVEFLOW_E2E_CASE_BASE=f"http://127.0.0.1:{CASE_PORT}",
                RESOLVEFLOW_E2E_MYSQL_HOST="127.0.0.1",
                RESOLVEFLOW_E2E_MYSQL_ROOT_PASSWORD="root",
            ))
        chain_log = report_dir / f"{stamp}-chain-test.txt"
        chain_log.write_text(chain.stdout + chain.stderr, encoding="utf-8", errors="replace")
        report.step(f"{SYSTEM_TEST} passes", chain.returncode == 0, time.time() - started,
                    f"log {chain_log.name}")

        # What the databases say, so the report stands on its own even if somebody only reads the report.
        case_row = base.mysql_rows(
            "SELECT case_id, status, version FROM case_db.aftersale_case "
            f"WHERE line_id = '{line}' ORDER BY created_at DESC LIMIT 1")
        operation = base.mysql_rows(
            "SELECT operation_id, state, amount_minor, IFNULL(provider_ref, '-') FROM commerce_db.refund_operation "
            f"WHERE line_id = '{line}' ORDER BY reserved_at DESC LIMIT 1")
        ledger = base.mysql_rows(
            "SELECT refunded_amount, reserved_refund_amount FROM commerce_db.payment_ledger WHERE order_id ="
            f" (SELECT order_id FROM commerce_db.order_line WHERE line_id = '{line}')")
        slot = base.mysql_rows(
            f"SELECT state, IFNULL(operation_id, '-') FROM commerce_db.line_refund WHERE line_id = '{line}'")

        report.section("what the databases hold")
        report.note(f"aftersale_case     {case_row}")
        report.note(f"refund_operation   {operation}")
        report.note(f"payment_ledger     {ledger}")
        report.note(f"line_refund        {slot}")

        if case_row:
            case_id = case_row[0][0]
            inbox = base.mysql_rows(
                "SELECT disposition, IFNULL(detail, '-'), deliveries, IFNULL(projected_at, 'NULL'), state,"
                " amount_minor FROM case_db.case_result_inbox "
                f"WHERE case_id = '{case_id}'")
            timeline = base.mysql_rows(
                "SELECT kind, COUNT(*) FROM case_db.case_timeline "
                f"WHERE case_id = '{case_id}' GROUP BY kind ORDER BY kind")
            command = base.mysql_rows(
                "SELECT COUNT(*) FROM case_db.case_execution_command "
                f"WHERE case_id = '{case_id}'")
            report.note(f"case_result_inbox  {inbox}")
            report.note(f"case_timeline      {timeline}")
            report.note(f"execution_command  {command}")
            report.check("the case is closed", case_row[0][1], "CLOSED_SUCCESS", case_row[0][1] == "CLOSED_SUCCESS")
        if operation:
            report.check("the provider settled it", operation[0][1], "SUCCEEDED", operation[0][1] == "SUCCEEDED")
            report.check("the refunded amount is the line's", operation[0][2], amount, operation[0][2] == amount)
        if ledger:
            report.check("nothing is left reserved", ledger[0][1], "0", ledger[0][1] == "0")
            report.check("the ledger holds exactly one refund", ledger[0][0], amount, ledger[0][0] == amount)
        if slot:
            report.check("the line can never be refunded again", slot[0][0], "CONSUMED", slot[0][0] == "CONSUMED")

        report.section("CF3: the line whose answer was lost")
        if cf3_line:
            cf3_case = base.mysql_rows(
                "SELECT case_id, status FROM case_db.aftersale_case "
                f"WHERE line_id = '{cf3_line}' ORDER BY created_at DESC LIMIT 1")
            cf3_operation = base.mysql_rows(
                "SELECT operation_id, state, IFNULL(provider_ref, '-') FROM commerce_db.refund_operation "
                f"WHERE line_id = '{cf3_line}' ORDER BY reserved_at DESC LIMIT 1")
            cf3_ledger = base.mysql_rows(
                "SELECT refunded_amount, reserved_refund_amount FROM commerce_db.payment_ledger WHERE order_id ="
                f" (SELECT order_id FROM commerce_db.order_line WHERE line_id = '{cf3_line}')")
            cf3_slot = base.mysql_rows(
                f"SELECT state, IFNULL(operation_id, '-') FROM commerce_db.line_refund WHERE line_id = '{cf3_line}'")
            cf3_inbox = base.mysql_rows(
                "SELECT event_type, state, disposition, IFNULL(detail, '-'), deliveries"
                " FROM case_db.case_result_inbox WHERE operation_id = (SELECT operation_id FROM"
                f" commerce_db.refund_operation WHERE line_id = '{cf3_line}' ORDER BY reserved_at DESC LIMIT 1)")
            report.note(f"case_result_inbox  {cf3_inbox}  (two facts: the unknown, then the recovered success)")
            report.note(f"aftersale_case     {cf3_case}")
            report.note(f"refund_operation   {cf3_operation}")
            report.note(f"payment_ledger     {cf3_ledger}")
            report.note(f"line_refund        {cf3_slot}")
            if cf3_case:
                report.check("the CF3 case is closed too", cf3_case[0][1], "CLOSED_SUCCESS",
                             cf3_case[0][1] == "CLOSED_SUCCESS")
            if cf3_ledger:
                report.check("the CF3 reservation became the refund", cf3_ledger[0][0], str(cf3_amount),
                             cf3_ledger[0][0] == str(cf3_amount))
                report.check("and is no longer reserved", cf3_ledger[0][1], "0", cf3_ledger[0][1] == "0")
            if cf3_operation:
                report.check("the lost answer was reconciled, not re-sent", cf3_operation[0][1], "SUCCEEDED",
                             cf3_operation[0][1] == "SUCCEEDED")

            # The provider's own file, which is the only place that can say how many times it was asked. Read
            # with the provider still running: SQLite in WAL mode allows a reader, and this is evidence rather
            # than an assertion, so a failure to read is reported instead of failing the run.
            provider_db = report_dir / f"{stamp}-provider.sqlite3"
            try:
                import sqlite3
                with sqlite3.connect(str(provider_db)) as provider:
                    for row in provider.execute(
                            "SELECT r.operation_id, r.state, IFNULL(r.provider_ref, '-'),"
                            " (SELECT COUNT(*) FROM request_attempt a WHERE a.operation_id = r.operation_id)"
                            " FROM refund_request r ORDER BY requested_at"):
                        report.note(f"provider sqlite    operation={row[0]} state={row[1]} ref={row[2]}"
                                    f" attempts={row[3]}")
            except Exception as unreadable:  # noqa: BLE001 - evidence, not a gate
                report.note(f"could not read the provider sqlite file: {unreadable}")

        report.section("refusal: the command commerce would not accept (C05.3b)")
        if refused_line:
            refused_case = base.mysql_rows(
                "SELECT case_id, status FROM case_db.aftersale_case "
                f"WHERE line_id = '{refused_line}' ORDER BY created_at DESC LIMIT 1")
            # case_execution_command has no line_id column — it is keyed by case, which is also the honest way to
            # ask: "did THIS case send a command" rather than "did some case for this line". Each of these is a
            # subquery on the case's own command, so nothing here can silently answer about a different case.
            refused_case_id = refused_case[0][0] if refused_case else ""
            command_sql = (
                "SELECT operation_id FROM case_db.case_execution_command"
                f" WHERE case_id = '{refused_case_id}' ORDER BY created_at DESC LIMIT 1")
            refused_command = base.mysql_rows(command_sql) if refused_case_id else []
            refused_answer = base.mysql_rows(
                "SELECT event_type, status, JSON_UNQUOTE(JSON_EXTRACT(envelope, '$.payload.reason_code')),"
                " JSON_UNQUOTE(JSON_EXTRACT(envelope, '$.payload.state'))"
                " FROM commerce_db.event_outbox WHERE event_type = 'RefundFailed' AND"
                f" JSON_UNQUOTE(JSON_EXTRACT(envelope, '$.payload.operation_id')) = ({command_sql})"
            ) if refused_case_id else []
            refused_inbox = base.mysql_rows(
                "SELECT event_type, state, disposition, IFNULL(detail, '-'), deliveries"
                f" FROM case_db.case_result_inbox WHERE operation_id = ({command_sql})"
            ) if refused_case_id else []
            refused_operations = base.mysql_rows(
                f"SELECT COUNT(*) FROM commerce_db.refund_operation WHERE line_id = '{refused_line}'")
            refused_closed = base.mysql_rows(
                "SELECT COUNT(*) FROM case_db.case_timeline"
                f" WHERE case_id = '{refused_case_id}' AND kind = 'CASE_CLOSED'") if refused_case_id else []
            report.note(f"case_execution_command {refused_command}   (the case did send a command)")
            report.note(f"event_outbox (answer)    {refused_answer}   (commerce's answer, signed)")
            report.note(f"case_result_inbox        {refused_inbox}")
            report.note(f"aftersale_case           {refused_case}")
            report.note(f"refund_operation count   {refused_operations}   (a refusal reserves nothing)")
            report.note(f"CASE_CLOSED count        {refused_closed}")
            if refused_case:
                report.check("the refused case went back to a person", refused_case[0][1], "PENDING_REVIEW",
                             refused_case[0][1] == "PENDING_REVIEW")
            if refused_answer:
                report.check("commerce answered the refusal", refused_answer[0][2], "LINE_NOT_FOUND",
                             refused_answer[0][2] == "LINE_NOT_FOUND")
            if refused_inbox:
                report.check("the case recorded the refusal as a fact", refused_inbox[0][0], "RefundFailed",
                             refused_inbox[0][0] == "RefundFailed")
            if refused_operations:
                report.check("no operation was opened for a refused command", refused_operations[0][0], "0",
                             refused_operations[0][0] == "0")
            if refused_closed:
                report.check("and nothing was closed", refused_closed[0][0], "0", refused_closed[0][0] == "0")

        report.section("background noise this run did not cause")
        orphans = base.mysql_rows(
            "SELECT state, COUNT(*) FROM commerce_db.refund_operation "
            "WHERE line_id = '7001' AND case_id NOT IN (SELECT case_id FROM case_db.aftersale_case)"
            " GROUP BY state ORDER BY state")
        report.note(f"operations left on line 7001 by earlier driver runs, by state: {orphans}")
        report.note("with the dispatch loop enabled these are swept on the first tick. The ones whose line is held"
                    " by a different operation refuse to settle and stay IN_PROGRESS forever — the gap the ledger"
                    " records. The one that really did hold line 7001's slot settles: that is a reservation from"
                    " C05.1c that had been stuck since, and this loop finishing it is money actually moving, not"
                    " noise. Neither is caused by this run.")

        report.finish("PASSED" if not report.failures else "FAILED: " + "; ".join(report.failures))
        return 0 if not report.failures else 1
    except Exception as unexpected:  # noqa: BLE001 - a driver must report its own failure too
        import traceback
        report.note("the driver itself failed:\n" + traceback.format_exc())
        report.finish(f"FAILED: {unexpected}")
        return 1
    finally:
        if args.keep_running:
            report.note("--keep-running: leaving the three processes up")
        else:
            stop(case_proc, CASE_PORT)
            stop(commerce_proc, COMMERCE_PORT)
            if provider_proc is not None and provider_proc.poll() is None:
                provider_proc.terminate()
                try:
                    provider_proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    provider_proc.kill()


if __name__ == "__main__":
    sys.exit(main())
