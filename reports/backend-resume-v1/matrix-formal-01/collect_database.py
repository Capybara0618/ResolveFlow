"""SELECT-only final ledger check while the owned lab is running. Raw directory argument required."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluation.backend_lab import Settings
from evaluation.backend_trade_matrix import inventory, verify_manifest
from evaluation.trade_request_journal import durable


def collect(raw):
    manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
    base = Settings(manifest["run_id"], ROOT)
    with base.operation_lock():
        verify_manifest(base, raw)
        summary = json.loads((raw / "summary.json").read_text(encoding="utf-8"))
        assert summary["passed"] == 160 and len(summary["rounds"]) == 160
        expected = {key: sorted(v for r in summary["rounds"] for v in r["effects"][key])
                    for key in ("orders", "receipts", "attempts")}
        assert all(len(v) == len(set(v)) == 90 for v in expected.values())
        before = json.loads((raw / "rounds" / manifest["plan"][0]["id"] / "before-inventory.json").read_text(encoding="utf-8"))
        after = inventory(base)
        actual = {key: sorted(set(after[key]) - set(before[key])) for key in before}
        assert actual == expected
        for value in expected["attempts"]:
            assert re.fullmatch(r"[a-f0-9-]{36}", value)
        identifiers = ",".join("'" + value + "'" for value in expected["attempts"])
        sql = f"""SELECT JSON_OBJECT('attempt_id',a.attempt_id,'order_id',a.order_id,'status',a.status,
          'draft_status',d.status,'customer',o.customer_id,'store',o.merchant_id,'currency',o.currency,
          'paid',l.paid_amount,'reserved',l.reserved_refund_amount,'refunded',l.refunded_amount,
          'lines',(SELECT COUNT(*) FROM commerce_db.order_line x WHERE x.order_id=a.order_id),
          'line_total',(SELECT SUM(line_paid_amount) FROM commerce_db.order_line x WHERE x.order_id=a.order_id),
          'slots',(SELECT COUNT(*) FROM commerce_db.line_refund f JOIN commerce_db.order_line x ON f.line_id=x.line_id WHERE x.order_id=a.order_id),
          'receipts',(SELECT COUNT(*) FROM commerce_db.simulated_checkout_receipt r WHERE r.attempt_id=a.attempt_id),
          'receipt_amount',(SELECT total_amount FROM commerce_db.simulated_checkout_receipt r WHERE r.attempt_id=a.attempt_id))
          FROM commerce_db.checkout_payment_attempt a JOIN commerce_db.checkout_draft d ON d.draft_id=a.draft_id
          JOIN commerce_db.orders o ON o.order_id=a.order_id JOIN commerce_db.payment_ledger l ON l.order_id=a.order_id
          WHERE a.attempt_id IN ({identifiers}) ORDER BY a.attempt_id;"""
        payments = [json.loads(line) for line in base.sql(sql).splitlines()]
        assert len(payments) == 90
        durable(raw / "database-audit.json", {"run_id": base.identity, "global_effects": actual, "payments": payments,
                                           "scope": "synthetic formal cohort only; read-only final query"})


if __name__ == "__main__":
    collect(Path(sys.argv[1]))
