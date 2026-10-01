#!/usr/bin/env python
"""Reviewer demonstration: a resumable, isolated synthetic dataset on the core stack.

Authority: ``tasks/dsh-reviewer/02-demo-chain.md`` sections 3 and 4. This driver is the
one command that prepares, advances, inspects and stops the reviewer demonstration.
It is not a second progress ledger and it decides nothing: every business step goes
through the authenticated core API, and the model is an explicit mock script bound to
one run.

What it is careful about, and why:

* **Isolation is checked, not assumed.** The demonstration owns host ports 5174, 8180-8183,
  3307, 55433, 9877 and 10912, one compose project (``resolveflow-review-demo``) and its
  own named volumes. ``guard()`` refuses to run if any demo port collides with a port the
  shared ``resolveflow`` project uses, and every database statement goes through a
  container whose compose project label is the demo's. A run that pointed at the shared
  database would be worse than a run that failed.
* **Nothing irreversible is done twice.** Each sample records its case/line/run ids in
  ``reports/reviewer-demo/samples.json``, written atomically after every irreversible
  step. ``prepare`` and ``run`` re-read that record first: an existing sample in its
  expected state is reported as already complete instead of being re-created, and a
  sample a person has moved on is reported as changed rather than reset.
* **No SQL stands in for a business step.** Order lines and shipment rows are seeded
  directly, because Commerce has no order-creation route and the manual allows exactly
  that. Case material, verification, proposals, decisions and refunds go through the
  authenticated HTTP API; the demo never writes a final case status, an authorization, a
  refund ledger row or an Agent trajectory with SQL.
* **The mock is bound to one run.** The Agent process is stopped before a new case is
  created and started again with that scenario's script, so a script cannot serve a run
  it was not written for. The script cites observations and policy rules that a real
  preflight read produced for that very run.

Commands::

    agent/.venv/Scripts/python.exe scripts/reviewer_demo.py start
    agent/.venv/Scripts/python.exe scripts/reviewer_demo.py prepare
    agent/.venv/Scripts/python.exe scripts/reviewer_demo.py run --scenario lost-review
    agent/.venv/Scripts/python.exe scripts/reviewer_demo.py status
    agent/.venv/Scripts/python.exe scripts/reviewer_demo.py verify
    agent/.venv/Scripts/python.exe scripts/reviewer_demo.py stop

Everything the driver writes while running (logs, mock scripts, the provider SQLite file,
recorded PIDs) lands under the git-ignored ``tmp/reviewer-demo/``; the only tracked
artifacts are the desensitized sample manifest and the report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _extra in (ROOT / "scripts", ROOT / "agent" / "src"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

ENVIRONMENT = "reviewer-demo-2026-09"
PROJECT = "resolveflow-review-demo"
COMPOSE_FILE = ROOT / "infra" / "compose.reviewer-demo.yaml"
MANIFEST_PATH = ROOT / "reports" / "reviewer-demo" / "samples.json"
RUNTIME_ROOT = ROOT / "tmp" / "reviewer-demo"
MANIFEST_SCHEMA_VERSION = 1

#: The JDK the demonstration runs. Resolved rather than taken from ``JAVA_HOME``: this
#: machine's ``JAVA_HOME`` is a JDK 17, and the Maven enforcer correctly refuses it, so
#: inheriting it produces "the jars did not build" for a reason that has nothing to do
#: with the sources. Same search order as ``scripts/verify.ps1`` and the C07.1 driver.
PINNED_JDK = Path(r"C:\Users\hjn\.jdks\jdk-21.0.12.1+1")
AGENT_PYTHON = ROOT / "agent" / ".venv" / "Scripts" / "python.exe"
AGENT_SRC = ROOT / "agent" / "src"
EMBEDDING_PATH = ROOT / "tmp" / "c071-probe" / "models" / "BAAI--bge-small-zh-v1.5"
GATEWAY_JAR = ROOT / "java" / "gateway" / "target" / "gateway-0.1.0-SNAPSHOT.jar"
CASE_JAR = ROOT / "java" / "case-service" / "target" / "case-service-0.1.0-SNAPSHOT.jar"
COMMERCE_JAR = ROOT / "java" / "commerce-service" / "target" / "commerce-service-0.1.0-SNAPSHOT.jar"

#: The demo project's own compose services, by role.
DEMO_SERVICES = {
    "mysql": "mysql",
    "postgres": "postgres",
    "namesrv": "rocketmq-namesrv",
    "broker": "rocketmq-broker",
}

#: Host ports this demonstration owns. Every one is bound to 127.0.0.1 and is one away
#: from the shared stack's, so both can run at the same time.
DEFAULT_PORTS: dict[str, int] = {
    "mysql": 3307,
    "postgres": 55433,
    "namesrv": 9877,
    "broker": 10912,
    "broker_ha": 10913,
    "gateway": 8180,
    "commerce": 8181,
    "agent": 8182,
    "case": 8183,
    "frontend": 5174,
}

#: Ports the shared ``resolveflow`` project (or a host-run sibling) uses. A demo port
#: list that intersects this is refused rather than adjusted: silently moving a port is
#: how a demonstration ends up talking to the environment it was supposed to leave alone.
SHARED_PORTS = frozenset(
    {3306, 55432, 6379, 56379, 9876, 10911, 10909, 8080, 8081, 8082, 8083, 5173, 5432, 8848, 9848}
)
SHARED_MYSQL_CONTAINER = "resolveflow-mysql-1"

#: The shared environment's row counts, sampled read-only at prepare time so `verify` can
#: show that a demonstration did not move the environment it must not disturb.
SHARED_WITNESS_TABLES = (
    "case_db.aftersale_case",
    "case_db.case_proposal",
    "case_db.case_authorization",
    "commerce_db.order_line",
    "commerce_db.line_refund",
    "commerce_db.refund_operation",
)

#: The five read-only tools and the two local capabilities the ABI offers
#: (``agent/src/resolveflow/harness/actions.py``). Named here so a scenario's preflight
#: and its script cannot disagree about which tool an observation came from.
TOOL_GET_ORDER = "get_order_context"
TOOL_GET_SHIPMENT = "get_shipment_trace"
TOOL_GET_REFUND_STATUS = "get_refund_status"
TOOL_GET_EVIDENCE = "get_case_evidence"
TOOL_GET_MANIFEST = "get_policy_manifest"


class DemoRefused(RuntimeError):
    """The demonstration will not proceed, and says which fact stopped it."""


class SampleChanged(RuntimeError):
    """A sample a person has already moved on; the driver reports and never resets it."""


# --------------------------------------------------------------------------- settings


@dataclass(frozen=True, slots=True)
class Settings:
    """Where the demonstration runs. Injectable so a test needs no ports or containers."""

    environment: str = ENVIRONMENT
    project: str = PROJECT
    dataset: str = "reviewer-demo-2026-09-a"
    ports: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_PORTS))
    manifest_path: Path = MANIFEST_PATH
    runtime_root: Path = RUNTIME_ROOT

    @property
    def gateway_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['gateway']}"

    @property
    def case_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['case']}"

    @property
    def commerce_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['commerce']}"

    @property
    def agent_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['agent']}"

    @property
    def frontend_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['frontend']}"

    @property
    def case_dsn(self) -> str:
        return (
            f"jdbc:mysql://127.0.0.1:{self.ports['mysql']}/case_db"
            "?connectionTimeZone=UTC&preserveInstants=true&allowPublicKeyRetrieval=true&useSSL=false"
        )

    @property
    def commerce_dsn(self) -> str:
        return (
            f"jdbc:mysql://127.0.0.1:{self.ports['mysql']}/commerce_db"
            "?connectionTimeZone=UTC&preserveInstants=true&allowPublicKeyRetrieval=true&useSSL=false"
        )

    @property
    def agent_dsn(self) -> str:
        # A local development credential for the demo container, not a deployment secret.
        return f"postgresql://agent:agent@127.0.0.1:{self.ports['postgres']}/agent_db"

    @property
    def namesrv(self) -> str:
        return f"127.0.0.1:{self.ports['namesrv']}"

    def runtime(self, dataset: str | None = None) -> Path:
        return self.runtime_root / (dataset or self.dataset)


def settings_from_environ(environ: dict[str, str] | None = None) -> Settings:
    """The demo's settings, with every port overridable and the dataset named explicitly."""
    env = os.environ if environ is None else environ
    ports = dict(DEFAULT_PORTS)
    for role in list(ports):
        override = env.get(f"REVIEWER_DEMO_PORT_{role.upper()}")
        if override:
            try:
                ports[role] = int(override)
            except ValueError as refusal:
                raise DemoRefused(f"REVIEWER_DEMO_PORT_{role.upper()} is not a port: {override!r}") from refusal
    dataset = (env.get("REVIEWER_DEMO_DATASET") or "").strip() or "reviewer-demo-2026-09-a"
    root = Path(env.get("REVIEWER_DEMO_RUNTIME") or RUNTIME_ROOT)
    manifest = Path(env.get("REVIEWER_DEMO_MANIFEST") or MANIFEST_PATH)
    return Settings(dataset=dataset, ports=ports, manifest_path=manifest, runtime_root=root)


# --------------------------------------------------------------------------- guardrails


def guard(settings: Settings) -> None:
    """Refuse anything that would reach outside the demonstration.

    Three facts, each of which has a failure that reads as something else: a demo port on
    a shared port would make the driver talk to the shared stack while looking correct; a
    renamed project would make ``docker compose`` operate on someone else's containers; and
    a dataset without an environment would make the manifest unable to say what it belongs
    to.
    """
    if settings.project != PROJECT:
        raise DemoRefused(
            f"this driver only ever operates the {PROJECT!r} compose project; got {settings.project!r}"
        )
    if settings.environment != ENVIRONMENT:
        raise DemoRefused(f"unexpected environment id {settings.environment!r}")
    collisions = sorted(set(settings.ports.values()) & SHARED_PORTS)
    if collisions:
        raise DemoRefused(
            "these demo ports belong to the shared environment: "
            + ", ".join(str(port) for port in collisions)
            + ". The demonstration must not be pointed at the environment it must not disturb."
        )
    if len(set(settings.ports.values())) != len(settings.ports):
        raise DemoRefused("two demo roles share a port; the ports must be distinct")
    if not settings.dataset.startswith("reviewer-demo"):
        raise DemoRefused(
            f"dataset {settings.dataset!r} is not one of this demonstration's; an explicit new dataset "
            "must start with 'reviewer-demo'"
        )
    if not EMBEDDING_PATH.is_dir():
        raise DemoRefused(
            f"the pinned embedding snapshot is missing at {EMBEDDING_PATH}. Dense retrieval is required for "
            "the demonstration; a stub embedder would make the citations prove nothing."
        )
    if not COMPOSE_FILE.is_file():
        raise DemoRefused(f"missing {COMPOSE_FILE}")


# --------------------------------------------------------------------------- shell plumbing


def run(args: list[Any], *, timeout: float = 900.0, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=str(ROOT),
        env=env or child_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def child_env(**extra: str) -> dict[str, str]:
    """The environment a demo child process runs with: the resolved JDK 21, and nothing live."""
    home = java_home()
    env = dict(os.environ)
    env["JAVA_HOME"] = str(home)
    env["PATH"] = f"{home / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env.update({key: str(value) for key, value in extra.items()})
    return env


def java_home() -> Path:
    """A JDK 21+ home, resolved the way ``scripts/verify.ps1`` resolves it.

    ``JAVA_HOME`` is consulted **last**, not first: on this machine it points at a JDK 17,
    and inheriting that turns a correct build into an enforcer failure that reads like a
    broken source tree. An explicit ``REVIEWER_DEMO_JAVA_HOME`` still wins, so a machine
    with its JDK elsewhere is a setting rather than an edit.
    """
    import re

    candidates: list[Path] = []
    explicit = os.environ.get("REVIEWER_DEMO_JAVA_HOME")
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(PINNED_JDK)
    for root in (Path.home() / ".jdks", Path("C:/Program Files/Eclipse Adoptium"), Path("C:/Program Files/Java")):
        if root.is_dir():
            candidates.extend(sorted(path for path in root.iterdir() if path.is_dir()))
    configured = os.environ.get("JAVA_HOME")
    if configured:
        candidates.append(Path(configured))
    for home in candidates:
        java = home / "bin" / "java.exe"
        if not java.is_file():
            continue
        try:
            completed = subprocess.run(  # noqa: S603 - a resolved JDK path, not caller input
                [str(java), "-version"], capture_output=True, text=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError):
            continue
        reported = completed.stderr or completed.stdout
        match = re.search(r'version "(\d+)', reported)
        if match and int(match.group(1)) >= 21:
            return home
    raise DemoRefused(
        "no JDK 21+ found. Set REVIEWER_DEMO_JAVA_HOME, or install one under ~/.jdks "
        "(docs/compatibility-report.md)."
    )


def compose(*args: str, settings: Settings, timeout: float = 600.0) -> subprocess.CompletedProcess:
    return run(
        ["docker", "compose", "-f", COMPOSE_FILE, *args],
        timeout=timeout,
        # The demo's own env file is never read: DEMO_* names in the compose file keep the
        # shared project's infra/.env out of this stack.
        env=child_env(COMPOSE_PROJECT_NAME=settings.project),
    )


def tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def pids_on_port(port: int) -> list[str]:
    """Who is listening on a host port, by observation rather than by job bookkeeping."""
    proc = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, errors="replace")
    pids: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            if parts[1].endswith(f":{port}") and parts[4] not in pids:
                pids.append(parts[4])
    return pids


def live_container(role: str, settings: Settings) -> str:
    """The demo container for a role, checked to belong to the demo compose project.

    The label check is the point: ``docker exec resolveflow-mysql-1`` and
    ``docker exec resolveflow-review-demo-mysql-1`` differ by a suffix, and a typo in that
    suffix would run the demonstration's SQL against the shared database.
    """
    service = DEMO_SERVICES[role]
    listing = compose("ps", "-q", service, settings=settings, timeout=120)
    container_id = listing.stdout.strip().splitlines()[0] if listing.stdout.strip() else ""
    if not container_id:
        raise DemoRefused(f"the demo {service} container is not running; run `prepare` first")
    inspect = run(
        ["docker", "inspect", "--format", '{{index .Config.Labels "com.docker.compose.project"}}', container_id],
        timeout=60,
    )
    label = inspect.stdout.strip()
    if label != settings.project:
        raise DemoRefused(
            f"container {container_id[:12]} belongs to compose project {label!r}, not {settings.project!r}; "
            "refusing to touch it"
        )
    return container_id


def mysql_rows(statement: str, settings: Settings, *, database: str | None = None) -> list[list[str]]:
    """One demo MySQL statement, read as tab-separated rows. Never touches the shared MySQL."""
    container = live_container("mysql", settings)
    args = ["docker", "exec", container, "mysql", "-uroot", "-proot", "--default-character-set=utf8mb4", "-N", "-B"]
    if database:
        args.append(database)
    args += ["-e", statement]
    proc = run(args, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"demo MySQL refused the statement: {proc.stderr.strip()[:400]}")
    return [line.split("\t") for line in proc.stdout.splitlines() if line.strip()]


def mysql_scalar(statement: str, settings: Settings) -> str | None:
    rows = mysql_rows(statement, settings)
    return rows[0][0] if rows and rows[0] else None


def shared_mysql_scalar(statement: str) -> str | None:
    """A read-only count against the shared MySQL, used as a witness that it did not move."""
    proc = subprocess.run(
        ["docker", "exec", SHARED_MYSQL_CONTAINER, "mysql", "-uroot", "-proot", "-N", "-B", "-e", statement],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"shared MySQL refused the witness statement: {proc.stderr.strip()[:200]}")
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return lines[0] if lines else None


def postgres_scalar(statement: str, settings: Settings) -> str | None:
    container = live_container("postgres", settings)
    proc = run(
        ["docker", "exec", container, "psql", "-U", "agent", "-d", "agent_db", "-tAc", statement], timeout=120
    )
    if proc.returncode != 0:
        raise RuntimeError(f"demo PostgreSQL refused the statement: {proc.stderr.strip()[:400]}")
    return proc.stdout.strip() or None


# --------------------------------------------------------------------------- HTTP


def http(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    """One JSON request. Credentials travel in headers and are never logged."""
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method=method)
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - our own demo URLs
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, (json.loads(raw) if raw else None)
        except ValueError:
            return error.code, raw.decode("utf-8", errors="replace")
    except urllib.error.URLError as error:
        return 0, str(error.reason)


def api(
    settings: Settings,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    method: str | None = None,
    expect: tuple[int, ...] = (200,),
    base_url: str | None = None,
) -> Any:
    verb = method or ("POST" if body is not None else "GET")
    status, answer = http(
        verb, (base_url or settings.gateway_url) + path, token=token, body=body, headers=headers
    )
    if status not in expect:
        raise RuntimeError(f"{verb} {path} answered {status}: {str(answer)[:400]}")
    return answer


def login(settings: Settings, username: str, password: str, *, base_url: str | None = None) -> str:
    answer = api(
        settings,
        "/api/v1/auth/login",
        body={"username": username, "password": password},
        base_url=base_url,
    )
    return answer["access_token"]


# --------------------------------------------------------------------------- logging


class Log:
    """The run's record: printed and written, so a failed run still leaves evidence."""

    def __init__(self, path: Path | None = None, title: str = ""):
        self.path = path
        self.lines: list[str] = [title] if title else []
        self.failures: list[str] = []

    def note(self, text: str) -> None:
        self.lines.append(f"    {text}")
        print(f"    {text}", flush=True)

    def step(self, text: str, ok: bool = True, detail: str = "") -> None:
        mark = "PASS" if ok else "FAIL"
        line = f"[{mark}] {text}" + (f" -- {detail}" if detail else "")
        self.lines.append(line)
        print(line, flush=True)
        if not ok:
            self.failures.append(text)

    def section(self, text: str) -> None:
        self.lines.append(f"\n== {text}")
        print(f"\n== {text}", flush=True)

    def flush(self, verdict: str) -> None:
        self.lines.append(f"\nRESULT: {verdict}")
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def log_path(settings: Settings, command: str) -> Path:
    stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M%S")
    return settings.runtime() / "logs" / f"{stamp}-{command}.txt"


# --------------------------------------------------------------------------- process ownership


def processes_file(settings: Settings) -> Path:
    return settings.runtime() / "processes.json"


def read_owned(settings: Settings) -> list[dict[str, Any]]:
    path = processes_file(settings)
    if not path.is_file():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    if document.get("project") != settings.project or document.get("environment") != settings.environment:
        raise DemoRefused(
            f"{path} belongs to {document.get('project')!r}/{document.get('environment')!r}, "
            "not to this demonstration"
        )
    return list(document.get("processes", []))


def write_owned(settings: Settings, processes: list[dict[str, Any]]) -> None:
    path = processes_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": 1,
        "project": settings.project,
        "environment": settings.environment,
        "dataset": settings.dataset,
        "updated_at": now_iso(),
        "processes": processes,
    }
    atomic_write(path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def remember(settings: Settings, name: str, pid: int, port: int, log: Path) -> None:
    """Record a process this driver started, and the pid that ended up owning its port.

    Two pids for one process, because on Windows ``agent/.venv/Scripts/python.exe`` is a
    launcher stub that re-executes the real interpreter as a **child**: the pid ``Popen``
    returns is the stub, and the child is what holds the socket. Killing only the stub
    orphaned the child, which kept the port - and worse, kept serving with the previous
    scenario's mock script, so a new run's dispatch could be answered by a stale decision.
    The owner is recorded once the health check has confirmed it is ours, and stopping kills
    both trees.
    """
    processes = [entry for entry in read_owned(settings) if entry["name"] != name]
    processes.append(
        {
            "name": name,
            "pid": pid,
            "port": port,
            "owner_pid": None,
            "started_at": now_iso(),
            "log": str(log.relative_to(ROOT)) if log.is_relative_to(ROOT) else str(log),
        }
    )
    write_owned(settings, processes)


def record_port_owner(settings: Settings, name: str) -> str | None:
    """Note which pid holds this process's port, now that it is up and answering."""
    processes = read_owned(settings)
    owner = None
    for entry in processes:
        if entry["name"] != name:
            continue
        owners = pids_on_port(int(entry["port"]))
        entry["owner_pid"] = owners[0] if owners else None
        owner = entry["owner_pid"]
    write_owned(settings, processes)
    return owner


def stop_owned(settings: Settings, name: str | None = None, *, log: Log | None = None) -> list[str]:
    """Stop only processes this driver started, and only while they still own their port.

    The port is the check that matters: a PID can be reused, and a process that exited while
    another took the port must not be killed. Anything that does not match is left alone —
    but an entry whose process is still *alive* is kept rather than forgotten, because
    dropping it would silently give up the only handle the demonstration has on its own
    process. A live process that no longer owns its port is reported and kept.

    The port is also waited for: ``taskkill`` returns before the socket is necessarily
    released, and a caller that immediately rebinds would otherwise race itself.
    """
    stopped: list[str] = []
    remaining: list[dict[str, Any]] = []
    for entry in read_owned(settings):
        if name is not None and entry["name"] != name:
            remaining.append(entry)
            continue
        pid, port = int(entry["pid"]), int(entry["port"])
        owner = int(entry["owner_pid"]) if entry.get("owner_pid") else None
        if not _pid_alive(pid) and (owner is None or not _pid_alive(owner)):
            continue
        owners = pids_on_port(port)
        ours = {str(pid)} | ({str(owner)} if owner is not None else set())
        if not (ours & set(owners)):
            if log is not None:
                log.note(
                    f"{entry['name']}: pid {pid} is alive but port {port} is held by "
                    f"{', '.join(owners) or 'nobody'}; left untouched and kept on the record"
                )
            remaining.append(entry)
            continue
        # /T kills the tree: the socket is held by the launcher's child, not by the pid Popen
        # handed back, and a stop that left the child running left a stale Agent on the port.
        targets = ([str(owner)] if owner is not None and str(owner) in owners else []) + [str(pid)]
        for target in targets:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", target], capture_output=True, text=True, errors="replace"
            )
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and (ours & set(pids_on_port(port))):
            time.sleep(0.5)
        if ours & set(pids_on_port(port)):
            if log is not None:
                log.note(f"{entry['name']}: port {port} is still held after taskkill; kept on the record")
            remaining.append(entry)
            continue
        stopped.append(f"{entry['name']}(pid {pid}, port {port})")
    write_owned(settings, remaining)
    return stopped


def _pid_alive(pid: int) -> bool:
    proc = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, errors="replace"
    )
    return str(pid) in proc.stdout


def start_process(settings: Settings, name: str, args: list[Any], env: dict[str, str], port: int) -> subprocess.Popen:
    """Start a demo process with its output in a file, and record that we own it."""
    directory = settings.runtime() / "processes"
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / f"{name}.log"
    handle = log.open("w", encoding="utf-8", errors="replace")
    handle.write(f"# {' '.join(str(arg) for arg in args)}\n")
    handle.flush()
    process = subprocess.Popen(  # noqa: S603 - fixed argv built from this repository's paths
        [str(arg) for arg in args],
        cwd=str(ROOT),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    remember(settings, name, process.pid, port, log)
    return process


def wait_for(description: str, probe, *, timeout: float, interval: float = 1.0, processes: tuple = ()) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if probe():
                return True
        except Exception:  # noqa: BLE001 - a probe may read a table that does not exist yet
            pass
        if any(proc is not None and proc.poll() is not None for proc in processes):
            return False
        time.sleep(interval)
    return False


# --------------------------------------------------------------------------- manifest


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def atomic_write(path: Path, text: str) -> None:
    """Write a file in one step, always with LF endings.

    `newline=""` matters: Python's default translates `\n` to `\r\n` on Windows, and a manifest
    with CRLF endings shows up as "trailing whitespace" on every line in `git diff --check`,
    which is the check the batch workflow runs before every commit.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temporary, path)


def load_manifest(settings: Settings) -> dict[str, Any]:
    path = settings.manifest_path
    if not path.is_file():
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "environment": settings.environment,
            "project": settings.project,
            "dataset_id": settings.dataset,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "samples": [],
        }
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("environment") != settings.environment or document.get("project") != settings.project:
        raise DemoRefused(
            f"{path} belongs to {document.get('project')!r}/{document.get('environment')!r}, "
            "not to this demonstration"
        )
    return document


def save_manifest(settings: Settings, document: dict[str, Any]) -> None:
    document["updated_at"] = now_iso()
    document["samples"] = sorted(document.get("samples", []), key=lambda sample: sample["scenario"])
    atomic_write(settings.manifest_path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def sample_of(document: dict[str, Any], dataset: str, scenario: str) -> dict[str, Any] | None:
    for sample in document.get("samples", []):
        if sample.get("dataset_id") == dataset and sample.get("scenario") == scenario:
            return sample
    return None


def record_sample(settings: Settings, document: dict[str, Any], sample: dict[str, Any]) -> None:
    """Write one sample's identity immediately after the step that made it irreversible."""
    samples = [entry for entry in document.get("samples", [])
               if not (entry.get("dataset_id") == sample["dataset_id"] and entry.get("scenario") == sample["scenario"])]
    samples.append(sample)
    document["samples"] = samples
    save_manifest(settings, document)


def retire_sample(settings: Settings, document: dict[str, Any], sample: dict[str, Any], *, reason: str) -> None:
    """Move an unfinished attempt out of the sample list without deleting anything.

    An attempt that never became a sample — the run failed before a proposal existed, or the
    driver stopped halfway — is closed through the product's own decision route and then
    recorded as retired, with its case id and the reason. It is never deleted from the demo
    database and never reset: the case keeps its history, and the manifest still says what
    happened to it. This is the only way the driver removes a sample record.
    """
    document["samples"] = [
        entry for entry in document.get("samples", [])
        if not (entry.get("dataset_id") == sample["dataset_id"] and entry.get("scenario") == sample["scenario"])
    ]
    retired = document.setdefault("retired", [])
    retired.append({**sample, "retired_at": now_iso(), "retired_reason": reason})
    save_manifest(settings, document)


# --------------------------------------------------------------------------- scenarios


@dataclass(frozen=True, slots=True)
class Scenario:
    """One synthetic sample: what to seed, what the script decides, and where it stops."""

    name: str
    title: str
    merchant_id: str
    customer_username: str
    customer_password: str
    reviewer_username: str
    reviewer_password: str
    amount_minor: int
    description: str
    customer_material: str
    shipment_status: str
    shipment_conclusion: str
    shipment_events: tuple[tuple[str, str], ...]
    verification: tuple[str, str] | None
    expected_status: str
    expected_authorization: str | None
    #: Synthetic display values for the demo order line (V7's two optional columns). Written only
    #: by the seed, only for lines this driver mints, and never used by any amount computation.
    product_name: str = "演示商品"
    variant_text: str | None = None
    #: Which extra steps this scenario takes after the run settles.
    advance: str = "none"


SCENARIOS: dict[str, Scenario] = {
    "lost-review": Scenario(
        name="lost-review",
        product_name="演示商品 · 降噪蓝牙耳机",
        variant_text="深空灰 · 标准版",
        title="承运商确认丢失，等待人工审批",
        merchant_id="M-1001",
        customer_username="demo-customer",
        customer_password="demo-pass-1001",
        reviewer_username="demo-reviewer",
        reviewer_password="demo-pass-1003",
        amount_minor=32900,
        description="包裹发货后多日未送达，物流一直没有签收记录；承运商现已确认丢失。",
        customer_material="物流页面持续显示运输异常，未出现签收记录。我联系承运商后获知包裹已判定丢失。",
        shipment_status="LOST",
        shipment_conclusion="LOST",
        shipment_events=(("SHIPMENT_CREATED", "2026-09-10 12:00:00.000000"), ("CARRIER_LOST", "2026-09-12 07:30:00.000000")),
        verification=(
            "CONFIRMED",
            "已核对本地合成物流记录：承运商结论为 LOST，只有丢失事件，未见签收事件；与客户陈述一致。",
        ),
        expected_status="PENDING_REVIEW",
        expected_authorization="PENDING_REVIEW",
        advance="none",
    ),
    "signed-conflict": Scenario(
        name="signed-conflict",
        product_name="演示商品 · 机械键盘",
        variant_text="茶轴 · 87 键",
        title="客户称未收到，物流已有有效签收",
        merchant_id="M-1001",
        customer_username="demo-customer-2",
        customer_password="demo-pass-1002",
        reviewer_username="demo-reviewer",
        reviewer_password="demo-pass-1003",
        amount_minor=19800,
        description="包裹显示已签收，但我本人没有收到，也没有人通知我代收。",
        customer_material="我全天在家，没有收到包裹，也没有收到任何代收通知；请核实签收记录。",
        shipment_status="DELIVERED",
        shipment_conclusion="DELIVERED",
        shipment_events=(("SHIPMENT_CREATED", "2026-09-11 14:00:00.000000"), ("DELIVERED", "2026-09-13 16:20:00.000000")),
        verification=None,
        expected_status="PENDING_REVIEW",
        expected_authorization=None,
        advance="none",
    ),
    "damage-review": Scenario(
        name="damage-review",
        product_name="演示商品 · 陶瓷马克杯",
        variant_text="白色 · 单只",
        title="客户主张到货破损，尚无人工核验",
        # The pinned bundle this merchant holds has no damage rule, and that is the honest
        # state of the demonstration: `fixtures/policies/bundles/policy-damage-*.yaml` belongs
        # to M-2002 while the seeded second account (`demo-customer-m2`) is M-1002, so the
        # damage bundles have no account and the accounts' merchants have no damage rule. The
        # sample therefore shows what a reviewer actually faces: a damage claim with no
        # applicable rule on this case, which is a hand-off rather than an automatic refund.
        merchant_id="M-1001",
        customer_username="demo-customer-2",
        customer_password="demo-pass-1002",
        reviewer_username="demo-reviewer",
        reviewer_password="demo-pass-1003",
        amount_minor=45600,
        description="收到的商品外包装破损，内部商品有裂痕，申请全额退款。",
        customer_material="开箱时外包装已经压扁，商品外壳有明显裂痕；照片已提交给客服，尚未有人核验。",
        shipment_status="DELIVERED",
        shipment_conclusion="DELIVERED",
        shipment_events=(("SHIPMENT_CREATED", "2026-09-12 09:00:00.000000"), ("DELIVERED", "2026-09-14 11:05:00.000000")),
        verification=None,
        expected_status="PENDING_REVIEW",
        expected_authorization=None,
        advance="none",
    ),
    "waiting-info": Scenario(
        name="waiting-info",
        product_name="演示商品 · 便携充电宝",
        title="调查缺少一件关键材料，已向客户追问",
        merchant_id="M-1001",
        customer_username="demo-customer",
        customer_password="demo-pass-1001",
        reviewer_username="demo-reviewer",
        reviewer_password="demo-pass-1003",
        amount_minor=12900,
        description="包裹一直没有更新物流，也没有送达。",
        customer_material="物流已经很久没有更新，我这边一直没有收到商品。",
        shipment_status="IN_TRANSIT",
        shipment_conclusion="IN_TRANSIT",
        shipment_events=(("SHIPMENT_CREATED", "2026-09-12 15:00:00.000000"), ("IN_TRANSIT_HUB", "2026-09-13 10:00:00.000000")),
        verification=None,
        expected_status="WAITING_CUSTOMER",
        expected_authorization=None,
        advance="none",
    ),
    "unknown-refund": Scenario(
        name="unknown-refund",
        product_name="演示商品 · 运动手环",
        variant_text="黑色 · 标准表带",
        title="审批后 provider 未给出回答，保持 UNKNOWN 占用",
        merchant_id="M-1001",
        customer_username="demo-customer",
        customer_password="demo-pass-1001",
        reviewer_username="demo-reviewer",
        reviewer_password="demo-pass-1003",
        amount_minor=25900,
        description="承运商确认包裹丢失，申请全行退款。",
        customer_material="承运商电话告知包裹已判定丢失，我没有收到商品。",
        shipment_status="LOST",
        shipment_conclusion="LOST",
        shipment_events=(("SHIPMENT_CREATED", "2026-09-10 12:00:00.000000"), ("CARRIER_LOST", "2026-09-12 07:30:00.000000")),
        verification=(
            "CONFIRMED",
            "已核对本地合成物流记录：承运商结论为 LOST，未见签收事件。",
        ),
        expected_status="RECONCILING",
        expected_authorization="CONSUMED",
        advance="approve-unknown",
    ),
    "unknown-recovery": Scenario(
        name="unknown-recovery",
        product_name="演示商品 · 桌面音箱",
        title="丢响应的一次性样本：同 operation 查询后恢复成功",
        merchant_id="M-1001",
        customer_username="demo-customer-2",
        customer_password="demo-pass-1002",
        reviewer_username="demo-reviewer",
        reviewer_password="demo-pass-1003",
        amount_minor=8800,
        description="承运商确认包裹丢失，申请全行退款（一次性恢复验证样本）。",
        customer_material="承运商确认丢失，我没有收到商品。",
        shipment_status="LOST",
        shipment_conclusion="LOST",
        shipment_events=(("SHIPMENT_CREATED", "2026-09-10 12:00:00.000000"), ("CARRIER_LOST", "2026-09-12 07:30:00.000000")),
        verification=None,
        expected_status="CLOSED_SUCCESS",
        expected_authorization="CONSUMED",
        advance="approve-lost-response",
    ),
    "success-refund": Scenario(
        name="success-refund",
        product_name="演示商品 · 保温杯",
        variant_text="雾蓝 · 500ml",
        title="人工审批后完成全行模拟退款",
        merchant_id="M-1001",
        customer_username="demo-customer",
        customer_password="demo-pass-1001",
        reviewer_username="demo-reviewer",
        reviewer_password="demo-pass-1003",
        amount_minor=17600,
        description="承运商确认包裹丢失，申请全行退款并已完成审批。",
        customer_material="承运商确认包裹丢失，我没有收到商品。",
        shipment_status="LOST",
        shipment_conclusion="LOST",
        shipment_events=(("SHIPMENT_CREATED", "2026-09-10 12:00:00.000000"), ("CARRIER_LOST", "2026-09-12 07:30:00.000000")),
        verification=(
            "CONFIRMED",
            "已核对本地合成物流记录：承运商结论为 LOST，未见签收事件。",
        ),
        expected_status="CLOSED_SUCCESS",
        expected_authorization="CONSUMED",
        advance="approve",
    ),
}

#: The six samples the demonstration shows, in the order a reviewer would meet them.
DISPLAY_SCENARIOS = (
    "lost-review",
    "signed-conflict",
    "damage-review",
    "waiting-info",
    "unknown-refund",
    "success-refund",
)

#: Every bundle the controlled import installs; the same four the C07.1 driver names, so a
#: fixture that stopped being importable is a missing-name failure rather than a shorter run.
POLICY_BUNDLES = (
    "policy-logistics-2026.08",
    "policy-logistics-2026.09",
    "policy-damage-2026.08",
    "policy-damage-2026.09",
    "policy-demo-m1002-logistics-2026.08",
    "policy-demo-m1002-logistics-2026.09",
)

#: The two demo service tokens this driver mints. The secret is the local demo identity
#: secret both Java services ship (``application.yml``), not a deployment credential.
JWT_SECRET = "resolveflow-core-demo-identity-secret"  # noqa: S105 - a development default
SERVICE_ISSUER = "resolveflow-demo-identity"
SERVICE_AUDIENCE = "resolveflow-service"

POLICY_READ_SCOPE = "policy:read"


def scenario_or_refuse(name: str) -> Scenario:
    if name not in SCENARIOS:
        raise DemoRefused(f"unknown scenario {name!r}; known: {', '.join(sorted(SCENARIOS))}")
    return SCENARIOS[name]


def agent_run_id(case_id: str, input_revision: int) -> str:
    """The run id Case derives, taken from the production derivation rather than re-implemented.

    An inlined ``uuid5`` with the wrong namespace produces a valid-looking id Case has never
    heard of, which then reads as "the credential route says my run does not exist".
    """
    from resolveflow.runtime.runs import agent_run_id_for

    return agent_run_id_for(case_id, input_revision)


def b64(raw: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def mint_service_token(subject: str, *, scope: str | None = None, seconds: int = 900) -> str:
    """A service token signed with the demo secret, for the ``/internal`` surface.

    Minted here rather than imported from the C05/C06 drivers: those modules carry the
    shared environment's container names at import time, and a demonstration driver that
    pulled them in would be one rename away from reading the shared database.
    """
    import hashlib
    import hmac

    issued = int(time.time())
    claims: dict[str, Any] = {
        "sub": subject,
        "aud": SERVICE_AUDIENCE,
        "iss": SERVICE_ISSUER,
        "iat": issued,
        "exp": issued + seconds,
    }
    if scope is not None:
        claims["scope"] = scope
    header = b64(b'{"alg":"HS256","typ":"JWT"}')
    payload = b64(json.dumps(claims, ensure_ascii=False).encode("utf-8"))
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{b64(signature)}"


# --------------------------------------------------------------------------- seeding


def _sql_text(value: str | None) -> str:
    """A SQL string literal, or NULL. The seed's only quote is escaped rather than interpolated."""
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def mint_line_id(settings: Settings, index: int) -> str:
    """A fresh numeric line id, marked as this driver's own by its leading 9.

    Numeric because the existing drivers' line ids are, and the leading 9 so a later look at
    the database can tell a demonstration line from the migration seed.
    """
    candidate = f"9{datetime.now(UTC).strftime('%m%d%H%M')}{index:02d}"
    while mysql_scalar(f"SELECT COUNT(*) FROM commerce_db.order_line WHERE line_id = '{candidate}'", settings) != "0":
        candidate += "9"
    return candidate


def seed_line(settings: Settings, scenario: Scenario, index: int) -> str:
    """Mint one synthetic order, line, ledger row, refund slot and shipment story.

    Commerce has no order-creation route, so these rows are seeded directly — the manual
    allows exactly this for a *new, synthetic* order line and forbids nothing else. What the
    driver must never do is write a case status, an authorization, a refund ledger row or an
    Agent record with SQL; everything after this goes through the authenticated API.
    """
    order_id = str(uuid.uuid4())
    line_id = mint_line_id(settings, index)
    sku, category = mysql_rows("SELECT sku, category FROM commerce_db.order_line WHERE line_id = '7001'", settings)[0]
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    # The customer the seeded line belongs to matches the demo account that will open the case.
    customer_id = {
        "demo-customer": "C-2002",
        "demo-customer-2": "C-2003",
        "demo-customer-m2": "C-2004",
    }[scenario.customer_username]
    statements = [
        "START TRANSACTION",
        "INSERT INTO commerce_db.orders (order_id, merchant_id, customer_id, order_status, currency, paid_at,"
        f" created_at) VALUES ('{order_id}', '{scenario.merchant_id}', '{customer_id}', 'PAID', 'CNY', '{now}',"
        f" '{now}')",
        "INSERT INTO commerce_db.order_line (line_id, order_id, merchant_id, customer_id, sku, product_name,"
        " variant_text, category, quantity, line_paid_amount, currency, paid_at, order_status, version) VALUES"
        f" ('{line_id}', '{order_id}', '{scenario.merchant_id}', '{customer_id}', '{sku}-DEMO-{line_id}',"
        f" {_sql_text(scenario.product_name)}, {_sql_text(scenario.variant_text)},"
        f" '{category}', 1, {scenario.amount_minor}, 'CNY', '{now}', 'PAID', 1)",
        "INSERT INTO commerce_db.payment_ledger (order_id, paid_amount, refunded_amount,"
        f" reserved_refund_amount, version) VALUES ('{order_id}', {scenario.amount_minor}, 0, 0, 1)",
        "INSERT INTO commerce_db.line_refund (line_id, state, operation_id, version, updated_at)"
        f" VALUES ('{line_id}', 'FREE', NULL, 1, '{now}')",
        "INSERT INTO commerce_db.shipment (line_id, status, carrier_conclusion, source_version)"
        f" VALUES ('{line_id}', '{scenario.shipment_status}', '{scenario.shipment_conclusion}',"
        f" {len(scenario.shipment_events)})",
    ]
    for version, (code, occurred_at) in enumerate(scenario.shipment_events, start=1):
        statements.append(
            "INSERT INTO commerce_db.shipment_event (line_id, code, occurred_at, source_version)"
            f" VALUES ('{line_id}', '{code}', '{occurred_at}', {version})"
        )
    statements.append("COMMIT")
    mysql_rows("; ".join(statements) + ";", settings)
    return line_id


def discard_seeded_line(settings: Settings, line_id: str, order_id: str) -> bool:
    """Remove a synthetic line this driver minted and never used.

    Only ever called for rows the driver itself created moments earlier and for which no case
    exists: the demonstration seeds orders directly because Commerce has no create route, so a
    seeding step that fails before the case exists would otherwise leave a paid line with no
    case behind, and a reader would have no way to tell it from a real one. Nothing that any
    case refers to is ever touched.
    """
    referenced = mysql_scalar(
        f"SELECT COUNT(*) FROM case_db.aftersale_case WHERE line_id = '{line_id}'", settings
    )
    if referenced != "0":
        return False
    mysql_rows(
        "; ".join(
            [
                "START TRANSACTION",
                f"DELETE FROM commerce_db.shipment_event WHERE line_id = '{line_id}'",
                f"DELETE FROM commerce_db.shipment WHERE line_id = '{line_id}'",
                f"DELETE FROM commerce_db.line_refund WHERE line_id = '{line_id}'",
                f"DELETE FROM commerce_db.order_line WHERE line_id = '{line_id}'",
                f"DELETE FROM commerce_db.payment_ledger WHERE order_id = '{order_id}'",
                f"DELETE FROM commerce_db.orders WHERE order_id = '{order_id}'",
                "COMMIT",
            ]
        )
        + ";",
        settings,
    )
    return True


def backfill_display_fields(settings: Settings, document: dict[str, Any], log: Log) -> None:
    """Give the recorded demo lines their synthetic product name and variant.

    Only the lines this dataset's manifest owns, and only those two columns: the amounts, times,
    statuses, revisions and every referenced original stay exactly as they were, so no citation and
    no evidence hash can move. The shared fixture lines (7001 and friends) are deliberately not
    touched — a review of *them* should show what the seed actually says. Repeatable: the same
    values are written again on every `prepare`.
    """
    updated: list[str] = []
    for sample in document.get("samples", []):
        scenario = SCENARIOS.get(sample.get("scenario", ""))
        if scenario is None or not sample.get("line_id"):
            continue
        rows = mysql_rows(
            f"SELECT product_name, variant_text FROM commerce_db.order_line WHERE line_id = '{sample['line_id']}'",
            settings,
        )
        if not rows:
            continue
        if rows[0][0] == scenario.product_name and (rows[0][1] or None) == scenario.variant_text:
            continue
        mysql_rows(
            "UPDATE commerce_db.order_line"
            f" SET product_name = {_sql_text(scenario.product_name)},"
            f" variant_text = {_sql_text(scenario.variant_text)}"
            f" WHERE line_id = '{sample['line_id']}'",
            settings,
        )
        updated.append(sample["line_id"])
    if updated:
        log.note("display fields set on this dataset's own lines: " + ", ".join(updated))


def pinned_bundle(settings: Settings, case_id: str) -> tuple[str, str]:
    rows = mysql_rows(
        "SELECT cp.bundle_id, pm.manifest_hash FROM case_db.case_policy_bundle cp"
        " JOIN case_db.case_policy_manifest pm ON pm.case_id = cp.case_id"
        f" WHERE cp.case_id = '{case_id}'",
        settings,
    )
    if len(rows) != 1:
        raise RuntimeError(f"expected exactly one pinned policy bundle for {case_id}, found {len(rows)}")
    return rows[0][0], rows[0][1]


# --------------------------------------------------------------------------- preflight


def preflight(
    settings: Settings,
    *,
    case_id: str,
    run_id: str,
    input_revision: int,
    line_id: str,
    tool_calls: tuple[tuple[str, dict[str, Any]], ...],
) -> dict[str, dict[str, Any]]:
    """Read, for real, the sources this run's script is going to cite.

    The script is a fixed list, so the citations have to exist before it runs. They are
    produced by making the same reads a run makes — through the run's own tool credential —
    and the observation ids are stable for a given tool, so the script cites the very
    observation the run will also make rather than an invented one. That distinction is the
    whole reason this is a preflight and not a fixture.
    """
    from resolveflow.harness.mcp_client import McpToolExecutor
    from resolveflow.tools.credential import credential_source

    source = credential_source(
        case_base_url=settings.case_url,
        run_id=run_id,
        case_id=case_id,
        input_revision=input_revision,
        service_token=mint_service_token("agent-service"),
        static_token=None,
    )
    executor = McpToolExecutor(
        python=str(AGENT_PYTHON),
        line_id=line_id,
        run_id=run_id,
        case_id=case_id,
        input_revision=input_revision,
        case_base_url=settings.case_url,
        commerce_base_url=settings.commerce_url,
        credential_source=source,
        env_extra={"PYTHONPATH": str(AGENT_SRC)},
    )
    citations: dict[str, dict[str, Any]] = {}
    try:
        for tool_name, arguments in tool_calls:
            observation = executor.call_tool(run_id=run_id, tool_name=tool_name, arguments=arguments)
            if observation.error is not None:
                raise RuntimeError(
                    f"preflight {tool_name} answered {observation.error.code}: {observation.error.message}"
                )
            citation = {
                key: getattr(observation, key)
                for key in ("observation_id", "source_ref", "source_version", "content_hash")
            }
            if any(value is None for value in citation.values()):
                raise RuntimeError(f"preflight {tool_name} produced no citable version/hash")
            citations[tool_name] = citation
    finally:
        executor.close()
    return citations


def policy_ref(settings: Settings, *, merchant_id: str, bundle_id: str, manifest_hash: str,
               rule_id: str, query: str) -> dict[str, str]:
    """One pinned policy rule, found the way the run finds it: dense search over this PG."""
    from resolveflow.policies.index import PolicyIndex
    from resolveflow.policies.retrieval import embedder
    from resolveflow.runtime.db import Database

    database = Database(settings.agent_dsn)
    try:
        hits = PolicyIndex(database).search(
            merchant_id=merchant_id,
            bundle_ids=[bundle_id],
            manifest_hash=manifest_hash,
            query=query,
            path="dense",
            top_k=5,
            embedder=embedder(str(EMBEDDING_PATH)),
        )
    finally:
        database.close()
    hit = next((candidate for candidate in hits if candidate.rule_id == rule_id), None)
    if hit is None:
        raise RuntimeError(
            f"the demo policy index did not return {rule_id} from {bundle_id} for {query!r}; "
            f"got {[candidate.rule_id for candidate in hits]}"
        )
    return {key: getattr(hit, key) for key in ("bundle_id", "version", "rule_id", "chunk_id", "content_hash")}


# --------------------------------------------------------------------------- mock scripts


def build_script(
    scenario: Scenario,
    *,
    citations: dict[str, dict[str, Any]],
    policies: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """The decisions for one scenario, bound to the run's real observations and rules."""
    if scenario.name in {"lost-review", "unknown-refund", "unknown-recovery", "success-refund"}:
        lost = policies["R-LOST-001"]
        shipment = citations[TOOL_GET_SHIPMENT]
        shipment_id = shipment["observation_id"]
        return [
            {"kind": "READ_TOOL", "tool_name": TOOL_GET_SHIPMENT, "arguments": {"limit": 3}},
            {"kind": "SEARCH_POLICY", "query": "物流丢失 全额退款", "arguments": {"top_k": 5}},
            {
                "kind": "PROPOSE",
                "case_type": "LOGISTICS",
                "recommended_action": "REFUND",
                "reason_codes": ["CARRIER_LOST"],
                "summary": "合成物流记录显示承运商结论为 LOST 且无有效签收，按钉住的丢失条款建议全行退款。",
                "evidence_refs": [shipment],
                "policy_refs": [lost],
                "review_findings": [
                    {
                        "kind": "FACT",
                        "text": "已保存的物流记录显示承运商结论为 LOST，并且没有签收事件。",
                        "observation_ids": [shipment_id],
                    }
                ],
            },
        ]
    if scenario.name == "signed-conflict":
        shipment = citations[TOOL_GET_SHIPMENT]
        shipment_id = shipment["observation_id"]
        evidence = citations[TOOL_GET_EVIDENCE]
        signed = policies["R-SIGNED-001"]
        return [
            {"kind": "READ_TOOL", "tool_name": TOOL_GET_SHIPMENT, "arguments": {"limit": 3}},
            {"kind": "READ_TOOL", "tool_name": TOOL_GET_EVIDENCE, "arguments": {}},
            {"kind": "SEARCH_POLICY", "query": "已签收 客户未收到 人工核验", "arguments": {"top_k": 5}},
            {
                "kind": "PROPOSE",
                "case_type": "LOGISTICS",
                "recommended_action": "MANUAL_REVIEW",
                "reason_codes": ["SIGNED_WITH_CUSTOMER_DISPUTE"],
                "summary": "物流有有效签收记录，而客户主张未收到：两个已保存来源互相矛盾，按签收条款转人工核验，"
                           "不按丢失执行退款。",
                "evidence_refs": [shipment, evidence],
                "policy_refs": [signed],
                "review_findings": [
                    {
                        "kind": "CONFLICT",
                        "text": "物流侧存在有效签收记录，客户材料主张从未收到，两者不能同时成立。",
                        "observation_ids": [shipment_id, evidence["observation_id"]],
                    }
                ],
            },
        ]
    if scenario.name == "damage-review":
        evidence = citations[TOOL_GET_EVIDENCE]
        return [
            {"kind": "READ_TOOL", "tool_name": TOOL_GET_EVIDENCE, "arguments": {}},
            {"kind": "SEARCH_POLICY", "query": "到货破损 图片核验 转人工", "arguments": {"top_k": 5}},
            {
                "kind": "PROPOSE",
                "case_type": "DAMAGED",
                "recommended_action": "REQUEST_INFO",
                "reason_codes": ["DAMAGE_NOT_VERIFIED"],
                "summary": "客户主张到货破损，但材料里没有任何人工核验结论；按破损条款要求先补齐可核验的破损证据，"
                           "不把客户描述写成已验证事实。",
                # No policy reference: this merchant's pinned bundle has no damage rule, and
                # inventing one from another bundle is exactly what the contract forbids. A
                # non-REFUND proposal is not required to cite a rule, so the honest proposal is
                # "route this to a person", with the gap named.
                "evidence_refs": [evidence],
                "missing_evidence": ["reviewed-evidence:破损部位与包装的人工核验结论"],
                "review_findings": [
                    {
                        "kind": "INFERENCE",
                        "text": "本工单当前只有客户对破损的描述，尚无人工核验记录，破损事实未确认。",
                        "observation_ids": [evidence["observation_id"]],
                    }
                ],
            },
        ]
    if scenario.name == "waiting-info":
        shipment = citations[TOOL_GET_SHIPMENT]
        return [
            {"kind": "READ_TOOL", "tool_name": TOOL_GET_SHIPMENT, "arguments": {"limit": 3}},
            {
                "kind": "ASK_CUSTOMER",
                "reason_codes": ["NEED_TRACKING_OR_CARRIER_STATEMENT"],
                "questions": [
                    {
                        "question_id": f"q-{scenario.name}-carrier",
                        "field": "logistics_evidence",
                        "prompt": "请提供承运商对这次运输异常的书面结论，或最近的物流查询截图。",
                    }
                ],
                "summary": "现有记录只显示运输中，缺少能判断是否丢失的承运商结论。",
            },
        ]
    raise DemoRefused(f"scenario {scenario.name!r} has no script builder")


# --------------------------------------------------------------------------- stage


def start_stage(settings: Settings, log: Log, *, build: bool) -> None:
    """Bring up the demo infrastructure and the three always-on demo services."""
    guard(settings)
    settings.runtime().mkdir(parents=True, exist_ok=True)

    log.section("demo infrastructure (project resolveflow-review-demo)")
    up = compose("up", "-d", settings=settings)
    if up.returncode != 0:
        raise DemoRefused(f"docker compose up failed: {up.stderr.strip()[-400:]}")
    log.step("the demo compose project is up", True, settings.project)

    healthy = wait_for(
        "demo datastores",
        lambda: container_health("mysql", settings) == "healthy" and container_health("postgres", settings) == "healthy",
        timeout=180.0,
    )
    log.step("demo MySQL and PostgreSQL are healthy", healthy)
    if not healthy:
        raise DemoRefused("the demo datastores never became healthy")
    namesrv = wait_for("demo name server", lambda: tcp_open("127.0.0.1", settings.ports["namesrv"]), timeout=60.0)
    log.step("the demo RocketMQ name server listens", namesrv, settings.namesrv)
    if not namesrv:
        raise DemoRefused("the demo name server never listened")

    if build:
        log.section("build (current sources, no test run)")
        built = run(
            [
                "cmd",
                "/c",
                str(ROOT / "java" / "mvnw.cmd"),
                "-f",
                str(ROOT / "java" / "pom.xml"),
                "-B",
                "-ntp",
                "-DskipTests",
                "-pl",
                "gateway,case-service,commerce-service",
                "-am",
                "package",
            ],
            timeout=1800,
        )
        ok = built.returncode == 0
        log.step("gateway, case-service and commerce-service jars built", ok, "" if ok else built.stdout[-500:])
        if not ok:
            raise DemoRefused("the Java jars did not build")

    # The controlled policy import: the same operator command the C07.1 driver runs, pointed at
    # the demo database. It is a one-shot process because it ends with System.exit.
    log.section("policies into the demo case database")
    imported = run(
        [
            str(java_home() / "bin" / "java"),
            "-jar",
            str(CASE_JAR),
            "--spring.main.web-application-type=none",
            "--resolveflow.policy.import-dir=fixtures/policies/bundles",
        ],
        timeout=300,
        env=child_env(CASE_DB_URL=settings.case_dsn, CASE_DB_USER="case_svc", CASE_DB_PASSWORD="case_svc"),
    )
    log.step("the controlled policy import accepted every fixture", imported.returncode == 0, _import_detail(imported))
    if imported.returncode != 0:
        raise DemoRefused("the policy import refused a fixture")

    log.section("demo services")
    start_case_service(settings, log)
    start_commerce_service(settings, log)
    start_gateway(settings, log)

    log.section("policy index in the demo PostgreSQL")
    indexed = run(
        [
            str(AGENT_PYTHON),
            str(ROOT / "scripts" / "policy_index_ingest.py"),
            "--case-base-url",
            settings.case_url,
            "--service-token",
            mint_service_token("agent-service", scope=POLICY_READ_SCOPE),
            "--dsn",
            settings.agent_dsn,
            "--replace",
            *[item for bundle in POLICY_BUNDLES for item in ("--bundle", bundle)],
        ],
        timeout=900,
        env=child_env(RESOLVEFLOW_EMBEDDING_PATH=str(EMBEDDING_PATH)),
    )
    ok = "RESULT: INDEXED" in indexed.stdout
    log.step("the demo policy index is READY", ok, "" if ok else indexed.stdout[-500:])
    if not ok:
        raise DemoRefused("the demo policy index did not build; the citations would prove nothing")


def _import_detail(completed: subprocess.CompletedProcess) -> str:
    for line in (completed.stdout or "").splitlines():
        if "policy import:" in line:
            return line.split("policy import:", 1)[1].strip()[:200]
    return (completed.stderr or "")[-200:]


def container_health(role: str, settings: Settings) -> str:
    try:
        container = live_container(role, settings)
    except DemoRefused:
        return ""
    inspect = run(["docker", "inspect", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{end}}",
                   container], timeout=60)
    return inspect.stdout.strip()


def owns_port(settings: Settings, name: str, port: int) -> bool:
    """Whether a recorded process still owns the port assigned to it."""
    entry = next((item for item in read_owned(settings) if item["name"] == name), None)
    if entry is None:
        return False
    owners = set(pids_on_port(port))
    return bool(owners) and (
        str(entry["pid"]) in owners or str(entry.get("owner_pid") or "") in owners
    )


def healthy_and_owned(settings: Settings, name: str, port: int, url: str) -> bool:
    """Whether this driver already has a healthy process of its own on that port.

    Re-running `prepare` must not start a second copy of a service: the copy that loses the bind
    race would exit, the health check would pass on the winner, and the record would name the
    loser. That is exactly how an earlier version left a case-service entry pointing at a process
    that was already gone.
    """
    return owns_port(settings, name, port) and health(url)


def refuse_if_port_held(settings: Settings, name: str, port: int) -> None:
    squatters = pids_on_port(port)
    if squatters:
        raise DemoRefused(
            f"port {port} is held by pid(s) {', '.join(squatters)} and they are not this driver's "
            f"{name}; stop them explicitly, then re-run"
        )


def start_case_service(settings: Settings, log: Log) -> None:
    if healthy_and_owned(settings, "case-service", settings.ports["case"], settings.case_url):
        log.step("demo case-service is already up under this driver", True, settings.case_url)
        return
    stop_owned(settings, "case-service", log=log)
    refuse_if_port_held(settings, "case-service", settings.ports["case"])
    start_process(
        settings,
        "case-service",
        [
            str(java_home() / "bin" / "java"),
            "-jar",
            str(CASE_JAR),
            f"--server.port={settings.ports['case']}",
            f"--resolveflow.commerce.base-url={settings.commerce_url}",
            f"--resolveflow.agent.base-url={settings.agent_url}",
            "--resolveflow.dispatch.enabled=true",
            "--resolveflow.dispatch.poll-interval-ms=500",
            f"--resolveflow.events.namesrv={settings.namesrv}",
            "--resolveflow.events.publisher.enabled=true",
            "--resolveflow.events.consumer.enabled=true",
            "--resolveflow.events.outbox.delivery-enabled=true",
            "--resolveflow.events.outbox.poll-interval-ms=300",
        ],
        child_env(
            CASE_DB_URL=settings.case_dsn,
            CASE_DB_USER="case_svc",
            CASE_DB_PASSWORD="case_svc",
            COMMERCE_BASE_URL=settings.commerce_url,
            AGENT_BASE_URL=settings.agent_url,
            REVIEW_CACHE_ENABLED="false",
        ),
        settings.ports["case"],
    )
    ok = wait_for("case-service", lambda: health(settings.case_url), timeout=240.0)
    log.step("demo case-service is healthy", ok, settings.case_url)
    if ok:
        record_port_owner(settings, "case-service")
    if not ok:
        raise DemoRefused("the demo case-service never became healthy")


def start_commerce_service(settings: Settings, log: Log) -> None:
    if healthy_and_owned(settings, "commerce-service", settings.ports["commerce"], settings.commerce_url):
        log.step("demo commerce-service is already up under this driver", True, settings.commerce_url)
        return
    stop_owned(settings, "commerce-service", log=log)
    refuse_if_port_held(settings, "commerce-service", settings.ports["commerce"])
    start_process(
        settings,
        "commerce-service",
        [
            str(java_home() / "bin" / "java"),
            "-jar",
            str(COMMERCE_JAR),
            f"--server.port={settings.ports['commerce']}",
            f"--resolveflow.provider.base-url={settings.agent_url}",
            f"--resolveflow.events.namesrv={settings.namesrv}",
            "--resolveflow.events.consumer.enabled=true",
            "--resolveflow.events.publisher.enabled=true",
            "--resolveflow.events.outbox.delivery-enabled=true",
            "--resolveflow.events.outbox.poll-interval-ms=300",
            "--resolveflow.refund.dispatch-enabled=true",
            "--resolveflow.refund.reconcile-enabled=true",
            "--resolveflow.refund.poll-interval-ms=1000",
        ],
        child_env(
            COMMERCE_DB_URL=settings.commerce_dsn,
            COMMERCE_DB_USER="commerce",
            COMMERCE_DB_PASSWORD="commerce",
            REFUND_PROVIDER_URL=settings.agent_url,
        ),
        settings.ports["commerce"],
    )
    ok = wait_for("commerce-service", lambda: health(settings.commerce_url), timeout=240.0)
    log.step("demo commerce-service is healthy", ok, settings.commerce_url)
    if ok:
        record_port_owner(settings, "commerce-service")
    if not ok:
        raise DemoRefused("the demo commerce-service never became healthy")


def start_gateway(settings: Settings, log: Log) -> None:
    if healthy_and_owned(settings, "gateway", settings.ports["gateway"], settings.gateway_url):
        log.step("demo gateway is already up under this driver", True, settings.gateway_url)
        return
    stop_owned(settings, "gateway", log=log)
    refuse_if_port_held(settings, "gateway", settings.ports["gateway"])
    start_process(
        settings,
        "gateway",
        [
            str(java_home() / "bin" / "java"),
            "-jar",
            str(GATEWAY_JAR),
            f"--server.port={settings.ports['gateway']}",
        ],
        child_env(RESOLVEFLOW_CASE_BASE_URL=settings.case_url),
        settings.ports["gateway"],
    )
    ok = wait_for("gateway", lambda: health(settings.gateway_url), timeout=180.0)
    log.step("demo gateway is healthy", ok, settings.gateway_url)
    if ok:
        record_port_owner(settings, "gateway")
    if not ok:
        raise DemoRefused("the demo gateway never became healthy")


def health(base_url: str) -> bool:
    status, answer = http("GET", f"{base_url}/actuator/health", timeout=3)
    return status == 200 and isinstance(answer, dict) and answer.get("status") == "UP"


def start_agent(settings: Settings, scenario: Scenario, script_path: Path, log: Log) -> None:
    """Start the Agent with one scenario's script. The script is the run binding.

    The previous Agent is stopped first: a process holding another scenario's script would
    happily answer this run's dispatch, and the resulting proposal would look like a model
    decision while being a stale one.
    """
    stopped = stop_owned(settings, "agent-readonly", log=log)
    stopped += stop_owned(settings, "agent-live", log=log)
    stopped += stop_owned(settings, "agent", log=log)
    if stopped:
        log.note("stopped the previous Agent: " + ", ".join(stopped))
    squatters = pids_on_port(settings.ports["agent"])
    if squatters:
        # A loud refusal, because the alternative is the worst failure this driver has: an
        # older Agent, holding another scenario's script, answers this run's dispatch and the
        # resulting proposal looks like a model decision while being a stale one.
        raise DemoRefused(
            f"port {settings.ports['agent']} is still held by pid(s) {', '.join(squatters)} after stopping "
            "this driver's own Agent. That process is not ours to kill; stop it explicitly, then re-run."
        )
    provider_db = settings.runtime() / "refund-provider.sqlite3"
    env = child_env(
        RESOLVEFLOW_AGENT_DB=settings.agent_dsn,
        RESOLVEFLOW_CASE_BASE_URL=settings.case_url,
        RESOLVEFLOW_COMMERCE_BASE_URL=settings.commerce_url,
        RESOLVEFLOW_PROVIDER_DB=str(provider_db),
        RESOLVEFLOW_INVESTIGATION_ENABLED="1",
        RESOLVEFLOW_MODEL_MODE="mock",
        RESOLVEFLOW_MOCK_SCRIPT=str(script_path),
        RESOLVEFLOW_POLICY_INDEX="1",
        RESOLVEFLOW_EMBEDDING_PATH=str(EMBEDDING_PATH),
        # The fault surface exists so the demonstration can make the provider lose a response.
        # It is a lab route and this is a lab: nothing here is a deployment.
        RESOLVEFLOW_LAB_ROUTES="1",
    )
    for name in (
        "RESOLVEFLOW_MODEL_ENDPOINT",
        "RESOLVEFLOW_MODEL_ID",
        "RESOLVEFLOW_MODEL_API_KEY",
        "RESOLVEFLOW_MODEL_PROVIDER",
        "RESOLVEFLOW_MODEL_CEILING_PARAMETER",
        "RESOLVEFLOW_MODEL_CONTEXT_WINDOW_TOKENS",
    ):
        env.pop(name, None)
    start_process(
        settings,
        "agent",
        [
            str(AGENT_PYTHON),
            "-m",
            "uvicorn",
            "resolveflow.api.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(settings.ports["agent"]),
            "--log-level",
            # `info` rather than `warning`: this is a demonstration, and the loop's own reasons
            # (which action it refused and why) are the most useful thing in the process log.
            os.environ.get("REVIEWER_DEMO_AGENT_LOG_LEVEL", "info"),
        ],
        env,
        settings.ports["agent"],
    )
    ready = wait_for("agent", lambda: agent_health(settings), timeout=180.0)
    log.step("demo Agent is healthy with this scenario's mock script", ready, script_path.name)
    if ready:
        # The launcher's child is what holds the port; recording it is what lets `stop` and the
        # next `run` retire this Agent instead of leaving it to answer a later run's dispatch.
        record_port_owner(settings, "agent")
    if not ready:
        raise DemoRefused("the demo Agent never became healthy; check the process log")


def agent_health(settings: Settings) -> bool:
    status, answer = http("GET", f"{settings.agent_url}/health", timeout=3)
    return status == 200 and isinstance(answer, dict) and answer.get("status") == "UP"


def start_readonly_agent(settings: Settings, log: Log, *, live: bool = False) -> None:
    """Serve the browser API; explicitly opt into live investigation with the user's key.

    The default only reads persisted records. Live mode uses the fixed official DeepSeek endpoint,
    while scenario commands replace either process before binding their isolated mock script.
    """
    process_name = "agent-live" if live else "agent-readonly"
    if live and not os.environ.get("RESOLVEFLOW_MODEL_API_KEY"):
        raise DemoRefused("DeepSeek key is missing; set Deepseek_API_KEY in your user environment and run demo.ps1 -Live")
    if owns_port(settings, process_name, settings.ports["agent"]) and agent_health(settings):
        log.step(f"{process_name} is already up under this driver", True, settings.agent_url)
        return
    stop_owned(settings, "agent-readonly", log=log)
    stop_owned(settings, "agent-live", log=log)
    stopped = stop_owned(settings, "agent", log=log)
    if stopped:
        log.note("stopped the scenario Agent before entering browser experience mode: " + ", ".join(stopped))
    refuse_if_port_held(settings, "read-only Agent API", settings.ports["agent"])

    provider_db = settings.runtime() / "refund-provider.sqlite3"
    env = child_env(
        RESOLVEFLOW_AGENT_DB=settings.agent_dsn,
        RESOLVEFLOW_CASE_BASE_URL=settings.case_url,
        RESOLVEFLOW_COMMERCE_BASE_URL=settings.commerce_url,
        RESOLVEFLOW_PROVIDER_DB=str(provider_db),
        RESOLVEFLOW_INVESTIGATION_ENABLED="1" if live else "0",
        RESOLVEFLOW_LAB_ROUTES="1",
    )
    for name in (
        "RESOLVEFLOW_MODEL_MODE",
        "RESOLVEFLOW_MOCK_SCRIPT",
        "RESOLVEFLOW_MODEL_ENDPOINT",
        "RESOLVEFLOW_MODEL_ID",
        "RESOLVEFLOW_MODEL_API_KEY",
        "RESOLVEFLOW_MODEL_PROVIDER",
        "RESOLVEFLOW_MODEL_CEILING_PARAMETER",
        "RESOLVEFLOW_MODEL_CONTEXT_WINDOW_TOKENS",
    ):
        env.pop(name, None)
    if live:
        env.update(
            RESOLVEFLOW_MODEL_MODE="live",
            RESOLVEFLOW_MODEL_PROVIDER="deepseek",
            RESOLVEFLOW_MODEL_ENDPOINT="https://api.deepseek.com/chat/completions",
            RESOLVEFLOW_MODEL_ID="deepseek-flash",
            RESOLVEFLOW_MODEL_CONTEXT_WINDOW_TOKENS="32768",
            RESOLVEFLOW_MODEL_API_KEY=os.environ["RESOLVEFLOW_MODEL_API_KEY"],
            RESOLVEFLOW_POLICY_INDEX="1",
            RESOLVEFLOW_EMBEDDING_PATH=str(EMBEDDING_PATH),
        )
    start_process(
        settings,
        process_name,
        [
            str(AGENT_PYTHON),
            "-m",
            "uvicorn",
            "resolveflow.api.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(settings.ports["agent"]),
            "--log-level",
            os.environ.get("REVIEWER_DEMO_AGENT_LOG_LEVEL", "info"),
        ],
        env,
        settings.ports["agent"],
    )
    ready = wait_for(process_name, lambda: agent_health(settings), timeout=180.0)
    log.step(f"{process_name} is healthy", ready, settings.agent_url)
    if ready:
        record_port_owner(settings, process_name)
    else:
        raise DemoRefused(f"{process_name} never became healthy; check its process log")


def frontend_health(settings: Settings) -> bool:
    try:
        request = urllib.request.Request(settings.frontend_url, method="GET")
        with urllib.request.urlopen(request, timeout=3) as response:
            body = response.read(64_000)
            return response.status == 200 and b'id="app"' in body
    except (OSError, urllib.error.URLError):
        return False


def start_frontend(settings: Settings, log: Log) -> None:
    """Start the desktop Vite page against the isolated demo gateway."""
    if owns_port(settings, "frontend", settings.ports["frontend"]) and frontend_health(settings):
        log.step("desktop frontend is already up under this driver", True, settings.frontend_url)
        return
    stop_owned(settings, "frontend", log=log)
    refuse_if_port_held(settings, "desktop frontend", settings.ports["frontend"])

    pnpm = shutil.which("pnpm.cmd") or shutil.which("pnpm")
    if pnpm is None:
        raise DemoRefused("pnpm is not installed or is not on PATH; install the version pinned by web/package.json")
    if not (ROOT / "web" / "node_modules").is_dir():
        log.section("frontend dependencies")
        installed = run(["cmd", "/c", pnpm, "--dir", "web", "install", "--frozen-lockfile"], timeout=900)
        log.step("frontend dependencies installed from the lockfile", installed.returncode == 0)
        if installed.returncode != 0:
            raise DemoRefused(f"pnpm install failed: {(installed.stderr or installed.stdout)[-400:]}")

    env = child_env(VITE_API_PROXY=settings.gateway_url, VITE_PORT=str(settings.ports["frontend"]))
    start_process(
        settings,
        "frontend",
        ["cmd", "/c", pnpm, "--dir", "web", "dev", "--", "--host", "127.0.0.1"],
        env,
        settings.ports["frontend"],
    )
    ready = wait_for("desktop frontend", lambda: frontend_health(settings), timeout=120.0)
    log.step("desktop frontend is ready", ready, settings.frontend_url)
    if ready:
        record_port_owner(settings, "frontend")
    else:
        raise DemoRefused("the desktop frontend never became ready; check its process log")


# --------------------------------------------------------------------------- sample state


def case_state(settings: Settings, case_id: str) -> dict[str, Any]:
    """What the demo database says about one case: the record of what actually happened."""
    rows = mysql_rows(
        "SELECT status, input_revision, version, IFNULL(description, '') FROM case_db.aftersale_case"
        f" WHERE case_id = '{case_id}'",
        settings,
    )
    if not rows:
        return {"exists": False}
    status, input_revision, version, description = rows[0]
    # `recommended_action` lives inside the proposal payload, which is the document the case
    # service stored; reading it back out is reading the record, not re-deriving it.
    proposal = mysql_rows(
        "SELECT status, origin, refusal_reason,"
        " IFNULL(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.recommended_action')), '')"
        f" FROM case_db.case_proposal WHERE case_id = '{case_id}' ORDER BY created_at DESC LIMIT 1",
        settings,
    )
    authorization = mysql_rows(
        "SELECT authorization_id, status, IFNULL(planned_operation_id, ''), authorization_version"
        f" FROM case_db.case_authorization WHERE case_id = '{case_id}' ORDER BY created_at DESC LIMIT 1",
        settings,
    )
    question = mysql_rows(
        "SELECT IFNULL(JSON_UNQUOTE(JSON_EXTRACT(detail, '$.question_id')), '')"
        " FROM case_db.case_timeline"
        f" WHERE case_id = '{case_id}' AND kind = 'QUESTION_REQUIRED'"
        " ORDER BY occurred_at DESC, sequence DESC LIMIT 1",
        settings,
    )
    question_id = question[0][0] if question and question[0][0] else None
    answered = None
    if question_id:
        answered = mysql_scalar(
            f"SELECT COUNT(*) FROM case_db.case_evidence WHERE case_id = '{case_id}'"
            f" AND question_id = '{question_id}'",
            settings,
        )
    return {
        "exists": True,
        "status": status,
        "input_revision": int(input_revision),
        "version": int(version),
        "description": description,
        "proposal": (
            {"status": proposal[0][0], "origin": proposal[0][1], "refusal_reason": proposal[0][2],
             "recommended_action": proposal[0][3]}
            if proposal
            else None
        ),
        "authorization": (
            {"authorization_id": authorization[0][0], "status": authorization[0][1],
             "operation_id": authorization[0][2], "authorization_version": int(authorization[0][3])}
            if authorization
            else None
        ),
        # The id of the newest question this case asked, and whether material has since answered it.
        # A question that has been answered is not a case waiting on the customer any more.
        "question_id": question_id,
        "question_answered": (answered or "0") != "0",
    }


def unchanged_from_expected(state: dict[str, Any], scenario: Scenario) -> bool:
    """Whether the recorded sample is still in the state this scenario stops at.

    A customer's answer moves the case on, so a `waiting-info` sample whose question has been
    answered is not "still waiting" even if the status column has not caught up: the interesting
    fact about that sample is that a person used it.
    """
    if not state.get("exists") or state["status"] != scenario.expected_status:
        return False
    if scenario.expected_status == "WAITING_CUSTOMER" and state.get("question_answered"):
        return False
    if scenario.expected_authorization is None:
        return state.get("authorization") is None
    return bool(state.get("authorization")) and state["authorization"]["status"] == scenario.expected_authorization


# --------------------------------------------------------------------------- run


def advance_approve(
    settings: Settings, scenario: Scenario, sample: dict[str, Any], log: Log, *, fault: str | None
) -> None:
    """Approve the pending authorization, optionally after arming a provider fault."""
    case_id = sample["case_id"]
    state = case_state(settings, case_id)
    authorization = state.get("authorization") or {}
    if not authorization or authorization["status"] != "PENDING_REVIEW":
        raise RuntimeError(f"{scenario.name}: no pending authorization to approve ({authorization})")
    if fault:
        status, answer = http(
            "POST",
            f"{settings.agent_url}/provider/v1/_lab/faults",
            body={"fault": fault, "operation_id": authorization["operation_id"]},
            timeout=10,
        )
        log.step(
            f"armed {fault} for operation {authorization['operation_id'][:8]}",
            status == 204,
            "" if status == 204 else str(answer)[:200],
        )
        if status != 204:
            raise RuntimeError(f"the provider refused the {fault} fault: {status} {answer}")
        sample["provider_fault"] = fault
    reviewer = login(settings, scenario.reviewer_username, scenario.reviewer_password)
    answer = api(
        settings,
        f"/api/v1/cases/{case_id}/reviews",
        token=reviewer,
        headers={"If-Match": f'"{state["version"]}"'},
        body={
            "authorization_id": authorization["authorization_id"],
            "authorization_version": authorization["authorization_version"],
            "decision": "APPROVE",
            "reason": "合成证据与钉住政策一致，同意按订单行全额模拟退款。",
        },
        expect=(200,),
    )
    log.note(
        f"human decision recorded: authorization {answer.get('authorization_id', '')[:8]} "
        f"{answer.get('status')} at case version {answer.get('case_version')}"
    )
    sample["decision_by"] = scenario.reviewer_username
    sample["decision_at"] = now_iso()


def run_scenario(settings: Settings, log: Log, scenario_name: str, *, index: int, build: bool) -> int:
    scenario = scenario_or_refuse(scenario_name)
    guard(settings)
    document = load_manifest(settings)

    resuming = False
    sample: dict[str, Any] = {}
    existing = sample_of(document, settings.dataset, scenario.name)
    if existing is not None:
        state = case_state(settings, existing["case_id"])
        if unchanged_from_expected(state, scenario):
            log.step(f"{scenario.name}: already prepared in {settings.dataset}", True,
                     f"case={existing['case_id']} status={state['status']}")
            log.note("nothing was created; re-running a sample never re-mints an order or a decision")
            # Backfill the completion markers so an interrupted run that has since reached its stop
            # state is recorded as finished rather than left looking resumable forever.
            if not existing.get("settled"):
                existing["settled"] = True
                existing["verified_at"] = now_iso()
                _record_run_evidence(settings, existing, state)
                record_sample(settings, document, existing)
            return 0
        if not existing.get("settled"):
            # An interrupted run: the sample was written down but never reached its stop state.
            # Continuing is the honest move — nothing within it was ever finished — and it is what
            # makes "exit halfway, run again" not produce a second order line or a second decision.
            resuming = True
            sample = dict(existing)
            log.section(f"{scenario.name}: resuming an unfinished sample")
            log.note(f"case={existing['case_id']} line={existing['line_id']} is still at {state.get('status')}")
        else:
            log.step(f"{scenario.name}: the recorded sample has changed since it was made", False,
                     f"expected {scenario.expected_status}, found {state.get('status')}")
            log.note(
                "a person has moved this sample on. The demonstration does not reset it: an explicit "
                f"new dataset is how a replacement is made, e.g. --new-dataset {settings.dataset}-2"
            )
            return 2

    if not health(settings.gateway_url):
        start_stage(settings, log, build=build)
    elif not resuming:
        log.step("the demo stack is already up", True, settings.gateway_url)

    if not resuming:
        sample = {
            "scenario": scenario.name,
            "dataset_id": settings.dataset,
            "title": scenario.title,
            "merchant_id": scenario.merchant_id,
            "model_mode": "mock",
            "proposal_origin": "AGENT",
            "recorded_at": now_iso(),
        }
        line_id = seed_line(settings, scenario, index)
        sample["line_id"] = line_id
        order_id = mysql_scalar(f"SELECT order_id FROM commerce_db.order_line WHERE line_id = '{line_id}'", settings)
        sample["order_id"] = order_id
        sample["amount_minor"] = scenario.amount_minor
        log.section(f"{scenario.name}: {scenario.title}")
        log.note(f"seeded synthetic line {line_id} for {scenario.amount_minor} minor (merchant {scenario.merchant_id})")

        # The Agent is stopped before the case exists, so it cannot answer this run with the
        # previous scenario's script.
        stop_owned(settings, "agent")
        stop_owned(settings, "agent-readonly")
        stop_owned(settings, "agent-live")

        customer = login(settings, scenario.customer_username, scenario.customer_password)
        try:
            created = api(
                settings,
                "/api/v1/cases",
                token=customer,
                # Scoped by the line: a replacement sample has a new line and therefore a new
                # key, while a retry of *this* sample reuses the same one and cannot open a
                # second case for one order line.
                headers={"Idempotency-Key": f"{settings.dataset}:{scenario.name}:{line_id}:case"},
                body={"line_id": line_id, "description": scenario.description, "requested_actions": ["REFUND"]},
                expect=(201,),
            )
        except Exception:
            discarded = discard_seeded_line(settings, line_id, sample["order_id"])
            log.note(
                f"case creation failed; the unused synthetic line {line_id} was "
                f"{'removed' if discarded else 'kept because a case already refers to it'}"
            )
            raise
        case_id = str(uuid.UUID(created["case_id"]))
        sample["case_id"] = case_id
        record_sample(settings, document, dict(sample))

        api(
            settings,
            f"/api/v1/cases/{case_id}/evidence",
            token=customer,
            body={"text": scenario.customer_material, "evidence_kind": "CUSTOMER_STATEMENT"},
            expect=(200,),
        )
        viewer = login(settings, scenario.reviewer_username, scenario.reviewer_password)
        if scenario.verification is not None:
            view = api(settings, f"/api/v1/cases/{case_id}", token=viewer)
            statement = next(item for item in view["evidence"] if item["evidence_kind"] == "CUSTOMER_STATEMENT")
            api(
                settings,
                f"/api/v1/cases/{case_id}/reviewed-evidence",
                token=viewer,
                body={
                    "source_evidence_id": statement["observation_id"],
                    "verification_result": scenario.verification[0],
                    "reason": scenario.verification[1],
                },
                expect=(200,),
            )
            log.note("reviewer verification appended as a new record; the customer's material is unchanged")

        view = api(settings, f"/api/v1/cases/{case_id}", token=viewer)
    else:
        line_id = sample["line_id"]
        case_id = sample["case_id"]
        stop_owned(settings, "agent")
        viewer = login(settings, scenario.reviewer_username, scenario.reviewer_password)
        view = api(settings, f"/api/v1/cases/{case_id}", token=viewer)

    revision = view["case"]["input_revision"]
    run_id = agent_run_id(case_id, revision)
    sample["run_id"] = run_id
    sample["input_revision"] = revision
    record_sample(settings, document, dict(sample))

    bundle_id, manifest_hash = pinned_bundle(settings, case_id)
    log.note(f"pinned policy bundle {bundle_id} at revision {revision}")

    tool_calls = _tool_calls_for(scenario)
    citations = preflight(
        settings,
        case_id=case_id,
        run_id=run_id,
        input_revision=revision,
        line_id=line_id,
        tool_calls=tool_calls,
    )
    for tool_name, citation in citations.items():
        log.note(f"real read {tool_name}: {citation['observation_id']} version={citation['source_version']}")

    policies = _policies_for(settings, scenario, bundle_id=bundle_id, manifest_hash=manifest_hash)
    for rule_id, reference in policies.items():
        log.note(f"pinned rule {rule_id} chunk={reference['chunk_id']} hash={reference['content_hash'][:12]}…")

    script = build_script(scenario, citations=citations, policies=policies)
    directory = settings.runtime() / "scenarios" / scenario.name
    directory.mkdir(parents=True, exist_ok=True)
    script_path = directory / "mock-decisions.json"
    atomic_write(script_path, json.dumps(script, ensure_ascii=False, indent=2) + "\n")

    start_agent(settings, scenario, script_path, log)

    settled = wait_for(
        f"{scenario.name} settling",
        lambda: _settled(settings, case_id, scenario),
        timeout=240.0,
    )
    state = case_state(settings, case_id)
    log.step(
        f"{scenario.name}: run settled at {state.get('status')}",
        settled,
        f"proposal={(state.get('proposal') or {}).get('status')} authorization="
        f"{(state.get('authorization') or {}).get('status')}",
    )
    if not settled:
        raise RuntimeError(f"{scenario.name} did not settle as expected; last state {state}")

    _record_run_evidence(settings, sample, state)
    if scenario.expected_authorization is None:
        # Nothing further is asked of this sample: it stops where the reviewer meets it.
        sample["settled"] = True
        sample["verified_at"] = now_iso()
        record_sample(settings, document, sample)
        return 0

    if scenario.advance in {"approve", "approve-unknown", "approve-lost-response"}:
        if (state.get("authorization") or {}).get("status") == "PENDING_REVIEW":
            fault = {
                "approve": None,
                "approve-unknown": "REQUEST_TIMEOUT",
                "approve-lost-response": "LOST_RESPONSE",
            }[scenario.advance]
            advance_approve(settings, scenario, sample, log, fault=fault)
        else:
            log.note(
                f"the decision is already recorded (authorization "
                f"{(state.get('authorization') or {}).get('status')}); not approving twice"
            )
        reached = wait_for(
            f"{scenario.name} reaching {scenario.expected_status}",
            lambda: (case_state(settings, case_id).get("status") == scenario.expected_status),
            timeout=240.0,
        )
        final = case_state(settings, case_id)
        log.step(
            f"{scenario.name}: case is {final.get('status')}",
            reached,
            f"authorization={(final.get('authorization') or {}).get('status')}",
        )
        if not reached:
            raise RuntimeError(f"{scenario.name} did not reach {scenario.expected_status}; last state {final}")
        _record_run_evidence(settings, sample, final)

    sample["status"] = case_state(settings, case_id).get("status")
    sample["settled"] = True
    sample["verified_at"] = now_iso()
    record_sample(settings, document, sample)
    return 0


def _tool_calls_for(scenario: Scenario) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Exactly the reads the scenario's script makes, in order."""
    if scenario.name == "waiting-info":
        return ((TOOL_GET_SHIPMENT, {"limit": 3}),)
    if scenario.name == "signed-conflict":
        return ((TOOL_GET_SHIPMENT, {"limit": 3}), (TOOL_GET_EVIDENCE, {}))
    if scenario.name == "damage-review":
        return ((TOOL_GET_EVIDENCE, {}),)
    return ((TOOL_GET_SHIPMENT, {"limit": 3}),)


def _policies_for(
    settings: Settings, scenario: Scenario, *, bundle_id: str, manifest_hash: str
) -> dict[str, dict[str, str]]:
    if scenario.name == "signed-conflict":
        return {
            "R-SIGNED-001": policy_ref(
                settings, merchant_id=scenario.merchant_id, bundle_id=bundle_id, manifest_hash=manifest_hash,
                rule_id="R-SIGNED-001", query="已签收 客户未收到 人工核验",
            )
        }
    if scenario.name == "damage-review":
        # Nothing to look up: the pinned bundle has no damage rule. Returning an empty mapping
        # rather than borrowing another merchant's rule keeps "no applicable policy" visible in
        # the sample instead of papered over by a citation that would not verify.
        return {}
    return {
        "R-LOST-001": policy_ref(
            settings, merchant_id=scenario.merchant_id, bundle_id=bundle_id, manifest_hash=manifest_hash,
            rule_id="R-LOST-001", query="物流丢失 全额退款",
        )
    }


def _settled(settings: Settings, case_id: str, scenario: Scenario) -> bool:
    """Whether the *investigation* part of this scenario is done.

    Deliberately about the recorded outcome rather than about the case status: a resumed sample
    whose refund has already moved on is past this point, and re-entering the wait would hang on
    a status the sample has legitimately left. The approving scenarios need an authorization as
    well as a proposal, because the authorization is what the next step decides on.
    """
    state = case_state(settings, case_id)
    if not state.get("exists"):
        return False
    if scenario.expected_authorization is not None:
        return state.get("proposal") is not None and bool(state.get("authorization"))
    if scenario.expected_status == "WAITING_CUSTOMER":
        return bool(state.get("question_id")) and not state.get("question_answered")
    return state.get("proposal") is not None


def _record_run_evidence(settings: Settings, sample: dict[str, Any], state: dict[str, Any]) -> None:
    sample["status"] = state.get("status")
    if state.get("proposal"):
        sample["proposal_status"] = state["proposal"]["status"]
        sample["proposal_origin"] = state["proposal"]["origin"]
        sample["recommended_action"] = state["proposal"]["recommended_action"]
    if state.get("authorization"):
        sample["authorization_status"] = state["authorization"]["status"]
        sample["operation_id"] = state["authorization"]["operation_id"]
    if state.get("question_id"):
        sample["question_id"] = state["question_id"]
    rows = mysql_rows(
        "SELECT COUNT(*) FROM commerce_db.refund_operation"
        f" WHERE line_id = '{sample['line_id']}'",
        settings,
    )
    sample["refund_operations"] = int(rows[0][0]) if rows else 0


# --------------------------------------------------------------------------- verify / status / stop


def witness(settings: Settings) -> dict[str, str]:
    observed: dict[str, str] = {}
    for table in SHARED_WITNESS_TABLES:
        observed[table] = shared_mysql_scalar(f"SELECT COUNT(*) FROM {table}") or "?"
    return observed


def stage_ready(settings: Settings) -> bool:
    """Whether a subsequent ``start`` can reuse the already prepared demo stage."""
    try:
        return (
            container_health("mysql", settings) == "healthy"
            and container_health("postgres", settings) == "healthy"
            and tcp_open("127.0.0.1", settings.ports["namesrv"])
            and healthy_and_owned(settings, "case-service", settings.ports["case"], settings.case_url)
            and healthy_and_owned(settings, "commerce-service", settings.ports["commerce"], settings.commerce_url)
            and healthy_and_owned(settings, "gateway", settings.ports["gateway"], settings.gateway_url)
        )
    except (DemoRefused, OSError, subprocess.SubprocessError):
        return False


def command_start(settings: Settings, log: Log, *, build: bool, open_browser: bool, live: bool = False) -> int:
    """Bring up the complete browser experience and return once it is ready."""
    guard(settings)
    if stage_ready(settings):
        log.step("prepared demo backend is already running", True, settings.gateway_url)
    else:
        command_prepare(settings, log, build=build)

    log.section("browser experience")
    start_readonly_agent(settings, log, live=live)
    start_frontend(settings, log)
    if open_browser:
        opened = webbrowser.open(settings.frontend_url, new=2)
        log.step("opened the desktop page in the default browser", opened, settings.frontend_url)
        if not opened:
            log.note(f"open this address manually: {settings.frontend_url}")
    else:
        log.note(f"browser opening was disabled; open {settings.frontend_url}")
    log.note("login: demo-reviewer / demo-pass-1003")
    return 0


def command_prepare(settings: Settings, log: Log, *, build: bool) -> int:
    guard(settings)
    manifest_exists = settings.manifest_path.is_file()
    document = load_manifest(settings)
    baseline = settings.runtime() / "shared-witness.json"
    if not baseline.is_file():
        observed = witness(settings)
        atomic_write(
            baseline,
            json.dumps({"recorded_at": now_iso(), "tables": observed}, ensure_ascii=False, indent=2) + "\n",
        )
        log.note(f"recorded the shared environment's row counts in {baseline.name}")
    start_stage(settings, log, build=build)
    backfill_display_fields(settings, document, log)
    if not manifest_exists:
        save_manifest(settings, document)
    log.step("demo stage prepared", True, f"dataset={settings.dataset} manifest={settings.manifest_path.name}")
    log.note(
        "the Agent is started per scenario by `run`: one mock script is bound to one run, so there is no "
        "always-on mock process to mistake for a model"
    )
    return 0


def command_status(settings: Settings, log: Log) -> int:
    document = load_manifest(settings)
    database_ready = container_health("mysql", settings) == "healthy"
    live_cases: dict[str, tuple[str, str | None]] = {}
    case_ids = [sample["case_id"] for sample in document.get("samples", []) if sample.get("case_id")]
    if database_ready and case_ids:
        identifiers = ", ".join(_sql_text(case_id) for case_id in case_ids)
        rows = mysql_rows(
            "SELECT c.case_id, c.status, IFNULL(a.status, '')"
            " FROM case_db.aftersale_case c"
            " LEFT JOIN case_db.case_authorization a ON a.case_id = c.case_id"
            f" WHERE c.case_id IN ({identifiers})",
            settings,
        )
        live_cases = {case_id: (status, authorization or None) for case_id, status, authorization in rows}
    log.section(f"manifest {settings.manifest_path}")
    log.note(f"environment={document['environment']} dataset={document['dataset_id']} "
             f"samples={len(document.get('samples', []))}")
    if not database_ready:
        log.note("demo MySQL is stopped; live sample state is shown as offline")
    for sample in document.get("samples", []):
        status, authorization = live_cases.get(sample.get("case_id", ""), ("offline", None))
        log.note(
            f"  {sample['scenario']:<16} case={sample.get('case_id')} line={sample.get('line_id')} "
            f"recorded={sample.get('status')} live={status} authorization={authorization}"
        )
    log.section("running demo processes")
    owned = read_owned(settings)
    if not owned:
        log.note("none recorded; `run --scenario ...` starts the Agent for one scenario")
    for entry in owned:
        owners = pids_on_port(int(entry["port"]))
        ours = {str(entry["pid"]), str(entry.get("owner_pid") or "")}
        log.note(
            f"  {entry['name']:<16} pid={entry['pid']} port={entry['port']} "
            f"owner={'ours' if ours & set(owners) else ', '.join(owners) or 'nobody'}"
        )
    return 0


def command_verify(settings: Settings, log: Log) -> int:
    guard(settings)
    log.section("isolation")
    services = compose("ps", "--format", "{{.Name}}|{{.Status}}", settings=settings, timeout=120)
    names = [line for line in services.stdout.splitlines() if line.strip()]
    log.step("the demo compose project has its own containers", bool(names), "; ".join(names) or "none")
    for role in ("mysql", "postgres"):
        log.step(f"demo {role} is healthy", container_health(role, settings) == "healthy")
    collisions = sorted(set(settings.ports.values()) & SHARED_PORTS)
    log.step("no demo port is a shared port", not collisions, ", ".join(str(item) for item in collisions) or "none")
    stacked = run(
        ["docker", "volume", "ls", "--filter", f"name={settings.project}_", "--format", "{{.Name}}"], timeout=60
    )
    volumes = [line for line in stacked.stdout.splitlines() if line.strip()]
    log.step("the demo owns its own named volumes", len(volumes) >= 2, ", ".join(volumes) or "none")

    log.section("the shared environment did not move")
    baseline_path = settings.runtime() / "shared-witness.json"
    if not baseline_path.is_file():
        log.step("a shared-environment witness exists", False, "run `prepare` first")
    else:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))["tables"]
        current = witness(settings)
        moved = {table: (baseline.get(table), current.get(table))
                 for table in current if baseline.get(table) != current.get(table)}
        log.step("shared row counts are unchanged since prepare", not moved,
                 "; ".join(f"{table} {was}->{now}" for table, (was, now) in moved.items()) or "unchanged")

    log.section("samples")
    document = load_manifest(settings)
    for sample in document.get("samples", []):
        state = case_state(settings, sample["case_id"]) if sample.get("case_id") else {}
        expected = SCENARIOS[sample["scenario"]].expected_status
        log.step(
            f"{sample['scenario']}: recorded {sample.get('status')} / live {state.get('status')}",
            state.get("status") == sample.get("status"),
            f"the sample's own expectation is {expected}",
        )
    verify_sources(settings, log, document)
    verify_money(settings, log, document)

    log.section("the demo Agent holds no live model configuration")
    agent_log = settings.runtime() / "processes" / "agent.log"
    if agent_log.is_file():
        text = agent_log.read_text(encoding="utf-8", errors="replace")
        log.step("no live provider is named in the Agent's own command line",
                 "RESOLVEFLOW_MODEL_ENDPOINT" not in text and "api_key" not in text.lower())
    else:
        log.note("the Agent is not running; `run` starts it with an explicit mock script")
    return 1 if log.failures else 0


def command_retire(settings: Settings, log: Log, scenario_name: str, reason: str) -> int:
    """Close an unfinished attempt through the product's own route and record it as retired.

    The demonstration never resets a sample and never deletes a case. When an attempt did not
    become a sample — the run failed, or the driver stopped halfway — the honest close is a
    reviewer decision on that very case, followed by a manifest record saying so.
    """
    scenario = scenario_or_refuse(scenario_name)
    guard(settings)
    document = load_manifest(settings)
    sample = sample_of(document, settings.dataset, scenario.name)
    if sample is None:
        raise DemoRefused(f"{scenario.name} has no recorded sample in {settings.dataset}")
    state = case_state(settings, sample["case_id"])
    if not state.get("exists"):
        raise DemoRefused(f"{scenario.name}: case {sample['case_id']} is not in the demo database")
    # Stop the run first, through the Agent's own cancel route, when one is recorded and the
    # Agent is up. A run left RUNNING by an interrupted attempt is not recoverable: the retry
    # allowance for its first provider request is already spent, so recovery can only fail it.
    # Cancelling is what keeps a retired attempt from leaving a run for the worker to trip over.
    if sample.get("run_id"):
        status, answer = http(
            "POST",
            f"{settings.agent_url}/internal/v1/runs/{sample['run_id']}/cancel",
            token=mint_service_token("case-service"),
            body={"reason": reason},
            timeout=10,
        )
        log.note(f"cancel {sample['run_id'][:8]}: {status}" + ("" if status in (200, 202, 404) else f" {answer}"))
    if not state["status"].startswith("CLOSED") and state["status"] != "CANCELLED":
        viewer = login(settings, scenario.reviewer_username, scenario.reviewer_password)
        api(
            settings,
            f"/api/v1/cases/{sample['case_id']}/review-actions",
            token=viewer,
            headers={"If-Match": f'"{state["version"]}"'},
            body={"action": "REJECT", "reason": reason},
            expect=(200,),
        )
        state = case_state(settings, sample["case_id"])
    retire_sample(settings, document, sample, reason=reason)
    log.step(f"{scenario.name} retired at {state['status']}", True, f"case={sample['case_id']}")
    log.note("the case and its history stay in the demo database; only the manifest record moved")
    return 0


def verify_sources(settings: Settings, log: Log, document: dict[str, Any]) -> None:
    """The proposal's citations must be findable in the case's own investigation record.

    This is the acceptance row that distinguishes an Agent sample from a manual one: the
    reviewer reads `GET /api/v1/cases/{case_id}/investigation` and every cited observation has
    to be there, with the same source, version and hash the proposal named. A mock source is
    still a recorded source, and the run's model mode is reported beside it rather than implied.
    """
    log.section("recorded sources behind the proposals")
    for scenario_name in ("lost-review", "signed-conflict", "damage-review"):
        sample = sample_of(document, settings.dataset, scenario_name)
        if sample is None:
            log.step(f"{scenario_name}: a recorded sample exists", False, "missing from the manifest")
            continue
        case_id = sample["case_id"]
        state = case_state(settings, case_id)
        viewer = login(settings, SEQUENCE_REVIEWER[scenario_name][0], SEQUENCE_REVIEWER[scenario_name][1])
        answer = api(settings, f"/api/v1/cases/{case_id}/investigation", token=viewer)
        availability = answer.get("availability")
        record = answer.get("investigation") or {}
        sources = record.get("observations") or []
        observed = {
            (item.get("observation_id"), item.get("source_ref"), str(item.get("source_version")),
             item.get("content_hash"))
            for item in sources
        }
        cited = mysql_rows(
            "SELECT JSON_EXTRACT(payload, '$.evidence_refs'), JSON_EXTRACT(payload, '$.policy_refs')"
            f" FROM case_db.case_proposal WHERE case_id = '{case_id}' ORDER BY created_at DESC LIMIT 1",
            settings,
        )
        # `mysql -N -B` prints SQL NULL as the four letters NULL, so an absent JSON member
        # arrives as a string rather than as an absence.
        def json_or_empty(value: Any) -> list[dict[str, Any]]:
            if not value or value == "NULL":
                return []
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []

        evidence_refs = json_or_empty(cited[0][0]) if cited else []
        policy_refs = json_or_empty(cited[0][1]) if cited else []
        matched = [
            ref for ref in evidence_refs
            if (ref.get("observation_id"), ref.get("source_ref"), str(ref.get("source_version")),
                ref.get("content_hash")) in observed
        ]
        log.step(
            f"{scenario_name}: availability AVAILABLE with {len(sources)} recorded sources",
            availability == "AVAILABLE" and bool(sources),
            f"availability={availability}",
        )
        log.step(
            f"{scenario_name}: every evidence citation matches a recorded source on all four keys",
            len(matched) == len(evidence_refs) and bool(evidence_refs),
            f"{len(matched)}/{len(evidence_refs)} matched",
        )
        log.step(
            f"{scenario_name}: the proposal records an Agent origin and a mock model mode",
            bool(state.get("proposal")) and state["proposal"]["origin"] == "AGENT"
            and sample.get("model_mode") == "mock",
            f"origin={(state.get('proposal') or {}).get('origin')} mode={sample.get('model_mode')}",
        )
        if policy_refs:
            # The rule's content hash is not stored: `docs/core-contracts.md:56` derives it from
            # the stored text, so the check asks the service that serves the case's pinned bundle
            # rather than looking for a column that deliberately does not exist.
            bundle_id = policy_refs[0]["bundle_id"]
            status_code, served = http(
                "GET",
                f"{settings.case_url}/internal/v1/policies/{bundle_id}",
                token=mint_service_token("agent-service", scope=POLICY_READ_SCOPE),
            )
            rules = (served or {}).get("rules") if isinstance(served, dict) else None
            match = next(
                (rule for rule in (rules or []) if rule.get("rule_id") == policy_refs[0]["rule_id"]), None
            )
            log.step(
                f"{scenario_name}: the policy citation matches the rule this case pinned",
                status_code == 200
                and match is not None
                and match.get("content_hash") == policy_refs[0]["content_hash"],
                f"{policy_refs[0]['rule_id']} from {bundle_id}",
            )
        else:
            log.step(
                f"{scenario_name}: no policy rule is cited, and the sample says why",
                scenario_name == "damage-review",
                "this merchant's pinned bundle has no damage rule",
            )


#: Which account reviews which scenario's sample, for the read-only checks.
SEQUENCE_REVIEWER = {
    "lost-review": ("demo-reviewer", "demo-pass-1003"),
    "signed-conflict": ("demo-reviewer", "demo-pass-1003"),
    "damage-review": ("demo-reviewer", "demo-pass-1003"),
}


def verify_money(settings: Settings, log: Log, document: dict[str, Any]) -> None:
    """The money invariants the demonstration claims, checked against the demo's own records.

    Every one of these is read from the database that owns the fact - Commerce for the ledger and
    the single-refund slot, the provider's own SQLite file for what it settled, and the case for
    its status - rather than from a screen or a report sentence.
    """
    import sqlite3

    log.section("money invariants")
    provider_path = settings.runtime() / "refund-provider.sqlite3"

    def provider_rows(operation_id: str) -> list[tuple]:
        if not provider_path.is_file():
            return []
        with sqlite3.connect(provider_path.as_uri() + "?mode=ro", uri=True) as provider:
            return provider.execute(
                "SELECT state, amount_minor, (SELECT COUNT(*) FROM request_attempt a"
                " WHERE a.operation_id = r.operation_id)"
                " FROM refund_request r WHERE operation_id = ?",
                (operation_id,),
            ).fetchall()

    for scenario_name in ("unknown-refund", "success-refund", "unknown-recovery"):
        sample = sample_of(document, settings.dataset, scenario_name)
        if sample is None:
            log.step(f"{scenario_name}: a recorded sample exists", False, "missing from the manifest")
            continue
        line_id = sample["line_id"]
        order_id = sample["order_id"]
        operations = mysql_rows(
            "SELECT operation_id, state, amount_minor FROM commerce_db.refund_operation"
            f" WHERE line_id = '{line_id}'",
            settings,
        )
        slot = mysql_rows(
            f"SELECT state, IFNULL(operation_id, '') FROM commerce_db.line_refund WHERE line_id = '{line_id}'",
            settings,
        )
        ledger = mysql_rows(
            "SELECT paid_amount, refunded_amount, reserved_refund_amount FROM commerce_db.payment_ledger"
            f" WHERE order_id = '{order_id}'",
            settings,
        )
        expected_operation = sample.get("operation_id")
        settled = [row for row in operations if row[0] == expected_operation]
        log.step(
            f"{scenario_name}: exactly one refund operation for this line, under the recorded id",
            len(operations) == 1 and bool(settled),
            f"{operations}",
        )
        attempts = provider_rows(expected_operation) if expected_operation else []
        if scenario_name == "unknown-refund":
            log.step(
                "unknown-refund: the reservation is still held and nothing was released",
                bool(ledger) and ledger[0][1] == "0" and ledger[0][2] == sample["amount_minor"].__str__(),
                f"ledger={ledger}",
            )
            log.step(
                "unknown-refund: the slot still names the original operation",
                bool(slot) and slot[0][0] == "RESERVED" and slot[0][1] == expected_operation,
                f"slot={slot}",
            )
            # REQUEST_TIMEOUT records the request and settles nothing: the provider's own row is
            # UNKNOWN, and the count of呈递 is one, so a later retry did not become a second
            # payment attempt under the same key.
            log.step(
                "unknown-refund: the provider settled nothing and was asked exactly once",
                len(attempts) == 1 and attempts[0][0] == "UNKNOWN" and attempts[0][2] == 1,
                f"provider={attempts or 'no request recorded'}",
            )
        else:
            log.step(
                f"{scenario_name}: paid=refunded and the reservation is released",
                bool(ledger)
                and ledger[0][1] == ledger[0][0] == str(sample["amount_minor"])
                and ledger[0][2] == "0",
                f"ledger={ledger}",
            )
            log.step(
                f"{scenario_name}: the line's single refund slot is consumed by the original operation",
                bool(slot) and slot[0][0] == "CONSUMED" and slot[0][1] == expected_operation,
                f"slot={slot}",
            )
            log.step(
                f"{scenario_name}: the provider settled the same key exactly once",
                len(attempts) == 1 and attempts[0][0] == "SUCCEEDED" and attempts[0][2] == 1,
                f"provider={attempts}",
            )
        log.step(
            f"{scenario_name}: the run's operation id never changed",
            all(row[0] == expected_operation for row in operations),
            f"recorded={expected_operation}",
        )

    log.section("ownership and credentials")
    document_case = sample_of(document, settings.dataset, "lost-review")
    if document_case is not None:
        other = login(settings, "demo-reviewer-m2", "demo-pass-2002")
        status, _ = http("GET", f"{settings.gateway_url}/api/v1/cases/{document_case['case_id']}", token=other)
        log.step(
            "another merchant's reviewer cannot read this case",
            status == 404,
            f"M-1002 reviewer on an M-1001 case -> {status}",
        )
        customer = login(settings, "demo-customer", "demo-pass-1001")
        status, _ = http(
            "GET", f"{settings.gateway_url}/api/v1/cases/{document_case['case_id']}/review-context", token=customer
        )
        log.step(
            "a customer cannot read the reviewer surface",
            status == 403,
            f"customer on review-context -> {status}",
        )
    agent_log = settings.runtime() / "processes" / "agent.log"
    if agent_log.is_file():
        text = agent_log.read_text(encoding="utf-8", errors="replace")
        leaked = [name for name in ("RESOLVEFLOW_MODEL_API_KEY", "sk-", "Bearer sk") if name in text]
        log.step("no credential appears in the Agent's process log", not leaked, ", ".join(leaked) or "none")


def command_stop(settings: Settings, log: Log) -> int:
    guard(settings)
    stopped = stop_owned(settings, log=log)
    log.step("stopped the demo processes this driver started", True, ", ".join(stopped) or "none were running")
    down = compose("stop", settings=settings)
    log.step("stopped the demo compose project", down.returncode == 0, settings.project)
    log.note("the demo volumes and the shared environment are untouched: no `down -v`, no reset, no clear")
    return 0


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    # The reports and the sample descriptions carry Chinese text, so the console has to be
    # UTF-8 whatever the code page is: a run that passed and then failed to *print* its result
    # reads as a failing run. `errors="replace"` keeps an unprintable console from turning a
    # result into a crash; the written report is the record.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Reviewer demonstration: an isolated synthetic dataset on the core stack.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dataset", default=None, help="the dataset id this command works on")
    parser.add_argument("--new-dataset", default=None, help="make a replacement sample set under this id")
    parser.add_argument("--skip-build", action="store_true", help="reuse the jars already on disk")
    sub = parser.add_subparsers(dest="command", required=True)

    starter = sub.add_parser("start", help="start backend, read-only Agent API and desktop page")
    starter.add_argument("--no-browser", action="store_true", help="start everything without opening a browser")
    starter.add_argument("--live", action="store_true", help="enable DeepSeek V4.1 Flash investigations (uses API credits)")
    sub.add_parser("prepare", help="bring up the demo stage and build the demo policy index")
    verify = sub.add_parser("verify", help="read-only checks of isolation and sample state")
    status = sub.add_parser("status", help="read-only view of the manifest and the demo processes")
    stop = sub.add_parser("stop", help="stop the demo services this driver started")
    runner = sub.add_parser("run", help="advance one scenario")
    runner.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    runner.add_argument("--index", type=int, default=0, help="line-id suffix, so two samples never collide")
    retired = sub.add_parser("retire", help="close an unfinished attempt through the product's own route")
    retired.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    retired.add_argument("--reason", required=True, help="why this attempt is being closed")
    # Also accepted after `run`, where a caller naturally types it; SUPPRESS keeps the
    # sub-parser from resetting the top-level value when it is not repeated.
    runner.add_argument("--skip-build", action="store_true", default=argparse.SUPPRESS,
                        help="reuse the jars already on disk")
    starter.add_argument("--skip-build", action="store_true", default=argparse.SUPPRESS,
                         help="reuse the jars already on disk")
    for command in (verify, status, stop, runner, retired):
        command.add_argument("--json", action="store_true", help="accepted for symmetry; reports are text")

    args = parser.parse_args(argv)
    settings = settings_from_environ()
    if args.new_dataset:
        settings = Settings(
            environment=settings.environment,
            project=settings.project,
            dataset=args.new_dataset,
            ports=settings.ports,
            manifest_path=settings.manifest_path,
            runtime_root=settings.runtime_root,
        )
    elif args.dataset:
        settings = Settings(
            environment=settings.environment,
            project=settings.project,
            dataset=args.dataset,
            ports=settings.ports,
            manifest_path=settings.manifest_path,
            runtime_root=settings.runtime_root,
        )

    log = Log(log_path(settings, args.command), title=f"reviewer demo · {args.command} · {settings.dataset}")
    try:
        if args.command == "start":
            code = command_start(settings, log, build=not args.skip_build, open_browser=not args.no_browser, live=args.live)
        elif args.command == "prepare":
            code = command_prepare(settings, log, build=not args.skip_build)
        elif args.command == "verify":
            code = command_verify(settings, log)
        elif args.command == "status":
            code = command_status(settings, log)
        elif args.command == "stop":
            code = command_stop(settings, log)
        elif args.command == "retire":
            code = command_retire(settings, log, args.scenario, args.reason)
        else:
            index = args.index or _next_index(settings, args.scenario)
            code = run_scenario(settings, log, args.scenario, index=index, build=not args.skip_build)
    except (DemoRefused, SampleChanged) as refusal:
        log.step("refused", False, str(refusal))
        log.flush(f"REFUSED: {refusal}")
        return 3
    except Exception as unexpected:  # noqa: BLE001 - a failed run must still leave its report
        import traceback

        log.note(traceback.format_exc())
        log.flush(f"FAILED: {unexpected}")
        return 1
    verdict = "PASSED" if not log.failures else "FAILED: " + "; ".join(log.failures)
    log.flush(verdict)
    print(f"[driver] report {log.path}")
    return code


def _next_index(settings: Settings, scenario: str) -> int:
    """A stable, colliding-free suffix: how many samples this dataset already holds."""
    document = load_manifest(settings)
    if sample_of(document, settings.dataset, scenario) is not None:
        return 0
    return len(document.get("samples", [])) + 1


if __name__ == "__main__":
    raise SystemExit(main())
