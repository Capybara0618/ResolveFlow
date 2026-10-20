"""Small, deterministic candidate fusion. Source text/version stays authoritative, scores do not."""

from __future__ import annotations

from dataclasses import replace

from resolveflow.policies.index import PolicyHit


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
            scores[key] = scores.get(key, 0.0) + 1 / (60 + position)
    keys = sorted(scores, key=lambda key: (-scores[key], *key))
    return [replace(originals[key], score=scores[key]) for key in keys[:top_k]]
