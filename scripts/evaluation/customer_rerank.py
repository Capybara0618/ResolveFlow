"""Offline experiment helpers. No production default, downloads or business writes."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from resolveflow.policies.index import PolicyHit


def candidate_union(rankings: list[list[PolicyHit]]) -> list[PolicyHit]:
    scopes = {(h.merchant_id, h.manifest_hash) for route in rankings for h in route}
    if len(scopes) > 1:
        raise ValueError("candidate scopes differ")
    items: dict[tuple[str, str], PolicyHit] = {}
    for route in rankings:
        for hit in route:
            key = (hit.bundle_id, hit.chunk_id)
            if key in items and replace(items[key], score=0.0, path="dense") != replace(hit, score=0.0, path="dense"):
                raise ValueError("candidate originals differ")
            items[key] = hit
    return [items[key] for key in sorted(items)]


class LocalReranker:
    def __init__(self, model: Any, *, max_length: int = 512, synchronize: Callable[[], None] | None = None) -> None:
        self.model = model
        self.max_length = max_length
        self.synchronize = synchronize or (lambda: None)

    def rank(self, query: str, candidates: list[PolicyHit]) -> tuple[list[PolicyHit], dict[str, Any]]:
        self.synchronize()
        start = time.perf_counter()
        candidates = candidate_union([candidates])
        pairs = [(query, h.text) for h in candidates]
        lengths = [len(self.model.tokenizer(a, b, truncation=False)["input_ids"]) for a, b in pairs]
        if any(n > self.max_length for n in lengths):
            raise ValueError("reranker pair exceeds fixed window; refusing silent truncation")
        if not pairs:
            return [], {"pairs": 0, "max_pair_tokens": 0, "elapsed_ms": (time.perf_counter() - start) * 1000}
        values = self.model.predict(pairs, batch_size=8, show_progress_bar=False)
        self.synchronize()
        if len(values) != len(candidates) or any(not math.isfinite(float(s)) for s in values):
            raise ValueError("reranker output count or finite score differs")
        ranked = [replace(h, score=float(s)) for h, s in zip(candidates, values, strict=True)]
        ranked.sort(key=lambda h: (-h.score, h.bundle_id, h.chunk_id))
        profile = {
            "pairs": len(pairs),
            "max_pair_tokens": max(lengths),
            "elapsed_ms": (time.perf_counter() - start) * 1000,
        }
        if hasattr(self.model, "gpu_predict_ms"):
            profile["gpu_predict_ms"] = self.model.gpu_predict_ms
        return ranked, profile
