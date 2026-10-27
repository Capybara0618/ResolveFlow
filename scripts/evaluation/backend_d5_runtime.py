"""Owned D5 measurement bootstrap. No model, refunds, shared databases or implicit run selection."""

from __future__ import annotations

import argparse
import json
import os
import socket
import time
import urllib.request
import zipfile
from pathlib import Path

from evaluation.backend_lab import (
    ROOT,
    Settings,
    allocate_ports,
    child_env,
    freeze_file,
    run,
    sha256,
    wait,
)
from evaluation.trade_request_journal import durable

BASELINE = "c5265fe48bc946ec99398450c998a014"
CANDIDATE = "tmp/backend-resume-candidates/d4-functional-01"
SOURCES = [
    "scripts/evaluation/backend_d5_runtime.py",
    "scripts/evaluation/D5Probe.java",
]


def free_ports(count, excluded):
    held, values = [], []
    try:
        while len(values) < count:
            probe = socket.socket()
            probe.bind(("127.0.0.1", 0))
            value = probe.getsockname()[1]
            if value in excluded:
                probe.close()
                continue
            held.append(probe)
            values.append(value)
        return values
    finally:
        for probe in held:
            probe.close()


def unpack(jar, output):
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(jar) as archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.startswith(
                ("BOOT-INF/classes/", "BOOT-INF/lib/")
            ):
                continue
            relative = Path(info.filename.removeprefix("BOOT-INF/"))
            if ".." in relative.parts:
                raise ValueError("unsafe application archive")
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(archive.read(info))
    return {
        p.relative_to(output).as_posix(): sha256(p)
        for p in output.rglob("*")
        if p.is_file()
    }


def verify_files(settings):
    manifest = json.loads(
        (settings.folder / "d5-builds.json").read_text(encoding="utf-8")
    )
    for name, digest in manifest["artifacts"].items():
        if sha256(settings.folder / name) != digest:
            raise ValueError("D5 artifact changed: " + name)
    for group, files in manifest["unpacked"].items():
        for name, digest in files.items():
            if sha256(settings.folder / group / name) != digest:
                raise ValueError("D5 extracted application changed: " + name)
    for name, digest in manifest["probe_classes"].items():
        if sha256(settings.folder / "probe-classes" / name) != digest:
            raise ValueError("D5 measurement class changed: " + name)
    return manifest


def build(settings):
    artifacts, expanded = {}, {}
    for condition in ("A", "B"):
        for role in ("case", "commerce"):
            source = ROOT / (
                f"tmp/backend-resume-v1/{BASELINE}/baseline/{role}.jar"
                if condition == "A"
                else f"{CANDIDATE}/{role}.jar"
            )
            relative = f"artifacts/{condition}/{role}.jar"
            artifacts[relative] = freeze_file(source, settings.folder / relative)
            group = f"unpacked/{condition}/{role}"
            expanded[group] = unpack(
                settings.folder / relative, settings.folder / group
            )
    artifacts["artifacts/gateway.jar"] = freeze_file(
        ROOT / f"tmp/backend-resume-v1/{BASELINE}/baseline/gateway.jar",
        settings.folder / "artifacts/gateway.jar",
    )
    copied = {}
    for name in SOURCES:
        copied[name] = freeze_file(
            ROOT / name, settings.folder / "execution-sources" / name
        )
    libraries = settings.folder / "unpacked/B/commerce/lib/*"
    java = Path(os.environ.get("JAVA_HOME", str(Path.home() / ".jdks/jdk-21.0.12.1+1")))
    target = settings.folder / "probe-classes"
    target.mkdir()
    output = run(
        [
            str(java / "bin/javac.exe"),
            "-encoding",
            "UTF-8",
            "-cp",
            str(libraries),
            "-d",
            str(target),
            str(settings.folder / "execution-sources/scripts/evaluation/D5Probe.java"),
        ]
    )
    (settings.folder / "probe-build.log").write_bytes(output.encode())
    manifest = {
        "run_id": settings.identity,
        "git_sha": run(["git", "rev-parse", "HEAD"]),
        "artifacts": artifacts,
        "unpacked": expanded,
        "sources": copied,
        "probe_classes": {
            p.relative_to(target).as_posix(): sha256(p) for p in target.rglob("*.class")
        },
        "measurement": "identical measurement bootstrap around byte-identical extracted original classes and libraries; no recompile of baseline application",
        "model_requests": 0,
    }
    durable(settings.folder / "d5-builds.json", manifest)
    return manifest


def probe(settings, role, action="snapshot", body=None):
    state = settings.load()
    request = urllib.request.Request(
        f"http://127.0.0.1:{state['d5_probes'][role]}/{action}",
        headers={"X-D5-Run": settings.identity, "Content-Type": "application/json"},
        data=None if body is None else json.dumps(body).encode(),
        method="GET" if action == "snapshot" else "POST",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


def start(
    settings,
    role,
    condition="B",
    *,
    cache=False,
    locking=False,
    namespace=None,
    commerce_port=None,
    redis_port=None,
):
    state = settings.load()
    if role not in ("case", "commerce", "commerce2", "gateway") or condition not in (
        "A",
        "B",
    ):
        raise ValueError("unsupported explicitly owned service")
    service = "commerce" if role == "commerce2" else role
    port = (
        state["d5_service_ports"][role] if role == "commerce2" else state["ports"][role]
    )
    with socket.socket() as check:
        if check.connect_ex(("127.0.0.1", port)) == 0:
            raise ValueError("service port occupied")
    env = child_env()
    java = str(
        Path(os.environ.get("JAVA_HOME", str(Path.home() / ".jdks/jdk-21.0.12.1+1")))
        / "bin/java.exe"
    )
    args = [
        java,
        "-XX:ActiveProcessorCount=2",
        "-Xms128m",
        "-Xmx512m",
        "-Drf.backend.run=" + settings.identity,
    ]
    if role == "gateway":
        args += [
            "-jar",
            str(settings.folder / "artifacts/gateway.jar"),
            f"--resolveflow.case.base-url=http://127.0.0.1:{state['ports']['case']}",
        ]
    else:
        ready = settings.folder / (role + ".ready")
        if ready.exists():
            # Historical ready records are retained under a fresh name; no stale readiness reuse.
            ready.rename(settings.folder / (role + f"-{time.time_ns()}.ready"))
        group = settings.folder / f"unpacked/{condition}/{service}"
        classpath = os.pathsep.join(
            map(
                str,
                [
                    settings.folder / state.get("d5_probe_group", "probe-classes"),
                    group / "classes",
                    group / "lib/*",
                ],
            )
        )
        application = "com.resolveflow." + (
            "caseservice.CaseServiceApplication"
            if role == "case"
            else "commerce.CommerceServiceApplication"
        )
        args += [
            "-Drf.d5.run=" + settings.identity,
            "-Drf.d5.node=" + role,
            "-Drf.d5.folder=" + str(settings.folder),
            "-Drf.d5.probe-port=" + str(state["d5_probes"][role]),
            "-cp",
            classpath,
            "com.resolveflow.evaluation.D5Probe",
            application,
        ]
        account = "case_svc" if role == "case" else "commerce"
        args += [
            f"--spring.datasource.url=jdbc:mysql://127.0.0.1:{state['ports']['mysql']}/{service}_db?connectionTimeZone=UTC&preserveInstants=true&allowPublicKeyRetrieval=true&useSSL=false",
            "--spring.datasource.username=" + account,
            "--spring.datasource.password=" + account,
            "--spring.datasource.hikari.maximum-pool-size=10",
            "--spring.datasource.hikari.minimum-idle=2",
            "--spring.data.redis.host=127.0.0.1",
            "--spring.data.redis.port=" + str(redis_port or state["ports"]["redis"]),
            "--resolveflow.review-cache.enabled=" + str(cache).lower(),
            "--resolveflow.product-reviews.cache-enabled=" + str(cache).lower(),
            "--resolveflow.product-reviews.rebuild-lock-enabled="
            + str(locking).lower(),
            "--resolveflow.product-reviews.rate-limit-enabled=false",
            "--resolveflow.identity.jwt.ttl-seconds=86400",
            "--resolveflow.dispatch.enabled=false",
            "--resolveflow.support-agent.enabled=false",
            "--resolveflow.refund.dispatch-enabled=false",
            "--resolveflow.refund.reconcile-enabled=false",
            "--resolveflow.checkout.recovery-enabled=false",
            "--resolveflow.events.consumer.enabled=false",
            "--resolveflow.events.publisher.enabled=false",
        ]
        if role == "case":
            args += [
                f"--resolveflow.commerce.base-url=http://127.0.0.1:{commerce_port or state['ports']['commerce']}"
            ]
        if namespace:
            args += [
                "--resolveflow.review-cache.namespace=" + namespace,
                "--resolveflow.product-reviews.cache-namespace=" + namespace,
            ]
    args += ["--server.address=127.0.0.1", "--server.port=" + str(port)]
    settings.start_child(role, args, env, state)

    def healthy():
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/actuator/health", timeout=3
        ) as response:
            return response.status == 200

    wait(role + " ready", healthy, seconds=120)
    if role != "gateway":
        wait(
            role + " SQL probe",
            lambda: probe(settings, role)["pid"] == settings.load()["pids"][role],
        )
    print(role + ": frozen " + condition + " ready", flush=True)


def stop_role(settings, role):
    if role not in ("case", "commerce", "commerce2", "gateway", "relay"):
        raise ValueError("unknown owned D5 role")
    state = settings.load()
    pid = state.get("pids", {}).get(role)
    if pid is None:
        return
    if type(pid) is not int or pid < 1:
        raise ValueError("invalid owned PID")
    marker = (
        "--run-id=" if role == "relay" else "-Drf.backend.run="
    ) + settings.identity
    command = (
        f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; "
        f"if ($p -and $p.CommandLine.Contains('{marker}')) {{ Stop-Process -Id {pid} -ErrorAction Stop }} "
        "elseif ($p) { throw 'process ownership mismatch' }"
    )
    run(["powershell", "-NoProfile", "-Command", command])
    state["pids"].pop(role)
    settings.save(state)


def upgrade_probe(settings, version):
    if not version.isalnum():
        raise ValueError("explicit probe version required")
    target = settings.folder / ("probe-classes-" + version)
    target.mkdir(exist_ok=False)
    source = settings.folder / ("D5Probe-" + version + ".java")
    freeze_file(ROOT / "scripts/evaluation/D5Probe.java", source)
    # javac requires the public class filename even when the immutable snapshot has a version.
    compile_source = target / "source/D5Probe.java"
    freeze_file(source, compile_source)
    java = Path(os.environ.get("JAVA_HOME", str(Path.home() / ".jdks/jdk-21.0.12.1+1")))
    output = run(
        [
            str(java / "bin/javac.exe"),
            "-encoding",
            "UTF-8",
            "-cp",
            str(settings.folder / "unpacked/B/commerce/lib/*"),
            "-d",
            str(target),
            str(compile_source),
        ]
    )
    (target / "compile.log").write_bytes(output.encode())
    state = settings.load()
    state["d5_probe_group"] = target.name
    settings.save(state)
    return {
        p.relative_to(settings.folder).as_posix(): sha256(p)
        for p in target.rglob("*.class")
    }


def prepare(settings):
    if settings.state_path.exists():
        raise ValueError("D5 runtime already exists")
    ports = allocate_ports()
    controls = free_ports(3, {*ports.values(), ports["broker"] - 2})
    settings.initialize(
        {
            "run_id": settings.identity,
            "ports": ports,
            "d5_probes": dict(
                zip(("case", "commerce", "commerce2"), controls, strict=True)
            ),
            "pids": {},
            "stopped": True,
        }
    )
    build(settings)
    definition = settings.compose_definition(ports)
    definition["services"] = {
        k: v for k, v in definition["services"].items() if k in ("mysql", "redis")
    }
    definition["volumes"] = {"mysql-data": {}}
    durable(settings.folder / "compose.json", definition)
    settings.compose("up", "-d")
    wait(
        "D5 MySQL",
        lambda: (
            settings.sql(
                "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name IN ('case_db','commerce_db');"
            )
            == "2"
        ),
    )
    try:
        start(settings, "commerce")
        start(settings, "case")
        checks = {role: probe(settings, role) for role in ("commerce", "case")}
        assert all(
            row["sql"] > 0 and row["sql_inflight"] == 0 for row in checks.values()
        )
        durable(settings.folder / "bootstrap-checks.json", checks)
    finally:
        settings.stop_children(settings.load())
    print(
        "D5 owned databases migrated; extracted application/probe verified; JVMs stopped, data retained",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify", "stop"))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    settings = Settings(args.run_id)
    with settings.operation_lock():
        if args.action == "prepare":
            prepare(settings)
        elif args.action == "verify":
            text = verify_files(settings)
            print(
                json.dumps(
                    {
                        "artifacts_verified": len(text["artifacts"]),
                        "sources": text["sources"],
                    }
                )
            )
        else:
            for role in ("mysql", "redis"):
                settings.assert_owned(role)
            settings.stop_children(settings.load())
            settings.compose("stop", "--timeout", "30")


if __name__ == "__main__":
    main()
