"""D5 rebuild fixture, read-only Redis observer, owned process pause and durable SQL probe."""

from __future__ import annotations

import base64
import ctypes
import hmac
import json
import os
import socket
import time
import uuid
from datetime import datetime
from pathlib import Path

from evaluation.backend_d5_seed import literal
from evaluation.backend_lab import ROOT, freeze_file, run, sha256


def service_token():
    now = int(time.time())
    payload = {
        "sub": "case-service",
        "aud": "resolveflow-service",
        "iss": "resolveflow-demo-identity",
        "scope": "commerce:read",
        "iat": now,
        "exp": now + 86400,
    }
    encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
    unsigned = (
        encode(b'{"alg":"HS256","typ":"JWT"}')
        + "."
        + encode(json.dumps(payload).encode())
    )
    return (
        unsigned
        + "."
        + encode(
            hmac.digest(
                b"resolveflow-core-demo-identity-secret", unsigned.encode(), "sha256"
            )
        )
    )


def redis(settings, *args):
    """Observer talks only to the owned Redis; no DEL/FLUSH or lock writes are accepted."""
    if not args or args[0] not in ("GET", "PTTL", "HGETALL", "EXISTS"):
        raise ValueError("read-only Redis observer")
    body = ("*" + str(len(args)) + "\r\n").encode()
    for value in args:
        raw = str(value).encode()
        body += ("$" + str(len(raw)) + "\r\n").encode() + raw + b"\r\n"
    with socket.create_connection(
        ("127.0.0.1", settings.load()["ports"]["redis"]), timeout=1
    ) as client:
        client.sendall(body)
        with client.makefile("rb") as stream:
            return resp(stream)


def resp(stream):
    line = stream.readline()
    if not line.endswith(b"\r\n"):
        raise ValueError("truncated Redis reply")
    kind, value = line[:1], line[1:-2]
    if kind == b":":
        return int(value)
    if kind == b"+":
        return value.decode()
    if kind == b"$":
        length = int(value)
        if length == -1:
            return None
        content = stream.read(length + 2)
        if len(content) != length + 2 or not content.endswith(b"\r\n"):
            raise ValueError("truncated Redis bulk")
        return content[:-2].decode()
    if kind == b"*":
        return [resp(stream) for _ in range(int(value))]
    raise ValueError("unexpected Redis reply")


class Paused:
    def __init__(self, settings, role):
        pid = settings.load()["pids"][role]
        if role not in ("commerce", "commerce2") or type(pid) is not int or pid < 1:
            raise ValueError("explicit owned Commerce PID required")
        marker = "-Drf.backend.run=" + settings.identity
        answer = run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; if ($p -and $p.CommandLine.Contains('{marker}')) {{'OWNED'}} else {{throw 'process ownership mismatch'}}",
            ]
        )
        if answer != "OWNED":
            raise ValueError("process ownership not confirmed")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.nt = ctypes.WinDLL("ntdll")
        self.kernel.OpenProcess.argtypes = [
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_uint32,
        ]
        self.kernel.OpenProcess.restype = ctypes.c_void_p
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        for name in ("NtSuspendProcess", "NtResumeProcess"):
            fn = getattr(self.nt, name)
            fn.argtypes, fn.restype = [ctypes.c_void_p], ctypes.c_long
        self.handle = self.kernel.OpenProcess(0x0800 | 0x1000, 0, pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "owned process handle")
        self.active = False
        if self.nt.NtSuspendProcess(self.handle) != 0:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise OSError("NtSuspendProcess failed")
        self.active = True
        self.pid = pid
        self.suspended_ns = time.time_ns()

    def resume(self):
        if self.active:
            if self.nt.NtResumeProcess(self.handle) != 0:
                raise OSError("NtResumeProcess failed")
            self.active = False
        return time.time_ns()

    def close(self):
        try:
            self.resume()
        finally:
            if self.handle:
                self.kernel.CloseHandle(self.handle)
                self.handle = None


def fixture(settings, folder, label):
    """New synthetic paid read model with FREE line and a valid review; no provider call."""
    identity = uuid.uuid5(uuid.UUID(settings.identity), label)
    suffix = identity.hex[:20]
    product, sku, line, order = (
        "D5R-" + suffix,
        "D5RS-" + suffix,
        "D5RL-" + suffix,
        str(identity),
    )
    sql = f"""
    INSERT INTO commerce_db.catalog_product(product_id,store_id,name,description,category,asset_key,listed)
    VALUES({literal(product)},'M-1001','D5 rebuild product','synthetic fixture','electronics','headphones',TRUE);
    INSERT INTO commerce_db.catalog_sku(sku_id,product_id,variant,unit_amount,max_quantity,version,listed)
    VALUES({literal(sku)},{literal(product)},'D5 fixture',32900,9,1,TRUE);
    INSERT INTO commerce_db.orders(order_id,merchant_id,customer_id,order_status,currency,paid_at,created_at)
    VALUES({literal(order)},'M-1001','D5-C000-M-1001','PAID','CNY','2026-10-20','2026-10-20');
    INSERT INTO commerce_db.payment_ledger(order_id,paid_amount,refunded_amount,reserved_refund_amount,version)
    VALUES({literal(order)},32900,0,0,1);
    INSERT INTO commerce_db.order_line(line_id,order_id,merchant_id,customer_id,sku,category,quantity,line_paid_amount,currency,paid_at,order_status,version,product_name,variant_text)
    VALUES({literal(line)},{literal(order)},'M-1001','D5-C000-M-1001',{literal(sku)},'electronics',1,32900,'CNY','2026-10-20','PAID',1,'D5 rebuild product','D5 fixture');
    INSERT INTO commerce_db.line_refund(line_id,state,operation_id,version,updated_at)
    VALUES({literal(line)},'FREE',NULL,1,'2026-10-20');
    INSERT INTO commerce_db.shipment(line_id,status,carrier_conclusion,source_version)
    VALUES({literal(line)},'DELIVERED','DELIVERED',2);
    INSERT INTO commerce_db.product_review(line_id,product_id,product_name,merchant_id,customer_id,variant,rating,body,version,created_at,updated_at)
    VALUES({literal(line)},{literal(product)},'D5 rebuild product','M-1001','D5-C000-M-1001','D5 fixture',3,'D5 rebuild review',1,'2026-10-21','2026-10-21');
    INSERT INTO commerce_db.product_review_epoch(product_id,version) VALUES({literal(product)},1);
    """
    sql_path = folder / (label + ".sql")
    with sql_path.open("xb") as handle:
        handle.write(sql.encode())
    settings.sql(sql)
    review_id = int(
        settings.sql(
            "SELECT review_id FROM commerce_db.product_review WHERE line_id="
            + literal(line)
            + ";"
        )
    )
    return {
        "product": product,
        "line": line,
        "order": order,
        "review_id": review_id,
        "epoch": 1,
        "fixture_sql_sha256": sha256(sql_path),
        "synthetic_direct_read_model": True,
    }


def durable_probe(settings, version):
    """Derive an evaluation-only probe with write-ahead SQL events for killed-owner counters."""
    if not version.replace("-", "").isalnum():
        raise ValueError("explicit fresh probe version")
    target = settings.folder / ("probe-classes-" + version)
    target.mkdir(exist_ok=False)
    original = (ROOT / "scripts/evaluation/D5Probe.java").read_text(encoding="utf-8")
    old = "statements.incrementAndGet();int active="
    new = 'statements.incrementAndGet();event(Map.of("stage","sql_execute","sql",sql));int active='
    if original.count(old) != 1:
        raise ValueError("unexpected frozen measurement source")
    source = target / "source/D5Probe.java"
    source.parent.mkdir()
    source.write_bytes(original.replace(old, new).encode())
    freeze_file(
        ROOT / "scripts/evaluation/D5Probe.java", target / "D5Probe-original.java"
    )
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
            str(source),
        ]
    )
    (target / "compile.log").write_bytes(output.encode())
    state = settings.load()
    state["d5_probe_group"] = target.name
    settings.save(state)
    return target


def event_time(row):
    return datetime.fromisoformat(row["at"]).timestamp()


def rebuild_peak(events, product, terminal=None):
    changes = []
    active_calls = {}
    for row in events:
        if row.get("product") != product:
            continue
        key = (row["node"], row["call"])
        if row["stage"] == "load_start":
            active_calls[key] = row
            changes.append((event_time(row), 1))
        elif row["stage"] == "load_end":
            active_calls.pop(key, None)
            changes.append((event_time(row), -1))
    for (node, _), row in active_calls.items():
        if terminal and terminal["node"] == node:
            changes.append((terminal["at_ns"] / 1e9, -1))
        else:
            raise ValueError("unfinished load without actual terminal process event")
    active, peak = 0, 0
    for _, delta in sorted(changes, key=lambda value: (value[0], value[1])):
        active += delta
        if active < 0:
            raise ValueError("load event ordering invalid")
        peak = max(active, peak)
    if active:
        raise ValueError("load event denominator mismatch")
    return peak
