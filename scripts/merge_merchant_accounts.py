"""One-time, backed-up upgrade of the fixed local foundation; never resets transactions.

Applications remain stopped on failure. Restart with manage.ps1 only after the report passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re

import demo_foundation as foundation
import reviewer_demo as demo


def preserved_tables(settings: demo.Settings) -> dict:
    """Hash every business row; identity/assignment are the only permitted mutations."""
    columns = demo.mysql_rows(
        "SELECT table_schema,table_name,column_name FROM information_schema.columns "
        "WHERE table_schema IN ('case_db','commerce_db') ORDER BY table_schema,table_name,ordinal_position",
        settings,
    )
    tables: dict[str, list[str]] = {}
    for schema, table, column in columns:
        if not all(re.fullmatch(r"[A-Za-z0-9_]+", v) for v in (schema, table, column)):
            raise demo.DemoRefused("unexpected database identifier")
        if table == "flyway_schema_history" or (
            schema == "case_db"
            and table
            in {
                "identity_account",
                "identity_merchant",
                "case_collaboration",
                "case_collaboration_event",
            }
        ):
            continue
        tables.setdefault(f"{schema}.{table}", []).append(column)
    statements = [
        f"SELECT '{table}',JSON_ARRAY({','.join('HEX(`' + c + '`)' for c in fields)}) FROM {table}"
        for table, fields in tables.items()
    ]
    values: dict[str, list[str]] = {table: [] for table in tables}
    for table, row in demo.mysql_rows(";".join(statements), settings):
        values[table].append(row)
    return {
        table: {
            "rows": len(rows),
            "sha256": hashlib.sha256(
                json.dumps(sorted(rows), ensure_ascii=False).encode("utf-8")
            ).hexdigest(),
        }
        for table, rows in values.items()
    }


def validate_foundation(settings: demo.Settings) -> dict:
    if not foundation.MARKER.exists():
        raise demo.DemoRefused(
            "merchant merge requires the existing fixed foundation marker"
        )
    marker = json.loads(foundation.MARKER.read_text(encoding="utf-8"))
    if marker.get("profile") != "foundation-v1":
        raise demo.DemoRefused("merchant merge only accepts foundation-v1")
    for i in range(1, 4):
        rows = demo.mysql_rows(
            f"SELECT username FROM case_db.identity_account WHERE merchant_id='M-100{i}' "
            "AND role='MERCHANT_ADMIN' AND enabled=TRUE ORDER BY username",
            settings,
        )
        if rows != [[f"admin{i:02d}"]]:
            raise demo.DemoRefused(
                f"M-100{i} must have exactly its original enabled merchant account"
            )
    return marker


def convert(settings: demo.Settings) -> None:
    statements = [
        "USE case_db",
        "CREATE TEMPORARY TABLE merge_guard(ok TINYINT CHECK(ok=1))",
        "START TRANSACTION",
        "SELECT merchant_id FROM identity_merchant WHERE merchant_id IN ('M-1001','M-1002','M-1003') ORDER BY merchant_id FOR UPDATE",
        "SELECT username FROM identity_account WHERE merchant_id IN ('M-1001','M-1002','M-1003') ORDER BY username FOR UPDATE",
        "SELECT case_id FROM aftersale_case WHERE merchant_id IN ('M-1001','M-1002','M-1003') ORDER BY case_id FOR UPDATE",
    ]
    for i in range(1, 4):
        merchant, owner = f"M-100{i}", f"admin{i:02d}"
        statements += [
            f"INSERT INTO merge_guard SELECT IF(COUNT(*)=1 AND MIN(username)='{owner}',1,0) FROM identity_account WHERE merchant_id='{merchant}' AND role='MERCHANT_ADMIN' AND enabled=TRUE",
            f"UPDATE identity_account a JOIN identity_merchant m ON m.merchant_id=a.merchant_id SET a.display_name=CONCAT(m.display_name,'商家'),a.identity_version=a.identity_version+1,a.account_version=a.account_version+1 WHERE a.username='{owner}' AND m.single_operator=FALSE",
            f"UPDATE identity_merchant SET single_operator=TRUE WHERE merchant_id='{merchant}'",
        ]
        eligible = (
            f"c.merchant_id='{merchant}' AND c.status IN ('QUEUED','ANALYZING','WAITING_CUSTOMER','PENDING_REVIEW','AUTHORIZED') "
            "AND NOT EXISTS(SELECT 1 FROM case_authorization a WHERE a.case_id=c.case_id AND a.status='CONSUMED') "
            f"AND (s.owner_username IS NULL OR s.owner_username<>'{owner}')"
        )
        statements += [
            (
                "INSERT INTO case_collaboration_event(case_id,version,action,actor_username,from_username,to_username,reason,occurred_at) "
                f"SELECT c.case_id,COALESCE(s.version,0)+1,'AUTO_ASSIGN','SYSTEM',s.owner_username,'{owner}','角色合并，未消费工单归属本店商家',UTC_TIMESTAMP(6) "
                f"FROM aftersale_case c LEFT JOIN case_collaboration s ON s.case_id=c.case_id WHERE {eligible}"
            ),
            (
                "INSERT INTO case_collaboration(case_id,owner_username,version,updated_at) "
                f"SELECT c.case_id,'{owner}',COALESCE(s.version,0)+1,UTC_TIMESTAMP(6) "
                f"FROM aftersale_case c LEFT JOIN case_collaboration s ON s.case_id=c.case_id WHERE {eligible} "
                "ON DUPLICATE KEY UPDATE owner_username=VALUES(owner_username),version=VALUES(version),updated_at=VALUES(updated_at)"
            ),
        ]
    statements += [
        "UPDATE identity_account SET enabled=FALSE,identity_version=identity_version+1,account_version=account_version+1 WHERE merchant_id IN ('M-1001','M-1002','M-1003') AND role IN ('REVIEWER','OPERATOR') AND enabled=TRUE",
        # Keep referenced identities for both FK and logical historical audit references.
        (
            "DELETE a FROM identity_account a WHERE a.username IN ('staff01','staff02','staff03','staff04','staff05','staff06') AND a.enabled=FALSE "
            "AND NOT EXISTS(SELECT 1 FROM case_collaboration s WHERE s.owner_username=a.username) "
            "AND NOT EXISTS(SELECT 1 FROM case_collaboration_event e WHERE e.actor_username=a.username OR e.from_username=a.username OR e.to_username=a.username) "
            "AND NOT EXISTS(SELECT 1 FROM identity_account_audit e WHERE e.actor_username=a.username OR e.target_username=a.username) "
            "AND NOT EXISTS(SELECT 1 FROM platform_management_audit e WHERE e.actor=a.username OR e.target=a.username) "
            # Other historical human decision tables have logical username references; retain all
            # six if any case exists, rather than guessing the full historical reference graph.
            "AND NOT EXISTS(SELECT 1 FROM aftersale_case)"
        ),
        "COMMIT",
    ]
    foundation.mysql_write(";".join(statements), settings)


def upgrade(*, apply: bool, build: bool = True) -> dict:
    if not apply:
        raise demo.DemoRefused("one-time account upgrade requires --apply")
    settings = foundation.checked_settings()
    marker = validate_foundation(settings)
    demo.stop_owned(settings)
    if demo.read_owned(settings) or any(
        demo.tcp_open("127.0.0.1", settings.ports[k])
        for k in ("gateway", "case", "commerce", "agent", "frontend")
    ):
        raise demo.DemoRefused("applications did not stop; refusing account conversion")
    folder = foundation.backup(settings)
    print(f"Verified backup: {folder}", flush=True)
    before = preserved_tables(settings)
    if build:
        result = demo.run(
            [
                "cmd",
                "/c",
                str(demo.ROOT / "java/mvnw.cmd"),
                "-f",
                str(demo.ROOT / "java/pom.xml"),
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
        demo.atomic_write(
            settings.runtime() / "merchant-merge-build.log",
            result.stdout + result.stderr,
        )
        if result.returncode:
            raise demo.DemoRefused(
                "build failed; applications remain stopped; backup retained"
            )
    result = demo.run(
        [
            str(demo.java_home() / "bin/java"),
            "-jar",
            str(demo.CASE_JAR),
            "--spring.main.web-application-type=none",
            "--spring.main.keep-alive=false",
            f"--resolveflow.policy.import-dir={foundation.POLICY_DIR}",
        ],
        timeout=90,
        env=demo.child_env(
            CASE_DB_URL=settings.case_dsn,
            CASE_DB_USER="case_svc",
            CASE_DB_PASSWORD="case_svc",
            RESOLVEFLOW_POLICY_IMPORT_DIR=str(foundation.POLICY_DIR),
        ),
    )
    demo.atomic_write(
        settings.runtime() / "merchant-merge-migration.log",
        result.stdout + result.stderr,
    )
    if result.returncode:
        raise demo.DemoRefused(
            "migration startup failed; applications remain stopped; backup retained"
        )
    convert(settings)
    after = preserved_tables(settings)
    if before != after:
        raise demo.DemoRefused(
            "business preservation verification failed; applications remain stopped; backup retained"
        )
    marker.update(role_profile="merchant-single-v1", merchant_merge_backup=str(folder))
    demo.atomic_write(
        foundation.MARKER, json.dumps(marker, ensure_ascii=False, indent=2) + "\n"
    )
    report = {
        "verified_at": demo.now_iso(),
        "project": settings.project,
        "backup": str(folder),
        "business_rows_preserved": True,
        "before": before,
        "after": after,
        "accounts": demo.mysql_rows(
            "SELECT username,role,enabled FROM case_db.identity_account ORDER BY username",
            settings,
        ),
    }
    demo.atomic_write(
        demo.RUNTIME_ROOT / "merchant-merge.json",
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    report = upgrade(apply=args.apply, build=not args.skip_build)
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ("before", "after")},
            ensure_ascii=False,
            indent=2,
        )
    )
