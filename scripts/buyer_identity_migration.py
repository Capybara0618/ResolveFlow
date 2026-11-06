"""Read-only ownership plan for replacing shop customer identities with platform buyers.

Run against an explicitly named local Docker MySQL container. This planner does not start
applications, change schema, rewrite signed messages, or mutate existing run snapshots.
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


def main() -> int:
    parser = argparse.ArgumentParser(description="只读核对 customer_id 到 buyer_id 的资源归属")
    parser.add_argument("--mysql-container", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report, _ = inspect(DockerMysql(args.mysql_container))
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    print(encoded, end="")
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
