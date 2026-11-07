"""Guarded, explicitly destructive reset of the isolated local demo only.

The human authorized this reset on 2026-10-03. Ordinary start never calls reset.
Backups contain potentially sensitive historical trajectories and stay in ignored tmp.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reviewer_demo as demo
from foundation_data import accounts, catalog

MARKER = demo.RUNTIME_ROOT / "foundation.json"
POLICY_DIR = demo.ROOT / "fixtures" / "demo-foundation" / "policies"


def checked_settings() -> demo.Settings:
    settings = demo.settings_from_environ()
    if (
        settings.project != demo.PROJECT
        or settings.ports != demo.DEFAULT_PORTS
        or settings.runtime_root.resolve() != demo.RUNTIME_ROOT.resolve()
    ):
        raise demo.DemoRefused(
            "reset only accepts the fixed local demo project, ports and runtime path"
        )
    demo.guard(settings)
    for role in ("mysql", "postgres", "broker", "namesrv"):
        demo.live_container(role, settings)
    return settings


def local_path(path: Path) -> Path:
    resolved = path.resolve()
    if (
        not resolved.is_relative_to(demo.RUNTIME_ROOT.resolve())
        or resolved == demo.RUNTIME_ROOT.resolve()
    ):
        raise demo.DemoRefused(
            "refusing a file mutation outside the exact demo runtime subtree"
        )
    return resolved


def capture(args: list[str], path: Path) -> None:
    with path.open("wb") as output:
        result = subprocess.run(
            args, stdout=output, stderr=subprocess.PIPE, timeout=180, check=False
        )
    if result.returncode:
        raise demo.DemoRefused(
            f"backup command failed ({result.returncode}); no data reset was performed"
        )


def mysql_write(statement: str, settings: demo.Settings) -> None:
    """SQL travels on stdin, avoiding Windows command-line limits and credential echo."""
    container = demo.live_container("mysql", settings)
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "mysql",
            "-uroot",
            "-proot",
            "--default-character-set=utf8mb4",
        ],
        input=statement.encode("utf-8"),
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode:
        raise demo.DemoRefused(
            "database initialization failed; application remains stopped; backups retained"
        )


def backup(settings: demo.Settings) -> Path:
    folder = local_path(
        demo.RUNTIME_ROOT / "backups" / datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    )
    folder.mkdir(parents=True, exist_ok=False)
    mysql = demo.live_container("mysql", settings)
    pg = demo.live_container("postgres", settings)
    capture(
        [
            "docker",
            "exec",
            mysql,
            "mysqldump",
            "-uroot",
            "-proot",
            "--default-character-set=utf8mb4",
            "--single-transaction",
            "--no-tablespaces",
            "--set-gtid-purged=OFF",
            "--databases",
            "case_db",
            "commerce_db",
        ],
        folder / "mysql.sql",
    )
    capture(
        ["docker", "exec", pg, "pg_dump", "-U", "agent", "-d", "agent_db", "-Fc"],
        folder / "agent.dump",
    )
    broker = demo.live_container("broker", settings)
    capture(
        ["docker", "exec", broker, "tar", "-czf", "-", "-C", "/home/rocketmq", "store"],
        folder / "broker.tar.gz",
    )
    # Back up only this demo's recorded runtime, never another checkout or arbitrary configured path.
    runtime = local_path(settings.runtime())
    if runtime.exists():
        shutil.copytree(runtime, folder / "runtime")
    for path in demo.RUNTIME_ROOT.glob("*/refund-provider.sqlite3"):
        safe = local_path(path)
        with (
            sqlite3.connect(str(safe)) as source,
            sqlite3.connect(
                str(folder / f"provider-{path.parent.name}.sqlite3")
            ) as target,
        ):
            source.backup(target)
    if MARKER.exists():
        shutil.copyfile(MARKER, folder / "foundation.json")
    if b"CREATE TABLE" not in (folder / "mysql.sql").read_bytes() or not (
        folder / "agent.dump"
    ).read_bytes().startswith(b"PGDMP"):
        raise demo.DemoRefused("backup content validation failed; refusing reset")
    files = {
        p.name: {
            "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in folder.iterdir()
        if p.is_file()
    }
    (folder / "backup.json").write_text(
        json.dumps(
            {"project": settings.project, "created_at": demo.now_iso(), "files": files},
            indent=2,
        ),
        encoding="utf-8",
    )
    (folder / "RESTORE.md").write_text(
        "Stop demo applications first. Restore mysql.sql into this project's MySQL with mysql -uroot -proot; "
        "restore agent.dump using pg_restore -U agent -d agent_db --clean --if-exists. "
        "Restore provider SQLite files and runtime from this backup before starting applications. "
        "broker.tar.gz contains the old /home/rocketmq/store; restore only with the demo broker stopped. "
        "Never import these backups into the shared resolveflow environment.\n",
        encoding="utf-8",
    )
    return folder


def truncate_business(settings: demo.Settings) -> None:
    rows = demo.mysql_rows(
        "SELECT table_schema,table_name FROM information_schema.tables WHERE table_schema IN ('case_db','commerce_db') AND table_type='BASE TABLE' AND table_name<>'flyway_schema_history' ORDER BY table_schema,table_name",
        settings,
    )
    statements = ["SET FOREIGN_KEY_CHECKS=0"]
    for schema, table in rows:
        if schema not in ("case_db", "commerce_db") or not re.fullmatch(
            r"[A-Za-z0-9_]+", table
        ):
            raise demo.DemoRefused("unexpected database/table identifier")
        statements.append(f"TRUNCATE TABLE `{schema}`.`{table}`")
    statements.append("SET FOREIGN_KEY_CHECKS=1")
    mysql_write(";".join(statements), settings)
    import psycopg
    from psycopg import sql

    demo.live_container("postgres", settings)
    with psycopg.connect(settings.agent_dsn) as connection:
        tables = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        ).fetchall()
        if tables:
            connection.execute(
                sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(",").join(
                        sql.Identifier("public", row[0]) for row in tables
                    )
                )
            )


def literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    # Hex UTF-8 avoids shell or SQL quote/backslash interpolation, including PBKDF2 '$'.
    return "CONVERT(0x" + str(value).encode("utf-8").hex() + " USING utf8mb4)"


def seed(settings: demo.Settings) -> None:
    data = catalog()
    statements = ["START TRANSACTION"]
    for s in data["stores"]:
        values = ",".join(literal(s[k]) for k in ("store_id", "name", "description"))
        statements.append(
            f"INSERT INTO case_db.identity_merchant(merchant_id,display_name,description,single_operator) VALUES ({values},TRUE)"
        )
        statements.append(
            f"INSERT INTO commerce_db.catalog_store(store_id,name,description) VALUES ({values})"
        )
    for p in data["products"]:
        columns = "product_id,store_id,name,description,category,asset_key"
        values = ",".join(literal(p[k]) for k in columns.split(","))
        statements.append(
            f"INSERT INTO commerce_db.catalog_product({columns}) VALUES ({values})"
        )
    for s in data["skus"]:
        columns = "sku_id,product_id,variant,unit_amount,max_quantity"
        statements.append(
            f"INSERT INTO commerce_db.catalog_sku({columns}) VALUES ({','.join(literal(s[k]) for k in columns.split(','))})"
        )
    for a in accounts():
        buyer = a["buyer_id"]
        if buyer:
            statements.append(
                f"INSERT INTO case_db.platform_buyer(buyer_id) VALUES ({literal(buyer)})"
            )
        hashed = (
            "pbkdf2-sha256$120000$"
            + __import__("base64").b64encode(salt := secrets.token_bytes(16)).decode()
            + "$"
            + __import__("base64")
            .b64encode(hashlib.pbkdf2_hmac("sha256", b"123456", salt, 120000))
            .decode()
        )
        values = [
            a[k]
            for k in ("username", "merchant_id", "role", "buyer_id", "display_name")
        ] + [hashed]
        statements.append(
            "INSERT INTO case_db.identity_account(username,merchant_id,role,buyer_id,display_name,password_hash,identity_version) VALUES ("
            + ",".join(literal(v) for v in values)
            + ","
            + str(int(datetime.now(UTC).timestamp()))
            + ")"
        )
    statements.append("COMMIT")
    mysql_write(";".join(statements), settings)


def verify(settings: demo.Settings) -> dict:
    expected = {
        "case_db.identity_merchant": 3,
        "case_db.identity_account": 14,
        "case_db.platform_buyer": 10,
        "commerce_db.catalog_store": 3,
        "commerce_db.catalog_product": len(catalog()["products"]),
        "commerce_db.catalog_sku": len(catalog()["skus"]),
    }
    observed = {
        table: int(demo.mysql_scalar(f"SELECT COUNT(*) FROM {table}", settings) or -1)
        for table in expected
    }
    empty = [
        "case_db.aftersale_case",
        "case_db.case_authorization",
        "commerce_db.order_line",
        "commerce_db.payment_ledger",
        "commerce_db.refund_operation",
        "commerce_db.checkout_draft",
        "commerce_db.shopping_cart",
        "commerce_db.shopping_cart_item",
    ]
    # Use current metadata: cart table names changed during early implementation.
    existing = {
        ".".join(row)
        for row in demo.mysql_rows(
            "SELECT table_schema,table_name FROM information_schema.tables WHERE table_schema IN ('case_db','commerce_db')",
            settings,
        )
    }
    observed.update(
        {
            table: int(
                demo.mysql_scalar(f"SELECT COUNT(*) FROM {table}", settings) or 0
            )
            for table in empty
            if table in existing
        }
    )
    agent_empty = [
        "agent_run",
        "agent_model_call",
        "agent_tool_call",
        "agent_callback_outbox",
    ]
    observed.update(
        {
            "agent." + table: int(
                demo.postgres_scalar(f"SELECT COUNT(*) FROM {table}", settings) or 0
            )
            for table in agent_empty
        }
    )
    ready = int(
        demo.postgres_scalar(
            "SELECT COUNT(*) FROM policy_index_generation WHERE status='READY'",
            settings,
        )
        or 0
    )
    if (
        any(observed[t] != n for t, n in expected.items())
        or any(observed.get(t, 0) for t in empty)
        or any(observed["agent." + t] for t in agent_empty)
        or ready != 3
    ):
        raise demo.DemoRefused(
            "clean baseline verification failed: " + json.dumps(observed)
        )
    return {"counts": observed, "ready_policy_indexes": ready}


def reset(*, authorized: bool, build: bool = True) -> dict:
    if not authorized:
        raise demo.DemoRefused("reset requires the explicit --clear-demo-data flag")
    settings = checked_settings()
    demo.stop_owned(settings)
    if demo.read_owned(settings) or any(
        demo.tcp_open("127.0.0.1", settings.ports[k])
        for k in ("gateway", "case", "commerce", "agent", "frontend")
    ):
        raise demo.DemoRefused(
            "demo applications did not all stop; no reset was performed"
        )
    folder = backup(settings)
    print(f"Verified backup: {folder}", flush=True)
    # Apply pending additive migrations before truncating; this also keeps Flyway history intact.
    if build:
        result = demo.run(
            [
                "cmd",
                "/c",
                str(demo.ROOT / "java" / "mvnw.cmd"),
                "-f",
                str(demo.ROOT / "java" / "pom.xml"),
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
        if result.returncode:
            raise demo.DemoRefused("build failed before reset; backups retained")
    for jar, dsn, username in (
        (demo.CASE_JAR, settings.case_dsn, "case_svc"),
        (demo.COMMERCE_JAR, settings.commerce_dsn, "commerce_svc"),
    ):
        # Non-web startup does not enable dispatch/Agent work.
        result = demo.run(
            [
                str(demo.java_home() / "bin" / "java"),
                "-jar",
                str(jar),
                "--spring.main.web-application-type=none",
                "--spring.main.keep-alive=false",
            ],
            timeout=90,
            env=demo.child_env(
                CASE_DB_URL=settings.case_dsn,
                CASE_DB_USER="case_svc",
                CASE_DB_PASSWORD="case_svc",
                COMMERCE_DB_URL=settings.commerce_dsn,
                COMMERCE_DB_USER="commerce",
                COMMERCE_DB_PASSWORD="commerce",
            ),
        )
        if result.returncode:
            raise demo.DemoRefused(
                "migration startup failed before reset; backups retained"
            )
    truncate_business(settings)
    seed(settings)
    for path in demo.RUNTIME_ROOT.glob("*/refund-provider.sqlite3*"):
        local_path(path).unlink()
    # Broker data is container-local (no writable data mount in the pinned compose file).
    recreated = demo.compose(
        "up",
        "-d",
        "--force-recreate",
        "rocketmq-namesrv",
        "rocketmq-broker",
        settings=settings,
    )
    if recreated.returncode:
        raise demo.DemoRefused(f"empty broker recreation failed; restore from {folder}")
    marker = {
        "profile": "foundation-v1",
        "role_profile": "merchant-single-v1",
        "backup": str(folder),
        "policy_dir": str(POLICY_DIR),
        "bundles": [f"policy-foundation-m100{i}-2026.10" for i in range(1, 4)],
    }
    demo.atomic_write(MARKER, json.dumps(marker, ensure_ascii=False, indent=2) + "\n")
    log = demo.Log(
        demo.log_path(settings, "foundation-start"), title="clean foundation start"
    )
    try:
        demo.command_start(settings, log, build=False, open_browser=False)
        result = verify(settings)
        log.flush("PASSED")
    except Exception:
        demo.stop_owned(settings)
        raise
    demo.atomic_write(
        demo.RUNTIME_ROOT / "foundation-verification.json",
        json.dumps(result, indent=2) + "\n",
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["reset", "verify"])
    parser.add_argument("--clear-demo-data", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    result = (
        reset(authorized=args.clear_demo_data, build=not args.skip_build)
        if args.command == "reset"
        else verify(checked_settings())
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
