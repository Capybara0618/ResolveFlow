"""Compare the same field-fusion candidate on retained external policy snapshots and cached vectors."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from policy_chunks import load_draft, representations
from policy_codex_review import resolve_atom, sufficiently_covered, validate_fragments, validate_labels
from policy_context_packet_eval import catalog
from policy_query_eval import coverage, load_inputs, rank
from resolveflow.policies.index import PolicyHit
from resolveflow.policies.retrieval import bm25_scores
from resolveflow.support.retrieval import reciprocal_rank_fusion

ROOT = Path(__file__).resolve().parents[1]


def evaluate(output: Path):
    if output.exists():
        raise FileExistsError("external comparison is immutable")
    paths = [
        "evals/policy-query-v1/manifest.json",
        "evals/policy-query-v1/queries.json",
        "evals/policy-query-v1/evidence.json",
        "evals/rag-codex-review-v1/labels.json",
        "tmp/policy-documents-v1/children-final.json",
        "tmp/policy-documents-v1/drafts-audited.json",
        "tmp/rag-structure-v1/vectors-v1.json",
        "agent/src/resolveflow/support/retrieval.py",
    ]
    inputs = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    _, cases, _, bundle = load_inputs(ROOT / "evals/policy-query-v1", ROOT / paths[4], ROOT / paths[5])
    draft = load_draft(ROOT / paths[5], ROOT / "reports/policy-document-ingestion/draft-summary.json")
    index = catalog(draft)
    index["representations"] = {
        (d["source_id"], d["raw_sha256"], b["id"]): representations(b) for d in draft["documents"] for b in d["blocks"]
    }
    labels = validate_labels(json.loads((ROOT / paths[3]).read_text(encoding="utf-8")), cases, index)
    validate_fragments(bundle["chunks"], index)
    cache = json.loads((ROOT / paths[6]).read_text(encoding="utf-8"))
    vectors = {q["id"]: (q, v) for q, v in zip(cache["queries"], cache["vectors"], strict=True)}
    rows = []
    for case in cases:
        cached, vector = vectors[case["id"]]
        if cached != {k: case[k] for k in ("id", "query", "subject", "scope")}:
            raise ValueError("cached query vector input differs")
        dense = rank(case, bundle, "dense", vector)
        body = rank(case, bundle, "bm25")
        chunks = [c for c, _ in dense]
        title_scores = bm25_scores([" > ".join(c["section_path"]) for c in chunks], case["query"])
        title = sorted(zip(chunks, title_scores, strict=True), key=lambda pair: (-pair[1], pair[0]["id"]))
        manifest = hashlib.sha256(json.dumps(case["scope"], sort_keys=True).encode()).hexdigest()
        by_key = {}

        def convert(ranking, case=case, manifest=manifest, by_key=by_key):
            result = []
            for chunk, score in ranking[:5]:
                hit = PolicyHit(
                    bundle_id=chunk["source_id"],
                    merchant_id=case["subject"],
                    version=chunk["raw_sha256"],
                    manifest_hash=manifest,
                    rule_id=chunk["id"],
                    chunk_id=chunk["id"],
                    content_hash=hashlib.sha256(chunk["retrieval_text"].encode()).hexdigest(),
                    title=" > ".join(chunk["section_path"]),
                    text=chunk["retrieval_text"],
                    score=score,
                    path="dense",
                )
                by_key[(hit.bundle_id, hit.chunk_id)] = chunk
                result.append(hit)
            return result

        routes = {
            "dense": convert(dense),
            "body-bm25": convert([(c, s) for c, s in body if s > 0]),
            "title-bm25": convert([(c, s) for c, s in title if s > 0]),
        }
        for name, members in {
            "body-rrf": ["dense", "body-bm25"],
            "title-rrf": ["dense", "title-bm25"],
            "fields-rrf": ["dense", "body-bm25", "title-bm25"],
        }.items():
            routes[name] = reciprocal_rank_fusion([routes[m] for m in members], top_k=5)
        label = labels[case["id"]]
        sets = [[resolve_atom(ref, case, index) for ref in group] for group in label["evidence_sets"]]
        for name, hits in routes.items():
            for k in [3, 5]:
                selected = [by_key[(h.bundle_id, h.chunk_id)] for h in hits[:k]]
                rows.append(
                    {
                        "id": case["id"],
                        "variant": name,
                        "k": k,
                        "answerability": label["answerability"],
                        "direct_sufficient_evidence": sufficiently_covered(
                            sets, lambda atom, selected=selected: coverage(selected, atom)
                        ),
                        "hits": [h.chunk_id for h in hits[:k]],
                    }
                )
    summary = {}
    for name in routes:
        for k in [3, 5]:
            for state in ["ANSWERABLE", "PARTIAL"]:
                selected = [r for r in rows if r["variant"] == name and r["k"] == k and r["answerability"] == state]
                baseline = {r["id"]: r for r in rows if r["variant"] == "dense" and r["k"] == k}
                summary[f"{name}/top{k}/{state}"] = {
                    "n": len(selected),
                    "covered": sum(bool(r["direct_sufficient_evidence"]) for r in selected),
                    "regressions": [
                        r["id"]
                        for r in selected
                        if baseline[r["id"]]["direct_sufficient_evidence"] and not r["direct_sufficient_evidence"]
                    ],
                }
    for p, digest in inputs.items():
        if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != digest:
            raise ValueError("external inputs changed during comparison")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "version": "customer-rag-external-fields-v1",
                "inputs": inputs,
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "new_llm_calls": 0,
                "new_embedding_calls": 0,
                "production_writes": 0,
                "label_origin": "CODEX_REVIEW",
                "blind_review": False,
                "formal_accuracy": None,
                "candidate_k": 5,
                "rrf_constant": 60,
                "query_count": len(cases),
                "chunk_count": len(bundle["chunks"]),
                "summary": summary,
                "rows": rows,
                "note": (
                    "Direct complete block/row evidence coverage; no parent expansion. "
                    "Section paths differ from short business rule titles."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    evaluate(parser.parse_args().output)
