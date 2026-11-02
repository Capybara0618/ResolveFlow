"""Three real JVMs and disposable, labelled databases; never touches project runtime/data.

Build first: java/mvnw.cmd -f java/pom.xml -pl gateway,case-service,commerce-service -am -DskipTests package
Run: agent/.venv/Scripts/python.exe scripts/verify_service_boundaries.py
No Agent/model/MQ worker is started. Credentials stay in memory; output is redacted assertions.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL = "resolveflow.boundary-check"


def command(args, *, data=None, timeout=60):
    result = subprocess.run(args, input=data, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed with exit {result.returncode}")
    return result.stdout.strip()


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class BoundaryCheck:
    def __init__(self):
        self.identity = uuid.uuid4().hex
        self.folder = ROOT / "tmp/service-boundary-live" / self.identity
        self.folder.mkdir(parents=True)
        self.containers = []
        self.processes = {}
        self.logs = []
        self.checks = []
        self.ports = {role: port() for role in ["case", "commerce", "gateway"]}
        if len(set(self.ports.values())) != 3:
            raise RuntimeError("port allocation collision; retry")
        self.password = secrets.token_hex(20)

    def owned(self, container):
        label = command(["docker", "inspect", "--format", '{{index .Config.Labels "' + LABEL + '"}}', container])
        if label != self.identity:
            raise RuntimeError("refusing a container outside this check")

    def container(self, role, image, internal, extra):
        name = "rf-boundary-" + self.identity + "-" + role
        identifier = command(["docker", "run", "--rm", "-d", "--name", name, "--label", LABEL + "=" + self.identity,
                              "-p", f"127.0.0.1::{internal}", *extra, image], timeout=90)
        self.containers.append(identifier)
        self.owned(identifier)
        endpoint = command(["docker", "port", identifier, str(internal)]).splitlines()[0]
        return identifier, int(endpoint.rsplit(":", 1)[1])

    def sql(self, text):
        self.owned(self.mysql)
        return command(["docker", "exec", "-i", "-e", "MYSQL_PWD=" + self.password, self.mysql,
                        "mysql", "-uroot", "--batch", "--skip-column-names", "--default-character-set=utf8mb4"], data=text)

    def request(self, path, *, role="gateway", token=None, body=None, expected=200, key=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if key:
            headers["Idempotency-Key"] = key
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{self.ports[role]}" + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status, content = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, content = error.code, error.read()
        if status != expected:
            raise AssertionError(f"{role} {'POST' if data else 'GET'} {path.split('?')[0]}: {status}, expected {expected}")
        return json.loads(content) if content else None

    def wait(self, label, action, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                action()
                return
            except (RuntimeError, AssertionError, OSError, urllib.error.URLError):
                time.sleep(0.5)
        raise RuntimeError("timed out waiting for " + label)

    def start(self, role):
        module = "gateway" if role == "gateway" else role + "-service"
        jar = ROOT / f"java/{module}/target/{module}-0.1.0-SNAPSHOT.jar"
        java = Path(os.environ.get("JAVA_HOME", str(Path.home() / ".jdks/jdk-21.0.12.1+1"))) / "bin/java.exe"
        if not java.exists() or not jar.exists():
            raise RuntimeError("build jars and supply Java 21 before this check")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("RESOLVEFLOW_", "SPRING_"))}
        env.update(REDIS_HOST="127.0.0.1", REDIS_PORT=str(self.redis_port), COMMERCE_BASE_URL=f"http://127.0.0.1:{self.ports['commerce']}",
                   RESOLVEFLOW_COMMERCE_BASE_URL=f"http://127.0.0.1:{self.ports['commerce']}",
                   RESOLVEFLOW_CASE_BASE_URL=f"http://127.0.0.1:{self.ports['case']}",
                   RESOLVEFLOW_IDENTITY_BASE_URL=f"http://127.0.0.1:{self.ports['case']}",
                   RESOLVEFLOW_USER_MEDIA_DIR=str(self.folder / "media"), PRODUCT_REVIEW_RATE_LIMIT_ENABLED="true")
        if role != "gateway":
            env.update({role.upper() + "_DB_URL": f"jdbc:mysql://127.0.0.1:{self.mysql_port}/{role}_db?connectionTimeZone=UTC&preserveInstants=true&allowPublicKeyRetrieval=true&useSSL=false",
                        role.upper() + "_DB_USER": "case_svc" if role == "case" else "commerce",
                        role.upper() + "_DB_PASSWORD": "case_svc" if role == "case" else "commerce"})
        log = (self.folder / f"{role}-{len(self.logs)}.log").open("wb")
        self.logs.append(log)
        self.processes[role] = subprocess.Popen([str(java), "-Xmx384m", "-jar", str(jar), "--server.address=127.0.0.1",
                                                f"--server.port={self.ports[role]}", "--resolveflow.compat.commerce-facade-enabled=false"],
                                               cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        self.wait(role, lambda: self.request("/actuator/health", role=role))

    def stop(self, role):
        process = self.processes.pop(role, None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def passed(self, name):
        self.checks.append(name)
        print("PASS " + name, flush=True)

    def exercise(self):
        self.mysql, self.mysql_port = self.container("mysql", "mysql:8.4", 3306, ["-e", "MYSQL_ROOT_PASSWORD=" + self.password])
        _, self.redis_port = self.container("redis", "redis:7.4-alpine", 6379, [])
        self.wait("isolated mysql", lambda: self.sql("SELECT 1;"))
        self.sql((ROOT / "infra/mysql/init/01-databases.sql").read_text(encoding="utf-8"))
        for role in ["commerce", "case", "gateway"]:
            self.start(role)
        self.passed("three real JVMs with separate DB accounts and Case trading facades disabled")
        for role, expected in [("case", 404), ("commerce", 200), ("gateway", 200)]:
            self.request("/api/v1/shop/products", role=role, expected=expected)
        self.request("/internal/v1/shop/products", expected=404)
        self.passed("catalog enters Commerce directly; internal paths stay private")
        username = "boundary_" + self.identity[:16]
        password = secrets.token_urlsafe(24)
        receipt = self.request("/api/v1/auth/register", body={"username": username, "display_name": "边界合成买家", "password": password}, expected=201)
        login = self.request("/api/v1/auth/login", body={"username": username, "password": password})
        token = login["access_token"]
        other = self.request("/api/v1/auth/login", body={"username": "demo-buyer", "password": "demo-pass-4001"})["access_token"]
        merchant = self.request("/api/v1/auth/login", body={"username": "demo-admin", "password": "demo-pass-1100"})["access_token"]
        other_merchant = self.request("/api/v1/auth/login", body={"username": "demo-admin-m2", "password": "demo-pass-2100"})["access_token"]
        address = self.request("/api/v1/account/addresses", token=token, body={"recipient": "合成收件人", "phone": "13800000000",
                               "province": "浙江省", "city": "杭州市", "district": "西湖区", "detail": "隔离验证路1号", "is_default": True})
        draft_body = {"sku_id": "SKU-1001-BLACK", "quantity": 1, "expected_sku_version": 1,
                      "shipping": {"address_id": address["address_id"], "expected_version": address["version"]}}
        key = uuid.uuid4().hex
        baseline_orders = int(self.sql("SELECT COUNT(*) FROM commerce_db.orders;"))
        draft = self.request("/api/v1/shop/drafts", token=token, body=draft_body, key=key)
        assert self.request("/api/v1/shop/drafts", token=token, body=draft_body, key=key)["draft_id"] == draft["draft_id"]
        self.request("/api/v1/shop/drafts", role="case", token=token, body=draft_body, key=key, expected=404)
        payment_key = uuid.uuid4().hex
        path = "/api/v1/shop/drafts/" + draft["draft_id"] + "/payment"
        payment = self.request(path, token=token, body={}, key=payment_key)
        assert self.request(path, token=token, body={}, key=payment_key)["order_id"] == payment["order_id"]
        assert int(self.sql("SELECT COUNT(*) FROM commerce_db.orders;")) == baseline_orders + 1
        self.passed("registration, current account, owned address, draft and payment replay publish one order")
        order, line = payment["order_id"], payment["line_id"]
        self.request("/api/v1/orders/" + order, token=other, expected=404)
        self.request("/api/v1/merchant/orders/" + order, token=other_merchant, expected=404)
        self.request("/api/v1/merchant/orders/" + order, token=token, expected=403)
        self.request("/api/v1/orders/lines/" + line, token=token)
        self.request("/api/v1/merchant/orders/" + order, token=merchant)
        self.request("/api/v1/customer/cases", token=token)
        self.request("/api/v1/support/conversations", token=token)
        self.passed("Commerce resource isolation and Case aftercare read APIs coexist")
        self.request("/api/v1/merchant/orders/" + order + "/simulated-shipment", token=merchant,
                     body={"expected_version": 1}, key=uuid.uuid4().hex)
        self.request("/api/v1/shop/purchases/draft:" + draft["draft_id"] + "/fulfillment", token=token)
        view = self.request("/api/v1/shop/purchases/draft:" + draft["draft_id"] + "/shipping", token=token)
        assert view["shipping"]["recipient"] == "合成收件人"
        self.passed("merchant shipment and buyer immutable shipping/fulfillment work through split routes")
        # Fault injection is restricted to this run's throwaway DB, never a project container.
        self.sql("UPDATE case_db.identity_account SET enabled=FALSE WHERE username='" + username + "';")
        self.request("/api/v1/shop/cart", token=token, expected=401)
        self.sql("UPDATE case_db.identity_account SET enabled=TRUE WHERE username='" + username + "';")
        new_password = secrets.token_urlsafe(24)
        self.request("/api/v1/auth/recover", body={"username": username, "recovery_key": receipt["recovery_key"], "new_password": new_password})
        self.request("/api/v1/shop/purchases", token=token, expected=401)
        token = self.request("/api/v1/auth/login", body={"username": username, "password": new_password})["access_token"]
        self.request("/api/v1/orders/" + order, token=token)
        self.passed("disabled accounts and recovered-password old sessions are rejected across services")
        self.stop("case")
        self.request("/api/v1/shop/products")
        self.request("/api/v1/shop/products/P-1001/presentation")
        self.request("/api/v1/shop/cart", token=token, expected=503)
        self.passed("Case outage leaves catalog available and protected trading fails closed")
        self.start("case")
        self.request("/api/v1/orders/" + order, token=token)
        assert int(self.sql("SELECT COUNT(*) FROM commerce_db.orders;")) == baseline_orders + 1
        self.passed("Case restart preserves current sessions and original Commerce order")

    def close(self):
        for role in list(self.processes):
            self.stop(role)
        for log in self.logs:
            log.close()
        for identifier in reversed(self.containers):
            self.owned(identifier)
            command(["docker", "stop", "-t", "2", identifier], timeout=30)


def main():
    check = BoundaryCheck()
    status = "failed"
    try:
        check.exercise()
        status = "passed"
    finally:
        check.close()
        result = {"status": status, "checks": check.checks, "model_requests": 0, "project_data_touched": False}
        (check.folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Evidence: " + str(check.folder), flush=True)


if __name__ == "__main__":
    main()
