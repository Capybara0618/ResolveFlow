"""Owned Gateway/Case/Commerce/MySQL/Redis/RocketMQ laboratory. No model worker."""

import argparse
import json
import os
import socket
import sys
import urllib.request
from pathlib import Path

from evaluation.backend_lab import (
    ROOT,
    SERVICES,
    Settings,
    allocate_ports,
    child_env,
    freeze_file,
    run,
    verify_file,
    wait,
)


def healthy(port, path="/actuator/health"):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
        return response.status == 200


def require_free(ports):
    for role, port in ports.items():
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise ValueError("occupied port; refusing to replace " + role)


def prepare(settings):
    ports = allocate_ports()
    settings.validate_ports(ports)
    require_free({**ports, "broker_vip": ports["broker"] - 2})
    # Before creating anything, refuse a pre-existing name even if its label looks plausible.
    for role in ("mysql", "redis", "namesrv", "broker", "broker-init"):
        existing = run(["docker", "ps", "-a", "--filter", "name=^/" + settings.container(role) + "$", "--format", "{{.ID}}"])
        if existing:
            raise ValueError("container already exists: " + role)
    settings.initialize({"run_id": settings.identity, "ports": ports, "pids": {}, "stopped": True})
    definition = settings.compose_definition(ports)
    (settings.folder / "compose.json").write_bytes((json.dumps(definition, indent=2) + "\n").encode())
    settings.freeze()
    settings.compose("config", "--quiet")
    resume(settings)


def resume(settings):
    state = settings.load()
    settings.freeze()  # Verify frozen jars, not the current Maven target directory.
    require_free({role: state["ports"][role] for role in (*SERVICES, "provider")})
    for role in ("mysql", "redis", "namesrv", "broker", "broker-init"):
        existing = run(["docker", "ps", "-a", "--filter", "name=^/" + settings.container(role) + "$", "--format", "{{.ID}}"])
        if existing:
            settings.assert_owned(role)
    (settings.folder / "compose.json").write_bytes(
        (json.dumps(settings.compose_definition(state["ports"]), indent=2) + "\n").encode())
    settings.compose("up", "-d")
    for role in ("mysql", "redis", "namesrv", "broker"):
        settings.assert_owned(role)
    wait("MySQL", lambda: settings.sql("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name IN ('case_db','commerce_db');") == "2")
    import_policies(settings, state)
    wait("Redis", lambda: run(["docker", "exec", settings.container("redis"), "redis-cli", "ping"]) == "PONG")
    for topic in ("rf-case-core-v2", "rf-commerce-core-v2"):
        command = ("exec /home/rocketmq/rocketmq-*/bin/mqadmin updateTopic -n namesrv:9876 "
                   f"-b 127.0.0.1:{state['ports']['broker']} -t {topic}")
        wait("MQ " + topic, lambda cmd=command: "success" in run(
            ["docker", "exec", settings.container("broker"), "sh", "-c", cmd], timeout=15).lower())
    env = child_env()
    env["PYTHONPATH"] = str(ROOT / "scripts")
    settings.start_child("provider", [sys.executable, "-m", "evaluation.backend_provider", "--run-id=" + settings.identity], env, state)
    wait("provider", lambda: healthy(state["ports"]["provider"], "/health"))
    java = Path(os.environ.get("JAVA_HOME", str(Path.home() / ".jdks/jdk-21.0.12.1+1"))) / "bin/java.exe"
    for role in ("commerce", "case", "gateway"):
        env = child_env()
        env.update(REDIS_HOST="127.0.0.1", REDIS_PORT=str(state["ports"]["redis"]),
                   PRODUCT_REVIEW_CACHE_ENABLED="true", PRODUCT_REVIEW_RATE_LIMIT_ENABLED="true",
                   REVIEW_CACHE_ENABLED="true", CHECKOUT_RECOVERY_ENABLED="true",
                   REFUND_PROVIDER_URL=f"http://127.0.0.1:{state['ports']['provider']}",
                   COMMERCE_BASE_URL=f"http://127.0.0.1:{state['ports']['commerce']}")
        args = [str(java), "-Xms128m", "-Xmx512m", "-Drf.backend.run=" + settings.identity,
                "-jar", str(settings.folder / "baseline" / (role + ".jar")),
                "--server.address=127.0.0.1", f"--server.port={state['ports'][role]}"]
        if role in ("case", "commerce"):
            account = "case_svc" if role == "case" else "commerce"
            env.update({role.upper() + "_DB_URL": f"jdbc:mysql://127.0.0.1:{state['ports']['mysql']}/{role}_db?connectionTimeZone=UTC&preserveInstants=true&allowPublicKeyRetrieval=true&useSSL=false",
                        role.upper() + "_DB_USER": account, role.upper() + "_DB_PASSWORD": account})
            args.extend([f"--resolveflow.events.namesrv=127.0.0.1:{state['ports']['namesrv']}",
                         "--resolveflow.events.consumer.enabled=true", "--resolveflow.events.publisher.enabled=true",
                         "--resolveflow.events.outbox.delivery-enabled=true", "--resolveflow.events.outbox.poll-interval-ms=300",
                         "--resolveflow.events.consumer.group=" + settings.project + "-" + role,
                         "--resolveflow.events.producer.group=" + settings.project + "-" + role + "-outbox"])
        if role == "commerce":
            args.extend(["--resolveflow.refund.dispatch-enabled=true", "--resolveflow.refund.reconcile-enabled=true",
                         "--resolveflow.refund.poll-interval-ms=1000"])
        elif role == "case":
            args.extend(["--resolveflow.dispatch.enabled=true", "--resolveflow.dispatch.poll-interval-ms=500",
                         "--resolveflow.agent.dispatch-enabled=false", "--resolveflow.support.dispatch-enabled=false"])
        else:
            args.append(f"--resolveflow.case.base-url=http://127.0.0.1:{state['ports']['case']}")
        settings.start_child(role, args, env, state)
        wait(role, lambda r=role: healthy(state["ports"][r]))
    state["stopped"] = False
    settings.save(state)
    print(json.dumps({"run_id": settings.identity, "gateway": f"http://127.0.0.1:{state['ports']['gateway']}"}))


def import_policies(settings, state):
    snapshot = settings.folder / "policy-snapshot.json"
    target = settings.folder / "baseline/policies"
    if snapshot.exists():
        hashes = json.loads(snapshot.read_text())
        for name, digest in hashes.items():
            verify_file(target / name, digest)
    else:
        target.mkdir(parents=True, exist_ok=True)
        hashes = {p.name: freeze_file(p, target / p.name) for p in sorted((ROOT / "fixtures/policies/bundles").glob("*.yaml"))}
        snapshot.write_bytes((json.dumps(hashes, indent=2) + "\n").encode())
    java = Path(os.environ.get("JAVA_HOME", str(Path.home() / ".jdks/jdk-21.0.12.1+1"))) / "bin/java.exe"
    env = child_env()
    env.update(CASE_DB_URL=f"jdbc:mysql://127.0.0.1:{state['ports']['mysql']}/case_db?connectionTimeZone=UTC&preserveInstants=true&allowPublicKeyRetrieval=true&useSSL=false",
               CASE_DB_USER="case_svc", CASE_DB_PASSWORD="case_svc")
    output = run([str(java), "-Xmx384m", "-jar", str(settings.folder / "baseline/case.jar"),
                  "--spring.main.web-application-type=none", "--resolveflow.policy.import-dir=" + str(target)], env=env)
    (settings.folder / "policy-import.log").write_bytes(output.encode())
    print("immutable synthetic policy fixtures imported", flush=True)


def check(settings):
    state = settings.load()
    baseline = settings.freeze()
    for role in ("mysql", "redis", "namesrv", "broker"):
        settings.assert_owned(role)
    checks = {role: healthy(state["ports"][role]) for role in SERVICES}
    checks["provider"] = healthy(state["ports"]["provider"], "/health")
    checks["mysql"] = settings.sql("SELECT 1;") == "1"
    checks["redis"] = run(["docker", "exec", settings.container("redis"), "redis-cli", "ping"]) == "PONG"
    for account, forbidden in (("case_svc", "commerce_db.orders"), ("commerce", "case_db.aftersale_case")):
        try:
            settings.sql("SELECT COUNT(*) FROM " + forbidden, account)
        except RuntimeError as error:
            if "denied" not in str(error).lower():
                raise
            checks[account + "_cross_db_denied"] = True
        else:
            checks[account + "_cross_db_denied"] = False
    if not all(checks.values()):
        raise AssertionError(checks)
    settings.report.mkdir(parents=True, exist_ok=True)
    result = {"run_id": settings.identity, "baseline": baseline, "checks": checks,
              "mq_topics": ["rf-case-core-v2", "rf-commerce-core-v2"],
              "topic_isolation": "dedicated broker, unchanged signed protocol topics; run-specific client groups"}
    (settings.report / "setup-checks.json").write_bytes((json.dumps(result, indent=2) + "\n").encode())
    print(json.dumps(checks))


def stop(settings):
    state = settings.load()
    for role in ("mysql", "redis", "namesrv", "broker", "broker-init"):
        settings.assert_owned(role)
    settings.stop_children(state)
    settings.compose("stop", "--timeout", "30")
    state["stopped"] = True
    settings.save(state)
    print("owned services stopped; containers, database and broker volumes retained")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "resume", "check", "exercise", "verify", "stop"))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    settings = Settings(args.run_id)
    with settings.operation_lock():
        if args.action in ("exercise", "verify"):
            from evaluation.backend_smoke import exercise, verify
            {"exercise": exercise, "verify": verify}[args.action](settings)
        else:
            {"prepare": prepare, "resume": resume, "check": check, "stop": stop}[args.action](settings)


if __name__ == "__main__":
    main()
