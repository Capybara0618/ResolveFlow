"""Actual current BoundSources timing and separately cached external original-document evidence coverage."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src"), str(ROOT / "scripts")]

from resolveflow.policies.index import PolicyIndex
from resolveflow.support.embeddings import SupportEmbeddings
from resolveflow.support.protocol import SupportInput
from resolveflow.support.sources import BoundSources

from scripts.customer_agent_eval_v2 import digest, read_json, write_new
from scripts.customer_current_eval import DIRECTORY, load_plan
from scripts.customer_rag_benchmark import percentile
from scripts.customer_rag_diagnostic import ReadOnlyDatabase, snapshot
from scripts.customer_rag_live_v2 import DSN, MODEL_PATH


def evaluate(output):
    import httpx

    load_plan()
    if output.exists():
        raise FileExistsError("immutable actual retrieval timing")
    plan = read_json(ROOT / "evals/customer-rag-v1/queries.json")
    source = ROOT / "reports/customer-agent-live-v1/runtime-results.json"
    if digest(source) != plan["source_sha256"]:
        raise ValueError("saved runtime changed")
    runs = {r["case"]: r for r in read_json(source)["runs"]}
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    import torch

    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    pool = SupportEmbeddings()
    warmup_ms = pool.prewarm(MODEL_PATH)
    database = ReadOnlyDatabase(DSN)
    try:
        before = snapshot(database)
        index = PolicyIndex(database)
        rows = []
        # First actual search per frozen query is separated; ten following rounds are all warm.
        for round_index in range(11):
            for case in plan["cases"]:
                run = runs[case["source_case"]]
                raw = run["run"]["input_json"]
                request = SupportInput.model_validate(raw)
                query = case.get("query") or next(c["request_json"]["arguments"]["query"]
                    for c in run["calls"] if c["request_json"].get("name") == "search_policy")
                with httpx.Client(transport=httpx.MockTransport(lambda call: httpx.Response(403))) as client:
                    sources = BoundSources(request, case_url="http://frozen-case.local", token="frozen-read-token",
                                           index=index, embedder=pool.get(MODEL_PATH), client=client)
                    sources.generations = run["run"]["generations_json"]
                    started = time.perf_counter()
                    hits = sources.search(query, 5)
                    elapsed = (time.perf_counter() - started) * 1000
                rules = [h.get("data", {}).get("rule_id") for h in hits]
                rows.append({"id": case["id"], "kind": case["kind"], "round": round_index,
                    "warm": round_index > 0, "query": query, "elapsed_ms": elapsed,
                    "retrieval_context": [h.get("retrieval_context") for h in hits], "rules": rules,
                    "required_rules": case["required_rules"], "error": any("error" in h for h in hits),
                    "required_input_coverage": set(case["required_rules"]) <= set(rules)})
        after = snapshot(database)
        if before != after:
            raise ValueError("retained data changed")
        warm = [r["elapsed_ms"] for r in rows if r["warm"]]
        load_plan()
        write_new(output, {"version": "current-bound-sources-v1", "scope": "CPU4 readonly actual BoundSources.search",
            "new_llm_calls": 0, "local_embedding_prewarm_ms": warmup_ms, "first_query_pass": rows[:9],
            "warm_n": len(warm), "warm_p50_ms": percentile(warm, .5), "warm_p95_ms": percentile(warm, .95),
            "required_input_covered": sum(r["required_input_coverage"] for r in rows if r["warm"]),
            "error_count": sum(r["error"] for r in rows), "public_before": before, "public_after": after, "rows": rows})
        print(json.dumps({"warm_n": len(warm), "p50_ms": percentile(warm, .5), "p95_ms": percentile(warm, .95)}))
    finally:
        database.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["external", "runtime"])
    args = parser.parse_args()
    if args.mode == "external":
        load_plan()
        from scripts.customer_rag_external import evaluate as external

        external(DIRECTORY / "rag-external.json")
        load_plan()
    else:
        evaluate(DIRECTORY / "rag-runtime.json")
