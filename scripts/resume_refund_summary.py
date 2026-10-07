"""Aggregate the complete real-service, simulated-payment fault matrix."""

import hashlib
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/resume-quantification-v1/refund"


def main():
    directory = OUT / "formal-v1"
    raw = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    assert raw["state"] == "COMPLETED" and not raw["trial"]
    rows = raw["results"]
    assert len(rows) == 60
    assert {(row["scenario"], row["repeat"]) for row in rows} == {
        (f"F{i}", repeat) for i in range(1, 7) for repeat in range(10)
    }
    for path, digest in metadata["source_sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    successes = [row for row in rows if row["status"] == "PASSED"]
    assert len(successes) == 60
    for row in rows:
        assert len(row["snapshots"]) >= 3
        assert row["domain_failed_results"] == 0
        assert all(n == 1 for n in row["provider_successes_per_line"].values())
        assert all(n == 1 for n in row["closed_events"].values())
        if row["scenario"] == "F4":
            assert row["unknown_observed"]
            unknown = next(s for s in row["snapshots"] if s["stage"] == "UNKNOWN")
            assert unknown["reserved"] == unknown["paid"] and unknown["refunded"] == 0
            assert {r["operation_id"] for r in row["provider_http"]} == set(
                row["operations"]
            )
            assert any(r["method"] == "GET" for r in row["provider_http"])
        if row["scenario"] == "F5":
            assert row["settled_unpublished_before_kill"]
    unknown_rows = [row for row in rows if row.get("unknown_observed")]
    result = {
        "state": "COMPLETED",
        "scope": "real Case/Commerce/MySQL/RocketMQ; durable simulated payment provider; synthetic isolated orders",
        "fault_trials": len(rows),
        "passed": len(successes),
        "successful_order_lines": sum(len(row["lines"]) for row in rows),
        "duplicate_successful_refunds": sum(row["duplicate_successes"] for row in rows),
        "overpaid_orders_at_observed_boundaries": sum(
            any(s["excess"] > 0 for s in row["snapshots"]) for row in rows
        ),
        "maximum_excess_minor": max(
            s["excess"] for row in rows for s in row["snapshots"]
        ),
        "domain_failed_results": sum(row["domain_failed_results"] for row in rows),
        "unknown_entered": len(unknown_rows),
        "unknown_converged": sum(row["status"] == "PASSED" for row in unknown_rows),
        "observed_ledger_boundaries": sum(len(row["snapshots"]) for row in rows),
        "scenarios": {
            scenario: {
                "trials": 10,
                "passed": sum(
                    row["status"] == "PASSED"
                    for row in rows
                    if row["scenario"] == scenario
                ),
                "end_to_end_seconds_mean": statistics.mean(
                    row["elapsed_seconds"]
                    for row in rows
                    if row["scenario"] == scenario
                ),
                "end_to_end_seconds_max": max(
                    row["elapsed_seconds"]
                    for row in rows
                    if row["scenario"] == scenario
                ),
            }
            for scenario in (f"F{i}" for i in range(1, 7))
        },
        "hashes": {
            str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in list(directory.glob("*.json")) + [Path(__file__).resolve()]
        },
    }
    assert result["duplicate_successful_refunds"] == 0
    assert result["overpaid_orders_at_observed_boundaries"] == 0
    assert result["unknown_entered"] == result["unknown_converged"] == 10
    (OUT / "summary.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in result.items() if key != "hashes"}))


if __name__ == "__main__":
    main()
