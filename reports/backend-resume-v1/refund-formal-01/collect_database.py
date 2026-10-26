"""Read-only final SQL/SQLite collection for the fixed refund cohort."""

import json
import sqlite3
import sys
from pathlib import Path

from cohort import load

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluation.backend_lab import Settings, sha256
from evaluation.backend_refund_inspect import inspect_operation
from evaluation.backend_refund_matrix import ids
from evaluation.trade_request_journal import durable


def collect(raw):
    manifest, records, lineage = load(raw)
    revised = json.loads((raw / "refund-formal-04/manifest.json").read_text(encoding="utf-8"))
    base = Settings(manifest["run_id"], ROOT)
    with base.operation_lock():
        assert manifest["jars"] == base.freeze()["jars"] and lineage["fault_rounds_passed"] == 68
        for name, digest in revised["sources"].items():
            assert sha256(ROOT / name) == digest
        operations = sorted(op for _, row, _, _ in records for op in row["entities"]["operations"])
        assert len(operations) == len(set(operations)) == 80
        before = json.loads((raw / "refund-formal-01/before-inventory.json").read_text(encoding="utf-8"))
        current = sorted(json.loads(base.sql("SELECT JSON_ARRAYAGG(operation_id) FROM commerce_db.refund_operation;")))
        successful = sorted(json.loads(base.sql("SELECT JSON_ARRAYAGG(operation_id) FROM commerce_db.refund_operation WHERE state='SUCCEEDED';")))
        new = sorted(set(current) - set(before["operations"]))
        new_success = sorted(set(successful) - set(before["success_operations"]))
        assert new == new_success == operations
        sql = f"""SELECT JSON_OBJECT('operation_id',o.operation_id,'case_id',o.case_id,'line_id',o.line_id,
          'state',o.state,'amount_minor',o.amount_minor,'operation_revision',o.input_revision,'authorization_revision',a.input_revision,
          'case_revision',c.input_revision,'authorization_status',a.status,'case_status',c.status,
          'line_state',f.state,'paid',l.paid_amount,'refunded',l.refunded_amount,'reserved',l.reserved_refund_amount,
          'command_count',(SELECT COUNT(*) FROM case_db.case_execution_command x WHERE x.operation_id=o.operation_id),
          'result_count',(SELECT COUNT(*) FROM commerce_db.event_outbox e WHERE e.event_type='RefundSucceeded' AND JSON_UNQUOTE(JSON_EXTRACT(e.envelope,'$.payload.operation_id'))=o.operation_id),
          'closed_events',(SELECT COUNT(*) FROM case_db.case_timeline t WHERE t.case_id=o.case_id AND t.kind='CASE_CLOSED'),
          'success_result_deliveries',(SELECT SUM(i.deliveries) FROM case_db.case_result_inbox i WHERE i.operation_id=o.operation_id AND i.state='SUCCEEDED'))
          FROM commerce_db.refund_operation o JOIN case_db.case_authorization a ON a.authorization_id=o.authorization_id
          JOIN case_db.aftersale_case c ON c.case_id=o.case_id JOIN commerce_db.line_refund f ON f.line_id=o.line_id
          JOIN commerce_db.order_line x ON x.line_id=o.line_id JOIN commerce_db.payment_ledger l ON l.order_id=x.order_id
          WHERE o.operation_id IN ({ids(operations)}) ORDER BY o.operation_id;"""
        rows = [json.loads(line) for line in base.sql(sql).splitlines()]
        assert len(rows) == 80
        provider = []
        with sqlite3.connect((base.folder / "provider.sqlite3").as_uri() + "?mode=ro", uri=True) as database:
            database.row_factory = sqlite3.Row
            success = sorted(row[0] for row in database.execute("SELECT operation_id FROM refund_request WHERE state='SUCCEEDED'"))
            new_provider = sorted(set(success) - set(before["provider_successes"]))
            assert new_provider == operations
            for op in operations:
                row = dict(database.execute("SELECT operation_id,line_id,amount_minor,state,provider_ref FROM refund_request WHERE operation_id=?", (op,)).fetchone())
                row["successes_per_line"] = database.execute("SELECT COUNT(*) FROM refund_request WHERE line_id=? AND state='SUCCEEDED'", (row["line_id"],)).fetchone()[0]
                row["processing_attempts"] = database.execute("SELECT COUNT(*) FROM request_attempt WHERE operation_id=? AND outcome<>'REPEAT'", (op,)).fetchone()[0]
                row["requests"] = database.execute("SELECT COUNT(*) FROM request_attempt WHERE operation_id=?", (op,)).fetchone()[0]
                provider.append(row)
        control = json.loads((raw / "refund-wiring-02/rounds/U00-control/entities.json").read_text(encoding="utf-8"))
        unknown = inspect_operation(base, control["operations"][0])
        assert unknown["operation"]["state"] == "UNKNOWN" and unknown["ledger"]["reserved"] == 32900
        assert unknown["ledger"]["refunded"] == 0 and not unknown["provider_receipts"]
        durable(raw / "refund-formal-final-database.json", {"run_id": base.identity, "new_operations": new,
                "new_success_operations": new_success, "new_provider_successes": new_provider,
                "operations": rows, "provider": provider, "nonconverging_control": unknown, "scope": "fixed formal cohort; original global inventory difference"})


if __name__ == "__main__":
    collect(Path(sys.argv[1]))
