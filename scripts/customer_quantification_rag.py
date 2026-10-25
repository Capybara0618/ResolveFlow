"""Frozen five-path policy retrieval benchmark; no answer model or business writes."""

from __future__ import annotations

import argparse
import hashlib
import os
import time
from pathlib import Path

from resolveflow.policies.index import PolicyHit
from resolveflow.policies.retrieval import bm25_scores, embedder

from scripts.customer_agent_eval_v2 import digest, read_json, write_new
from scripts.customer_rag_benchmark import GPU_PYTHON, percentile
from scripts.customer_rag_rerank import MODEL
from scripts.evaluation.customer_quantification_data import DATA, ROOT, rag_data
from scripts.evaluation.customer_rerank import LocalReranker
from scripts.evaluation.customer_rerank_gpu import GPUWorker
from scripts.policy_codex_review import sufficiently_covered
from scripts.policy_context_packet_eval import select_contexts
from scripts.policy_query_eval import coverage, rank

PLAN = DATA / "rag-manifest.json"
VARIANTS = ["bm25", "dense", "rrf", "bm25-ce", "rrf-ce"]
EMBEDDING = ROOT / "tmp/c071-probe/models/BAAI--bge-small-zh-v1.5"


def frozen_paths():
    names = ["docs/customer-quantification-v1.md", "evals/customer-quantification-v1/rag-queries.json",
        "scripts/customer_quantification_rag.py", "scripts/evaluation/customer_quantification_data.py",
        "agent/tests/unit/test_customer_quantification_rag.py", "scripts/customer_rag_benchmark.py",
        "scripts/customer_rag_rerank.py", "scripts/customer_agent_eval_v2.py",
        "scripts/policy_query_eval.py", "scripts/policy_codex_review.py", "scripts/policy_chunks.py",
        "scripts/policy_context_packet_eval.py", "scripts/evaluation/customer_rerank.py",
        "scripts/evaluation/customer_rerank_gpu.py", "scripts/evaluation/customer_rerank_gpu_worker.py",
        "agent/uv.lock", "agent/src/resolveflow/policies/retrieval.py",
        "tmp/policy-documents-v1/children-final.json", "tmp/policy-documents-v1/drafts-audited.json"]
    inherited = read_json(ROOT / "evals/customer-rag-v5/manifest.json")
    return {"files": {name: digest(ROOT / name) for name in names},
        "embedding_files": {name: digest(EMBEDDING / name) for name in inherited["embedding_files"]},
        "reranker_files": {p.relative_to(MODEL).as_posix(): digest(p) for p in sorted(MODEL.rglob("*"))
                           if p.is_file() and not p.name.endswith(".lock")}}


def freeze():
    rag_data()
    paths = frozen_paths()
    if not paths["reranker_files"] or not GPU_PYTHON.exists():
        raise ValueError("pinned local GPU runtime or model absent")
    write_new(PLAN, {"version": "customer-quantification-rag-v1", "variants": VARIANTS,
        "rounds": 3, "queries": 40, "candidate_k": 20, "rrf_constant": 60, "final_k": [3, 5],
        "primary_candidate": "rrf", "selection": "RRF chosen before new ranks; all other paths comparison only",
        "independent_holdout": False, "inference": "local CPU embedding / existing CUDA CE worker",
        "latency_scope": "Query to assembled evidence; excludes startup/HTTP/PG/answer generation", **paths})


def check():
    plan = read_json(PLAN)
    if plan["variants"] != VARIANTS or plan["rounds"] != 3:
        raise ValueError("frozen retrieval protocol differs")
    for field, root in (("files", ROOT), ("embedding_files", EMBEDDING), ("reranker_files", MODEL)):
        for name, expected in plan[field].items():
            if digest(root / name) != expected:
                raise ValueError("frozen asset changed: " + name)
    return plan


def fuse(routes, limit=20):
    scores, chunks = {}, {}
    for route in routes:
        for position, (chunk, _) in enumerate(route[:limit], 1):
            scores[chunk["id"]] = scores.get(chunk["id"], 0) + 1 / (60 + position)
            chunks[chunk["id"]] = chunk
    return [(chunks[key], score) for key, score in sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]]


def score(query, ranked, atoms, children, index):
    scope = {(s["source_id"], s["raw_sha256"]) for s in query["scope"]}
    if any(c["subject"] != query["subject"] or (c["source_id"], c["raw_sha256"]) not in scope for c, _ in ranked):
        raise ValueError("rank escaped source scope")
    metrics, packets = {}, {}
    for k in (3, 5):
        hits = [c for c, _ in ranked[:k]]
        complete = sufficiently_covered(atoms, lambda a, hits=hits: coverage(hits, a))
        recall = max((sum(coverage(hits, a) for a in group) / len(group) for group in atoms), default=None)
        packet = select_contexts(query, hits, children, index, 8000)
        keys = set(packet.block_keys)
        expanded = sufficiently_covered(atoms, lambda a, keys=keys: (
            a["source_id"], a["raw_sha256"], a["block_id"]) in keys)
        metrics[str(k)] = {"direct_complete": complete, "direct_recall": recall,
                           "expanded_complete": expanded, "expanded_chars": packet.exported_chars}
        packets[str(k)] = {"sha256": packet.fingerprint, "block_count": len(keys)}
    return {"at_k": metrics, "packets": packets}


def retrieve(query, children, encoder, scorer, variant):
    started = time.perf_counter()
    dense_needed = variant in {"dense", "rrf", "rrf-ce"}
    encoded = time.perf_counter()
    vector = encoder.embed([query["query"]])[0] if dense_needed else None
    encode_ms = (time.perf_counter() - encoded) * 1000
    candidate_at = time.perf_counter()
    if variant == "dense":
        ranked = rank(query, children, "dense", vector)
    elif variant in {"bm25", "bm25-ce"}:
        ranked = rank(query, children, "bm25")
    else:
        dense = rank(query, children, "dense", vector)
        lexical = rank(query, children, "bm25")
        scoped = [c for c, _ in dense]
        title_scores = bm25_scores([" > ".join(c["section_path"]) for c in scoped], query["query"])
        title = sorted(zip(scoped, title_scores, strict=True), key=lambda pair: (-pair[1], pair[0]["id"]))
        ranked = fuse([dense, lexical, title])
    candidate_ms = (time.perf_counter() - candidate_at) * 1000
    rerank = None
    if variant.endswith("-ce"):
        manifest = hashlib.sha256(str(query["scope"]).encode()).hexdigest()
        hits = [PolicyHit(c["source_id"], query["subject"], c["raw_sha256"], manifest, c["id"], c["id"],
                         c["content_sha256"], " > ".join(c["section_path"]), c["retrieval_text"], s, "dense")
                for c, s in ranked[:20]]
        mapping = {c["id"]: c for c, _ in ranked[:20]}
        reranked, rerank = scorer.rank(query["query"], hits)
        ranked = [(mapping[h.chunk_id], h.score) for h in reranked]
    return ranked, {"encode_ms": encode_ms, "candidate_ms": candidate_ms, "rerank": rerank,
                    "ranking_ms": (time.perf_counter() - started) * 1000}


def execute(output):
    plan = check()
    if output.exists():
        raise FileExistsError(output)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    load_at = time.perf_counter()
    import torch

    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    queries, atoms, children, index = rag_data()
    encoder = embedder(str(EMBEDDING))
    worker = GPUWorker(GPU_PYTHON, MODEL, output.with_suffix(".gpu.log"))
    try:
        scorer = LocalReranker(worker, synchronize=worker.synchronize)
        # Generic warmups do not use the new acceptance labels or questions.
        encoder.embed(["售后政策的适用范围"])
        warm = PolicyHit("warm", "M", "v", "hash", "r", "c", "hash", "title", "人工核验后处理。", 0., "dense")
        for _ in range(3):
            scorer.rank("售后核验", [warm])
        startup_ms = (time.perf_counter() - load_at) * 1000
        rows = []
        for repeat in range(plan["rounds"]):
            order = VARIANTS[repeat:] + VARIANTS[:repeat]
            for query in queries:
                for variant in order:
                    started = time.perf_counter()
                    ranked, timing = retrieve(query, children, encoder, scorer, variant)
                    # Assemble packets inside latency; source-label scoring occurs afterwards.
                    packets = [select_contexts(query, [c for c, _ in ranked[:k]], children, index, 8000)
                               for k in (3, 5)]
                    elapsed = (time.perf_counter() - started) * 1000
                    rows.append({"id": query["id"], "variant": variant, "repeat": repeat + 1,
                        "answerability": query["answerability"], "elapsed_ms": elapsed, "timing": timing,
                        "hits": [c["id"] for c, _ in ranked], "packet_chars": [p.exported_chars for p in packets],
                        **score(query, ranked, atoms[query["id"]], children, index)})
        check()
        summaries = {}
        for variant in VARIANTS:
            selected = [r for r in rows if r["variant"] == variant]
            answerable = [r for r in selected if r["answerability"] == "ANSWERABLE" and r["repeat"] == 1]
            summaries[variant] = {"questions": len(answerable), "direct_complete_at_3": sum(
                r["at_k"]["3"]["direct_complete"] for r in answerable), "timed_requests": len(selected),
                "p50_ms": percentile([r["elapsed_ms"] for r in selected], .5),
                "p95_ms": percentile([r["elapsed_ms"] for r in selected], .95)}
        write_new(output, {"version": plan["version"], "manifest_sha256": digest(PLAN), "startup_ms": startup_ms,
            "new_chat_api_calls": 0, "latency_scope": plan["latency_scope"], "gpu": worker.ready,
            "summaries": summaries, "rows": rows})
    finally:
        worker.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["freeze", "check", "execute"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "freeze":
        freeze()
    elif args.mode == "check":
        print({"queries": check()["queries"], "new_model_inferences": 0})
    elif args.output:
        execute(args.output)
    else:
        parser.error("execute requires a new --output path")
