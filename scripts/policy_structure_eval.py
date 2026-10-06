"""Frozen local BGE/lexical/structure comparison with source evidence; no chat API or production writes."""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from resolveflow.harness.context import canonical_json  # noqa: E402
from resolveflow.harness.token_counting import load_tokenizer  # noqa: E402
from resolveflow.policies.retrieval import embedder  # noqa: E402
from scripts.policy_chunks import load_draft, representations  # noqa: E402
from scripts.policy_codex_review import resolve_atom, sufficiently_covered, validate_labels  # noqa: E402
from scripts.policy_context_packet_eval import catalog, select_contexts  # noqa: E402
from scripts.policy_documents import digest  # noqa: E402
from scripts.policy_query_eval import coverage, load_inputs, rank  # noqa: E402
from scripts.policy_structure_candidates import (  # noqa: E402
    aggregate,
    atomic_bundle,
    local_packet,
    rrf,
    selected_spans,
    source_metadata,
)


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_freeze(manifest: dict) -> None:
    for name, sha in manifest["inputs"].items():
        if digest((ROOT / name).read_bytes()) != sha:
            raise ValueError(f"frozen comparison input differs: {name}")


def inherited_probes(cases: list, probes: list) -> list:
    by_id = {q["id"]: q for q in cases}
    if len({p["id"] for p in probes}) != len(probes) or {p["id"] for p in probes} & set(by_id):
        raise ValueError("duplicate probe identity")
    result = []
    for probe in probes:
        case = copy.deepcopy(by_id[probe["based_on"]])
        case.update(
            id=probe["id"],
            query=probe["query"],
            based_on=probe["based_on"],
            origin={"kind": "CODEX_SYNTHETIC_PARAPHRASE_NOT_BLIND", "frozen_before_measurement": True},
        )
        result.append(case)
    return result


def metrics(rows: list) -> list:
    result = []
    for cohort in ("original", "probe"):
        variants = list(dict.fromkeys(r["variant"] for r in rows))
        for variant in variants:
            for k in (2, 5):
                selected = [r for r in rows if (r["cohort"], r["variant"], r["k"]) == (cohort, variant, k)]
                full = [r for r in selected if r["answerability"] == "ANSWERABLE"]
                result.append(
                    {
                        "cohort": cohort,
                        "variant": variant,
                        "k": k,
                        "queries": len(selected),
                        "answerability": dict(Counter(r["answerability"] for r in selected)),
                        "answerable_n": len(full),
                        "raw_child_direct": sum(r["raw_child_direct"] for r in full),
                        "admitted_group_direct": sum(r["admitted_group_direct"] for r in full),
                        "authority_expanded": sum(r["authority_expanded"] for r in full),
                        "local_packet_covered": sum(r["local_packet_covered"] for r in full),
                        "mean_authority_chars": round(sum(r["authority_chars"] for r in full) / len(full), 2),
                        "mean_authority_tokens": round(sum(r["authority_tokens"] for r in full) / len(full), 2),
                        "mean_local_chars": round(sum(r["local_chars"] for r in full) / len(full), 2),
                        "mean_local_tokens": round(sum(r["local_tokens"] for r in full) / len(full), 2),
                        "mean_ranking_ms": round(sum(r["ranking_ms"] for r in selected) / len(selected), 3),
                        "authority_missing": [r["query_id"] for r in full if not r["authority_expanded"]],
                        "local_missing": [r["query_id"] for r in full if not r["local_packet_covered"]],
                    }
                )
    return result


def evaluate(manifest: dict, cache: dict) -> dict:
    """Use a saved vector cache to recompute all ranks and source packets without loading an encoder."""
    verify_freeze(manifest)
    _, cases, _, body = load_inputs(
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
    labels = validate_labels(read(ROOT / "evals/rag-codex-review-v1/labels.json"), cases, index)
    probes = inherited_probes(cases, read(ROOT / "evals/rag-structure-v1/probes.json"))
    all_cases = cases + probes
    if cache["queries"] != [{key: q[key] for key in ("id", "query", "subject", "scope")} for q in all_cases]:
        raise ValueError("query-vector cache input differs")
    if cache["config"] != manifest["config"]:
        raise ValueError("vector cache config differs")
    path = read(ROOT / "tmp/policy-documents-v1/representation-v1.json")["variants"]["title_path"]
    bundles = {"body": body, "path": path, "atomic": cache["atomic"]}
    expected_atomic_texts = [c["retrieval_text"] for c in cache["atomic"]["chunks"]]
    if digest(canonical_json(expected_atomic_texts).encode()) != cache["atomic_texts_sha256"]:
        raise ValueError("atomic vector cache text hash differs")
    for vector in cache["vectors"] + [c["embedding"] for c in cache["atomic"]["chunks"]]:
        if len(vector) != 512 or not all(math.isfinite(v) for v in vector) or not any(vector):
            raise ValueError("invalid cached query/atomic vector")
    baseline = {
        (r["query_id"], r["method"]): r
        for r in read(ROOT / "reports/policy-document-ingestion/query-baseline.json")["results"]
    }
    tokenizer = load_tokenizer()
    rows, rankings = [], []
    config = manifest["config"]
    for q, vector in zip(all_cases, cache["vectors"], strict=True):
        label = labels[q.get("based_on", q["id"])]
        sets = [[resolve_atom(ref, q, index) for ref in group] for group in label["evidence_sets"]]
        base_rankings = {}
        times = {}
        for name, bundle in bundles.items():
            for method in ("dense", "bm25"):
                if name == "path" and method == "bm25":
                    continue
                started = time.perf_counter()
                base_rankings[(name, method)] = rank(q, bundle, method, vector)
                times[(name, method)] = (time.perf_counter() - started) * 1000
        for variant in config["variants"]:
            bundle = bundles[variant["bundle"]]
            if variant["method"] == "rrf":
                started = time.perf_counter()
                dense = aggregate(base_rankings[(variant["bundle"], "dense")], "atom", bundle)
                lexical = aggregate(base_rankings[(variant["bundle"], "bm25")], "atom", bundle)
                ranked = rrf(dense, lexical, config["rrf_window"], config["rrf_constant"])
                ms = times[(variant["bundle"], "dense")] + times[(variant["bundle"], "bm25")]
                ms += (time.perf_counter() - started) * 1000
            else:
                ranked = aggregate(base_rankings[(variant["bundle"], variant["method"])], variant["grouping"], bundle)
                ms = times[(variant["bundle"], variant["method"])]
            if variant["name"] in {"body-dense", "body-bm25"} and "based_on" not in q:
                old = baseline[(q["id"], variant["method"])]["at_k"]["5"]["hits"]
                if [c["id"] for c, _ in ranked[:5]] != [h["chunk_id"] for h in old] or any(
                    not math.isclose(s, h["score"], abs_tol=1e-6, rel_tol=0)
                    for (_, s), h in zip(ranked[:5], old, strict=True)
                ):
                    raise ValueError("old BODY baseline rank/score not reproduced")
            first = {
                "raw_child_direct": None,
                "admitted_group_direct": None,
                "authority_expanded": None,
                "local_packet_covered": None,
            }
            for count in range(1, 6):
                hits = [c for c, _ in ranked[:count]]
                admitted = selected_spans(hits, bundle, variant["grouping"])
                authority = select_contexts(q, admitted, bundle, index, config["context_chars"])
                local = local_packet(q, admitted, bundle, draft, config["context_chars"])
                keys, local_keys = set(authority.block_keys), set(local["block_keys"])
                scores = {
                    "raw_child_direct": sufficiently_covered(sets, lambda a, hits=hits: coverage(hits, a)),
                    "admitted_group_direct": sufficiently_covered(
                        sets, lambda a, admitted=admitted: coverage(admitted, a)
                    ),
                    "authority_expanded": sufficiently_covered(
                        sets, lambda a, keys=keys: (a["source_id"], a["raw_sha256"], a["block_id"]) in keys
                    ),
                    "local_packet_covered": sufficiently_covered(
                        sets,
                        lambda a, local_keys=local_keys: (a["source_id"], a["raw_sha256"], a["block_id"]) in local_keys,
                    ),
                }
                for metric, passed in scores.items():
                    if passed and first[metric] is None:
                        first[metric] = count
                if count not in (2, 5):
                    continue
                authority_text = "\n\n".join(bundle["contexts"][cid]["text"] for cid in authority.context_ids)
                rows.append(
                    {
                        "query_id": q["id"],
                        "based_on": q.get("based_on"),
                        "variant": variant["name"],
                        "k": count,
                        "cohort": "probe" if "based_on" in q else "original",
                        "answerability": label["answerability"],
                        **scores,
                        "authority_chars": authority.exported_chars,
                        "authority_tokens": len(tokenizer.encode(authority_text).ids),
                        "authority_blocks": len(keys),
                        "authority_selection_sha256": authority.fingerprint,
                        "authority_blocked": list(authority.blocked_ids),
                        "local_chars": local["exported_chars"],
                        "local_tokens": len(tokenizer.encode(local["text"]).ids),
                        "local_blocks": len(local_keys),
                        "local_text_sha256": local["text_sha256"],
                        "local_complete_policy_guaranteed": False,
                        "local_blocked": local["blocked_ids"],
                        "local_refs": [
                            {"source_id": key[0], "raw_sha256": key[1], "block_id": key[2]}
                            for key in sorted(local_keys)
                        ],
                        "local_missing_by_alternative": [
                            [
                                a["block_id"]
                                for a in group
                                if (a["source_id"], a["raw_sha256"], a["block_id"]) not in local_keys
                            ]
                            for group in sets
                        ],
                        "ranking_ms": round(ms, 4),
                        "admitted_body_spans": len(admitted),
                        "hits": [
                            {
                                "id": c["id"],
                                "source_id": c["source_id"],
                                "context_id": c["context_id"],
                                "group_id": c.get("group_id"),
                                "score": s,
                                "body_fragments": [
                                    {k: f.get(k) for k in ("block_id", "table_row", "text_range")}
                                    for f in c["fragments"]
                                ],
                            }
                            for c, s in ranked[:count]
                        ],
                    }
                )
            rankings.append({"query_id": q["id"], "variant": variant["name"], "first_sufficient_within_top5": first})
    verify_freeze(manifest)
    return {
        "version": "rag-structure-comparison-v1",
        "origin": "CODEX_REVIEW",
        "blind_review": False,
        "new_chat_api_calls": 0,
        "production_writes": 0,
        "baseline_reproduced": True,
        "query_changed": False,
        "probe_origin": "CODEX_SYNTHETIC_PARAPHRASE_NOT_BLIND",
        "new_query_embedding": "PINNED_LOCAL_BGE_NOT_LLM_QUERY_REWRITE",
        "config": config,
        "inputs": manifest["inputs"],
        "encoder": body["encoder"],
        "atomic_children": len(cache["atomic"]["chunks"]),
        "atomic_heading_audits": cache["heading_audits"],
        "atomic_max_encoder_tokens": max(c["encoder_tokens"] for c in cache["atomic"]["chunks"]),
        "source_metadata": source_metadata(draft),
        "semantic_decline_accuracy": None,
        "latency_scope": "ranking only; excludes query encoding, corpus build, evidence serialization and DB/network",
        "query_encode_batch_seconds": cache["query_encode_batch_seconds"],
        "atomic_encode_batch_seconds": cache["atomic_encode_batch_seconds"],
        "token_scope": "pinned DeepSeek tokenizer over returned original text; not full request/provider usage",
        "summaries": metrics(rows),
        "results": rows,
        "rankings": rankings,
    }


def prepare(manifest: dict) -> dict:
    verify_freeze(manifest)
    _, cases, _, original = load_inputs(
        ROOT / "evals/policy-query-v1",
        ROOT / "tmp/policy-documents-v1/children-final.json",
        ROOT / "tmp/policy-documents-v1/drafts-audited.json",
    )
    draft = read(ROOT / "tmp/policy-documents-v1/drafts-audited.json")
    cases += inherited_probes(cases, read(ROOT / "evals/rag-structure-v1/probes.json"))
    local = embedder()
    if original["encoder"] != {"model": local.model, "revision": local.revision, "dimension": local.dimension}:
        raise ValueError("comparison encoder differs from frozen baseline")
    bundle, headings = atomic_bundle(draft, original, local._encoder())
    started = time.perf_counter()
    vectors = local.embed([q["query"] for q in cases])
    query_seconds = time.perf_counter() - started
    started = time.perf_counter()
    texts = [c["retrieval_text"] for c in bundle["chunks"]]
    embeddings = local.embed(texts)
    atomic_seconds = time.perf_counter() - started
    for chunk, vector in zip(bundle["chunks"], embeddings, strict=True):
        chunk["embedding"] = vector
    return {
        "config": manifest["config"],
        "queries": [{key: q[key] for key in ("id", "query", "subject", "scope")} for q in cases],
        "atomic": bundle,
        "heading_audits": headings,
        "vectors": vectors,
        "atomic_texts_sha256": digest(canonical_json(texts).encode()),
        "query_encode_batch_seconds": query_seconds,
        "atomic_encode_batch_seconds": atomic_seconds,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "evals/rag-structure-v1/manifest.json")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse-cache", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("comparison output is immutable")
    if not args.cache.resolve().is_relative_to((ROOT / "tmp").resolve()):
        raise ValueError("source text/vector cache must stay in ignored tmp")
    manifest = read(args.manifest)
    if args.reuse_cache:
        cache = read(args.cache)
    else:
        if args.cache.exists():
            raise FileExistsError("comparison cache is immutable")
        cache = prepare(manifest)
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        args.cache.write_text(json.dumps(cache, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    report = evaluate(manifest, cache)
    report.update(
        cache_sha256=digest(args.cache.read_bytes()),
        manifest_sha256=digest(args.manifest.read_bytes()),
        runner_sha256=digest(Path(__file__).read_bytes()),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report["summaries"], ensure_ascii=False))


if __name__ == "__main__":
    main()
