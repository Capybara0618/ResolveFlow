"""Explicitly owned backend measurement resources; no shared-resource defaults."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LABEL = "resolveflow.backend-resume.run"
PORT_ROLES = ("mysql", "redis", "namesrv", "broker", "broker_ha", "gateway", "case", "commerce", "provider")
SERVICES = {"gateway": "gateway", "case": "case-service", "commerce": "commerce-service"}


def run(args, *, data=None, env=None, timeout=120):
    result = subprocess.run(args, input=data, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"{args[0]} exited {result.returncode}: {result.stderr[-1400:]}")
    return result.stdout.strip()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze_file(source, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with Path(source).open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    return sha256(target)


def verify_file(path, digest):
    if sha256(path) != digest:
        raise ValueError("baseline artifact changed: " + str(path))


def child_env():
    prefixes = ("RESOLVEFLOW_", "DEEPSEEK", "CASE_", "COMMERCE_", "REFUND_", "REDIS_",
                "REVIEW_", "PRODUCT_REVIEW_", "CHECKOUT_", "AGENT_", "SPRING_", "SERVER_")
    return {k: v for k, v in os.environ.items() if not k.upper().startswith(prefixes)}


def allocate_ports():
    sockets = []
    ports = {}
    try:
        for role in PORT_ROLES:
            while True:
                candidate = socket.socket()
                candidate.bind(("127.0.0.1", 0))
                value = candidate.getsockname()[1]
                reserved = set(ports.values())
                if "broker" in ports:
                    reserved.add(ports["broker"] - 2)
                if value in reserved or (role == "broker" and value - 2 in reserved):
                    candidate.close()
                    continue
                if role == "broker":
                    vip = socket.socket()
                    try:
                        vip.bind(("127.0.0.1", value - 2))
                    except OSError:
                        candidate.close()
                        vip.close()
                        continue
                    sockets.append(vip)
                ports[role] = value
                sockets.append(candidate)
                break
        return ports
    finally:
        for owned in sockets:
            owned.close()


def wait(label, predicate, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if predicate():
                print(label + " ready", flush=True)
                return
        except (OSError, RuntimeError):
            pass
        time.sleep(.5)
    raise TimeoutError(label)


@dataclass(frozen=True)
class Settings:
    identity: str
    root: Path = ROOT

    def __post_init__(self):
        if not re.fullmatch(r"[a-f0-9]{32}", self.identity):
            raise ValueError("invalid run identity: expected 32 lowercase hex characters")

    @property
    def project(self):
        return "rfbe-" + self.identity

    @property
    def folder(self):
        return self.root / "tmp/backend-resume-v1" / self.identity

    @property
    def state_path(self):
        return self.folder / "runtime.json"

    @property
    def report(self):
        return self.root / "reports/backend-resume-v1" / self.identity

    def container(self, role):
        if role not in ("mysql", "redis", "namesrv", "broker", "broker-init"):
            raise ValueError("unknown container role")
        return self.project + "-" + role

    @contextmanager
    def operation_lock(self):
        import msvcrt

        self.folder.mkdir(parents=True, exist_ok=True)
        with (self.folder / "operation.lock").open("a+b") as handle:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ValueError("another laboratory command is running") from error
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def validate_ports(self, ports):
        if set(ports) != set(PORT_ROLES) or any(type(v) is not int or not 1024 <= v <= 65535 for v in ports.values()):
            raise ValueError("invalid port map")
        if len(set(ports.values())) != len(ports) or ports["broker"] - 2 in ports.values():
            raise ValueError("port collision, including broker VIP port")

    def initialize(self, state):
        self.folder.mkdir(parents=True, exist_ok=True)
        if self.state_path.exists():
            raise ValueError("runtime exists; use check/resume/stop, never replace it")
        with self.state_path.open("x", encoding="utf-8", newline="\n") as file:
            json.dump(state, file, indent=2)

    def save(self, state):
        self.state_path.write_bytes((json.dumps(state, indent=2) + "\n").encode())

    def load(self):
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        if state.get("run_id") != self.identity:
            raise ValueError("runtime ownership mismatch")
        self.validate_ports(state["ports"])
        return state

    def assert_owned(self, role):
        owner = run(["docker", "inspect", "--format", '{{index .Config.Labels "' + LABEL + '"}}', self.container(role)])
        if owner != self.identity:
            raise ValueError("container ownership mismatch: " + role)

    def sql(self, statement, account="root"):
        self.assert_owned("mysql")
        if account not in ("root", "case_svc", "commerce"):
            raise ValueError("unknown laboratory database account")
        password = "root" if account == "root" else account
        return run(["docker", "exec", "-i", self.container("mysql"), "mysql", "-u" + account,
                    "-p" + password, "--default-character-set=utf8mb4", "--batch", "--raw", "--skip-column-names"],
                   data="SET time_zone='+00:00';\n" + statement)

    def compose_definition(self, ports):
        self.validate_ports(ports)
        def service(role, image, **extra):
            return {"image": image, "container_name": self.container(role), "labels": {LABEL: self.identity}, **extra}

        return {"services": {
            "mysql": service("mysql", "mysql:8.4", environment={"MYSQL_ROOT_PASSWORD": "root"},
                             ports=[f"127.0.0.1:{ports['mysql']}:3306"],
                             volumes=["mysql-data:/var/lib/mysql", f"{(self.root / 'infra/mysql/init').as_posix()}:/docker-entrypoint-initdb.d:ro"]),
            "redis": service("redis", "redis:7.4-alpine", ports=[f"127.0.0.1:{ports['redis']}:6379"],
                             command=["redis-server", "--appendonly", "no", "--save", ""]),
            "namesrv": service("namesrv", "apache/rocketmq:5.3.3", command=["nameserver"],
                               ports=[f"127.0.0.1:{ports['namesrv']}:9876"],
                               environment={"JAVA_OPT_EXT": "-Xms128m -Xmx256m -Xmn64m"}),
            "broker-init": service("broker-init", "apache/rocketmq:5.3.3", user="0:0",
                                   entrypoint=["/bin/sh", "-c"],
                                   command=["chown -R rocketmq:rocketmq /home/rocketmq/store"],
                                   volumes=["broker-store:/home/rocketmq/store"]),
            "broker": service("broker", "apache/rocketmq:5.3.3",
                              depends_on={"namesrv": {"condition": "service_started"},
                                          "broker-init": {"condition": "service_completed_successfully"}},
                              entrypoint=["/bin/bash", "/home/rocketmq/broker-entrypoint.sh"],
                              environment={"NAMESRV_ADDR": "namesrv:9876", "BROKER_IP1": "127.0.0.1",
                                           "BROKER_LISTEN_PORT": str(ports["broker"]),
                                           "BROKER_HA_LISTEN_PORT": str(ports["broker_ha"]),
                                           "JAVA_OPT_EXT": "-Xms256m -Xmx512m -Xmn128m"},
                              ports=[f"127.0.0.1:{ports[name]}:{ports[name]}" for name in ("broker", "broker_ha")],
                              volumes=[f"{(self.root / 'infra/rocketmq/broker.conf').as_posix()}:/home/rocketmq/broker.conf.base:ro",
                                       f"{(self.root / 'infra/rocketmq/broker-entrypoint.sh').as_posix()}:/home/rocketmq/broker-entrypoint.sh:ro",
                                       "broker-store:/home/rocketmq/store"]),
        }, "volumes": {"mysql-data": {}, "broker-store": {}}}

    def compose(self, *args):
        return run(["docker", "compose", "-p", self.project, "-f", str(self.folder / "compose.json"), *args], timeout=180)

    def freeze(self):
        manifest_path = self.folder / "baseline.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for role, digest in manifest["jars"].items():
                verify_file(self.folder / "baseline" / (role + ".jar"), digest)
            return manifest
        jars = {}
        for role, module in SERVICES.items():
            source = self.root / f"java/{module}/target/{module}-0.1.0-SNAPSHOT.jar"
            if not source.is_file():
                raise ValueError("build Java services before prepare: " + module)
        for role, module in SERVICES.items():
            jars[role] = freeze_file(self.root / f"java/{module}/target/{module}-0.1.0-SNAPSHOT.jar",
                                     self.folder / "baseline" / (role + ".jar"))
        sources = run(["git", "-C", str(self.root), "ls-files", "java", "infra", "scripts/evaluation/backend_lab.py",
                       "scripts/backend_resume_lab.py", "scripts/evaluation/backend_provider.py"]).splitlines()
        sources = sorted(set(sources) | {"scripts/evaluation/backend_lab.py", "scripts/backend_resume_lab.py",
                                         "scripts/evaluation/backend_provider.py", "scripts/evaluation/backend_smoke.py"})
        manifest = {"run_id": self.identity, "git_sha": run(["git", "-C", str(self.root), "rev-parse", "HEAD"]),
                    "dirty_files": run(["git", "-C", str(self.root), "status", "--short", "--untracked-files=no"]).splitlines(),
                    "jars": jars, "source_sha256": {p: sha256(self.root / p) for p in sources if (self.root / p).is_file()},
                    "model_requests": 0, "phase": "D0 baseline, not formal benchmark"}
        manifest_path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
        return manifest

    def start_child(self, role, args, env, state):
        log = self.folder / (role + ".log")
        with log.open("ab") as output:
            child = subprocess.Popen(args, env=env, cwd=self.root, stdout=output, stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        state.setdefault("pids", {})[role] = child.pid
        self.save(state)

    def stop_children(self, state):
        for role, pid in state.get("pids", {}).items():
            if role not in (*SERVICES, "provider") or type(pid) is not int or pid < 1:
                raise ValueError("invalid owned process record")
            marker = ("-Drf.backend.run=" if role in SERVICES else "--run-id=") + self.identity
            marker = marker.replace("'", "''")
            command = (f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; "
                       f"if ($p -and $p.CommandLine.Contains('{marker}')) {{ Stop-Process -Id {pid} -ErrorAction Stop }} "
                       "elseif ($p) { throw 'process ownership mismatch' }")
            run(["powershell", "-NoProfile", "-Command", command])
