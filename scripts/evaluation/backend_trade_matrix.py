"""Freeze/execute/resume the backend trade matrix without replaying started requests."""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.backend_lab import Settings, freeze_file, run, sha256
from evaluation.backend_smoke import login
from evaluation.backend_trade import round_probe
from evaluation.backend_trade_boundaries import catalog_round, expiry_round
from evaluation.backend_trade_faults import fault_round
from evaluation.trade_journal_probe import row_gate
from evaluation.trade_request_journal import (
    RecordedSettings,
    RequestJournal,
    durable,
    overlap,
)

TOOLS = ["scripts/evaluation/" + name + ".py" for name in (
    "backend_trade_matrix", "backend_trade", "backend_trade_boundaries", "backend_trade_faults",
    "backend_smoke", "backend_lab", "backend_provider", "trade_request_journal", "trade_journal_probe")]
TOOLS += ["scripts/backend_resume_lab.py", "docs/backend-resume-evaluation-v1.md"]


def plan(profile):
    rows = []
    for scenario in (f"T{i:02d}" for i in range(1, 9)):
        for concurrency in ((10, 30) if profile == "formal" else (30,)):
            repetitions = range(10) if profile == "formal" else range(2 if scenario in ("T03", "T08") else 1)
            for index in repetitions:
                row = {"id": f"{scenario}-c{concurrency}-r{index + 1:02d}", "scenario": scenario,
                       "concurrency": concurrency, "repetition": index + 1}
                first = index < 5 if profile == "formal" else index == 0
                if scenario == "T03":
                    row.update(factor=("price", "variant", "unlisted")[index % 3],
                               order="checkout-first" if first else "update-first")
                if scenario == "T08":
                    row["order"] = "expiry-first" if first else "reserve-first"
                rows.append(row)
    return rows


def score_intervals(rows, expected):
    assert len(rows) == expected and len({r["request_id"] for r in rows}) == expected
    peak = overlap(rows)
    assert peak == expected, f"client overlap {peak}, requested {expected}"
    return peak


def inventory(settings):
    names = ("orders", "receipts", "attempts")
    sql = """SELECT COALESCE(JSON_ARRAYAGG(order_id),JSON_ARRAY()) FROM commerce_db.orders;
      SELECT COALESCE(JSON_ARRAYAGG(attempt_id),JSON_ARRAY()) FROM commerce_db.simulated_checkout_receipt WHERE status='SUCCEEDED';
      SELECT COALESCE(JSON_ARRAYAGG(attempt_id),JSON_ARRAY()) FROM commerce_db.checkout_payment_attempt;"""
    return dict(zip(names, (sorted(json.loads(line)) for line in settings.sql(sql).splitlines()), strict=True))


def inventory_check(before, after, allowed):
    changes = {key: sorted(set(after[key]) - set(before[key])) for key in before}
    assert all(set(before[key]) <= set(after[key]) for key in before), "inventory unexpectedly removed"
    assert all(len(ids) == allowed for ids in changes.values()), changes
    assert changes["receipts"] == changes["attempts"], "receipt not bound to the original attempt"
    return changes


def verify_manifest(base, folder):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == base.identity and manifest["jars"] == base.freeze()["jars"]
    for name, digest in manifest["sources"].items():
        if sha256(base.root / name) != digest:
            raise ValueError("frozen source changed: " + name)
    return manifest


def freeze(base, folder, profile):
    baseline = base.freeze()
    sources = {name: sha256(base.root / name) for name in TOOLS}
    prerequisite = None
    if profile == "formal":
        for prior in sorted(folder.parent.glob("*/summary.json")):
            summary = json.loads(prior.read_text(encoding="utf-8"))
            manifest_path = prior.parent / "manifest.json"
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (summary["profile"] == "wiring" and summary["passed"] == summary["planned"] == 10
                    and previous["sources"] == sources and previous["jars"] == baseline["jars"]):
                prerequisite = {"manifest": str(manifest_path.relative_to(base.report)), "sha256": sha256(manifest_path)}
                break
        if not prerequisite:
            raise ValueError("formal freeze requires all 10 wiring rounds on these exact sources/jars")
    folder.mkdir(parents=True, exist_ok=False)
    for name in TOOLS:
        freeze_file(base.root / name, folder / "execution-sources" / name)
    durable(folder / "manifest.json", {"run_id": base.identity, "profile": profile, "plan": plan(profile),
            "sources": sources, "jars": baseline["jars"], "git_sha": run(["git", "rev-parse", "HEAD"]),
            "prerequisite": prerequisite, "model_requests": 0,
            "timing": "measured client intervals; row/table gates; not a natural-load performance benchmark",
            "checkout_poll_ms": {"default": 2000, "T08_expiry_first": 2000, "T08_reserve_first": 10000}})


def summarize(folder, manifest):
    outcomes = []
    for spec in manifest["plan"]:
        target = folder / "rounds" / spec["id"] / "outcome.json"
        if target.exists():
            outcomes.append(json.loads(target.read_text(encoding="utf-8")))
    value = {"profile": manifest["profile"], "planned": len(manifest["plan"]), "finished": len(outcomes),
             "passed": sum(r["status"] == "PASSED" for r in outcomes),
             "failures": [r for r in outcomes if r["status"] != "PASSED"],
             "rounds": outcomes, "manifest_sha256": sha256(folder / "manifest.json")}
    # Each checkpoint is new; a process interruption cannot overwrite its previous summary.
    checkpoint = folder / "checkpoints"
    checkpoint.mkdir(exist_ok=True)
    durable(checkpoint / f"{len(list(checkpoint.glob('*.json'))):04d}.json", value)
    if len(outcomes) == len(manifest["plan"]) and not (folder / "summary.json").exists():
        durable(folder / "summary.json", value)
    return value


def finalize_round(base, folder, spec):
    journal = RequestJournal(folder / "journal", create=False)
    audit = journal.audit()
    assert audit["complete"], "unknown request tail: " + str(audit["unknown"])
    target = "recovery-requests.json" if spec["scenario"] in ("T06", "T07") else "requests.json"
    rows = json.loads((folder / target).read_text(encoding="utf-8"))
    persisted = journal.recover([r["request_id"] for r in rows])
    peak = score_intervals(persisted, spec["concurrency"])
    for row, saved in zip(rows, persisted, strict=True):
        assert row["status"] == saved["status"] and row["body"] == saved["body"]
    allowed = int(spec["scenario"] in ("T04", "T05", "T06", "T07")
                  or (spec["scenario"] == "T08" and spec["order"] == "reserve-first"))
    before = json.loads((folder / "before-inventory.json").read_text(encoding="utf-8"))
    after = inventory(base)
    effects = inventory_check(before, after, allowed)
    result = {**spec, "status": "PASSED", "actual_peak": peak, "requests": len(rows),
              "all_recorded_requests": audit["recorded"], "effects": effects,
              "selected_http": {str(status): sum(r["status"] == status for r in rows)
                                for status in sorted({r["status"] for r in rows})},
              "evidence": {str(p.relative_to(folder)): sha256(p) for p in folder.rglob("*") if p.is_file()}}
    durable(folder / "outcome.json", result)
    return result


def execute(base, folder, *, resume=False):
    manifest = verify_manifest(base, folder)
    marker = folder / "execution-started.json"
    if not resume:
        durable(marker, {"manifest_sha256": sha256(folder / "manifest.json")})
    elif not marker.exists():
        raise ValueError("resume requires a started matrix")
    buyer = login(base, "demo-buyer", "demo-pass-4001")
    merchant = login(base, "demo-admin", "demo-pass-1100")
    try:
        for spec in manifest["plan"]:
            verify_manifest(base, folder)
            output = folder / "rounds" / spec["id"]
            if (output / "outcome.json").exists():
                previous = json.loads((output / "outcome.json").read_text(encoding="utf-8"))
                for name, digest in previous.get("evidence", {}).items():
                    assert sha256(output / name) == digest
                continue
            if output.exists():
                # Only a completed business result can be finalized without sending.
                result = output / "result.json"
                if result.exists() and json.loads(result.read_text(encoding="utf-8"))["status"] == "PASSED":
                    finalize_round(base, output, spec)
                    continue
                raise ValueError("started round has unknown/unvalidated effects; inspect original journal without resend")
            output.mkdir(parents=True)
            durable(output / "before-inventory.json", inventory(base))
            journal = RequestJournal(output / "journal")
            journal.register(buyer, "demo-buyer")
            journal.register(merchant, "demo-admin")
            factory = None if spec["scenario"] in ("T03", "T08") else lambda path: row_gate(base, path)
            settings = RecordedSettings(base, journal, factory)
            try:
                scenario, concurrency = spec["scenario"], spec["concurrency"]
                if scenario in ("T01", "T02", "T04", "T05"):
                    round_probe(settings, buyer, scenario, concurrency, output)
                elif scenario == "T03":
                    catalog_round(settings, buyer, merchant, spec["factor"], spec["order"], concurrency, output)
                elif scenario in ("T06", "T07"):
                    fault_round(settings, buyer, scenario, concurrency, output)
                else:
                    expiry_round(settings, buyer, spec["order"], concurrency, output, reset_scheduler=True)
                result = finalize_round(base, output, spec)
            except Exception as error:
                audit = RequestJournal(output / "journal", create=False).audit()
                after = inventory(base)
                before = json.loads((output / "before-inventory.json").read_text(encoding="utf-8"))
                changes = {key: sorted(set(after[key]) - set(before[key])) for key in before}
                result = {**spec, "status": "UNKNOWN_REQUEST" if audit["unknown"] else
                          "NOT_REACHED" if isinstance(error, TimeoutError) else "FAILED",
                          "error": type(error).__name__ + ": " + str(error)[:800], "audit": audit, "effects": changes}
                durable(output / "outcome.json", result)
                if any(len(ids) > 1 for ids in changes.values()) or audit["unknown"]:
                    raise RuntimeError("halt matrix: unknown or unexpected additional business effects") from error
            print(f"{spec['id']} {result['status']}", flush=True)
            summarize(folder, manifest)
    finally:
        summary = summarize(folder, manifest)
        print(json.dumps({k: summary[k] for k in ("profile", "planned", "finished", "passed")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "execute", "resume"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--matrix-id", required=True)
    parser.add_argument("--profile", choices=("wiring", "formal"), default="formal")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", args.matrix_id):
        raise ValueError("invalid matrix identifier")
    base = Settings(args.run_id)
    with base.operation_lock():
        folder = base.report / "trade-matrices" / args.matrix_id
        if args.action == "freeze":
            freeze(base, folder, args.profile)
        else:
            execute(base, folder, resume=args.action == "resume")


if __name__ == "__main__":
    main()
