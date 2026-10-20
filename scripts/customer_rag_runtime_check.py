"""Exercise the actual consultation source adapter on retained scoped policies without a chat call."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path

import httpx
from customer_rag_diagnostic import PLAN, ROOT, ReadOnlyDatabase, snapshot
from resolveflow.policies.index import PolicyIndex
from resolveflow.support.embeddings import SupportEmbeddings
from resolveflow.support.protocol import SupportInput
from resolveflow.support.sources import BoundSources


def evaluate(output):
    if output.exists():
        raise FileExistsError("runtime check is immutable")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    source_path = ROOT / "reports/customer-agent-live-v1/runtime-results.json"
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != plan["source_sha256"]:
        raise ValueError("saved source differs")
    runs = {r["case"]: r for r in json.loads(source_path.read_text(encoding="utf-8"))["runs"]}
    candidate_path = ROOT / "reports/customer-rag-v2/candidates.json"
    expected = {
        r["id"]: r
        for r in json.loads(candidate_path.read_text(encoding="utf-8"))["rows"]
        if r["query_variant"] == "original" and r["variant"] == "fields-rrf"
    }
    database = ReadOnlyDatabase("postgresql://agent:agent@127.0.0.1:55433/agent_db")
    resources = SupportEmbeddings()
    encoder = resources.get(str(ROOT / "tmp/c071-probe/models/BAAI--bge-small-zh-v1.5"))
    rows = []

    def no_network(request):
        raise AssertionError("this diagnostic must not make any HTTP request")

    try:
        before = snapshot(database)
        with httpx.Client(transport=httpx.MockTransport(no_network)) as client:
            for case in plan["cases"]:
                saved = runs[case["source_case"]]
                # Only validate the original input, never claim/resume or change a persisted run.
                request = SupportInput.model_validate(saved["run"]["input_json"])
                query = case.get("query") or next(
                    c["request_json"]["arguments"]["query"]
                    for c in saved["calls"]
                    if c["request_json"].get("name") == "search_policy"
                )
                source = BoundSources(
                    request,
                    case_url="http://unused.local",
                    token="",
                    index=PolicyIndex(database),
                    embedder=encoder,
                    client=client,
                )
                source.generations = saved["run"]["generations_json"]
                started = time.perf_counter()
                hits = source.search(query, 3)
                ms = (time.perf_counter() - started) * 1000
                ids = [h["data"]["rule_id"] for h in hits]
                assert ids == expected[case["id"]]["rules"][:3], case["id"]
                manifest = request.context["policy_manifest"]
                assert all(
                    h["data"]["merchant_id"] == request.merchant_id
                    and h["data"]["manifest_hash"] == manifest["manifest_hash"]
                    and h["data"]["bundle_id"] in manifest["bundle_ids"]
                    and "timings" not in h
                    for h in hits
                )
                rows.append(
                    {
                        "id": case["id"],
                        "kind": case["kind"],
                        "query": query,
                        "rules": ids,
                        "all_required_at_3": set(case["required_rules"]) <= set(ids),
                        "elapsed_ms": ms,
                        "citations": [
                            {
                                k: h["data"][k]
                                for k in [
                                    "bundle_id",
                                    "merchant_id",
                                    "manifest_hash",
                                    "rule_id",
                                    "chunk_id",
                                    "content_hash",
                                ]
                            }
                            for h in hits
                        ],
                    }
                )
                source.close()
        after = snapshot(database)
        if before != after:
            raise RuntimeError("retained data witness differs")
        output.parent.mkdir(parents=True, exist_ok=True)
        paths = [
            PLAN,
            source_path,
            candidate_path,
            Path(__file__).resolve(),
            *[
                (ROOT / "agent/src/resolveflow/support" / name)
                for name in ["engine.py", "sources.py", "service.py", "retrieval.py"]
            ],
        ]
        output.write_text(
            json.dumps(
                {
                    "version": "customer-rag-runtime-v2",
                    "new_llm_calls": 0,
                    "http_calls": 0,
                    "not_holdout": True,
                    "all_rankings_match_selected_candidate": True,
                    "adapter": "BoundSources.search",
                    "summary": {
                        cohort: {
                            "n": sum(r["kind"] == cohort for r in rows),
                            "all_required_at_3": sum(r["all_required_at_3"] for r in rows if r["kind"] == cohort),
                        }
                        for cohort in ["saved-live", "synthetic-probe"]
                    },
                    "latency": {
                        "cold_ms": rows[0]["elapsed_ms"],
                        "subsequent_n": len(rows) - 1,
                        "subsequent_median_ms": statistics.median(r["elapsed_ms"] for r in rows[1:]),
                    },
                    "rows": rows,
                    "preservation": {"before": before, "after": after, "equal": before == after},
                    "inputs": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print("adapter matches candidate for", len(rows), "queries")
    finally:
        resources.clear()
        database.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    evaluate(parser.parse_args().output)
