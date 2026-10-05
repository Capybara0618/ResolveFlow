"""Offline same-corpus experiments; synthetic diagnostics are not independent quality evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from resolveflow.policies import PolicyHit  # noqa: E402
from resolveflow.policies.retrieval import bm25_scores, cosine_similarity  # noqa: E402
from scripts.evaluation.dataset import ALIGNED_DATA, check_input, digest, read, validate  # noqa: E402
from scripts.evaluation.environment import environment  # noqa: E402

CHALLENGE = ROOT / "evals/rag-challenge-v1"
LIVE_REPORTS = (
    "live-dev-final.json", "live-test-final.json", "live-test-quality-negative.json",
)


def challenge():
    manifest = read("manifest.json", CHALLENGE)
    if manifest["base_manifest_sha256"] != digest(ALIGNED_DATA / "manifest.json"):
        raise ValueError("Challenge base dataset differs")
    for name, sha in manifest["files"].items():
        path = (CHALLENGE / name).resolve()
        if not path.is_relative_to(CHALLENGE) or digest(path) != sha:
            raise ValueError("Challenge frozen file mismatch")
    queries, gold = read("queries.json", CHALLENGE), read("gold.json", CHALLENGE)
    check_input(queries)
    if len({q["id"] for q in queries}) != len(queries) or set(gold) != {q["id"] for q in queries}:
        raise ValueError("Challenge ids/Gold differ")
    return queries, gold


def live_queries():
    """Already paid synthetic live decisions, not mock scripts or final-answer Gold."""
    cases = {case["id"]: case for case in read("agent/cases.json", ALIGNED_DATA)}
    probes = []
    for name in LIVE_REPORTS:
        path = ROOT / "reports/agent-investigation-batch3" / name
        report = json.loads(path.read_text(encoding="utf-8"))
        if (report["mode"] != "live" or report["synthetic"] is not True
                or report["manifest_hash"] != digest(ALIGNED_DATA / "manifest.json")):
            raise ValueError("Expected saved live report on the frozen synthetic dataset")
        for case in report["results"]:
            source = cases[case["id"]]
            for turn, request in enumerate(case.get("requests", []), 1):
                action = request.get("decision") or {}
                if action.get("kind") == "SEARCH_POLICY" and isinstance(action.get("query"), str):
                    probes.append({"id": f"{name}:{case['id']}:{turn}", "split": "live_query_probe",
                        "query": action["query"], "merchant_id": source["scope"]["merchant_id"],
                        "bundle_id": source["bundle_id"], "original_top_k": action.get("arguments", {}).get("top_k"),
                        "source_report": path.relative_to(ROOT).as_posix(), "source_sha256": digest(path)})
    check_input(probes)
    return probes


def metrics(hits, required):
    """All evidence rank distinguishes one good hit from complete supporting evidence."""
    ids = [hit.rule_id for hit in hits]
    if not required:
        return {"scored": True, "positive": False, "returned_candidates": bool(hits)}
    positions = [ids.index(rule) + 1 if rule in ids else len(hits) + 1 for rule in required]
    return {"scored": True, "positive": True,
        "complete_evidence_rr": 1 / max(positions) if all(rule in ids for rule in required) else 0.0,
        **{f"coverage_at_{k}": len(set(ids[:k]) & required) / len(required) for k in (1, 2, 5)},
        **{f"all_required_at_{k}": required <= set(ids[:k]) for k in (1, 2, 5)}}


def summarize(entries):
    groups = {}
    for entry in entries:
        groups.setdefault(f"{entry['representation']}/{entry['path']}/{entry['split']}", []).append(entry)
    summaries = {}
    for key, values in groups.items():
        positives = [v for v in values if v.get("positive")]
        summaries[key] = {"n": len(values), "positive_n": len(positives),
            "unscored_n": sum(not v["scored"] for v in values),
            "negative_n": sum(v["scored"] and v.get("positive") is False for v in values),
            "negative_with_candidates": sum(v.get("returned_candidates", False) for v in values),
            "filter_violations": sum(v["filter_violations"] for v in values),
            "mean_returned_chars": round(sum(v["returned_chars"] for v in values) / len(values), 2),
            **{f"mean_returned_chars_at_{k}": round(sum(v[f"returned_chars_at_{k}"] for v in values) / len(values), 2)
               for k in (1, 2, 5)},
            "mean_complete_evidence_rr": (round(sum(v["complete_evidence_rr"] for v in positives) / len(positives), 4)
                                           if positives else None),
            **{f"coverage_at_{k}": (round(sum(v[f"coverage_at_{k}"] for v in positives) / len(positives), 4)
                                    if positives else None) for k in (1, 2, 5)},
            **{f"all_required_at_{k}": sum(v[f"all_required_at_{k}"] for v in positives) for k in (1, 2, 5)}}
    return summaries


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Existing report is immutable; choose a new output")
    validate(ALIGNED_DATA)
    diagnostics, diagnostic_gold = challenge()
    probes = live_queries()
    queries = read("rag/queries.json", ALIGNED_DATA) + diagnostics + probes
    gold = {**read("gold/rag.json", ALIGNED_DATA), **diagnostic_gold}
    documents = {b["bundle_id"]: b for b in read("policies/bundles.json", ALIGNED_DATA)}
    for query in queries:
        bundle = documents[query["bundle_id"]]
        if query["merchant_id"] != bundle["merchant_id"]:
            raise ValueError("Query subject differs from the frozen policy")
        if not set(gold.get(query["id"], {}).get("must_rules", [])) <= {r["rule_id"] for r in bundle["rules"]}:
            raise ValueError("Gold refers to an absent rule")
    check_input(queries)
    report = {"synthetic": True, "external_llm_calls": 0, "blind": False,
        "gold_review": "PENDING_INDEPENDENT_REVIEW", "base_manifest_sha256": digest(ALIGNED_DATA / "manifest.json"),
        "challenge_manifest_sha256": digest(CHALLENGE / "manifest.json"),
        "query_sources": {"frozen": 60, "diagnostic": len(diagnostics), "saved_live": len(probes)},
        "code_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True).strip(),  # noqa: S607 - fixed read-only git metadata
        "script_sha256": digest(Path(__file__)), "results": [],
        "source_sha256": {name: digest(ROOT / name) for name in (
            "agent/src/resolveflow/policies/index.py", "agent/src/resolveflow/policies/retrieval.py",
            "agent/src/resolveflow/policies/chunking.py", "scripts/evaluation/environment.py")},
        "limitations": ["Same-author synthetic queries and Gold; test already inspected, not a blind benchmark.",
            "Saved live queries come from synthetic cases, with no per-query Gold or final-case goal scoring.",
            "Nine candidates per bundle; top5 is an easy coverage measure.",
            "Candidate text changes representation only, never citation/body/permissions.",
            "No real users, paid model calls or live Agent quality comparison."]}
    with environment(dataset=ALIGNED_DATA) as (_, index, encoder, pins):
        started = time.perf_counter()
        vectors = encoder.embed([q["query"] for q in queries])
        report["query_embedding_ms"] = round((time.perf_counter() - started) * 1000, 2)
        report["embedding"] = {"model": encoder.model, "revision": encoder.revision, "dimension": encoder.dimension}
        title_vectors = {}
        for bid, bundle in documents.items():
            title_vectors[bid] = encoder.embed([r["title"] + "\n" + r["text"] for r in bundle["rules"]])
        for query, vector in zip(queries, vectors, strict=True):
            pin = pins[query["bundle_id"]]
            bundle = documents[query["bundle_id"]]
            query = {**query, "policy_version": bundle["version"], "policy_manifest_hash": pin["manifest_hash"]}
            for path in ("dense", "bm25"):
                started = time.perf_counter()
                original = index.search(**{k: pin[k] for k in ("merchant_id", "bundle_ids", "manifest_hash")},
                                        query=query["query"], path=path, top_k=5, embedder=encoder)
                report_row(report, query, original, gold, "body", path, (time.perf_counter() - started) * 1000)
                originals = {h.rule_id: h for h in original}
                # Original top5 does not expose all rules. Read each stored rule through
                # the scoped generation, preserving the authoritative citation fields.
                rows = index._chunks_for(pin["bundle_ids"], pin["manifest_hash"],
                    generation_ids=[index.require_ready(pin["bundle_ids"], pin["manifest_hash"])[0].generation_id])
                candidates = [PolicyHit(r.bundle_id, r.merchant_id, r.version, r.manifest_hash, r.rule_id,
                    r.chunk_id, r.content_hash, r.title, r.text, 0.0, path) for r in rows]
                titles = [r.title + "\n" + r.text for r in rows]
                started = time.perf_counter()
                if path == "dense":
                    positions = {r["rule_id"]: pos for pos, r in enumerate(bundle["rules"])}
                    scores = [cosine_similarity(vector, title_vectors[bundle["bundle_id"]][positions[h.rule_id]])
                              for h in candidates]
                else:
                    scores = bm25_scores(titles, query["query"])
                ranked = [replace(h, score=s) for h, s in zip(candidates, scores, strict=True)]
                ranked.sort(key=lambda h: (-h.score, h.bundle_id, h.chunk_id))
                report_row(report, query, ranked[:5], gold, "title_body", path, (time.perf_counter() - started) * 1000)
                assert all(h.citation() == originals[h.rule_id].citation() for h in ranked if h.rule_id in originals)
    report["summary"] = summarize(report["results"])
    # Pre-declared dev-only selection, not a test-set winner or a threshold fit.
    baseline = report["summary"]["body/dense/dev"]
    candidate = report["summary"]["title_body/dense/dev"]
    report["title_body_passes_dev_gate"] = (
        candidate["all_required_at_2"] >= baseline["all_required_at_2"]
        and candidate["mean_complete_evidence_rr"] > baseline["mean_complete_evidence_rr"]
        and candidate["all_required_at_5"] >= baseline["all_required_at_5"])
    report["timing_note"] = (
        "Baseline includes PG and query encoding; candidate is ranking-only with cached vectors, "
        "not a speed comparison.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"query_sources": report["query_sources"], "summary": report["summary"],
        "title_body_passes_dev_gate": report["title_body_passes_dev_gate"]}, ensure_ascii=False))
    return int(any(r["filter_violations"] for r in report["results"]))


def report_row(report, query, hits, gold, representation, path, elapsed):
    required = set(gold[query["id"]]["must_rules"]) if query["id"] in gold else None
    report["results"].append({**query, "representation": representation, "path": path,
        "elapsed_ms": round(elapsed, 2), "candidate_count": 9,
        "returned_chars": sum(len(h.title) + len(h.text) for h in hits),
        **{f"returned_chars_at_{k}": sum(len(h.title) + len(h.text) for h in hits[:k]) for k in (1, 2, 5)},
        "filter_violations": sum(h.merchant_id != query["merchant_id"] or h.bundle_id != query["bundle_id"]
                                 or ("policy_version" in query and h.version != query["policy_version"])
                                 or ("policy_manifest_hash" in query
                                     and h.manifest_hash != query["policy_manifest_hash"])
                                 for h in hits),
        "hits": [asdict(h) for h in hits],
        **(metrics(hits, required) if required is not None else {"scored": False})})


if __name__ == "__main__":
    raise SystemExit(run())
