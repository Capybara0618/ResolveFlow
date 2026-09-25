#!/usr/bin/env python
"""C06.4⑤: the Harness drives the five tools against **running Java**, not a stub.

This is the step C06.4 was missing. Everything before it proved the tool *boundary* — a real MCP server, a real
handshake, a real `tools/call` — against `tests/integration/stub_upstream.py`. The tools were reached the way a
deployment reaches them, and every byte they read came from a stub that answers whatever it is told to. That is
exactly the shape of thing that hides a broken read: a stub answers a route nobody serves, and a route the tool
reads with the wrong member name, and both look like a working tool.

It already did hide two:

* `GET /internal/v1/cases/{case_id}/evidence` was declared by the contract and **implemented nowhere** — the
  same gap C06.2c found for `refund-status`. `get_case_evidence` could never have worked against Case.
* `get_policy_manifest` read a top-level `version`/`bundle_version`, while Case answers the contract's
  `PolicyManifestResponse` — `bundles[0].manifest_hash`. The stub answered `version`, so tool and stub agreed
  with each other and disagreed with the service, and against the real Case every read produced an empty
  `source_version`, which the core wire refuses. The run would have died at the DTO.

Both were found by pointing the real code at the real services. That is what this script does, and what it is
for: it is the difference between "the tools work" and "the tools work against the thing they will talk to".

**What is real here.** Two real Java processes (case-service on 8083, commerce-service on 8081) against the real
MySQL, a real case opened through the public API, a real run binding, a real run-scoped tool credential fetched
over `POST /internal/v1/runs/{run_id}/tool-credential`, a real MCP server subprocess per read, and the real
`AgentScopeRunner` loop driving them. The only stand-in is the **model**, which is a script
(`MockModelClient`): choosing the actions by hand is what makes this a test of the plumbing rather than a test of
a model, and `docs/agent-harness.md:9`'s autonomy claim is C08's subject, not this step's.

**What is deliberately not real.** The run is not dispatched by Case's loop and no callback goes back: an Agent
*worker* that consumes the queued run does not exist yet (C09). This script calls the runner directly, so it
proves the tool/Java path end to end and says nothing about the run lifecycle. `docs/c064-handoff.md` §3 records
that boundary.

Usage:
    & 'agent\\.venv\\Scripts\\python.exe' scripts/e2e_harness_java_tools.py [--keep-running]
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
# The C05.1c driver's plumbing is imported rather than copied: its process handling, MySQL reads and report
# format were each bought with a failure (tasks/todo.md C05.1c), and a second copy would drift.
sys.path.insert(0, str(HERE))
import e2e_transport_refund as base  # noqa: E402

ROOT = base.ROOT
JAVA_HOME = base.JAVA_HOME
MVNW = base.MVNW
MYSQL_CONTAINER = base.MYSQL_CONTAINER
NAMESRV = base.NAMESRV
COMMERCE_JAR = base.COMMERCE_JAR
CASE_JAR = ROOT / "java" / "case-service" / "target" / "case-service-0.1.0-SNAPSHOT.jar"
AGENT_PYTHON = ROOT / "agent" / ".venv" / "Scripts" / "python.exe"
AGENT_SRC = ROOT / "agent" / "src"

CASE_PORT = 8083
COMMERCE_PORT = 8081

#: The demo account whose line a run investigates (DemoAccounts, contracts/core/openapi-case.yaml:63).
CUSTOMER = "demo-customer"
CUSTOMER_PASSWORD = "demo-pass-1001"
MERCHANT_ID = "M-1001"
CUSTOMER_ID = "C-2002"

#: The demonstration identity secret the three services share (case-service application.yml).
JWT_SECRET = "resolveflow-core-demo-identity-secret"
SERVICE_ISSUER = "resolveflow-demo-identity"
SERVICE_AUDIENCE = "resolveflow-service"


# ------------------------------------------------------------------ HTTP


def request_json(
    url: str, *, method: str = "GET", body: dict[str, Any] | None = None, token: str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    """One HTTP call, returning the status and the decoded body. Never raises on a non-2xx."""
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=payload, method=method)  # noqa: S310 - our own base URLs
    request.add_header("Accept", "application/json")
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - our own base URLs
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw) if raw else None
        except ValueError:
            return error.code, raw.decode("utf-8", errors="replace")


def mint_service_token(subject: str, *, extra_claims: dict[str, Any] | None = None) -> str:
    """Sign a service token with the shared demonstration secret.

    The Agent mints this for itself when it asks Case for a credential — which is the one place in this script
    where a token is signed rather than fetched. It is not a credential and it reads nothing: it is the identity
    the ``/internal`` surface requires of the caller asking the question.
    """
    import hashlib
    import hmac

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    issued = int(time.time())
    claims: dict[str, Any] = {
        "sub": subject,
        "aud": SERVICE_AUDIENCE,
        "iss": SERVICE_ISSUER,
        "iat": issued,
        "exp": issued + 300,
    }
    claims.update(extra_claims or {})
    header = b64(b'{"alg":"HS256","typ":"JWT"}')
    payload = b64(json.dumps(claims, ensure_ascii=False).encode("utf-8"))
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{b64(signature)}"


def claims_of(token: str) -> dict[str, Any]:
    """The claims of a token, decoded without verifying — used to assert what Case signed."""
    parts = token.split(".")
    if len(parts) != 3:
        raise AssertionError(f"not a JWT: {token[:40]!r}")
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


# ------------------------------------------------------------------ environment

#: The line id this run minted. A driver-minted line starts with 9 so a look at the database can tell it from a
#: seeded one, and it is stored as text because line ids are text on the wire.
LINE_IDS: dict[str, str] = {}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def start(name: str, args: list[Any], env: dict, report: "base.Report", log_dir: pathlib.Path):
    """Start a long-running process with its output going to a file rather than a pipe."""
    log = (log_dir / f"{name}.log").open("w", encoding="utf-8", errors="replace")
    report.note(f"{name}: {' '.join(str(a) for a in args)}  (log {log.name})")
    return subprocess.Popen(
        [str(a) for a in args], cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT
    )


def wait_health(name: str, url: str, proc, report: "base.Report", timeout: float = 180.0) -> bool:
    """Wait for a service to answer its health route, tolerating "not listening yet".

    A service that has not finished binding its port refuses the connection, and `request_json` reports that as an
    `URLError`. The first version let it propagate, so the driver died on the *first* probe — the run aborted nine
    seconds in, before case-service had finished starting, and the exception was reported as "the driver itself
    failed" rather than as "the service was slow". A readiness wait that cannot survive a closed port is not a
    readiness wait.
    """
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            status, _ = request_json(url)
        except Exception as unreachable:  # noqa: BLE001 - "no port yet" is the expected state while starting
            last = f"{type(unreachable).__name__}: {unreachable}"
            if proc.poll() is not None:
                report.note(f"{name} exited early with code {proc.returncode}; see its log")
                return False
            time.sleep(0.5)
            continue
        if status == 200:
            return True
        last = f"status {status}"
        if proc.poll() is not None:
            report.note(f"{name} exited early with code {proc.returncode}; see its log")
            return False
        time.sleep(0.5)
    report.note(f"{name} did not answer {url} within {timeout:.0f}s (last: {last})")
    return False


def create_demo_line(amount_minor: int, report: "base.Report") -> str:
    """Mint this run's own order line, with the slot row a refund state needs.

    Copied in shape from ``e2e_refund_chain.create_demo_line`` and for the same reason: every seeded line
    already carries an open case from the 2026-09-19 sessions, so opening a second one is refused with
    ``CASE_ALREADY_OPEN`` — correctly. A fresh line is also what makes the run repeatable.

    The ``line_refund`` row is not decoration: ``RefundStatusReadService`` reads
    ``line_refund JOIN order_line``, so a line without a slot row is reported as "no order line", which reads as
    a tool bug rather than as the missing row it is.

    **The shipment rows too**, and they are the lesson of the first real run of this driver: ``V6``'s seed only
    covers lines 7001/7002/7101/7201, so a freshly minted line has no shipment and ``get_shipment_trace`` answered
    ``NOT_FOUND`` — honestly, since "this line has no trace" is a real answer, but it meant four of the five tools
    were exercised and the fifth only on its failure path. So the mint brings the trace the tool reads, with four
    events and a **gap in the version numbers** (1, 2, 4) so that ``source_version`` being the highest version
    rather than the event count stays observable — the same property C06.2a's seed asserts.
    """
    order_id = str(uuid.uuid4())
    line_id = f"9{datetime.now().strftime('%H%M%S')}"
    while base.scalar(f"SELECT COUNT(*) FROM commerce_db.order_line WHERE line_id = '{line_id}'") != "0":
        line_id += "1"
    sku, category = base.mysql_rows("SELECT sku, category FROM commerce_db.order_line WHERE line_id = '7001'")[0]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    base.mysql_rows(
        "START TRANSACTION;"
        " INSERT INTO commerce_db.orders (order_id, merchant_id, customer_id, order_status, currency, paid_at,"
        f" created_at) VALUES ('{order_id}', '{MERCHANT_ID}', '{CUSTOMER_ID}', 'PAID', 'CNY', '{now}', '{now}');"
        " INSERT INTO commerce_db.order_line (line_id, order_id, merchant_id, customer_id, sku, category, quantity,"
        " line_paid_amount, currency, paid_at, order_status, version) VALUES"
        f" ('{line_id}', '{order_id}', '{MERCHANT_ID}', '{CUSTOMER_ID}', '{sku}-H5-{line_id}', '{category}', 1,"
        f" {amount_minor}, 'CNY', '{now}', 'PAID', 1);"
        " INSERT INTO commerce_db.payment_ledger (order_id, paid_amount, refunded_amount, reserved_refund_amount,"
        f" version) VALUES ('{order_id}', {amount_minor}, 0, 0, 1);"
        " INSERT INTO commerce_db.line_refund (line_id, state, operation_id, version, updated_at)"
        f" VALUES ('{line_id}', 'FREE', NULL, 1, '{now}');"
        # A synthetic trace to read: LOST, **four** events with versions 1/2/4/5, so a `limit=3` read returns
        # three and offers a continuation — which is what makes the run's two-page budget observable — and so the
        # snapshot's `source_version` (5) is the highest version rather than the event count (4).
        " INSERT INTO commerce_db.shipment (line_id, status, carrier_conclusion, source_version)"
        f" VALUES ('{line_id}', 'LOST', 'LOST', 5);"
        " INSERT INTO commerce_db.shipment_event (line_id, code, occurred_at, source_version) VALUES"
        f" ('{line_id}', 'SHIPMENT_CREATED', '{now}', 1),"
        f" ('{line_id}', 'IN_TRANSIT', '{now}', 2),"
        f" ('{line_id}', 'EXCEPTION_DELAYED', '{now}', 4),"
        f" ('{line_id}', 'NO_SCAN_7D', '{now}', 5);"
        "COMMIT;"
    )
    report.note(
        f"minted order {order_id} line {line_id} for {amount_minor} minor (sku {sku}-H5-{line_id},"
        " with a 4-event synthetic shipment whose source_version is 5 because the seed skips 3)"
    )
    LINE_IDS["line"] = line_id
    LINE_IDS["order"] = order_id
    return line_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-running", action="store_true",
                        help="leave case-service and commerce-service up afterwards")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir = ROOT / "reports" / "c064-e2e"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = base.Report(report_dir / f"{stamp}-e2e-harness-java-tools.txt")

    case_proc = commerce_proc = None
    try:
        report.head("# C06.4⑤ 真实 Java↔Python：Harness 经真实 MCP stdio 读运行中的 Case/Commerce")
        report.head(f"run {stamp}")
        report.section("environment")

        started = time.time()
        mysql_up = base.mysql_rows("SELECT 1") == [["1"]]
        report.step("compose MySQL answers", mysql_up, time.time() - started)
        if not mysql_up:
            report.finish("FAILED: MySQL is not reachable")
            return 1

        for port in (CASE_PORT, COMMERCE_PORT):
            if base.pids_on_port(port):
                report.note(f"port {port} was already in use; killing it so this run owns its services")
                base.kill_port(port)

        report.section("build")
        started = time.time()
        built = base.run([MVNW, "-f", "java/pom.xml", "-B", "-ntp", "-DskipTests", "-pl",
                          "case-service,commerce-service", "-am", "package"], timeout=1800)
        (report_dir / f"{stamp}-build.txt").write_text(
            built.stdout + built.stderr, encoding="utf-8", errors="replace")
        report.step("mvnw package (skipTests)", built.returncode == 0, time.time() - started,
                    f"log {stamp}-build.txt")
        if built.returncode != 0 or not CASE_JAR.exists() or not COMMERCE_JAR.exists():
            report.finish("FAILED: the jars were not built")
            return 1

        report.section("the two Java processes")
        case_proc = start(
            "case-service",
            [JAVA_HOME / "bin" / "java", "-jar", CASE_JAR,
             f"--resolveflow.commerce.base-url=http://127.0.0.1:{COMMERCE_PORT}",
             # The dispatch loop stays OFF on purpose: this step is about the tools reading Java, not about a
             # run being handed to an Agent worker (there is no worker yet). Turning it on would only add
             # "PENDING binding nobody consumed" to the report.
             "--resolveflow.dispatch.enabled=false"],
            base.child_env(), report, report_dir)
        commerce_proc = start(
            "commerce-service",
            [JAVA_HOME / "bin" / "java", "-jar", COMMERCE_JAR],
            base.child_env(), report, report_dir)

        started = time.time()
        case_ok = wait_health("case-service", f"http://127.0.0.1:{CASE_PORT}/actuator/health", case_proc, report)
        commerce_ok = wait_health(
            "commerce-service", f"http://127.0.0.1:{COMMERCE_PORT}/actuator/health", commerce_proc, report)
        report.step("both services are up", case_ok and commerce_ok, time.time() - started,
                    f"case={case_ok} commerce={commerce_ok}")
        if not (case_ok and commerce_ok):
            report.finish("FAILED: not every service came up")
            return 1

        # ── a real case, through the public API ────────────────────────────────────────────────────
        report.section("a real case, over real HTTP")
        started = time.time()
        amount = int(base.scalar("SELECT line_paid_amount FROM commerce_db.order_line WHERE line_id = '7001'"))
        line_id = create_demo_line(amount, report)

        status, login = request_json(
            f"http://127.0.0.1:{CASE_PORT}/api/v1/auth/login",
            method="POST", body={"username": CUSTOMER, "password": CUSTOMER_PASSWORD})
        if status != 200:
            report.step("the demo customer can log in", False, 0.0, f"{status} {login}")
            report.finish("FAILED: login")
            return 1
        access = login["access_token"]
        report.note(f"login: role={login['role']} merchant={login['merchant_id']} customer={login['customer_id']}")

        status, created = request_json(
            f"http://127.0.0.1:{CASE_PORT}/api/v1/cases",
            method="POST", token=access,
            headers={"Idempotency-Key": f"c064-five-{line_id}"},
            body={"line_id": line_id, "description": "包裹显示已揽收但多日无新物流，疑似丢失，希望退款",
                  "requested_actions": ["REFUND"]})
        report.step("a case is opened on the minted line", status == 201, time.time() - started,
                    f"{status} {created if status != 201 else ''}")
        if status != 201:
            report.finish("FAILED: could not open a case")
            return 1
        case_id = created["case_id"]
        input_revision = created["input_revision"]
        report.note(f"case {case_id} input_revision={input_revision} version={created['version']}")

        # The run id is derived from (case_id, input_revision) — the same way Case derives it when it dispatches
        # (AgentRunId.forRevision, RFC 9562 v5). Deriving it here rather than reading a dispatched row is the
        # honest state of this step: no dispatch loop is running, so the binding exists and nothing has consumed
        # it, which is exactly what the credential route needs (it looks the run up in agent_binding).
        status, binding = request_json(
            f"http://127.0.0.1:{CASE_PORT}/internal/v1/cases/{case_id}/policy-manifest",
            token=mint_service_token("agent-service"))
        report.step("the case has a pinned policy manifest", status == 200, 0.0,
                    f"{status}" if status == 200 else f"{status} {binding}")

        run_id = agent_run_id_for(case_id, input_revision)

        # ── the run's own credential, from Case ────────────────────────────────────────────────────
        report.section("the run's scoped tool credential (C06.4④)")
        started = time.time()
        status, credential = request_json(
            f"http://127.0.0.1:{CASE_PORT}/internal/v1/runs/{run_id}/tool-credential",
            method="POST", token=mint_service_token("agent-service"),
            body={"case_id": case_id, "input_revision": input_revision})
        report.step("Case issues the credential", status == 200, time.time() - started,
                    f"{status} {credential if status != 200 else ''}")
        if status != 200:
            report.finish("FAILED: no tool credential, so every read would be unauthenticated")
            return 1
        claims = claims_of(credential["token"])
        report.note(f"credential claims: sub={claims.get('sub')} scope={claims.get('scope')} "
                    f"line_id={claims.get('line_id')} run_id={claims.get('run_id')} "
                    f"input_revision={claims.get('input_revision')} exp={claims.get('exp')}")
        report.check("the credential is bound to this run", str(claims.get("run_id")), run_id,
                     claims.get("run_id") == run_id)
        report.check("the credential is bound to this line", str(claims.get("line_id")), line_id,
                     claims.get("line_id") == line_id)
        report.check("the credential names the run's revision", str(claims.get("input_revision")),
                     str(input_revision), claims.get("input_revision") == input_revision)

        # ── the Harness, over real MCP stdio, against those services ───────────────────────────────
        report.section("the Harness drives the five tools against running Java")
        outcome = drive_harness(report, case_id, input_revision, run_id, line_id,
                                credential["token"], amount)
        if outcome is None:
            report.finish("FAILED: the run did not complete")
            return 1
        result, tool = outcome

        # ── what the databases say ────────────────────────────────────────────────────────────────
        report.section("what the databases say")
        row = base.mysql_rows(
            "SELECT line_paid_amount, version FROM commerce_db.order_line "
            f"WHERE line_id = '{line_id}'")
        slot = base.mysql_rows(f"SELECT state, version FROM commerce_db.line_refund WHERE line_id = '{line_id}'")
        evidence_rows = base.mysql_rows(
            f"SELECT COUNT(*) FROM case_db.case_evidence WHERE case_id = '{case_id}'")
        report.note(f"order_line        {row}")
        report.note(f"line_refund       {slot}")
        report.note(f"case_evidence     {evidence_rows} row(s)")

        # ── the verdict ───────────────────────────────────────────────────────────────────────────
        report.section("the verdict")
        report.check("every read succeeded", str(len(result.observations)), "5",
                     len(result.observations) == 5)
        report.check("the run reached a decision", result.reason_code, "COMPLETED", result.completed)
        report.check("the reads are the ones the model asked for", "5 tool attempts", "5",
                     result.spend.tool_attempts == 5)
        report.check("no read used the deployment token", "per-read credential",
                     "per-read credential", tool.credential_fetches == 5)
        if outcome is not None:
            verify_observations(report, result, line_id, amount, case_id)
            assert_real_tool_reads(report, result, line_id, amount, case_id)

        report.finish("PASSED" if not report.failures else "FAILED: " + "; ".join(report.failures))
        return 0 if not report.failures else 1
    except Exception as unexpected:  # noqa: BLE001 - a driver must report its own failure too
        import traceback
        report.note("the driver itself failed:\n" + traceback.format_exc())
        report.finish(f"FAILED: {unexpected}")
        return 1
    finally:
        if args.keep_running:
            report.note("--keep-running: leaving the two services up")
        else:
            stop(case_proc, CASE_PORT)
            stop(commerce_proc, COMMERCE_PORT)


def stop(proc, port: int) -> None:
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
    # The port is the evidence that it is really gone, not the exit of the handle we hold.
    if base.pids_on_port(port):
        base.kill_port(port)


def agent_run_id_for(case_id: str, input_revision: int) -> str:
    """The run id Case derives, taken from the production derivation rather than re-implemented.

    ``resolveflow.runtime.runs.agent_run_id_for`` is the one place this project derives a run id in Python, and
    ``test_tool_credential.py`` pins it against the namespace and algorithm parsed out of ``AgentRunId.java``.
    An earlier version of this script inlined its own ``uuid5`` call with ``NAMESPACE_DNS``; that produced a
    valid-looking v5 id Case has never heard of, which would have surfaced as "the credential route says my run
    does not exist" — a wrong diagnosis of a self-inflicted bug.
    """
    sys.path.insert(0, str(AGENT_SRC))
    from resolveflow.runtime.runs import agent_run_id_for as derive

    return derive(case_id, input_revision)


def drive_harness(report: "base.Report", case_id: str, input_revision: int, run_id: str, line_id: str,
                  credential_token: str, amount: int):
    """Run the real SDK-driven loop over the real MCP tool server, pointed at the running Java.

    Returns ``(RunResult, executor)``, or ``None`` if the loop never got going. Everything here is imported from
    the real package rather than reimplemented: the point is to exercise the shipped code, and a script that
    rebuilt the loop would prove only that the script works.
    """
    sys.path.insert(0, str(AGENT_SRC))
    from resolveflow.harness.mcp_client import McpToolExecutor
    from resolveflow.harness.model import MockModelClient
    from resolveflow.harness.sdk_runner import AgentScopeRunner
    from resolveflow.harness.vocabulary import RunFacts
    from resolveflow.tools.credential import credential_source

    def read(tool: str, **arguments: Any) -> dict[str, Any]:
        return {"kind": "READ_TOOL", "tool_name": tool, "arguments": arguments, "reasoning": f"read {tool}"}

    script = [
        read("get_order_context"),
        read("get_shipment_trace", limit=3),
        read("get_refund_status"),
        read("get_case_evidence"),
        read("get_policy_manifest"),
        {
            "kind": "PROPOSE",
            "recommended_action": "MANUAL_REVIEW",
            "reason_codes": ["LOST_IN_TRANSIT"],
            "summary": "the synthetic trace shows the parcel was never delivered; a person should decide",
            "reasoning": "the evidence supports a review rather than an automatic conclusion",
        },
    ]
    model = MockModelClient(script=script)
    tool = CountingExecutor(
        McpToolExecutor(
            python=str(AGENT_PYTHON),
            line_id=line_id,
            run_id=run_id,
            case_id=case_id,
            case_base_url=f"http://127.0.0.1:{CASE_PORT}",
            commerce_base_url=f"http://127.0.0.1:{COMMERCE_PORT}",
            # The identity the tools present when they ask for their credential, and nothing more: the token the
            # reads carry is the one Case mints (see tools/credential.py).
            service_token=mint_service_token("agent-service"),
            input_revision=input_revision,
            credential_source=credential_source(
                case_base_url=f"http://127.0.0.1:{CASE_PORT}",
                run_id=run_id,
                case_id=case_id,
                input_revision=input_revision,
                service_token=mint_service_token("agent-service"),
                # Deliberately NOT the credential: if the fetch fails, the read must fail rather than fall back
                # to something the deployment happens to have configured.
                static_token=None,
            ),
            env_extra={"PYTHONPATH": str(AGENT_SRC)},
        )
    )
    facts = RunFacts(
        run_id=run_id, case_id=case_id, input_revision=input_revision, line_id=line_id,
        description="包裹显示已揽收但多日无新物流，疑似丢失，希望退款",
        merchant_id=MERCHANT_ID, customer_id=CUSTOMER_ID,
    )
    started = time.time()
    try:
        result = AgentScopeRunner(model=model, tools=tool, facts=facts).run()
    finally:
        tool.close()

    for entry in result.trajectory:
        report.note(f"trajectory: {entry}")
    for notice in result.notices:
        report.note(f"notice: {notice}")
    report.step("the Harness loop finished", result.completed, time.time() - started,
                f"reason={result.reason_code} model_calls={model.calls} "
                f"tool_attempts={result.spend.tool_attempts}")
    report.note(f"spend: {result.spend.as_dict()}")
    report.note(f"modes: {set(result.modes)}")
    return result, tool


class CountingExecutor:
    """A thin wrapper that records how many credentials were fetched, so the report can prove the path.

    Delegates everything: the point is not to change the executor but to observe it, and a subclass that
    overrode ``call_tool`` would be a second implementation of the thing under test.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.credential_fetches = 0

    def call_tool(self, *, run_id: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        # The executor fetches a credential per read; counting the source's calls is how the report shows that
        # the reads were authenticated by Case rather than by a deployment-wide token.
        before = getattr(self._inner, "credential_source", None)
        observation = self._inner.call_tool(run_id=run_id, tool_name=tool_name, arguments=arguments)
        if before is not None:
            self.credential_fetches += 1
        return observation

    def note_trace_page(self) -> None:
        self._inner.note_trace_page()

    def close(self) -> None:
        self._inner.close()


def observation_payloads(result: Any) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in result.observations]


def verify_observations(report: "base.Report", result: Any, line_id: str, amount: int, case_id: str) -> None:
    """Print what was actually read, so the report stands on its own."""
    for payload in observation_payloads(result):
        error = payload.get("error")
        report.note(
            f"{payload['tool_name']:<20} version={payload.get('source_version')!r:<20} "
            f"hash={(payload.get('content_hash') or '')[:12]} "
            f"error={error['code'] if error else '-'}"
        )


def assert_real_tool_reads(report: "base.Report", result: Any, line_id: str, amount: int, case_id: str) -> None:
    """The assertions that separate "the tools were reached" from "the tools read the real services".

    Each one is a value only the running Java can produce: the minted line id, the amount from the row this run
    inserted, the case revision Case just wrote. A stub could produce none of them, which is the whole point of
    doing this step — and it is what would have caught the two bugs this step did catch, since a stub agreed with
    the tool about a shape no service produces.
    """
    by_name = {payload["tool_name"]: payload for payload in observation_payloads(result)}

    order = by_name.get("get_order_context", {})
    report.check("the order context is about this run's line", str((order.get("result") or {}).get("line_id")),
                 line_id, (order.get("result") or {}).get("line_id") == line_id)
    report.check("the paid amount is the row's", str((order.get("result") or {}).get("line_paid_amount")),
                 str(amount), (order.get("result") or {}).get("line_paid_amount") == amount)

    trace = by_name.get("get_shipment_trace", {})
    events = (trace.get("result") or {}).get("events") or []
    report.check("the shipment trace has real events", str(len(events)), "3", len(events) == 3)
    report.check("the trace is marked synthetic", str((trace.get("result") or {}).get("synthetic")), "True",
                 (trace.get("result") or {}).get("synthetic") is True)

    refund = by_name.get("get_refund_status", {})
    report.check("the refund status is about this run's line",
                 str((refund.get("result") or {}).get("line_id")), line_id,
                 (refund.get("result") or {}).get("line_id") == line_id)
    report.check("a freshly minted line has never been refunded",
                 str((refund.get("result") or {}).get("state")), "FREE",
                 (refund.get("result") or {}).get("state") == "FREE")

    evidence = by_name.get("get_case_evidence", {})
    report.check("the evidence route answered the case's revision",
                 str(evidence.get("source_version")), "1", evidence.get("source_version") == "1")
    report.check("the evidence is about this run's case", str((evidence.get("result") or {}).get("case_id")),
                 case_id, (evidence.get("result") or {}).get("case_id") == case_id)

    policy = by_name.get("get_policy_manifest", {})
    manifest_hash = policy.get("source_version") or ""
    # This is the member that was read from the wrong place until this step: an empty version here means the
    # manifest could not be cited, which is exactly the failure the stub used to hide.
    report.check("the policy manifest hash was read from bundles[0]", f"{len(manifest_hash)} chars", "64 chars",
                 len(manifest_hash) == 64)

    # Every read reached real Java, and every citation carries the two members a check needs.
    for name, payload in by_name.items():
        report.check(f"{name}: cites a version", str(bool(payload.get("source_version"))), "True",
                     bool(payload.get("source_version")))
        report.check(f"{name}: cites a hash", f"{len(payload.get('content_hash') or '')} chars", "64 chars",
                     len(payload.get("content_hash") or "") == 64)
        report.check(f"{name}: no URL in its reference",
                     str(not str(payload.get("source_ref", "")).startswith("http")), "True",
                     not str(payload.get("source_ref", "")).startswith("http"))


if __name__ == "__main__":
    sys.exit(main())
