"""Pinned, offline Cross-Encoder experiment: RRF truncation versus candidate union versus small full corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from resolveflow.policies.index import PolicyHit, PolicyIndex  # noqa: E402
from resolveflow.policies.retrieval import bm25_scores, embedder  # noqa: E402
from resolveflow.support.retrieval import reciprocal_rank_fusion  # noqa: E402
from scripts.customer_rag_diagnostic import ReadOnlyDatabase, snapshot  # noqa: E402
from scripts.evaluation.customer_rerank import LocalReranker, candidate_union  # noqa: E402
from scripts.policy_chunks import load_draft, representations  # noqa: E402
from scripts.policy_codex_review import (  # noqa: E402
    resolve_atom,
    sufficiently_covered,
    validate_fragments,
    validate_labels,
)
from scripts.policy_context_packet_eval import catalog  # noqa: E402
from scripts.policy_query_eval import coverage, load_inputs, rank  # noqa: E402
from scripts.policy_structure_eval import inherited_probes  # noqa: E402

MANIFEST = ROOT / "evals/customer-rag-v3/manifest.json"
REVISION = "2cfc18c9415c912f9d8155881c133215df768a70"
MODEL = Path.home() / ".cache/huggingface/hub/models--BAAI--bge-reranker-base/snapshots" / REVISION
INPUTS = [
    "evals/customer-rag-v1/queries.json",
    "reports/customer-agent-live-v1/runtime-results.json",
    "reports/customer-rag-v2/candidates.json",
    "reports/customer-rag-v2/external-final.json",
    "evals/policy-query-v1/manifest.json",
    "evals/policy-query-v1/queries.json",
    "evals/policy-query-v1/evidence.json",
    "evals/rag-codex-review-v1/labels.json",
    "evals/rag-structure-v1/probes.json",
    "tmp/policy-documents-v1/children-final.json",
    "tmp/policy-documents-v1/drafts-audited.json",
    "tmp/rag-structure-v1/vectors-v1.json",
    "agent/uv.lock",
    "agent/src/resolveflow/policies/index.py",
    "agent/src/resolveflow/policies/retrieval.py",
    "agent/src/resolveflow/policies/child_index.py",
    "agent/src/resolveflow/support/retrieval.py",
    "scripts/evaluation/customer_rerank.py",
    "scripts/customer_rag_rerank.py",
    "scripts/policy_query_eval.py",
    "scripts/policy_codex_review.py",
    "scripts/policy_chunks.py",
    "scripts/policy_context_packet_eval.py",
    "scripts/policy_structure_eval.py",
]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def freeze(manifest_path=MANIFEST, device="cpu"):
    if manifest_path.exists():
        raise FileExistsError("experiment manifest is immutable")
    result = {
        "version": "customer-rag-union-rerank-v1",
        "not_holdout": True,
        "new_chat_api_calls": 0,
        "query_changed": False,
        "model": {
            "id": "BAAI/bge-reranker-base",
            "revision": REVISION,
            "files": {p.name: digest(p) for p in sorted(MODEL.iterdir()) if p.is_file()},
        },
        "inputs": {p: digest(ROOT / p) for p in INPUTS},
        "config": {
            "candidate_per_route": 5,
            "rrf_constant": 60,
            "final_k": [3, 5],
            "device": device,
            "threads": 4,
            "interop_threads": 1,
            "precision": "float32",
            "batch_size": 8,
            "max_pair_tokens": 512,
            "truncation": "refuse",
            "warmup_passes": 3,
            "timing_rounds": 2,
            "synchronize_cuda_timing": device.startswith("cuda"),
            "tf32": False,
            "variants": ["fields-rrf", "rrf-top5-ce", "union-ce", "all-rules-ce-mall-only"],
        },
        "decision": (
            "Compare quality and latency before selecting any production change. "
            "Keep regressions. External labels remain CODEX_REVIEW."
        ),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def verify(manifest):
    for p, sha in manifest["inputs"].items():
        if digest(ROOT / p) != sha:
            raise ValueError("experiment input changed: " + p)
    for p, sha in manifest["model"]["files"].items():
        if digest(MODEL / p) != sha:
            raise ValueError("model artifact changed: " + p)


def external_tasks():
    _, cases, _, bundle = load_inputs(
        ROOT / "evals/policy-query-v1",
        ROOT / "tmp/policy-documents-v1/children-final.json",
        ROOT / "tmp/policy-documents-v1/drafts-audited.json",
    )
    draft = load_draft(
        ROOT / "tmp/policy-documents-v1/drafts-audited.json",
        ROOT / "reports/policy-document-ingestion/draft-summary.json",
    )
    index = catalog(draft)
    index["representations"] = {
        (d["source_id"], d["raw_sha256"], b["id"]): representations(b) for d in draft["documents"] for b in d["blocks"]
    }
    labels = validate_labels(
        json.loads((ROOT / "evals/rag-codex-review-v1/labels.json").read_text(encoding="utf-8")), cases, index
    )
    validate_fragments(bundle["chunks"], index)
    probes = json.loads((ROOT / "evals/rag-structure-v1/probes.json").read_text(encoding="utf-8"))
    cases += inherited_probes(cases, probes)
    cache = json.loads((ROOT / "tmp/rag-structure-v1/vectors-v1.json").read_text(encoding="utf-8"))
    if cache["queries"] != [{k: q[k] for k in ("id", "query", "subject", "scope")} for q in cases]:
        raise ValueError("cached query vector inputs differ")
    for case, vector in zip(cases, cache["vectors"], strict=True):
        dense = rank(case, bundle, "dense", vector)
        body = rank(case, bundle, "bm25")
        chunks = [c for c, _ in dense]
        titles = bm25_scores([" > ".join(c["section_path"]) for c in chunks], case["query"])
        title = sorted(zip(chunks, titles, strict=True), key=lambda pair: (-pair[1], pair[0]["id"]))
        by_id = {c["id"]: c for c in chunks}
        manifest_hash = hashlib.sha256(json.dumps(case["scope"], sort_keys=True).encode()).hexdigest()
        routes = []
        for route in [dense, [(c, s) for c, s in body if s > 0], [(c, s) for c, s in title if s > 0]]:
            routes.append(
                [
                    PolicyHit(
                        bundle_id=c["source_id"],
                        merchant_id=case["subject"],
                        version=c["raw_sha256"],
                        manifest_hash=manifest_hash,
                        rule_id=c["id"],
                        chunk_id=c["id"],
                        content_hash=hashlib.sha256(c["retrieval_text"].encode()).hexdigest(),
                        title=" > ".join(c["section_path"]),
                        text=c["retrieval_text"],
                        score=s,
                        path="dense",
                    )
                    for c, s in route[:5]
                ]
            )
        label = labels[case.get("based_on", case["id"])]
        sets = [[resolve_atom(ref, case, index) for ref in group] for group in label["evidence_sets"]]
        yield {
            "id": case["id"],
            "cohort": "external-probe" if "based_on" in case else "external-original",
            "query": case["query"],
            "routes": routes,
            "all": None,
            "answerability": label["answerability"],
            "sets": sets,
            "by_id": by_id,
            "scoped_corpus_count": len(chunks),
        }


def mall_tasks(database, encoder):
    plan = json.loads((ROOT / "evals/customer-rag-v1/queries.json").read_text(encoding="utf-8"))
    saved = json.loads((ROOT / "reports/customer-agent-live-v1/runtime-results.json").read_text(encoding="utf-8"))
    runs = {r["case"]: r for r in saved["runs"]}
    index = PolicyIndex(database)
    for case in plan["cases"]:
        run = runs[case["source_case"]]
        request = run["run"]["input_json"]
        manifest = request["context"]["policy_manifest"]
        query = case.get("query") or next(
            c["request_json"]["arguments"]["query"]
            for c in run["calls"]
            if c["request_json"].get("name") == "search_policy"
        )
        scope = dict(
            merchant_id=manifest["merchant_id"],
            bundle_ids=manifest["bundle_ids"],
            manifest_hash=manifest["manifest_hash"],
            generation_ids=run["run"]["generations_json"],
            query=query,
            top_k=5,
        )
        routes = []
        for path, field in [("dense", "body"), ("bm25", "body"), ("bm25", "title")]:
            hits = index.search(**scope, path=path, lexical_field=field, embedder=encoder if path == "dense" else None)
            routes.append(hits if path == "dense" else [h for h in hits if h.score > 0])
        # A successful dense search already validates all stored parents/children. Read that exact scoped set.
        parents = index._chunks_for(
            manifest["bundle_ids"],
            manifest["manifest_hash"],
            generation_ids=list(run["run"]["generations_json"].values()),
        )
        all_rules = [
            PolicyHit(**{k: v for k, v in asdict(row).items() if k != "embedding"}, path="dense") for row in parents
        ]
        yield {
            "id": case["id"],
            "cohort": "mall-saved-live" if case["kind"] == "saved-live" else "mall-probe",
            "query": query,
            "routes": routes,
            "all": all_rules,
            "answerability": "ANSWERABLE",
            "required": case["required_rules"],
            "scoped_corpus_count": len(parents),
            "scope": scope,
        }


def covered(task, hits):
    if "required" in task:
        return set(task["required"]) <= {h.rule_id for h in hits}
    chunks = [task["by_id"][h.chunk_id] for h in hits]
    return sufficiently_covered(task["sets"], lambda atom: coverage(chunks, atom))


def summarize(rows):
    result = {}
    for cohort in sorted({r["cohort"] for r in rows}):
        for variant in sorted({r["variant"] for r in rows if r["cohort"] == cohort}):
            selected = [r for r in rows if r["cohort"] == cohort and r["variant"] == variant]
            full = [r for r in selected if r["answerability"] == "ANSWERABLE"]
            baseline = {r["id"]: r for r in rows if r["cohort"] == cohort and r["variant"] == "fields-rrf"}
            result[cohort + "/" + variant] = {
                "query_n": len(selected),
                "answerable_n": len(full),
                "candidate_complete_n": sum(bool(r["candidate_complete"]) for r in full),
                "complete_at_3_n": sum(bool(r["complete_at_3"]) for r in full),
                "complete_at_5_n": sum(bool(r["complete_at_5"]) for r in full),
                "regressions_at_3": [
                    r["id"] for r in full if baseline[r["id"]]["complete_at_3"] and not r["complete_at_3"]
                ],
                "regressions_at_5": [
                    r["id"] for r in full if baseline[r["id"]]["complete_at_5"] and not r["complete_at_5"]
                ],
                "median_incremental_ranking_ms": statistics.median(r["timing"]["elapsed_ms"] for r in selected),
                "median_pair_count": statistics.median(r["timing"]["pairs"] for r in selected),
            }
    return result


def evaluate(output, manifest_path=MANIFEST):
    if output.exists():
        raise FileExistsError("rerank output is immutable")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify(manifest)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    start = time.perf_counter()
    import torch
    from sentence_transformers import CrossEncoder

    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    device = manifest["config"]["device"]
    gpu = device.startswith("cuda")
    if gpu and not torch.cuda.is_available():
        raise RuntimeError("manifest requires CUDA; refusing silent CPU substitution")
    if gpu:
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
    model = CrossEncoder(str(MODEL), device=device, max_length=512, local_files_only=True)
    synchronize = (lambda: torch.cuda.synchronize(device)) if gpu else (lambda: None)
    synchronize()
    load_ms = (time.perf_counter() - start) * 1000
    scorer = LocalReranker(model, synchronize=synchronize)
    warmup = []
    warm = [PolicyHit("warm", "M", "v", "hash", "r", "c", "hash", "title", "售后条件需要核实。", 0.0, "dense")]
    for _ in range(3):
        _, profile = scorer.rank("退款条件", warm)
        warmup.append(profile)
    if gpu:
        torch.cuda.reset_peak_memory_stats(device)
    database = ReadOnlyDatabase("postgresql://agent:agent@127.0.0.1:55433/agent_db")
    rows = []
    try:
        before = snapshot(database)
        # Query encoder loading/initialization is not included in reranking-only latency.
        encoder = embedder(str(ROOT / "tmp/c071-probe/models/BAAI--bge-small-zh-v1.5"))
        tasks = list(external_tasks()) + list(mall_tasks(database, encoder))
        for task in tasks:
            routes = task["routes"]
            start = time.perf_counter()
            fused = reciprocal_rank_fusion(routes, top_k=5)
            fusion_ms = (time.perf_counter() - start) * 1000
            union = candidate_union(routes)
            candidates = {"rrf-top5-ce": fused, "union-ce": union}
            if task["all"] is not None:
                candidates["all-rules-ce"] = task["all"]
            rankings = {"fields-rrf": (fused, union, {"pairs": 0, "elapsed_ms": fusion_ms, "max_pair_tokens": 0})}
            for variant, items in candidates.items():
                # Two separately executed forward passes; no score reuse across algorithms/rounds.
                rounds = []
                first_ids = None
                for _ in range(2):
                    ranked, profile = scorer.rank(task["query"], items)
                    ids = [(h.bundle_id, h.chunk_id) for h in ranked]
                    if first_ids is not None and ids != first_ids:
                        raise ValueError("repeated inference changed the ranking")
                    first_ids = ids
                    rounds.append(profile)
                rankings[variant] = (
                    ranked,
                    items,
                    {**rounds[-1], "elapsed_ms": statistics.median(p["elapsed_ms"] for p in rounds), "rounds": rounds},
                )
            for variant, (ranked, pool, timing) in rankings.items():
                rows.append(
                    {
                        "id": task["id"],
                        "cohort": task["cohort"],
                        "variant": variant,
                        "query": task["query"],
                        "answerability": task["answerability"],
                        "scoped_corpus_count": task["scoped_corpus_count"],
                        "candidate_ids": [h.chunk_id for h in pool],
                        "candidate_complete": covered(task, pool),
                        "complete_at_3": covered(task, ranked[:3]),
                        "complete_at_5": covered(task, ranked[:5]),
                        "ranking": [
                            {
                                "bundle_id": h.bundle_id,
                                "chunk_id": h.chunk_id,
                                "rule_id": h.rule_id,
                                "content_hash": h.content_hash,
                                "score": h.score,
                            }
                            for h in ranked
                        ],
                        "timing": timing,
                    }
                )
            print(
                task["cohort"], task["id"], {k: [h.rule_id for h in v[0][:3]] for k, v in rankings.items()}, flush=True
            )
        after = snapshot(database)
        if before != after:
            raise RuntimeError("public witness changed")
        verify(manifest)
        result = {
            "version": "customer-rag-union-rerank-v1",
            "manifest_sha256": digest(manifest_path),
            "new_chat_api_calls": 0,
            "query_changed": False,
            "production_writes": 0,
            "new_model_weight_downloads": 0,
            "not_holdout": True,
            "model_load_including_import_ms": load_ms,
            "warmup": warmup,
            "environment": {
                "torch": torch.__version__,
                "sentence_transformers": version("sentence-transformers"),
                "device": str(next(model.model.parameters()).device),
                "dtype": str(next(model.model.parameters()).dtype),
                "threads": torch.get_num_threads(),
                "cuda_build": torch.version.cuda,
                "gpu_name": torch.cuda.get_device_name(device) if gpu else None,
                "gpu_capability": list(torch.cuda.get_device_capability(device)) if gpu else None,
                "peak_allocated_bytes": torch.cuda.max_memory_allocated(device) if gpu else None,
                "peak_reserved_bytes": torch.cuda.max_memory_reserved(device) if gpu else None,
                "synchronized_timing": gpu,
                "tf32": False,
            },
            "latency_scope": (
                "Incremental fusion or Cross-Encoder tokenization+inference only; "
                "excludes retrieval, query embedding, model loading. "
                "Two passes per case/variant; not an end-to-end SLA."
            ),
            "preservation": {"before": before, "after": after, "equal": before == after},
            "summary": summarize(rows),
            "rows": rows,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    finally:
        database.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--device", choices=["cpu", "cuda:0"], default="cpu", help="Used only when freezing a manifest")
    args = parser.parse_args()
    if args.freeze:
        freeze(args.manifest, args.device)
    elif args.output:
        evaluate(args.output, args.manifest)
    else:
        parser.error("select --freeze or --output")
