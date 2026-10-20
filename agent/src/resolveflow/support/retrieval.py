"""Small, deterministic candidate fusion. Source text/version stays authoritative, scores do not."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Literal

from resolveflow.policies.index import PolicyHit, PolicyIndex, PolicyIndexNotReadyError, PolicySearchPath
from resolveflow.policies.retrieval import Embedder

CANDIDATE_K = 5
RRF_CONSTANT = 60
RETRIEVAL_VERSION = "support-fields-rrf-v1"


def retrieve_policy(
    index: PolicyIndex,
    *,
    merchant_id: str,
    bundle_ids: list[str],
    manifest_hash: str,
    generation_ids: dict[str, str],
    query: str,
    top_k: int,
    embedder: Embedder | None,
    timings: dict[str, float],
) -> list[PolicyHit]:
    """One Agent search action: bounded three-route recall, fixed pins, one dense query embedding."""
    if not 1 <= top_k <= 5:
        raise ValueError("final top_k must be 1..5")
    timings.clear()
    started = time.perf_counter()
    rankings = []
    routes: list[tuple[str, PolicySearchPath, Literal["body", "title"]]] = [
        ("dense", "dense", "body"),
        ("body_lexical", "bm25", "body"),
        ("title_lexical", "bm25", "title"),
    ]
    for name, path, field in routes:
        profile: dict[str, float] = {}
        route_start = time.perf_counter()
        hits = index.search(
            merchant_id=merchant_id,
            bundle_ids=bundle_ids,
            manifest_hash=manifest_hash,
            generation_ids=generation_ids,
            query=query,
            path=path,
            lexical_field=field,
            top_k=CANDIDATE_K,
            embedder=embedder if path == "dense" else None,
            timings=profile,
        )
        if any(
            h.merchant_id != merchant_id or h.bundle_id not in bundle_ids or h.manifest_hash != manifest_hash
            for h in hits
        ):
            raise PolicyIndexNotReadyError("candidate escaped the bound query scope")
        timings.update({name + "_" + key: value for key, value in profile.items()})
        timings[name + "_ms"] = (time.perf_counter() - route_start) * 1000
        rankings.append(hits if path == "dense" else [h for h in hits if h.score > 0])
    fusion_start = time.perf_counter()
    result = reciprocal_rank_fusion(rankings, top_k=top_k)
    timings["fusion_ms"] = (time.perf_counter() - fusion_start) * 1000
    timings["total_ms"] = (time.perf_counter() - started) * 1000
    return result


def reciprocal_rank_fusion(rankings: list[list[PolicyHit]], *, top_k: int) -> list[PolicyHit]:
    if not 1 <= top_k <= 5:
        raise ValueError("final top_k must be 1..5")
    scopes = {(h.merchant_id, h.manifest_hash) for route in rankings for h in route}
    if len(scopes) > 1:
        raise ValueError("candidate scopes differ")
    originals: dict[tuple[str, str], PolicyHit] = {}
    scores: dict[tuple[str, str], float] = {}
    for route in rankings:
        seen: set[tuple[str, str]] = set()
        position = 0
        for hit in route:
            key = (hit.bundle_id, hit.chunk_id)
            if key in originals:
                prior = originals[key]
                if replace(prior, score=0.0, path="dense") != replace(hit, score=0.0, path="dense"):
                    raise ValueError("candidate source originals differ")
            if key in seen:
                continue
            seen.add(key)
            position += 1
            originals[key] = hit
            scores[key] = scores.get(key, 0.0) + 1 / (RRF_CONSTANT + position)
    keys = sorted(scores, key=lambda key: (-scores[key], *key))
    return [replace(originals[key], score=scores[key]) for key in keys[:top_k]]
