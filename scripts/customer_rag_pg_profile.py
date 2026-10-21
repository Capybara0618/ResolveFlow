"""Read-only actual production retrieval stages on retained nine mall queries; no service or model API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from resolveflow.policies.index import PolicyIndex  # noqa: E402
from resolveflow.policies.retrieval import embedder  # noqa: E402
from resolveflow.support.retrieval import retrieve_policy  # noqa: E402
from scripts.customer_rag_benchmark import percentile, write_new  # noqa: E402
from scripts.customer_rag_diagnostic import ReadOnlyDatabase, snapshot  # noqa: E402
from scripts.customer_rag_rerank import digest  # noqa: E402


def evaluate(output):
    if output.exists():
        raise FileExistsError("PG profile output is immutable")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    import torch

    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    plan = json.loads((ROOT / "evals/customer-rag-v1/queries.json").read_text(encoding="utf-8"))
    source = ROOT / "reports/customer-agent-live-v1/runtime-results.json"
    if digest(source) != plan["source_sha256"]:
        raise ValueError("saved runtime changed")
    runs = {r["case"]: r for r in json.loads(source.read_text(encoding="utf-8"))["runs"]}
    database = ReadOnlyDatabase("postgresql://agent:agent@127.0.0.1:55433/agent_db")
    encoder = embedder(str(ROOT / "tmp/c071-probe/models/BAAI--bge-small-zh-v1.5"))
    index = PolicyIndex(database)
    try:
        before = snapshot(database)
        rows = []
        for round_index in range(3):
            for case in plan["cases"]:
                run = runs[case["source_case"]]
                manifest = run["run"]["input_json"]["context"]["policy_manifest"]
                query = case.get("query") or next(
                    c["request_json"]["arguments"]["query"]
                    for c in run["calls"]
                    if c["request_json"].get("name") == "search_policy"
                )
                profile = {}
                started = time.perf_counter()
                hits = retrieve_policy(
                    index,
                    merchant_id=manifest["merchant_id"],
                    bundle_ids=manifest["bundle_ids"],
                    manifest_hash=manifest["manifest_hash"],
                    generation_ids=run["run"]["generations_json"],
                    query=query,
                    top_k=5,
                    embedder=encoder,
                    timings=profile,
                )
                elapsed = (time.perf_counter() - started) * 1000
                rows.append(
                    {
                        "id": case["id"],
                        "kind": case["kind"],
                        "round": round_index,
                        "cold": not rows,
                        "elapsed_ms": elapsed,
                        "stages": profile,
                        "rule_ids": [h.rule_id for h in hits],
                        "required_rules": case["required_rules"],
                        "complete_at_3": set(case["required_rules"]) <= {h.rule_id for h in hits[:3]},
                        "complete_at_5": set(case["required_rules"]) <= {h.rule_id for h in hits[:5]},
                    }
                )
        after = snapshot(database)
        if before != after:
            raise ValueError("retained public data changed")
        warm = [r["elapsed_ms"] for r in rows if not r["cold"]]
        write_new(
            output,
            {
                "version": "customer-rag-actual-pg-profile-v1",
                "source_sha256": digest(source),
                "runner_sha256": digest(Path(__file__)),
                "scope": "Actual retrieve_policy with readonly retained PG, CPU embedding4 threads; no HTTP/LLM.",
                "cold_ms": rows[0]["elapsed_ms"],
                "warm_n": len(warm),
                "warm_p50_ms": percentile(warm, 0.5),
                "warm_p95_ms": percentile(warm, 0.95),
                "preservation": {"before": before, "after": after, "equal": True},
                "rows": rows,
            },
        )
    finally:
        database.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    evaluate(parser.parse_args().output)
