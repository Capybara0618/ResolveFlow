"""Compare the same frozen inputs; estimates are UTF-8 bytes, never billing tokens."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "reports/agent-alignment-batch1/mock-aligned-v2.json"
CURRENT = Path(__file__).with_name("mock-complete.json")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def measure(entry):
    estimates = [request["context_measurement"]["input_estimate"] for request in entry["requests"]]
    return {"first": estimates[0], "max": max(estimates), "cumulative": sum(estimates),
            "calls": len(estimates), "completed": entry["completed"], "reason": entry["reason_code"]}


def main():
    before, after = load(BASELINE), load(CURRENT)
    assert before["manifest_hash"] == after["manifest_hash"]
    assert after["state"] == "FINISHED"
    old = {entry["id"]: entry for entry in before["results"]}
    rows = [{"id": entry["id"], "before": measure(old[entry["id"]]), "after": measure(entry)}
            for entry in after["results"]]
    assert len(rows) == 32
    estimates = [request["context_measurement"] for entry in after["results"] for request in entry["requests"]]
    first = {side: sum(row[side]["first"] for row in rows) for side in ("before", "after")}
    result = {"measurement": "ESTIMATED_UTF8_BYTES, includes one wrapper allowance",
              "billing_claim": False, "llm_quality_claim": False,
              "dataset_manifest_sha256": after["manifest_hash"],
              "reports_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in (BASELINE, CURRENT)},
              "first_request_totals": first, "first_request_reduction_fraction": 1 - first["after"] / first["before"],
              "current_max_step": max(item["input_estimate"] for item in estimates),
              "all_requests_within_cap": all(item["input_estimate"] <= item["cap"] for item in estimates),
              "cumulative_totals": {side: sum(row[side]["cumulative"] for row in rows) for side in ("before", "after")},
              "rows": rows}
    target = Path(__file__).with_name("measurements.json")
    if target.exists():
        raise FileExistsError(target)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {"rows", "reports_sha256"}}))


if __name__ == "__main__":
    main()
