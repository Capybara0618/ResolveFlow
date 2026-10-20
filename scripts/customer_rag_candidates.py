"""Frozen Query x retrieval comparisons on original scoped generations. No chat API calls or writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path

from customer_rag_diagnostic import PLAN, ROOT, ReadOnlyDatabase, snapshot
from resolveflow.policies.index import PolicyIndex
from resolveflow.support.embeddings import SupportEmbeddings
from resolveflow.support.query import grounded_query
from resolveflow.support.retrieval import reciprocal_rank_fusion

VARIANTS = ("dense", "body-bm25", "title-bm25", "body-rrf", "title-rrf", "fields-rrf")


def evaluate(output: Path):
    if output.exists():
        raise FileExistsError("candidate report is immutable")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    source = ROOT / "reports/customer-agent-live-v1/runtime-results.json"
    if hashlib.sha256(source.read_bytes()).hexdigest() != plan["source_sha256"]:
        raise ValueError("saved evidence changed")
    runs = {r["case"]: r for r in json.loads(source.read_text(encoding="utf-8"))["runs"]}
    resources = SupportEmbeddings()
    encoder = resources.get(str(ROOT / "tmp/c071-probe/models/BAAI--bge-small-zh-v1.5"))
    database = ReadOnlyDatabase("postgresql://agent:agent@127.0.0.1:55433/agent_db")
    index, rows = PolicyIndex(database), []
    try:
        before = snapshot(database)
        for case in plan["cases"]:
            saved = runs[case["source_case"]]
            input_data = saved["run"]["input_json"]
            observations, original = [], case.get("query")
            if case["kind"] == "saved-live":
                for call in saved["calls"]:
                    action = call["request_json"]
                    if action.get("name") == "search_policy":
                        original = action["arguments"]["query"]
                        break
                    if call["kind"] == "tool":
                        observations.extend(call["response_json"])
            # Synthetic probes deliberately have no invented authoritative facts.
            query_plan = grounded_query(original, observations, input_data["line_id"])
            manifest = input_data["context"]["policy_manifest"]
            scope = dict(
                merchant_id=manifest["merchant_id"],
                bundle_ids=manifest["bundle_ids"],
                manifest_hash=manifest["manifest_hash"],
                generation_ids=saved["run"]["generations_json"],
                top_k=5,
            )
            for query_variant, query in {"original": original, "fact-anchored": query_plan.query}.items():
                timings = {}
                routes, elapsed = {}, {}
                for name, path, field in [
                    ("dense", "dense", "body"),
                    ("body-bm25", "bm25", "body"),
                    ("title-bm25", "bm25", "title"),
                ]:
                    start = time.perf_counter()
                    hits = index.search(
                        **scope,
                        query=query,
                        path=path,
                        lexical_field=field,
                        embedder=encoder if path == "dense" else None,
                        timings=timings,
                    )
                    routes[name] = hits if path == "dense" else [h for h in hits if h.score > 0]
                    elapsed[name] = (time.perf_counter() - start) * 1000
                combinations = {
                    "body-rrf": ["dense", "body-bm25"],
                    "title-rrf": ["dense", "title-bm25"],
                    "fields-rrf": ["dense", "body-bm25", "title-bm25"],
                }
                for name, members in combinations.items():
                    start = time.perf_counter()
                    routes[name] = reciprocal_rank_fusion([routes[m] for m in members], top_k=5)
                    elapsed[name] = sum(elapsed[m] for m in members) + (time.perf_counter() - start) * 1000
                for name in VARIANTS:
                    hits = routes[name]
                    ids = [h.rule_id for h in hits]
                    required = set(case["required_rules"])
                    rows.append(
                        {
                            "id": case["id"],
                            "kind": case["kind"],
                            "query_variant": query_variant,
                            "query": query,
                            "original_query": original,
                            "query_reason": query_plan.reason,
                            "variant": name,
                            "rules": ids,
                            "scores": [h.score for h in hits],
                            "all_required_at_3": required <= set(ids[:3]),
                            "all_required_at_5": required <= set(ids),
                            "estimated_sequential_ms": elapsed[name],
                        }
                    )
                print(case["id"], query_variant, {k: [h.rule_id for h in v[:3]] for k, v in routes.items()}, flush=True)
        after = snapshot(database)
        if before != after:
            raise RuntimeError("retained database witness differs")
        summary = {}
        for cohort in ["saved-live", "synthetic-probe"]:
            for query_variant in ["original", "fact-anchored"]:
                baseline = {
                    r["id"]: r
                    for r in rows
                    if r["kind"] == cohort and r["query_variant"] == "original" and r["variant"] == "dense"
                }
                for variant in VARIANTS:
                    selected = [
                        r
                        for r in rows
                        if r["kind"] == cohort and r["query_variant"] == query_variant and r["variant"] == variant
                    ]
                    summary[f"{cohort}/{query_variant}/{variant}"] = {
                        "n": len(selected),
                        "all_required_at_3": sum(r["all_required_at_3"] for r in selected),
                        "all_required_at_5": sum(r["all_required_at_5"] for r in selected),
                        "regressions_at_3": [
                            r["id"]
                            for r in selected
                            if baseline[r["id"]]["all_required_at_3"] and not r["all_required_at_3"]
                        ],
                        "median_estimated_sequential_ms": statistics.median(
                            r["estimated_sequential_ms"] for r in selected
                        ),
                    }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "version": "customer-rag-candidates-v1",
                    "new_llm_calls": 0,
                    "not_holdout": True,
                    "synthetic_business_data": True,
                    "rrf_constant": 60,
                    "candidate_k": 5,
                    "final_k": 3,
                    "synthetic_probes_have_no_invented_facts": True,
                    "summary": summary,
                    "rows": rows,
                    "preservation": {"before": before, "after": after, "equal": before == after},
                    "inputs": {
                        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in [
                            PLAN,
                            source,
                            Path(__file__).resolve(),
                            ROOT / "agent/src/resolveflow/support/query.py",
                            ROOT / "agent/src/resolveflow/support/retrieval.py",
                            ROOT / "agent/src/resolveflow/policies/index.py",
                        ]
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
    finally:
        resources.clear()
        database.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    evaluate(parser.parse_args().output)
