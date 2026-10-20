"""Bounded query enrichment from already observed shipment facts; no inference or extra model call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STATES = frozenset({"NOT_SHIPPED", "IN_TRANSIT", "DELAYED", "DELIVERED", "LOST", "UNKNOWN"})


@dataclass(frozen=True)
class GroundedQuery:
    original: str
    query: str
    source_ids: tuple[str, ...] = ()
    reason: str = "no_unambiguous_shipment_fact"


def grounded_query(query: str, observations: list[dict[str, Any]], line_id: str) -> GroundedQuery:
    candidates: list[tuple[int, str, str, str]] = []
    for observation in observations:
        # An unavailable new read cannot justify silently carrying an earlier success forward.
        if "error" in observation:
            candidates.clear()
            continue
        if observation.get("source_type") != "SHIPMENT":
            continue
        data = observation.get("data", {})
        if not isinstance(data, dict):
            continue
        lines = data.get("lines", [])
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, dict) or line.get("line_id") != line_id:
                continue
            version = line.get("source_version")
            status, conclusion = line.get("status"), line.get("carrier_conclusion")
            if type(version) is not int or version < 1 or not isinstance(status, str) or status not in STATES:
                continue
            if conclusion is not None and (not isinstance(conclusion, str) or conclusion not in STATES):
                continue
            candidates.append((version, status, conclusion or "", str(observation.get("source_id", ""))))
    if not candidates:
        return GroundedQuery(query, query)
    latest = max(c[0] for c in candidates)
    selected = [c for c in candidates if c[0] == latest]
    if len({c[1:3] for c in selected}) != 1:
        return GroundedQuery(query, query)
    _, status, conclusion, _ = selected[0]
    prefix = f"物流状态 {status}"
    if conclusion and conclusion != status:
        prefix += f"，承运商结论 {conclusion}"
    enriched = prefix + "；" + query
    if len(enriched) > 1000:
        return GroundedQuery(query, query, reason="enrichment_exceeds_query_limit")
    return GroundedQuery(query, enriched, tuple(dict.fromkeys(c[3] for c in selected if c[3])), "shipment_fact")
