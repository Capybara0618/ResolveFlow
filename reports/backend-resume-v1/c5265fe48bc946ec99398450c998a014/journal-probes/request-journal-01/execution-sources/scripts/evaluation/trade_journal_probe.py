"""One real 30-client payment probe for the durable recorder, not the formal matrix."""

import argparse
import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.backend_lab import Settings, sha256
from evaluation.backend_smoke import login
from evaluation.backend_trade import round_probe
from evaluation.backend_trade_faults import MysqlSession
from evaluation.trade_request_journal import (
    RecordedSettings,
    RequestJournal,
    durable,
    overlap,
)


@contextmanager
def row_gate(settings, path):
    if path in ("/api/v1/shop/cart/M-1001/items", "/api/v1/shop/cart/M-1001/drafts"):
        sql = "SELECT revision FROM shopping_cart WHERE merchant_id='M-1001' AND customer_id='C-B3001-M1001' FOR UPDATE"
    else:
        match = re.fullmatch(r"/api/v1/shop/drafts/([a-f0-9-]{36})/payment", path)
        if not match:
            raise ValueError("unsupported gated route")
        sql = f"SELECT draft_id FROM checkout_draft WHERE draft_id='{match[1]}' FOR UPDATE"
    with MysqlSession(settings) as session:
        session.execute("START TRANSACTION; " + sql)
        released = False
        def release():
            nonlocal released
            session.execute("ROLLBACK")
            released = True
        try:
            yield release
        finally:
            if not released:
                session.execute("ROLLBACK")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--probe-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", args.probe_id):
        raise ValueError("invalid probe identifier")
    base = Settings(args.run_id)
    with base.operation_lock():
        baseline = base.freeze()
        folder = base.report / "journal-probes" / args.probe_id
        folder.mkdir(parents=True, exist_ok=False)
        sources = ["scripts/evaluation/" + name + ".py" for name in
                   ("trade_journal_probe", "trade_request_journal", "backend_trade", "backend_smoke", "backend_trade_faults", "backend_lab")]
        sources.append("scripts/backend_resume_lab.py")
        durable(folder / "manifest.json", {"run_id": base.identity, "jars": baseline["jars"],
                "sources": {name: sha256(base.root / name) for name in sources}, "phase": "recorder wiring, not formal"})
        journal = RequestJournal(folder / "requests")
        settings = RecordedSettings(base, journal, lambda path: row_gate(base, path))
        token = login(settings, "demo-buyer", "demo-pass-4001")
        output = folder / "round"
        output.mkdir()
        result = round_probe(settings, token, "T04", 30, output)
        audit = RequestJournal(journal.folder, create=False).audit()
        requests = json.loads((output / "requests.json").read_text())
        peak = overlap(requests)
        assert audit["complete"] and peak == 30
        durable(folder / "audit.json", {**audit, "payment_requests": len(requests), "payment_peak": peak,
                                       "original_counts": result["counts"], "model_requests": 0})
        print(json.dumps({"recorded": audit["recorded"], "peak": peak, "unknown": audit["unknown"]}), flush=True)


if __name__ == "__main__":
    main()
