"""Compare actual saved requests on identical frozen cases and scripted trajectories."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "reports/agent-context-batch2/mock-complete.json"
CURRENT = Path(__file__).with_name("mock-complete.json")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def measure(entry):
    sizes = [request["context_measurement"]["input_estimate"] for request in entry["requests"]]
    return {"first": sizes[0], "max": max(sizes), "cumulative": sum(sizes), "calls": len(sizes)}


def prompt_parts(entry):
    system = entry["requests"][0]["messages"][0]["content"]
    rules, protocol = system.split("动作/工具 schema：", 1)
    return {"system_chars": len(rules.rstrip()), "system_utf8_bytes": len(rules.rstrip().encode()),
            "protocol_utf8_bytes": len(("动作/工具 schema：" + protocol).encode())}


def main():
    before, after = load(BASELINE), load(CURRENT)
    assert before["manifest_hash"] == after["manifest_hash"]
    previous = {entry["id"]: entry for entry in before["results"]}
    rows = []
    for entry in after["results"]:
        old = previous[entry["id"]]
        assert entry["completed"] and old["completed"]
        assert entry["action"] == old["action"] and entry["model_calls"] == old["model_calls"]
        rows.append({"id": entry["id"], "before": measure(old), "after": measure(entry)})
    assert len(rows) == 32
    totals = {side: {key: sum(row[side][key] for row in rows) for key in ("first", "cumulative", "calls")}
              for side in ("before", "after")}
    result = {"measurement": "ESTIMATED_UTF8_BYTES, actual saved requests, single wrapper allowance",
              "billing_claim": False, "llm_quality_claim": False,
              "note": ("32 mock trajectories use compatible canonical output refs; "
                       "separate SDK/recovery/replay tests exercise short output refs."),
              "dataset_manifest_sha256": after["manifest_hash"],
              "report_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (BASELINE, CURRENT)},
              "prompt": {"before": prompt_parts(before["results"][0]),
                         "after": prompt_parts(after["results"][0])},
              "totals": totals,
              "reduction_fraction": {key: 1 - totals["after"][key] / totals["before"][key]
                                     for key in ("first", "cumulative")},
              "current_max_step": max(row["after"]["max"] for row in rows),
              "all_requests_within_cap": all(req["context_measurement"]["input_estimate"] <=
                                             req["context_measurement"]["cap"]
                                             for entry in after["results"] for req in entry["requests"]),
              "rows": rows}
    with Path(__file__).with_name("measurements.json").open("x", encoding="utf-8") as target:
        json.dump(result, target, ensure_ascii=False, indent=2)
        target.write("\n")
    print(json.dumps({key: value for key, value in result.items() if key not in {"rows", "report_sha256"}}))


if __name__ == "__main__":
    main()
