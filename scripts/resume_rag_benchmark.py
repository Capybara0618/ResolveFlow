"""Five fixed retrieval pipelines; full-span evidence scoring and online query timings."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from resolveflow.policies.retrieval import embedder

from scripts.policy_chunks import load_draft, representations
from scripts.policy_codex_review import resolve_atom, validate_labels
from scripts.policy_context_packet_eval import catalog, select_contexts
from scripts.policy_query_eval import coverage, load_inputs, rank
from scripts.policy_structure_candidates import rrf
from scripts.policy_structure_eval import inherited_probes, read

VARIANTS = ("A", "B", "C", "D", "E")


def evidence_scores(ranked, sets, k):
    hits = [c for c, _ in ranked[:k]]
    fractions = [
        sum(coverage(hits, a) for a in group) / len(group) for group in sets if group
    ]
    first = next(
        (
            i
            for i, (c, _) in enumerate(ranked[:k], 1)
            if any(coverage([c], a) for group in sets for a in group)
        ),
        None,
    )
    return {
        "recall": max(fractions, default=0.0),
        "complete": any(f == 1 for f in fractions),
        "mrr": 1 / first if first else 0.0,
    }


def percentile(values, fraction):
    values = sorted(values)
    return values[min(len(values) - 1, int((len(values) - 1) * fraction))]


def summarize(rows, timings):
    result = {}
    for variant, cohort in sorted({(r["variant"], r["cohort"]) for r in rows}):
        selected = [r for r in rows if (r["variant"], r["cohort"]) == (variant, cohort)]
        full = [r for r in selected if r["answerability"] == "ANSWERABLE"]
        ms = [
            r["elapsed_ms"]
            for r in timings
            if (r["variant"], r["cohort"]) == (variant, cohort)
        ]
        summary = {
            "query_n": len(selected),
            "answerable_n": len(full),
            "timing_n": len(ms),
            "mean_ms": statistics.mean(ms) if ms else None,
            "p95_ms": percentile(ms, 0.95) if ms else None,
        }
        for k in (3, 5):
            summary[f"recall_at_{k}"] = statistics.mean(
                r["scores"][str(k)]["recall"] for r in full
            )
            summary[f"complete_at_{k}_n"] = sum(
                r["scores"][str(k)]["complete"] for r in full
            )
            summary[f"mrr_at_{k}"] = statistics.mean(
                r["scores"][str(k)]["mrr"] for r in full
            )
            parents = [r.get("parent_complete", {}).get(str(k)) for r in full]
            summary[f"parent_complete_at_{k}_n"] = sum(v is True for v in parents)
        result[f"{variant}:{cohort}"] = summary
    return result


def save(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".partial")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for attempt in range(8):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.1 * (attempt + 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reranker", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("new measurements require a new report path")
    import torch
    from sentence_transformers import CrossEncoder

    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    _, originals, _, body = load_inputs(
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
        (d["source_id"], d["raw_sha256"], b["id"]): representations(b)
        for d in draft["documents"]
        for b in d["blocks"]
    }
    labels = validate_labels(
        read(ROOT / "evals/rag-codex-review-v1/labels.json"), originals, index
    )
    probes = inherited_probes(
        originals, read(ROOT / "evals/rag-structure-v1/probes.json")
    )
    encoder = embedder()
    reranker = CrossEncoder(str(args.reranker), device="cpu", max_length=512)
    encoder.embed([originals[0]["query"]])
    truncated = []

    def rerank(case, ranked):
        candidates = ranked[:20]
        pairs = [(case["query"], c["retrieval_text"]) for c, _ in candidates]
        lengths = [
            len(reranker.tokenizer(a, b, truncation=False)["input_ids"])
            for a, b in pairs
        ]
        if any(n > 512 for n in lengths):
            truncated.append({"query": case["id"], "lengths": lengths})
        scores = reranker.predict(pairs, batch_size=8, show_progress_bar=False)
        return sorted(
            [(c, float(s)) for (c, _), s in zip(candidates, scores, strict=True)],
            key=lambda pair: (-pair[1], pair[0]["id"]),
        )

    def retrieve(case, variant):
        vector = (
            encoder.embed([case["query"]])[0] if variant in ("B", "D", "E") else None
        )
        if variant == "B":
            return rank(case, body, "dense", vector)
        lexical = rank(case, body, "bm25")
        if variant == "A":
            return lexical
        if variant == "C":
            return rerank(case, lexical)
        fused = rrf(rank(case, body, "dense", vector), lexical, 20, 60)[:20]
        return fused if variant == "D" else rerank(case, fused)

    inputs = [
        "scripts/resume_rag_benchmark.py",
        "scripts/policy_query_eval.py",
        "scripts/policy_structure_candidates.py",
        "scripts/policy_context_packet_eval.py",
        "scripts/policy_codex_review.py",
        "evals/policy-query-v1/queries.json",
        "evals/rag-codex-review-v1/labels.json",
        "evals/rag-structure-v1/probes.json",
        "tmp/policy-documents-v1/children-final.json",
        "tmp/policy-documents-v1/drafts-audited.json",
    ]
    report = {
        "version": "resume-rag-v1",
        "state": "RUNNING",
        "rows": [],
        "timings": [],
        "inputs": {
            p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in inputs
        },
        "config": {
            "variants": VARIANTS,
            "candidates": 20,
            "rrf_k": 60,
            "batch_size": 8,
            "max_length": 512,
            "device": "cpu",
            "dtype": "float32",
            "torch_threads": 4,
            "timing_rounds": 3,
            "warmup_per_group": 5,
            "body_chunks": len(body["chunks"]),
            "reranker_snapshot": args.reranker.name,
        },
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "torch": torch.__version__,
        },
        "latency_scope": "query encoding, scoped ranking, fusion, reranker tokenization and inference; excludes model loading and parent expansion",
        "label_origin": "CODEX_REVIEW",
    }
    save(args.output, report)
    for variant in VARIANTS:
        for case in originals[:5]:
            retrieve(case, variant)
        print(f"warmup {variant} done", flush=True)
    for round_id in range(3):
        order = VARIANTS[round_id:] + VARIANTS[:round_id]
        for variant in order:
            for case in originals + (probes if round_id == 0 else []):
                started = time.perf_counter()
                ranked = retrieve(case, variant)
                elapsed = (time.perf_counter() - started) * 1000
                cohort = "probe" if "based_on" in case else "original"
                report["timings"].append(
                    {
                        "variant": variant,
                        "cohort": cohort,
                        "round": round_id,
                        "query_id": case["id"],
                        "elapsed_ms": elapsed,
                    }
                )
                if round_id == 0:
                    label = labels[case.get("based_on", case["id"])]
                    sets = [
                        [resolve_atom(ref, case, index) for ref in group]
                        for group in label["evidence_sets"]
                    ]
                    parents = {}
                    for k in (3, 5):
                        selected = select_contexts(
                            case, [c for c, _ in ranked[:k]], body, index, 8000
                        )
                        keys = set(selected.block_keys)
                        parents[str(k)] = any(
                            all(
                                (a["source_id"], a["raw_sha256"], a["block_id"]) in keys
                                for a in group
                            )
                            for group in sets
                            if group
                        )
                    report["rows"].append(
                        {
                            "query_id": case["id"],
                            "variant": variant,
                            "cohort": cohort,
                            "answerability": label["answerability"],
                            "scores": {
                                str(k): evidence_scores(ranked, sets, k) for k in (3, 5)
                            },
                            "mrr_full": evidence_scores(ranked, sets, len(ranked))[
                                "mrr"
                            ],
                            "parent_complete": parents,
                            "ranking": [{"id": c["id"], "score": s} for c, s in ranked],
                        }
                    )
                save(args.output, report)
            print(f"round={round_id + 1} variant={variant} completed", flush=True)
    report.update(
        state="COMPLETED",
        summaries=summarize(report["rows"], report["timings"]),
        truncated_requests=truncated,
    )
    for p, expected in report["inputs"].items():
        if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != expected:
            raise ValueError(f"measurement input changed during execution: {p}")
    save(args.output, report)
    print(json.dumps(report["summaries"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
