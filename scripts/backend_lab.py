"""Exercise the three Java additions against isolated local infrastructure."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
from threading import Event, Thread
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", "infra/compose.backend-lab.yaml"]
CATALOG = "/api/v1/shop/products"
MERCHANT = "/api/v1/merchant/products"
GATEWAY = 18180
CASE = 18083
PRIMARY = 18081
SECONDARY = 18084
METRICS = 18082
ELASTIC = 19200
INDEX = "resolveflow-products-v1"
TOPIC = "resolveflow.catalog.search.v1"
GROUP = "resolveflow-catalog-index-v1"
MYSQL_URL = "jdbc:mysql://127.0.0.1:13307/{}_db?connectionTimeZone=UTC&allowPublicKeyRetrieval=true&useSSL=false"


def request(port, path, body=None, token=None):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers)
    try:
        reply = urlopen(req, timeout=6)
    except HTTPError as error:
        reply = error
    except (URLError, TimeoutError, ConnectionError):
        return 0, {}, {}
    with reply:
        payload = reply.read()
        return reply.code, reply.headers, json.loads(payload) if payload else {}


def required(port, path, body=None, token=None, status=200):
    code, _, response = request(port, path, body, token)
    if code != status:
        raise RuntimeError(
            f"{path.split('?')[0]} expected {status}, received {code}: {response.get('code')}"
        )
    return response


def until(description, probe, seconds=75, interval=0.25):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = probe()
        if value:
            return value
        time.sleep(interval)
    raise RuntimeError(f"Timed out waiting for {description}")


def docker(*args, stdin=None):
    return subprocess.run(
        [*COMPOSE, *args],
        cwd=ROOT,
        text=True,
        input=stdin,
        capture_output=True,
        check=True,
        timeout=220,
    ).stdout


class Lab:
    def __init__(self, java_home, output):
        suffix = ".exe" if os.name == "nt" else ""
        self.java = java_home / "bin" / f"java{suffix}"
        self.jcmd = java_home / "bin" / f"jcmd{suffix}"
        self.jfr = java_home / "bin" / f"jfr{suffix}"
        self.output = output
        self.processes = []
        self.results = {}

    def start(
        self, role, port, profiles="", *, consume=True, backfill=False, pool_size=10
    ):
        health_port = METRICS if "backend-profile" in profiles else port
        for candidate in {port, health_port}:
            try:
                connection = socket.create_connection(
                    ("127.0.0.1", candidate), timeout=0.2
                )
            except OSError:
                continue
            connection.close()
            raise RuntimeError(f"Lab port {candidate} is already occupied")
        jar = ROOT / f"java/{role}/target/{role}-0.1.0-SNAPSHOT.jar"
        if not jar.is_file():
            raise FileNotFoundError(f"Build the application jars first: {jar}")
        args = [
            str(self.java),
            "-Xms96m",
            "-Xmx384m",
            "-XX:ActiveProcessorCount=4",
            "-jar",
            str(jar),
            f"--server.port={port}",
            "--server.address=127.0.0.1",
        ]
        if profiles:
            args.append(f"--spring.profiles.active={profiles}")
        env = os.environ | {
            "CASE_DB_URL": MYSQL_URL.format("case"),
            "COMMERCE_DB_URL": MYSQL_URL.format("commerce"),
            "BACKEND_SEARCH_CONSUMER": str(consume).lower(),
            "BACKEND_SEARCH_BACKFILL": str(backfill).lower(),
            "BACKEND_METRICS_PORT": str(METRICS),
            "BACKEND_DB_POOL_SIZE": str(pool_size),
            "RESOLVEFLOW_IDENTITY_BASE_URL": f"http://127.0.0.1:{CASE}",
            "RESOLVEFLOW_COMMERCE_BASE_URL": f"http://127.0.0.1:{PRIMARY}",
            "RESOLVEFLOW_CASE_BASE_URL": f"http://127.0.0.1:{CASE}",
        }
        log_path = self.output / f"{role}-{port}-{len(self.processes)}.log"
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                args,
                cwd=ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        self.processes.append(process)

        def healthy():
            if process.poll() is not None:
                raise RuntimeError(f"{role} exited; see {log_path}")
            return request(health_port, "/actuator/health")[0] == 200

        until(f"{role}:{port}", healthy, seconds=100)
        return process

    @staticmethod
    def kill(process):
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)

    def close(self):
        for process in reversed(self.processes):
            self.kill(process)

    def result(self, name, value):
        self.results[name] = value
        (self.output / "results.json").write_text(
            json.dumps(self.results, indent=2), encoding="utf-8"
        )
        print(f"{name}: {json.dumps(value)}", flush=True)

    def tool(self, executable, *args):
        return subprocess.run(
            [str(executable), *map(str, args)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=50,
        ).stdout

    def search(self, primary, merchant):
        name = f"rflab{uuid4().hex[:12]}"
        document = {
            "name": name,
            "description": "用于本地搜索验收的商品",
            "category": "electronics",
            "asset_key": "headphones",
            "listed": True,
            "skus": [
                {
                    "variant": "black",
                    "unit_amount": 12000,
                    "max_quantity": 2,
                    "listed": True,
                }
            ],
        }
        start = time.monotonic()
        saved = required(GATEWAY, MERCHANT, document, merchant, 201)
        product_id = saved["product_id"]
        if not re.fullmatch(r"P-[0-9a-f-]{36}", product_id):
            raise RuntimeError("Invalid lab product id")
        path = f"{CATALOG}?{urlencode({'query': name, 'category': 'electronics'})}"
        index_path = f"/{INDEX}/_doc/{product_id}"
        sql = f"SELECT COUNT(*) FROM catalog_search_outbox WHERE product_id='{product_id}'"

        def published():
            return (
                docker(
                    "exec",
                    "-T",
                    "mysql",
                    "mysql",
                    "-N",
                    "-ucommerce",
                    "-pcommerce",
                    "commerce_db",
                    "-e",
                    sql,
                ).strip()
                == "0"
            )

        until("Kafka publish while consumer is disabled", published)
        assert request(ELASTIC, index_path)[0] == 404
        assert not required(PRIMARY, path)["items"]
        self.kill(primary)
        primary = self.start(
            "commerce-service",
            PRIMARY,
            "backend-discovery,backend-search,backend-profile",
        )

        def appears():
            code, _, reply = request(GATEWAY, path)
            return code == 200 and any(
                row["product_id"] == product_id for row in reply["items"]
            )

        until("consumer restart and search refresh", appears)
        backlog_visible_ms = round(1000 * (time.monotonic() - start))
        description_search = f"{CATALOG}?{urlencode({'query': '本地搜索验收', 'store_id': saved['store_id']})}"
        assert any(
            row["product_id"] == product_id
            for row in required(GATEWAY, description_search)["items"]
        )
        other_category = f"{CATALOG}?{urlencode({'query': name, 'category': 'home'})}"
        assert not required(GATEWAY, other_category)["items"]
        document["listed"] = False
        document["expected_version"] = saved["version"]
        document["skus"][0]["sku_id"] = saved["skus"][0]["sku_id"]
        document["skus"][0]["listed"] = False
        started = time.monotonic()
        unlisted = required(GATEWAY, f"{MERCHANT}/{product_id}", document, merchant)
        until(
            "unlisted index version",
            lambda: (
                request(ELASTIC, index_path)[2].get("_version") == unlisted["version"]
            ),
        )
        index_update_ms = round(1000 * (time.monotonic() - started))
        assert not required(GATEWAY, path)["items"]
        old = {
            "id": product_id,
            "store": saved["store_id"],
            "name": name,
            "description": document["description"],
            "category": "electronics",
            "listed": True,
            "version": saved["version"],
        }
        docker(
            "exec",
            "-T",
            "kafka",
            "/opt/kafka/bin/kafka-console-producer.sh",
            "--bootstrap-server",
            "localhost:29092",
            "--topic",
            TOPIC,
            "--property",
            "parse.key=true",
            "--property",
            "key.separator=|",
            stdin=f"{product_id}|{json.dumps(old)}\n",
        )

        def drained():
            output = docker(
                "exec",
                "-T",
                "kafka",
                "/opt/kafka/bin/kafka-consumer-groups.sh",
                "--bootstrap-server",
                "localhost:29092",
                "--describe",
                "--group",
                GROUP,
            )
            rows = [
                line.split() for line in output.splitlines() if line.startswith(GROUP)
            ]
            return (
                len(rows) == 2
                and any(row[5] == "0" for row in rows)
                and all(row[5] in {"0", "-"} for row in rows)
            )

        until("Kafka offsets after replay", drained, interval=1)
        index = required(ELASTIC, index_path)
        assert (
            index["_version"] == unlisted["version"] and not index["_source"]["listed"]
        )
        assert not required(GATEWAY, path)["items"]
        self.result(
            "search",
            {
                "consumer_catch_up_including_restart_ms": backlog_visible_ms,
                "unlist_to_index_ms": index_update_ms,
                "old_event_ignored": True,
            },
        )
        return primary

    def discovery(self):
        secondary = self.start(
            "commerce-service",
            SECONDARY,
            "backend-discovery,backend-search",
            consume=False,
        )

        def sample():
            status, headers, _ = request(GATEWAY, CATALOG + "?limit=1")
            return headers.get("X-ResolveFlow-Instance", str(status))

        seen = set()

        def both():
            seen.add(sample())
            return {str(PRIMARY), str(SECONDARY)} <= seen

        until("traffic to both discovered instances", both)
        distribution = Counter(sample() for _ in range(30))
        self.kill(secondary)
        started = time.monotonic()
        samples = []

        def removed():
            samples.append(sample())
            return samples[-10:] == [str(PRIMARY)] * 10

        until("traffic stabilized after force stop", removed, seconds=100)
        removal_ms = round(1000 * (time.monotonic() - started))
        started = time.monotonic()
        secondary = self.start(
            "commerce-service",
            SECONDARY,
            "backend-discovery,backend-search",
            consume=False,
        )
        until("restarted instance receives traffic", lambda: sample() == str(SECONDARY))
        self.result(
            "discovery",
            {
                "distribution": dict(distribution),
                "after_stop": dict(Counter(samples)),
                "stable_window_ms": removal_ms,
                "restart_to_traffic_ms": round(1000 * (time.monotonic() - started)),
            },
        )
        self.kill(secondary)

    def profile(self, primary, buyer, duration, name):
        path = "/api/v1/shop/purchases?limit=24"
        assert required(GATEWAY, path, token=buyer)["items"]

        def load(concurrency, seconds):
            started = time.monotonic()
            end = started + seconds

            def worker(_):
                local = []
                while time.monotonic() < end:
                    start = time.monotonic()
                    code, _, _ = request(GATEWAY, path, token=buyer)
                    local.append((code, (time.monotonic() - start) * 1000))
                return local

            with ThreadPoolExecutor(max_workers=concurrency) as workers:
                result = [
                    item
                    for batch in workers.map(worker, range(concurrency))
                    for item in batch
                ]
            return result, time.monotonic() - started

        load(8, 3)
        output = self.output / f"{name}.jfr"
        self.tool(
            self.jcmd, primary.pid, "JFR.start", "name=backend-lab", "settings=profile"
        )
        measurements = []
        pool = []
        done = Event()

        def monitor():
            while not done.wait(0.25):
                readings = {}
                for metric in ("active", "pending", "max"):
                    code, _, result = request(
                        METRICS, f"/actuator/metrics/hikaricp.connections.{metric}"
                    )
                    if code == 200:
                        readings[metric] = result["measurements"][0]["value"]
                if readings:
                    pool.append(readings)

        sampler = Thread(target=monitor, daemon=True)
        sampler.start()
        try:
            for concurrency in (1, 8, 24):
                result, elapsed = load(concurrency, duration)
                latencies = sorted(
                    elapsed for status, elapsed in result if status == 200
                )
                if not latencies:
                    raise RuntimeError(
                        "Order profiling returned no successful requests"
                    )

                def percentile(fraction):
                    return round(latencies[math.ceil(len(latencies) * fraction) - 1], 2)

                measurements.append(
                    {
                        "concurrency": concurrency,
                        "requests": len(result),
                        "statuses": dict(Counter(status for status, _ in result)),
                        "requests_per_second": round(len(result) / elapsed, 2),
                        "p95_ms": percentile(0.95),
                        "p99_ms": percentile(0.99),
                    }
                )
        finally:
            done.set()
            sampler.join(timeout=8)
            self.tool(
                self.jcmd,
                primary.pid,
                "JFR.stop",
                "name=backend-lab",
                f"filename={output}",
            )
        summary = self.tool(self.jfr, "summary", output)
        (self.output / f"{name}-jfr-summary.txt").write_text(summary, encoding="utf-8")
        count = re.search(r"resolveflow\.BuyerOrderShardRead\s+(\d+)", summary)
        assert count and int(count.group(1)) > 0 and pool
        (self.output / f"{name}-pool-samples.json").write_text(
            json.dumps(pool, indent=2), encoding="utf-8"
        )
        self.result(
            name,
            {
                "windows": measurements,
                "jfr_shard_events": int(count.group(1)),
                "pool_samples": len(pool),
                "pool_peak_active": max(item.get("active", 0) for item in pool),
                "pool_max": max(item.get("max", 0) for item in pool),
                "pool_peak_pending": max(item.get("pending", 0) for item in pool),
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-home", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seconds-per-window", type=int, default=8)
    args = parser.parse_args()
    if args.seconds_per_window < 2:
        parser.error("--seconds-per-window must be at least 2")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    lab = Lab(args.java_home.resolve(), output)
    try:
        docker("up", "-d", "--wait", "--pull", "never")
        lab.start("case-service", CASE)
        primary = lab.start(
            "commerce-service",
            PRIMARY,
            "backend-discovery,backend-search,backend-profile",
            consume=False,
            backfill=True,
        )
        lab.start("gateway", GATEWAY, "backend-discovery")
        buyer = required(
            GATEWAY,
            "/api/v1/auth/login",
            {"username": "demo-buyer", "password": "demo-pass-4001"},
        )["access_token"]
        merchant = required(
            GATEWAY,
            "/api/v1/auth/login",
            {"username": "demo-admin", "password": "demo-pass-1100"},
        )["access_token"]
        primary = lab.search(primary, merchant)
        lab.discovery()
        lab.profile(primary, buyer, args.seconds_per_window, "profiling-pool-10")
        lab.kill(primary)
        candidate = lab.start(
            "commerce-service",
            PRIMARY,
            "backend-discovery,backend-search,backend-profile",
            pool_size=16,
        )
        lab.profile(candidate, buyer, args.seconds_per_window, "profiling-pool-16")
        lab.kill(candidate)
        until(
            "gateway has no remaining Commerce instance",
            lambda: request(GATEWAY, CATALOG)[0] == 503,
        )
        lab.result("no_healthy_instance", {"http": 503})
    finally:
        lab.close()
        docker("stop")


if __name__ == "__main__":
    main()
