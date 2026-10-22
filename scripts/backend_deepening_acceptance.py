"""Isolated real-HTTP/browser acceptance; no Agent, original databases or paid APIs.

start -> prepare -> browser review/edit/reply -> verify -> stop.
Use resume to restart the owned services without recreating data after interruption.
Created containers are stopped and retained; original project resources are never reused.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "tmp/backend-deepening-acceptance"
STATE = RUNTIME / "runtime.json"
REPORT = ROOT / "reports/backend-deepening-v1/acceptance.json"
LABEL = "resolveflow.backend-acceptance"


def run(args, *, data=None, check=True):
    return subprocess.run(args, input=data, capture_output=True, check=check, timeout=120)


def save(state):
    STATE.write_bytes((json.dumps(state, indent=2) + "\n").encode())


def load():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if not re.fullmatch(r"[a-f0-9]{32}", state["run_id"]):
        raise ValueError("invalid acceptance ownership marker")
    for role in ("mysql", "redis"):
        expected = f"rf-backend-acceptance-{state['run_id'][:10]}-{role}"
        if state[role] != expected:
            raise ValueError("container is outside this acceptance run")
        label = run(["docker", "inspect", "--format", '{{index .Config.Labels "' + LABEL + '"}}', expected]).stdout.decode().strip()
        if label != state["run_id"]:
            raise ValueError("container ownership changed")
    return state


def api(state, method, path, token=None, body=None, key=None, expected=200, include_status=False):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["Idempotency-Key"] = key
    request = urllib.request.Request(
        f"http://127.0.0.1:{state['ports']['case']}{path}",
        data=None if body is None else json.dumps(body).encode(), headers=headers, method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status, content = response.status, response.read()
    except urllib.error.HTTPError as response:
        status, content = response.code, response.read()
    accepted = (expected,) if isinstance(expected, int) else expected
    if status not in accepted:
        raise AssertionError(f"{method} {path}: expected {expected}, got {status}: {content.decode()[:300]}")
    value = json.loads(content)
    return (status, value) if include_status else value


def login(state, name, password):
    return api(state, "POST", "/api/v1/auth/login", body={"username": name, "password": password})["access_token"]


def sql(state, statement):
    result = run(["docker", "exec", "-i", state["mysql"], "mysql", "-uroot", "-proot", "--default-character-set=utf8mb4", "--batch", "--raw", "--skip-column-names"], data=("SET time_zone='+00:00';\n" + statement).encode())
    return result.stdout.decode().strip()


def wait(label, predicate, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if predicate():
                print(label + " ready", flush=True)
                return
        except (OSError, urllib.error.URLError, subprocess.SubprocessError):
            pass
        time.sleep(.5)
    raise TimeoutError(label)


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def spawn(state, name, args, env):
    log = (RUNTIME / (name + ".log")).open("wb")
    process = subprocess.Popen(args, cwd=ROOT / "web" if name == "web" else ROOT,
                               env=env, stdout=log, stderr=subprocess.STDOUT,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    state.setdefault("pids", {})[name] = process.pid
    save(state)


def start():
    if STATE.exists():
        raise ValueError("acceptance runtime already exists; use its status/prepare/verify/stop rather than replacing it")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    identity = uuid.uuid4().hex
    state = {"run_id": identity, "ports": {name: port() for name in ("case", "commerce", "web")},
             "mysql": f"rf-backend-acceptance-{identity[:10]}-mysql", "redis": f"rf-backend-acceptance-{identity[:10]}-redis"}
    save(state)
    run(["docker", "run", "-d", "--name", state["mysql"], "--label", LABEL + "=" + identity,
         "-e", "MYSQL_ROOT_PASSWORD=root", "-p", "127.0.0.1::3306", "--mount",
         f"type=bind,source={ROOT / 'infra/mysql/init'},target=/docker-entrypoint-initdb.d,readonly", "mysql:8.4"])
    run(["docker", "run", "-d", "--name", state["redis"], "--label", LABEL + "=" + identity,
         "-p", "127.0.0.1::6379", "redis:7.4-alpine", "redis-server", "--appendonly", "no", "--save", ""])
    for name, internal in (("mysql", "3306/tcp"), ("redis", "6379/tcp")):
        state["ports"][name] = int(run(["docker", "port", state[name], internal]).stdout.decode().strip().rsplit(":", 1)[1])
    save(state)
    wait("temporary MySQL", lambda: sql(state, "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name IN ('commerce_db','case_db');") == "2")
    wait("temporary Redis", lambda: run(["docker", "exec", state["redis"], "redis-cli", "ping"]).stdout.strip() == b"PONG")
    resume(state)


def resume(state):
    # load() has already checked both exact container names and ownership labels.
    # Check all service ports before starting anything; never replace another process.
    for name in ("case", "commerce", "web"):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", state["ports"][name])) == 0:
                raise ValueError(name + " port is occupied; refusing to replace a service")
    run(["docker", "start", state["mysql"], state["redis"]])
    for name, internal in (("mysql", "3306/tcp"), ("redis", "6379/tcp")):
        state["ports"][name] = int(run(["docker", "port", state[name], internal]).stdout.decode().strip().rsplit(":", 1)[1])
    save(state)
    wait("temporary MySQL", lambda: sql(state, "SELECT 1;") == "1")
    wait("temporary Redis", lambda: run(["docker", "exec", state["redis"], "redis-cli", "ping"]).stdout.strip() == b"PONG")
    java = Path(os.environ.get("JAVA_HOME", str(Path.home() / ".jdks/jdk-21.0.12.1+1"))) / "bin/java.exe"
    for name in ("commerce", "case"):
        env = os.environ.copy()
        env.update(REDIS_HOST="127.0.0.1", REDIS_PORT=str(state["ports"]["redis"]),
                   PRODUCT_REVIEW_CACHE_ENABLED="true", PRODUCT_REVIEW_RATE_LIMIT_ENABLED="true",
                   REVIEW_CACHE_ENABLED="true", CHECKOUT_RECOVERY_ENABLED="true")
        prefix = name.upper()
        env.update({prefix + "_DB_URL": f"jdbc:mysql://127.0.0.1:{state['ports']['mysql']}/{name}_db?connectionTimeZone=UTC&preserveInstants=true&allowPublicKeyRetrieval=true&useSSL=false",
                    prefix + "_DB_USER": "commerce" if name == "commerce" else "case_svc",
                    prefix + "_DB_PASSWORD": "commerce" if name == "commerce" else "case_svc",
                    "COMMERCE_BASE_URL": f"http://127.0.0.1:{state['ports']['commerce']}"})
        jar = ROOT / f"java/{name}-service/target/{name}-service-0.1.0-SNAPSHOT.jar"
        spawn(state, name, [str(java), "-jar", str(jar), "--server.address=127.0.0.1", f"--server.port={state['ports'][name]}"], env)
        wait(name, lambda role=name: urllib.request.urlopen(f"http://127.0.0.1:{state['ports'][role]}/actuator/health", timeout=2).status == 200)
    env = os.environ.copy()
    env.update(VITE_API_PROXY=f"http://127.0.0.1:{state['ports']['case']}", VITE_PORT=str(state["ports"]["web"]))
    spawn(state, "web", [shutil.which("node"), str(ROOT / "web/node_modules/vite/bin/vite.js"), "--host", "127.0.0.1"], env)
    wait("web", lambda: urllib.request.urlopen(f"http://127.0.0.1:{state['ports']['web']}", timeout=2).status == 200)
    state["stopped"] = False
    save(state)
    print(json.dumps({"web": f"http://127.0.0.1:{state['ports']['web']}/", "run_id": state["run_id"]}))


def prepare(state):
    buyer = login(state, "demo-buyer", "demo-pass-4001")
    admin = login(state, "demo-admin", "demo-pass-1100")
    for name in ("draft_key", "pay_key", "ship_key", "logistics_key", "expire_key"):
        state.setdefault(name, uuid.uuid4().hex)
    save(state)
    product = api(state, "GET", "/api/v1/shop/products/P-1001")
    sku = product["skus"][0]
    draft = api(state, "POST", "/api/v1/shop/drafts", buyer,
                {"sku_id": sku["sku_id"], "quantity": 1, "expected_sku_version": sku["version"]}, state["draft_key"])
    api(state, "POST", f"/api/v1/shop/drafts/{draft['draft_id']}/payment", buyer, {}, state["pay_key"])
    purchase = api(state, "GET", "/api/v1/shop/purchases/draft:" + draft["draft_id"], buyer)
    assert purchase["status"] == "PAID"
    state.update(draft=draft["draft_id"], order=purchase["order_id"], line=purchase["lines"][0]["line_id"], product=product["product_id"])
    save(state)
    if not state.get("delivered"):
        own = api(state, "GET", f"/api/v1/shop/orders/lines/{state['line']}/review", buyer)
        assert own["can_review"] is False and own["review"] is None
        api(state, "POST", f"/api/v1/merchant/orders/{state['order']}/simulated-shipment", admin, {"expected_version": 1}, state["ship_key"])
        import logistics_simulator
        sql(state, "USE commerce_db;\n" + logistics_simulator.call_sql(state["order"], "M-1001", 2, "DELIVERED", state["logistics_key"], None))
        state["delivered"] = True
    assert api(state, "GET", f"/api/v1/shop/orders/lines/{state['line']}/review", buyer)["can_review"] is True
    state["money_before"] = sql(state, "SELECT JSON_OBJECT('paid',paid_amount,'refunded',refunded_amount,'reserved',reserved_refund_amount) FROM commerce_db.payment_ledger WHERE order_id='" + state["order"] + "';")
    save(state)
    print(json.dumps({"buyer_url": f"http://127.0.0.1:{state['ports']['web']}/#/shop/drafts/{state['draft']}",
                      "product_url": f"http://127.0.0.1:{state['ports']['web']}/#/shop/products/{state['product']}",
                      "delivery": "real purchase -> merchant simulated shipment -> existing controlled logistics procedure"}))


def verify(state):
    buyer = login(state, "demo-buyer", "demo-pass-4001")
    admin = login(state, "demo-admin", "demo-pass-1100")
    other = login(state, "demo-admin-m2", "demo-pass-2100")
    assert state["delivered"] is True
    assert api(state, "GET", "/api/v1/shop/purchases/draft:" + state["draft"], buyer)["status"] == "PAID"
    own = api(state, "GET", f"/api/v1/shop/orders/lines/{state['line']}/review", buyer)
    review = own["review"]
    assert review["rating"] == 4 and review["body"].startswith("隔离验收") and review["reply"]
    page = api(state, "GET", f"/api/v1/shop/products/{state['product']}/reviews?limit=10")
    assert page["summary"] == {"count": 1, "average": 4.0, "stars": [0, 1, 0, 0, 0]}
    assert page["items"] == [review]
    api(state, "POST", f"/api/v1/merchant/reviews/{review['review_id']}/reply", other, {"body": "cross-store denied", "expected_version": review["version"]}, expected=404)
    api(state, "GET", "/api/v1/merchant/reviews", buyer, expected=403)
    api(state, "POST", f"/api/v1/shop/orders/lines/{state['line']}/review", buyer,
        {"rating": 1, "body": "stale denied", "expected_version": 0}, expected=409)
    assert len(api(state, "GET", "/api/v1/merchant/reviews", admin)["items"]) == 1
    epoch = sql(state, "SELECT version FROM commerce_db.product_review_epoch WHERE product_id='P-1001';")
    cached = run(["docker", "exec", state["redis"], "redis-cli", "GET", "rf:reviews:first:v1:P-1001:" + epoch]).stdout.decode()
    assert json.loads(cached)["summary"] == page["summary"]
    # Replay identical content so exercising the live limiter cannot alter the review.
    for _ in range(7):
        status, _ = api(state, "POST", f"/api/v1/shop/orders/lines/{state['line']}/review", buyer,
                        {"rating": review["rating"], "body": review["body"], "expected_version": review["version"]},
                        expected=(200, 429), include_status=True)
        if status == 429:
            break
    else:
        raise AssertionError("live account limiter did not return 429 within seven writes")
    assert api(state, "GET", f"/api/v1/shop/orders/lines/{state['line']}/review", buyer)["review"] == review
    assert sql(state, "SELECT version FROM commerce_db.product_review_epoch WHERE product_id='P-1001';") == epoch
    assert sql(state, "SELECT JSON_OBJECT('paid',paid_amount,'refunded',refunded_amount,'reserved',reserved_refund_amount) FROM commerce_db.payment_ledger WHERE order_id='" + state["order"] + "';") == state["money_before"]
    assert sql(state, "SELECT state FROM commerce_db.line_refund WHERE line_id='" + state["line"] + "';") == "FREE"
    draft = api(state, "POST", "/api/v1/shop/drafts", buyer,
                {"sku_id": "SKU-1001-BLACK", "quantity": 1, "expected_sku_version": 1}, state["expire_key"])
    sql(state, "UPDATE commerce_db.checkout_draft SET created_at=UTC_TIMESTAMP(6)-INTERVAL 16 MINUTE,expires_at=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE draft_id='" + draft["draft_id"] + "';")
    wait("scheduled expiration", lambda: sql(state, "SELECT CONCAT(status,':',close_reason) FROM commerce_db.checkout_draft WHERE draft_id='" + draft["draft_id"] + "';") == "CANCELLED:EXPIRED", 10)
    assert api(state, "GET", "/api/v1/shop/drafts/" + draft["draft_id"], buyer)["status"] == "EXPIRED"
    assert sql(state, "SELECT COUNT(*) FROM commerce_db.checkout_payment_attempt WHERE draft_id='" + draft["draft_id"] + "';") == "0"
    result = {"date": "2026-10-22", "environment": "isolated MySQL8.4 + Redis7.4, actual Case/Commerce and Vite",
              "model_requests": 0, "gateway_exercised": False, "public_summary": page["summary"],
              "checks": {name: True for name in ["purchase_paid", "unshipped_review_ineligible", "controlled_delivery", "browser_review_content_present", "public_matches_saved_review", "cross_store_reply_404", "buyer_merchant_list_403", "stale_version_409", "real_redis_cache", "live_account_limit_429_without_review_change", "money_unchanged", "refund_slot_free", "scheduled_expiry_persisted", "expired_public_projection", "expired_without_payment_attempt"]}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps(result, ensure_ascii=False))


def stop(state):
    for name, pid in state.get("pids", {}).items():
        marker = str(ROOT / ("web/node_modules/vite/bin/vite.js" if name == "web" else f"java/{name}-service/target/{name}-service-0.1.0-SNAPSHOT.jar"))
        script = "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(int(pid)) + "'; if ($p -and $p.CommandLine.Contains('" + marker.replace("'", "''") + "')) { Stop-Process -Id " + str(int(pid)) + " -ErrorAction Stop }"
        run(["powershell", "-NoProfile", "-Command", script])
    run(["docker", "stop", "--timeout", "30", state["mysql"], state["redis"]])
    state["stopped"] = True
    save(state)
    print("owned Java/Node processes and isolated containers stopped; database containers retained")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "resume", "prepare", "verify", "stop", "status"))
    action = parser.parse_args().action
    if action == "start":
        start()
    else:
        state = load()
        if action == "status":
            print(json.dumps({"ports": state["ports"], "stopped": state.get("stopped", False)}))
        else:
            {"resume": resume, "prepare": prepare, "verify": verify, "stop": stop}[action](state)


if __name__ == "__main__":
    main()
