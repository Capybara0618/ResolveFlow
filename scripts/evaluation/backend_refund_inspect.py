"""SELECT-only diagnostic for one operation in an explicitly owned backend lab."""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.backend_lab import Settings


def inspect_operation(settings, operation):
    if not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", operation):
        raise ValueError("operation_id must be a UUID")
    value = settings.sql("SELECT JSON_OBJECT('operation_id',operation_id,'case_id',case_id,'authorization_id',authorization_id,"
        "'input_revision',input_revision,'merchant_id',merchant_id,'line_id',line_id,'amount_minor',amount_minor,"
        "'state',state,'provider_key',provider_key,'provider_ref',provider_ref,'reason_code',reason_code,"
        "'retry_at',retry_at,'reserved_at',reserved_at,'settled_at',settled_at,'version',version) "
        f"FROM commerce_db.refund_operation WHERE operation_id='{operation}';")
    if not value:
        raise LookupError("operation not found in the owned laboratory")
    result = {"operation": json.loads(value)}
    case, auth, line = (result["operation"][key] for key in ("case_id", "authorization_id", "line_id"))
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value) for value in (case, auth, line)):
        raise ValueError("stored identity is not valid")
    def one(query):
        text = settings.sql(query)
        return json.loads(text) if text else None
    result["case"] = one("SELECT JSON_OBJECT('status',status,'input_revision',input_revision,'version',version) "
                         f"FROM case_db.aftersale_case WHERE case_id='{case}';")
    result["authorization"] = one("SELECT JSON_OBJECT('status',status,'input_revision',input_revision,"
        f"'authorization_version',authorization_version) FROM case_db.case_authorization WHERE authorization_id='{auth}';")
    result["ledger"] = one("SELECT JSON_OBJECT('order_id',l.order_id,'paid',l.paid_amount,'refunded',l.refunded_amount,"
        "'reserved',l.reserved_refund_amount,'ledger_version',l.version,'line_state',f.state,'line_operation',f.operation_id) "
        "FROM commerce_db.order_line x JOIN commerce_db.payment_ledger l ON l.order_id=x.order_id "
        f"JOIN commerce_db.line_refund f ON f.line_id=x.line_id WHERE x.line_id='{line}';")
    for schema, key in (("case_db", "command_outbox"), ("commerce_db", "result_outbox")):
        text = settings.sql("SELECT JSON_OBJECT('event_id',event_id,'event_type',event_type,'status',status,"
            "'attempts',attempts,'next_attempt_at',next_attempt_at,'last_error',last_error,'published_at',published_at) "
            f"FROM {schema}.event_outbox WHERE JSON_UNQUOTE(JSON_EXTRACT(envelope,'$.payload.operation_id'))='{operation}' ORDER BY created_at,event_id;")
        result[key] = [json.loads(row) for row in text.splitlines()]
    result["original_command_inbox"] = []
    for command in result["command_outbox"]:
        event_id = command["event_id"]
        if not re.fullmatch(r"[a-f0-9-]{36}", event_id):
            raise ValueError("stored event identity is not valid")
        result["original_command_inbox"].append(one("SELECT JSON_OBJECT('event_id',event_id,'disposition',disposition,"
            f"'detail',detail,'received_at',received_at) FROM commerce_db.event_inbox WHERE event_id='{event_id}';"))
    text = settings.sql("SELECT JSON_OBJECT('event_id',event_id,'state',state,'deliveries',deliveries,'projected_at',projected_at) "
                        f"FROM case_db.case_result_inbox WHERE operation_id='{operation}' ORDER BY received_at;")
    result["result_inbox"] = [json.loads(row) for row in text.splitlines()]
    provider = settings.folder / "provider.sqlite3"
    with sqlite3.connect(provider.as_uri() + "?mode=ro", uri=True) as database:
        database.row_factory = sqlite3.Row
        result["provider_receipts"] = [dict(row) for row in database.execute(
            "SELECT operation_id,line_id,amount_minor,state,provider_ref,settled_at,visible_after FROM refund_request WHERE operation_id=?", (operation,))]
        result["provider_attempts"] = [dict(row) for row in database.execute(
            "SELECT attempt,outcome,at FROM request_attempt WHERE operation_id=? ORDER BY attempt", (operation,))]
    result["boundary"] = "explicit lab only; original command inbox excludes re-signed experimental event IDs"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--operation-id", required=True)
    args = parser.parse_args()
    # Only SELECT and read-only SQLite access; no application token/provider request is needed.
    print(json.dumps(inspect_operation(Settings(args.run_id), args.operation_id), indent=2))


if __name__ == "__main__":
    main()
