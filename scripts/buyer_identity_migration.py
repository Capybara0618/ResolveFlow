"""Ownership plan and explicit migration staging for replacing shop customer identities with platform buyers.

The default command is read-only against a named local Compose MySQL container.
--stage-map stages the audited owner map without rewriting signed messages or run snapshots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any


class OwnershipConflict(ValueError):
    """Ownership cannot be inferred uniquely from the persisted identity records."""


def build_mapping(bindings: Iterable[dict[str, str]], accounts: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    """Never merge legacy customers by name or by a customer id shared across shops."""
    accounts = list(accounts)
    owners: dict[tuple[str, str], str] = {}
    buyer_stores: dict[tuple[str, str], str] = {}
    subjects: dict[tuple[str, str], set[str]] = defaultdict(set)
    reserved_buyers = {row["buyer_id"] for row in accounts if row.get("buyer_id")}

    def bind(merchant: str, customer: str, buyer: str) -> None:
        if any(not isinstance(value, str) or not value.strip() or len(value) > 64
               for value in (merchant, customer, buyer)):
            raise OwnershipConflict("身份映射包含空值或超长编号")
        key = merchant, customer
        if key in owners and owners[key] != buyer:
            raise OwnershipConflict("同一店内客户被绑定到多个平台买家")
        reverse = buyer, merchant
        if reverse in buyer_stores and buyer_stores[reverse] != customer:
            raise OwnershipConflict("同一买家在一家店存在多个待合并客户身份")
        owners[key] = buyer
        buyer_stores[reverse] = customer

    for row in bindings:
        bind(row["merchant_id"], row["customer_id"], row["buyer_id"])
        reserved_buyers.add(row["buyer_id"])
    for row in accounts:
        if row.get("role") != "CUSTOMER" or row.get("buyer_id"):
            continue
        key = row["merchant_id"], row["customer_id"]
        subjects[key].add(row["username"])
        if len(subjects[key]) > 1:
            raise OwnershipConflict("多个旧账号共有一个资源归属，需先明确账号迁移关系")
        if key in owners:
            raise OwnershipConflict("旧账号与平台账号拥有相同的店内客户身份")
        identity = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
        buyer = "B-legacy-" + hashlib.sha256(identity.encode()).hexdigest()[:40]
        if buyer in reserved_buyers:
            raise OwnershipConflict("旧账号生成的买家编号与已有平台身份冲突")
        bind(*key, buyer)
        reserved_buyers.add(buyer)
    return [{"merchant_id": merchant, "customer_id": customer, "buyer_id": buyer}
            for (merchant, customer), buyer in sorted(owners.items())]


def audit_ownership(mapping: list[dict[str, str]], resources: list[dict[str, Any]]) -> dict[str, Any]:
    owners = {(row["merchant_id"], row["customer_id"]): row["buyer_id"] for row in mapping}
    totals: dict[str, int] = defaultdict(int)
    problems = []
    for resource in resources:
        key = resource["merchant_id"], resource["customer_id"]
        buyer = owners.get(key)
        totals[resource["table"]] += resource["count"]
        if buyer is None:
            problems.append({"table": resource["table"], "code": "UNMAPPED_OWNER", "count": resource["count"]})
        elif resource.get("buyer_id") is not None and resource["buyer_id"] != buyer:
            problems.append({"table": resource["table"], "code": "BUYER_OWNER_MISMATCH", "count": resource["count"]})
    return {"ready": not problems, "mapping_count": len(mapping), "tables": dict(sorted(totals.items())),
            "conflicts": problems}


class DockerMysql:
    def __init__(self, container: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", container):
            raise ValueError("请明确指定本地 MySQL 容器名")
        self.container = container
        result = self._run(["docker", "inspect", "--format", "{{json .}}", container])
        state = json.loads(result)
        labels = state["Config"].get("Labels") or {}
        if labels.get("com.docker.compose.service") != "mysql" or not state["State"]["Running"]:
            raise ValueError("目标必须是已运行的 Compose MySQL 容器")

    @staticmethod
    def _run(command: list[str], text: str | None = None) -> str:
        result = subprocess.run(command, input=text, capture_output=True, text=True,
                                encoding="utf-8", timeout=120, check=False)
        if result.returncode:
            raise RuntimeError("本地 MySQL 检查失败，请检查容器及数据库状态")
        return result.stdout

    def query(self, statement: str) -> list[dict[str, Any]]:
        result = self._run(
            ["docker", "exec", "-i", self.container, "sh", "-c",
             'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot --batch --raw --skip-column-names --default-character-set=utf8mb4'],
            "START TRANSACTION READ ONLY;\n" + statement + ";\nROLLBACK;\n")
        return [json.loads(line) for line in result.splitlines() if line.strip()]

    def stage_mapping(self, mapping: list[dict[str, str]]) -> None:
        """Persist the audited cross-service map before the append-only Flyway cutover."""
        statements = []
        for schema in ("case_db", "commerce_db"):
            statements.append(f"""CREATE TABLE IF NOT EXISTS {schema}.buyer_identity_legacy (
                merchant_id VARCHAR(64) NOT NULL, customer_id VARCHAR(64) NOT NULL,
                buyer_id VARCHAR(64) NOT NULL, PRIMARY KEY(merchant_id,customer_id),
                UNIQUE KEY uq_migration_buyer_store(buyer_id,merchant_id))""")
        self.execute(";\n".join(statements) + ";\n")
        statements = ["START TRANSACTION"]
        for schema in ("case_db", "commerce_db"):
            existing = self.query(f"""SELECT JSON_OBJECT('merchant_id',merchant_id,
                'customer_id',customer_id,'buyer_id',buyer_id) FROM {schema}.buyer_identity_legacy""")
            expected = {(r["merchant_id"], r["customer_id"]): r["buyer_id"] for r in mapping}
            if any(expected.get((r["merchant_id"], r["customer_id"])) != r["buyer_id"] for r in existing):
                raise OwnershipConflict("已暂存的归属映射与本次检查不一致")
            for row in mapping:
                values = ",".join("CONVERT(0x" + row[key].encode().hex() + " USING utf8mb4)"
                                  for key in ("merchant_id", "customer_id", "buyer_id"))
                statements.append(f"INSERT IGNORE INTO {schema}.buyer_identity_legacy VALUES ({values})")
        statements.append("COMMIT")
        self.execute(";\n".join(statements) + ";\n")

    def execute(self, statement: str) -> None:
        self._run(["docker", "exec", "-i", self.container, "sh", "-c",
                   'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot --batch --default-character-set=utf8mb4'], statement)


def inspect(database: DockerMysql) -> tuple[dict[str, Any], list[dict[str, str]]]:
    bindings = database.query("""SELECT JSON_OBJECT('merchant_id',merchant_id,'customer_id',customer_id,
        'buyer_id',buyer_id) FROM case_db.buyer_customer_binding""")
    accounts = database.query("""SELECT JSON_OBJECT('username',username,'role',role,'merchant_id',merchant_id,
        'customer_id',customer_id,'buyer_id',buyer_id) FROM case_db.identity_account""")
    mapping = build_mapping(bindings, accounts)
    columns = database.query("""SELECT JSON_OBJECT('schema',TABLE_SCHEMA,'table',TABLE_NAME,
        'buyer_column',SUM(COLUMN_NAME='buyer_id'),'merchant_column',SUM(COLUMN_NAME='merchant_id'))
        FROM information_schema.COLUMNS WHERE TABLE_SCHEMA IN ('case_db','commerce_db')
        GROUP BY TABLE_SCHEMA,TABLE_NAME HAVING SUM(COLUMN_NAME='customer_id')>0""")
    resources = []
    for column in columns:
        if column["table"] in {"identity_account", "buyer_customer_binding"}:
            continue
        if not column["merchant_column"]:
            raise OwnershipConflict("发现缺少店铺范围的客户归属表")
        schema, table = column["schema"], column["table"]
        if not all(re.fullmatch(r"[A-Za-z0-9_]+", name) for name in (schema, table)):
            raise OwnershipConflict("不支持的数据库标识符")
        buyer = "buyer_id" if column["buyer_column"] else "NULL"
        resources.extend(database.query(f"""SELECT JSON_OBJECT('table','{schema}.{table}',
            'merchant_id',merchant_id,'customer_id',customer_id,'buyer_id',{buyer},'count',COUNT(*))
            FROM `{schema}`.`{table}` GROUP BY merchant_id,customer_id{',buyer_id' if column['buyer_column'] else ''}"""))
    report = audit_ownership(mapping, resources)
    report.update({"version": "buyer-identity-plan-v1", "schema_tables": len(columns),
                   "legacy_accounts": sum(a["role"] == "CUSTOMER" and not a["buyer_id"] for a in accounts)})
    return report, mapping


def stage_postgres(container: str, mapping: list[dict[str, str]]) -> None:
    """Stage only the historical owner map; SQL migration refuses active or unknown runs."""
    details = json.loads(DockerMysql._run(["docker", "inspect", container]))
    labels = details[0].get("Config", {}).get("Labels", {})
    if labels.get("com.docker.compose.service") != "postgres" or not details[0]["State"]["Running"]:
        raise OwnershipConflict("必须显式指定运行中的本地 Compose PostgreSQL 容器")
    # Hex values avoid shell/SQL quoting of persisted identities.
    values = ["(" + ",".join("convert_from(decode('" + row[key].encode().hex() + "','hex'),'UTF8')"
                              for key in ("merchant_id", "customer_id", "buyer_id")) + ")" for row in mapping]
    statement = """BEGIN;
        CREATE TABLE IF NOT EXISTS buyer_identity_legacy (
          merchant_id text NOT NULL, customer_id text NOT NULL, buyer_id text NOT NULL,
          PRIMARY KEY(merchant_id,customer_id), UNIQUE(buyer_id,merchant_id));
        CREATE TEMP TABLE incoming_buyer_map (LIKE buyer_identity_legacy INCLUDING ALL) ON COMMIT DROP;
    """
    if values:
        statement += "INSERT INTO incoming_buyer_map VALUES " + ",".join(values) + ";\n"
    statement += """DO $$ BEGIN
        IF EXISTS(SELECT 1 FROM buyer_identity_legacy e LEFT JOIN incoming_buyer_map i
          ON e.merchant_id=i.merchant_id AND e.customer_id=i.customer_id
          WHERE i.buyer_id IS NULL OR e.buyer_id<>i.buyer_id) THEN
          RAISE EXCEPTION 'Conflicting staged buyer ownership';
        END IF;
        END $$;
        INSERT INTO buyer_identity_legacy SELECT * FROM incoming_buyer_map ON CONFLICT DO NOTHING;
        COMMIT;
    """
    DockerMysql._run(["docker", "exec", "-i", container, "psql", "-v", "ON_ERROR_STOP=1",
                      "-U", "agent", "-d", "agent_db"], statement)


def main() -> int:
    parser = argparse.ArgumentParser(description="只读核对 customer_id 到 buyer_id 的资源归属")
    parser.add_argument("--mysql-container", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stage-map", action="store_true", help="在应用停机维护窗口暂存已核对的迁移映射")
    parser.add_argument("--postgres-container", help="与该 MySQL 配对的 PostgreSQL；仅在 --stage-map 时使用")
    args = parser.parse_args()
    database = DockerMysql(args.mysql_container)
    report, mapping = inspect(database)
    if args.stage_map:
        if not report["ready"]:
            raise OwnershipConflict("资源归属检查失败，拒绝暂存")
        database.stage_mapping(mapping)
        if args.postgres_container:
            stage_postgres(args.postgres_container, mapping)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    print(encoded, end="")
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
