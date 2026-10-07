"""Require complete batches and bind the seven resume claims to actual evidence."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/resume-quantification-v1"


def main():
    files = {
        "agent": OUT / "agent/summary.json",
        "authorization": OUT / "authorization/summary.json",
        "refund": OUT / "refund/summary.json",
        "recovery": OUT / "recovery/summary.json",
        "review": OUT / "review/audited-summary.json",
        "strict": OUT / "recovery/strict-v1.json",
    }
    data = {
        key: json.loads(path.read_text(encoding="utf-8")) for key, path in files.items()
    }
    for key in ("agent", "refund", "recovery", "review"):
        assert data[key]["state"] == "COMPLETED"
    assert (
        sum(group["investigations"] for group in data["agent"]["groups"].values())
        == 128
    )
    assert data["refund"]["fault_trials"] == 60
    assert data["recovery"]["pairs"] == 15 and data["recovery"]["actual_crashes"] == 30
    assert (
        data["review"]["normal_windows"] == 18 and data["review"]["fault_windows"] == 12
    )
    assert data["strict"]["summary"] == {"n": 18, "matched": 18}
    authorization = data["authorization"]
    assert (
        authorization["state"] == "COMPLETED" and authorization["scenario_runs"] == 80
    )
    assert authorization["expired_attempts"] == authorization["expired_rejected"] == 90
    assert (
        authorization["valid_consumptions"] == 80
        and authorization["illegal_consumptions"] == 0
    )
    for path, digest in authorization["files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    rag = json.loads(
        (ROOT / "evals/resume-quantification-v1/rag-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    for path, digest in rag["files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    for key in ("agent", "refund", "recovery", "review"):
        for path, digest in data[key]["hashes"].items():
            assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, (
                path
            )
    original = json.loads((OUT / "agent/formal-v1.json").read_text(encoding="utf-8"))
    for path, digest in original["code_hashes"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    agent = data["agent"]["groups"]
    recovery = data["recovery"]["windows"]["all"]["groups"]
    formal_requests = sum(g["model_requests"] for g in agent.values()) + sum(
        g["post_requests"] + g["prefix_requests"] for g in recovery.values()
    )
    formal_input = sum(g["input_tokens"] for g in agent.values()) + sum(
        g["post_input_tokens"] + g["prefix_input_tokens"] for g in recovery.values()
    )
    formal_output = sum(g["output_tokens"] for g in agent.values()) + sum(
        g["post_output_tokens"] + g["prefix_output_tokens"] for g in recovery.values()
    )
    paths = list(files.values()) + [
        OUT / "rag/external-v2.json",
        OUT / "rag/mall-v1.json",
        ROOT / "evals/resume-quantification-v1/rag-manifest.json",
        ROOT / "docs/resume-seven-points.md",
        ROOT / "docs/resume-quantification-plan.md",
        ROOT / "docs/resume-evidence.md",
        OUT / "README.md",
        OUT / "review/README.md",
        OUT / "review/environment.json",
        Path(__file__).resolve(),
    ]
    result = {
        "state": "COMPLETED",
        "architecture_new_quantification": False,
        "formal_live_model_requests": formal_requests,
        "formal_live_input_tokens": formal_input,
        "formal_live_output_tokens": formal_output,
        "formal_live_total_tokens": formal_input + formal_output,
        "scope": "synthetic business/queue data; real LLM and service measurements; durable simulated payment; development trials excluded from formal totals",
        "seven_evidence": {
            "1": "Existing architecture/transactions/tenant isolation; see README code and evidence links",
            "2": "agent/README.md",
            "3": "rag/README.md",
            "4": "authorization/README.md",
            "5": "refund/README.md",
            "6": "recovery/README.md",
            "7": "review/README.md",
        },
        "hashes": {
            str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in paths
        },
    }
    assert formal_requests == 579
    (OUT / "completion.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in result.items() if k != "hashes"}))


if __name__ == "__main__":
    main()
