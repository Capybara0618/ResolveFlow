"""Local carrier scenarios for paid, shipped demo orders; no model calls or data reset."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

import reviewer_demo as demo

SCENARIOS = (
    "IN_TRANSIT",
    "DELAYED",
    "DELIVERED",
    "LOST",
    "UNKNOWN",
    "UNAVAILABLE",
    "AVAILABLE",
)


def identifier(value: str, maximum: int = 64) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1," + str(maximum) + r"}", value):
        raise ValueError(
            f"identifier must contain 1–{maximum} ASCII letters, digits, _ or -"
        )
    return value


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("time must include a timezone, e.g. 2026-10-14T08:00:00Z")
    return result.astimezone(UTC)


def sql_text(value: str | None) -> str:
    """Hex literals are unaffected by SQL mode or shell escaping; SQL travels on stdin."""
    return (
        "NULL"
        if value is None
        else "CONVERT(X'" + value.encode("utf-8").hex() + "' USING utf8mb4)"
    )


class LocalMysql:
    def __init__(self) -> None:
        settings = demo.settings_from_environ()
        demo.guard(settings)
        self.container = demo.live_container("mysql", settings)

    def execute(self, statement: str) -> list[dict[str, Any]]:
        command = [
            "docker",
            "exec",
            "-i",
            self.container,
            "sh",
            "-c",
            (
                'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot '
                "--default-character-set=utf8mb4 --batch --raw --skip-column-names commerce_db"
            ),
        ]
        result = subprocess.run(
            command,
            input=("SET time_zone='+00:00';\n" + statement).encode("utf-8"),
            capture_output=True,
            timeout=60,
            check=False,
        )
        if result.returncode:
            error = result.stderr.decode("utf-8", errors="replace").strip()
            raise demo.DemoRefused(
                "simulator SQL failed (receipt replay is safe if response was lost): "
                + error[:450]
            )
        return [
            json.loads(row)
            for row in result.stdout.decode("utf-8").splitlines()
            if row.strip()
        ]


def call_sql(
    order: str, merchant: str, version: int, scenario: str, key: str, at: str | None
) -> str:
    identifier(order)
    identifier(merchant)
    identifier(key, 128)
    if not 2 <= version < 9007199254740991 or scenario not in SCENARIOS:
        raise ValueError("expected version must be >=2 and scenario must be supported")
    if at is not None:
        if scenario in ("UNAVAILABLE", "AVAILABLE"):
            raise ValueError("query fault switches do not have an event time")
        at = instant(at).strftime("%Y-%m-%d %H:%M:%S.%f")
    return (
        "CALL simulate_logistics("
        + ",".join(
            [
                sql_text(order),
                sql_text(merchant),
                str(version),
                sql_text(scenario),
                sql_text(key),
                sql_text(at),
            ]
        )
        + ");\n"
    )


def inspect(
    mysql: LocalMysql, order: str, merchant: str, observed_at: str | None = None
) -> dict[str, Any]:
    identifier(order)
    identifier(merchant)
    rows = mysql.execute(f"""
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;
START TRANSACTION READ ONLY;
SELECT JSON_OBJECT('synthetic',JSON_EXTRACT('true','$'),'order_id',o.order_id,
 'merchant_id',o.merchant_id,'status',f.status,'fulfillment_version',f.version,
 'updated_at',DATE_FORMAT(f.updated_at,'%Y-%m-%dT%H:%i:%s.%fZ'),
 'query_unavailable',COALESCE(x.unavailable,FALSE),'fault_version',x.version,
 'lines',(SELECT JSON_ARRAYAGG(JSON_OBJECT('line_id',l.line_id,'status',s.status,
  'carrier_conclusion',s.carrier_conclusion,'source_version',s.source_version,
  'events',(SELECT JSON_ARRAYAGG(JSON_OBJECT('code',e.code,'source_version',e.source_version,
      'occurred_at',DATE_FORMAT(e.occurred_at,'%Y-%m-%dT%H:%i:%s.%fZ')))
      FROM shipment_event e WHERE e.line_id=l.line_id)))
  FROM order_line l LEFT JOIN shipment s ON s.line_id=l.line_id WHERE l.order_id=o.order_id))
FROM orders o LEFT JOIN order_fulfillment f ON f.order_id=o.order_id
LEFT JOIN shipment_simulation_fault x ON x.order_id=o.order_id
WHERE o.order_id={sql_text(order)} AND o.merchant_id={sql_text(merchant)};
COMMIT;
""")
    if len(rows) != 1:
        raise demo.DemoRefused("order not found in the specified merchant")
    state = rows[0]
    state["query_unavailable"] = bool(state["query_unavailable"])
    observed = instant(observed_at) if observed_at else datetime.now(UTC)
    state["observed_at"] = observed.isoformat().replace("+00:00", "Z")
    state["observation_time_is_service_clock"] = observed_at is None
    state["lines"] = sorted(state["lines"] or [], key=lambda row: row["line_id"])
    for line in state["lines"]:
        line["events"] = sorted(
            line["events"] or [], key=lambda row: row["source_version"]
        )
        last = max((instant(e["occurred_at"]) for e in line["events"]), default=None)
        line["hours_since_last_event"] = (
            (observed - last).total_seconds() / 3600 if last else None
        )
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    read = commands.add_parser(
        "inspect", help="read logistics and fault state without calling the model"
    )
    write = commands.add_parser(
        "advance", help="append one scenario or change the query fault switch"
    )
    for command in (read, write):
        command.add_argument("--order-id", required=True)
        command.add_argument("--merchant-id", required=True)
    read.add_argument(
        "--observed-at",
        help="evaluation reference time only; does not change service clocks",
    )
    write.add_argument("--expected-version", required=True, type=int)
    write.add_argument("--scenario", choices=SCENARIOS, required=True)
    write.add_argument(
        "--request-key",
        required=True,
        help="reuse the SAME key and payload for retries",
    )
    write.add_argument(
        "--occurred-at",
        help="optional event time; must follow existing events and not be future",
    )
    args = parser.parse_args()
    try:
        # Validate before contacting Docker, including inspection reference time.
        identifier(args.order_id)
        identifier(args.merchant_id)
        sql = (
            call_sql(
                args.order_id,
                args.merchant_id,
                args.expected_version,
                args.scenario,
                args.request_key,
                args.occurred_at,
            )
            if args.action == "advance"
            else None
        )
        if args.action == "inspect" and args.observed_at:
            instant(args.observed_at)
        mysql = LocalMysql()
        if sql:
            receipts = mysql.execute(sql)
            if len(receipts) != 1:
                raise demo.DemoRefused(
                    "missing simulator receipt; inspect and replay the original request"
                )
            output = {
                "receipt": receipts[0],
                "current": inspect(mysql, args.order_id, args.merchant_id),
            }
        else:
            output = inspect(mysql, args.order_id, args.merchant_id, args.observed_at)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (
        ValueError,
        demo.DemoRefused,
        RuntimeError,
        subprocess.TimeoutExpired,
        OSError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
