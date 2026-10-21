"""Frozen project corpus benchmark: quality, cold/hot stages and limited concurrency. No business writes."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src")]

from resolveflow.harness.token_counting import load_tokenizer  # noqa: E402
from resolveflow.policies.retrieval import bm25_scores, cosine_similarity, embedder  # noqa: E402
from resolveflow.support.retrieval import reciprocal_rank_fusion  # noqa: E402
from scripts.customer_rag_rerank import MODEL, digest  # noqa: E402
from scripts.evaluation.customer_knowledge import hits, load_dataset, make_packet, route_rankings  # noqa: E402
from scripts.evaluation.customer_rerank import LocalReranker, candidate_union  # noqa: E402
from scripts.evaluation.customer_rerank_gpu import GPUWorker  # noqa: E402

DIRECTORY = ROOT / "evals/customer-rag-v5"
GPU_PYTHON = Path("E:/Code/servicedesk-agent-sft/.venv/Scripts/python.exe")
EMBEDDING_PATH = ROOT / "tmp/c071-probe/models/BAAI--bge-small-zh-v1.5"
VARIANTS = ["bm25", "dense", "rrf", "rrf-linked", "union-ce", "all-ce", "all-read"]
CONFIG = {
    "variants": VARIANTS,
    "candidate_per_route": 5,
    "final_k": [3, 5],
    "rrf_constant": 60,
    "embedding_device": "cpu",
    "ce_device": "cuda:0",
    "threads": 4,
    "ce_batch": 8,
    "ce_max_pair_tokens": 512,
    "tf32": False,
    "concurrency": [1, 4],
    "requests_per_concurrency": 40,
    "quality_rounds": 1,
    "gpu_warmup": 3,
    "targets_ms": {"rrf_p95": 300, "ce_p95": 500},
    "selection": "Max dev complete_at_3; ties prefer rrf then bm25/dense/rrf-linked before CE; all-read excluded.",
    "scope": "In-memory file corpus; query-to-evidence only; no HTTP/PG/answer generation.",
}
FILES = [
    "scripts/customer_rag_pg_profile.py",
    "scripts/customer_rag_benchmark.py",
    "scripts/evaluation/customer_knowledge.py",
    "scripts/evaluation/customer_rerank.py",
    "scripts/evaluation/customer_rerank_gpu.py",
    "scripts/evaluation/customer_rerank_gpu_worker.py",
    "agent/tests/unit/test_customer_knowledge.py",
    "docs/customer-rag-data-design-speed.md",
    "agent/uv.lock",
    "agent/src/resolveflow/policies/retrieval.py",
    "agent/src/resolveflow/support/retrieval.py",
    "agent/src/resolveflow/harness/token_counting.py",
    "agent/src/resolveflow/assets/deepseek-v41/tokenizer.json.gz",
    "evals/customer-rag-v5/knowledge.json",
    "evals/customer-rag-v5/queries.json",
    "evals/customer-rag-v5/references.json",
]


def write_new(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def percentile(values, p):
    values = sorted(values)
    if not values:
        raise ValueError("empty timing sample")
    position = (len(values) - 1) * p
    lower = int(position)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (position - lower)


def freeze():
    knowledge, _ = load_dataset(ROOT)
    paths = list(FILES)
    refs = json.loads((DIRECTORY / "references.json").read_text(encoding="utf-8"))
    paths += [s["path"] for s in refs["project_sources"]]
    paths += [refs["external_policy_catalog"]["path"], refs["engineering_fixed_sources"]["path"]]
    import subprocess

    runtime = json.loads(
        subprocess.check_output(  # noqa: S603 - explicit local interpreter, fixed read-only command
            [
                str(GPU_PYTHON),
                "-c",
                "import json,sys;from importlib.metadata import version;"
                "print(json.dumps({'python':sys.version.split()[0],"
                "**{p:version(p) for p in ['torch','transformers']}}))",
            ],
            text=True,
        )
    )
    write_new(
        DIRECTORY / "manifest.json",
        {
            "version": "customer-corpus-design-speed-v1",
            "config": CONFIG,
            "not_holdout": True,
            "inputs": {p: digest(ROOT / p) for p in dict.fromkeys(paths)},
            "gpu_python": str(GPU_PYTHON),
            "gpu_runtime": runtime,
            "reranker_files": {p.name: digest(p) for p in MODEL.iterdir() if p.is_file()},
            "embedding_files": {p.name: digest(p) for p in EMBEDDING_PATH.iterdir() if p.is_file()},
            "unique_knowledge_count": len(knowledge["documents"]),
            "synthetic": True,
            "production_published": False,
        },
    )


def verify(manifest):
    if manifest["config"] != CONFIG:
        raise ValueError("benchmark config differs")
    for p, sha in manifest["inputs"].items():
        if digest(ROOT / p) != sha:
            raise ValueError("frozen input changed: " + p)
    for directory, key in [(MODEL, "reranker_files"), (EMBEDDING_PATH, "embedding_files")]:
        for name, sha in manifest[key].items():
            if digest(directory / name) != sha:
                raise ValueError("local model file changed")


class Search:
    def __init__(self, knowledge, encoder, vectors, scorer, tokenizer):
        self.knowledge, self.encoder, self.vectors = knowledge, encoder, vectors
        self.scorer, self.tokenizer = scorer, tokenizer
        self.gpu_lock = threading.Lock()

    def run(self, query, variant):
        started = time.perf_counter()
        stages = {}
        merchant, ver, text = query["merchant_id"], query["version"], query["query"]
        originals = hits(self.knowledge, merchant, ver)
        ranked = []
        if variant == "all-read":
            selected = [h.rule_id for h in originals]
        elif variant == "bm25":
            at = time.perf_counter()
            scores = bm25_scores([h.text for h in originals], text)
            ranked = [
                h
                for h, score in sorted(zip(originals, scores, strict=True), key=lambda p: (-p[1], p[0].chunk_id))
                if score > 0
            ][:5]
            stages["lexical_ms"] = (time.perf_counter() - at) * 1000
            selected = [h.rule_id for h in ranked]
        else:
            at = time.perf_counter()
            if variant == "all-ce":
                pool = originals
            else:
                vector, embedding_profile = self.encoder.embed_profiled([text])
                stages.update(embedding_profile)
                after_embedding = time.perf_counter()
                if variant == "dense":
                    ranked = [
                        h
                        for h, _ in sorted(
                            (
                                (h, cosine_similarity(v, vector[0]))
                                for h, v in zip(originals, self.vectors, strict=True)
                            ),
                            key=lambda pair: (-pair[1], pair[0].chunk_id),
                        )
                    ][:5]
                    routes = [ranked]
                else:
                    routes = route_rankings(self.knowledge, merchant, ver, text, self.vectors, vector[0])
                stages["route_ranking_ms"] = (time.perf_counter() - after_embedding) * 1000
                if variant == "dense":
                    ranked = routes[0]
                elif variant in {"rrf", "rrf-linked"}:
                    ranked = reciprocal_rank_fusion(routes, top_k=5)
                pool = candidate_union(routes)
            if variant in {"union-ce", "all-ce"}:
                wait = time.perf_counter()
                with self.gpu_lock:
                    stages["gpu_wait_ms"] = (time.perf_counter() - wait) * 1000
                    ranked, profile = self.scorer.rank(text, pool)
                stages.update({"ce_" + k: v for k, v in profile.items()})
            stages["retrieval_ms"] = (time.perf_counter() - at) * 1000
            selected = [h.rule_id for h in ranked[:5]]
            if variant == "rrf-linked":
                by_id = {d["id"]: d for d in self.knowledge["documents"]}
                selected = list(dict.fromkeys(selected + [r for key in selected for r in by_id[key]["related_ids"]]))
        at = time.perf_counter()
        packet = make_packet(self.knowledge, merchant, ver, selected)
        body = "\n\n".join(b["text"] for b in packet["blocks"])
        body_tokens = len(self.tokenizer.encode(body).ids)
        wire = json.dumps(packet, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        packet_tokens = len(self.tokenizer.encode(wire).ids)
        stages["assembly_tokenizing_ms"] = (time.perf_counter() - at) * 1000
        total = (time.perf_counter() - started) * 1000
        groups = query["evidence_sets"]

        def complete(ids):
            return any(set(g) <= set(ids) for g in groups)

        return {
            "id": query["id"],
            "family": query["family"],
            "split": query["split"],
            "variant": variant,
            "merchant_id": merchant,
            "answerability": query["answerability"],
            "ranked_ids": [h.rule_id for h in ranked],
            "selected_ids": selected,
            "complete_at_3": complete([h.rule_id for h in ranked[:3]]) if ranked else None,
            "complete_at_5": complete([h.rule_id for h in ranked[:5]]) if ranked else None,
            "packet_complete": complete(selected) if groups else None,
            "body_tokens": body_tokens,
            "packet_tokens": packet_tokens,
            "packet_sha256": digest_text(wire),
            "stages": stages,
            "total_ms": total,
        }


def digest_text(text):
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()


def summarize(rows):
    result = {}
    for variant in VARIANTS:
        selected = [r for r in rows if r["variant"] == variant]
        full = [r for r in selected if r["answerability"] == "ANSWERABLE"]
        result[variant] = {
            "query_n": len(selected),
            "answerable_n": len(full),
            "complete_at_3_n": sum(bool(r["complete_at_3"]) for r in full) if variant != "all-read" else None,
            "complete_at_5_n": sum(bool(r["complete_at_5"]) for r in full) if variant != "all-read" else None,
            "packet_complete_n": sum(bool(r["packet_complete"]) for r in full),
            "p50_ms": percentile([r["total_ms"] for r in selected], 0.5),
            "p95_ms": percentile([r["total_ms"] for r in selected], 0.95),
            "median_packet_tokens": statistics.median(r["packet_tokens"] for r in selected),
            "median_body_tokens": statistics.median(r["body_tokens"] for r in selected),
            "missing": [r["id"] for r in full if not r["packet_complete"]],
        }
    return result


def concurrent(search, cases):
    result = []
    for concurrency in CONFIG["concurrency"]:
        rows = []
        started = time.perf_counter()

        def run(query, submitted):
            begin = time.perf_counter()
            r = search.run(query, "rrf")
            return {
                "id": query["id"],
                "request_ms": (time.perf_counter() - submitted) * 1000,
                "executor_wait_ms": (begin - submitted) * 1000,
                "service_ms": r["total_ms"],
                "embedding_wait_ms": r["stages"].get("embedding_wait_ms", 0),
                "packet_sha256": r["packet_sha256"],
            }

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(run, cases[i % len(cases)], time.perf_counter())
                for i in range(CONFIG["requests_per_concurrency"])
            ]
            rows = [f.result() for f in futures]
        elapsed = time.perf_counter() - started
        result.append(
            {
                "variant": "rrf",
                "concurrency": concurrency,
                "n": len(rows),
                "arrival": "All 40 submitted immediately; request latency includes executor queue.",
                "wall_seconds": elapsed,
                "requests_per_second": len(rows) / elapsed,
                "service_p50_ms": percentile([r["service_ms"] for r in rows], 0.5),
                "service_p95_ms": percentile([r["service_ms"] for r in rows], 0.95),
                "request_p50_ms": percentile([r["request_ms"] for r in rows], 0.5),
                "request_p95_ms": percentile([r["request_ms"] for r in rows], 0.95),
                "rows": rows,
            }
        )
    return result


def evaluate(output):
    for name in ["dev.json", "acceptance.json", "performance.json"]:
        if (output / name).exists():
            raise FileExistsError("benchmark outputs are immutable")
    manifest_path = DIRECTORY / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify(manifest)
    knowledge, queries = load_dataset(ROOT)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    began = time.perf_counter()
    import torch

    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    encoder = embedder(str(EMBEDDING_PATH))
    # An actual cold first query embedding, before any corpus encoding or warmup.
    cold_begin = time.perf_counter()
    _, cold_profile = encoder.embed_profiled([queries["cases"][0]["query"]])
    cold_ms = (time.perf_counter() - cold_begin) * 1000
    token_begin = time.perf_counter()
    tokenizer = load_tokenizer()
    tokenizer_ms = (time.perf_counter() - token_begin) * 1000
    index_begin = time.perf_counter()
    vectors = encoder.embed([d["text"] for d in knowledge["documents"]])
    index_ms = (time.perf_counter() - index_begin) * 1000
    gpu_begin = time.perf_counter()
    worker = GPUWorker(GPU_PYTHON, MODEL, ROOT / "tmp/customer-rag-v5/gpu-worker.log")
    try:
        if any(worker.ready["environment"][k] != v for k, v in manifest["gpu_runtime"].items()):
            raise ValueError("frozen GPU environment differs")
        scorer = LocalReranker(worker, synchronize=worker.synchronize)
        max_pair = max(
            len(worker.tokenizer(q["query"], d["text"], truncation=False)["input_ids"])
            for q in queries["cases"]
            for d in knowledge["documents"]
        )
        if max_pair > 512:
            raise ValueError("CE would truncate")
        gpu_load_ms = (time.perf_counter() - gpu_begin) * 1000
        for _ in range(CONFIG["gpu_warmup"]):
            scorer.rank("退款条件", hits(knowledge, "M-1001", "2026.10")[:1])
        search = Search(knowledge, encoder, vectors, scorer, tokenizer)
        # Warm lexical initialization and complete pipeline once, recorded separately.
        warm = search.run(queries["cases"][0], "rrf")
        dev = []
        for q in queries["cases"]:
            if q["split"] != "dev":
                continue
            dev.extend(search.run(q, variant) for variant in VARIANTS)
            print("dev", q["id"], flush=True)
        dev_summary = summarize(dev)
        priority = ["rrf", "bm25", "dense", "rrf-linked", "union-ce", "all-ce"]
        chosen = min(priority, key=lambda v: (-dev_summary[v]["complete_at_3_n"], priority.index(v)))
        write_new(
            output / "dev.json",
            {
                "manifest_sha256": digest(manifest_path),
                "summary": dev_summary,
                "selection_before_acceptance": chosen,
                "rows": dev,
            },
        )
        acceptance = []
        for q in queries["cases"]:
            if q["split"] != "acceptance":
                continue
            acceptance.extend(search.run(q, variant) for variant in VARIANTS)
            print("acceptance", q["id"], flush=True)
        write_new(
            output / "acceptance.json",
            {
                "manifest_sha256": digest(manifest_path),
                "dev_result_sha256": digest(output / "dev.json"),
                "selection_frozen_before_acceptance": chosen,
                "summary": summarize(acceptance),
                "rows": acceptance,
            },
        )
        performance = concurrent(search, [q for q in queries["cases"] if q["split"] == "dev"])
        write_new(
            output / "performance.json",
            {
                "manifest_sha256": digest(manifest_path),
                "gpu_environment": worker.request("stats"),
                "main_environment": {
                    "python": sys.version.split()[0],
                    "torch": torch.__version__,
                    "sentence_transformers": version("sentence-transformers"),
                    "threads": 4,
                },
                "cold_first_query_embedding_ms": cold_ms,
                "cold_first_query_profile": cold_profile,
                "tokenizer_load_ms": tokenizer_ms,
                "offline_corpus_embedding_ms": index_ms,
                "gpu_worker_start_ms": gpu_load_ms,
                "gpu_model_load_ms": worker.ready["model_load_including_import_ms"],
                "warm_first_rrf": warm,
                "max_ce_pair_tokens": max_pair,
                "total_experiment_seconds": time.perf_counter() - began,
                "scope": CONFIG["scope"],
                "concurrency": performance,
                "new_chat_api_calls": 0,
                "production_writes": 0,
            },
        )
        verify(manifest)
    finally:
        worker.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.freeze:
        freeze()
    elif args.output:
        evaluate(args.output)
    else:
        parser.error("choose --freeze or --output")
