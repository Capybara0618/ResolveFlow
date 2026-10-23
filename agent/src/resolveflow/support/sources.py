"""Bound HTTP facts and existing dense PolicyIndex; no Case credential or arbitrary URL fallback."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any
from urllib.parse import quote

import httpx

from resolveflow.policies.index import PolicyIndexNotReadyError
from resolveflow.policies.retrieval import EmbeddingUnavailableError
from resolveflow.support.guide import guide_source
from resolveflow.support.protocol import History, SupportFailure, SupportInput
from resolveflow.support.retrieval import retrieve_policy

LOG = logging.getLogger(__name__)


class BoundSources:
    def __init__(
        self,
        request: SupportInput,
        *,
        case_url: str,
        token: str,
        index: Any = None,
        embedder: Any = None,
        journal: Any = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.request = request
        self.index, self.embedder, self.journal = index, embedder, journal
        self.client = client or httpx.Client(timeout=10, follow_redirects=False)
        self.owns_client = client is None
        self.prefix = case_url.rstrip("/") + "/internal/v1/support/turns/" + quote(request.run_id, safe="")
        self.headers = {"Authorization": "Bearer " + token}
        self.generations: dict[str, str] | None = None

    def close(self) -> None:
        if self.owns_client:
            self.client.close()

    def _get(self, suffix: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self.client.get(self.prefix + suffix, params=parameters, headers=self.headers)
        except httpx.RequestError:
            return {"error": "SOURCE_UNAVAILABLE", "retryable": True}
        if response.status_code in [401, 403]:
            raise SupportFailure("FORBIDDEN_SOURCE")
        if response.status_code == 409:
            raise SupportFailure("STALE_INPUT")
        if response.status_code == 404:
            return {"error": "NOT_FOUND", "retryable": False}
        if response.status_code != 200:
            return {"error": "SOURCE_UNAVAILABLE", "retryable": response.status_code >= 500}
        if len(response.content) > 262144:
            return {"error": "SOURCE_TOO_LARGE", "retryable": False}
        try:
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError("object required")
        except ValueError:
            return {"error": "SOURCE_INVALID", "retryable": False}
        return value

    def check_current(self) -> None:
        value = self._get("/current")
        if "error" in value:
            raise SupportFailure(value["error"])
        if (
            value.get("conversation_id") != self.request.conversation_id
            or value.get("input_version") != self.request.input_version
        ):
            raise SupportFailure("STALE_INPUT")

    def read(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "get_support_guide":
            return guide_source()
        route, source_type = {
            "get_order_context": ("order", "ORDER"),
            "get_shipment_trace": ("shipment", "SHIPMENT"),
            "read_history": ("history", "CONVERSATION"),
        }[name]
        parameters = History.model_validate(arguments).model_dump(exclude_none=True) if name == "read_history" else None
        value = self._get("/facts/" + route, parameters)
        if "error" in value:
            return value
        return {"source_type": source_type, "version": value.get("version", self.request.input_version), "data": value}

    def search(self, query: str, top_k: int, *, sub_queries: list[str] | None = None) -> list[dict[str, Any]]:
        started = time.perf_counter()
        timings: dict[str, float] = {}
        manifest = self.request.context.get("policy_manifest")
        if self.index is None or not manifest:
            return [{"error": "POLICY_INDEX_UNAVAILABLE", "retryable": False}]
        if manifest.get("merchant_id") != self.request.merchant_id:
            raise SupportFailure("POLICY_SCOPE_MISMATCH")
        try:
            if self.generations is None:
                saved = None if self.journal is None else self.journal.generations()
                if saved:
                    self.generations = saved
                else:
                    ready = self.index.require_ready(manifest["bundle_ids"], manifest["manifest_hash"])
                    if any(g.merchant_id != self.request.merchant_id for g in ready):
                        raise SupportFailure("POLICY_SCOPE_MISMATCH")
                    self.generations = {g.bundle_id: g.generation_id for g in ready}
                if self.journal is not None and saved is None:
                    self.journal.pin_generations(self.generations)
            # A tiny policy set is cheaper and more complete than a lossy ranked window.
            # Keep this explicit in the observation; top_k still bounds the ranked path.
            small = getattr(self.index, 'small_context', None)
            hits = small(merchant_id=self.request.merchant_id, bundle_ids=manifest['bundle_ids'],
                manifest_hash=manifest['manifest_hash'], generation_ids=self.generations) if callable(small) else None
            complete = hits is not None
            if hits is None:
                hits = retrieve_policy(
                    self.index,
                    merchant_id=self.request.merchant_id,
                    bundle_ids=manifest["bundle_ids"],
                    manifest_hash=manifest["manifest_hash"],
                    query=query,
                    top_k=top_k,
                    embedder=self.embedder,
                    generation_ids=self.generations,
                    timings=timings,
                    sub_queries=sub_queries,
                )
        except (PolicyIndexNotReadyError, EmbeddingUnavailableError):
            LOG.info(
                "support_policy_search run_id=%s status=unavailable elapsed_ms=%.3f",
                self.request.run_id,
                (time.perf_counter() - started) * 1000,
            )
            return [{"error": "POLICY_INDEX_UNAVAILABLE", "retryable": False}]
        LOG.info(
            "support_policy_search run_id=%s query_sha256=%s stages=%s source_total_ms=%.3f",
            self.request.run_id,
            hashlib.sha256(query.encode()).hexdigest(),
            timings,
            (time.perf_counter() - started) * 1000,
        )
        return [
            {
                "source_type": "POLICY",
                "version": hit.version,
                "title": hit.title,
                "retrieval_context": {"mode": "COMPLETE_SMALL_SET" if complete else "RANKED",
                                      "count": len(hits)},
                "data": {
                    k: getattr(hit, k)
                    for k in [
                        "bundle_id",
                        "merchant_id",
                        "manifest_hash",
                        "rule_id",
                        "chunk_id",
                        "content_hash",
                        "text",
                    ]
                },
            }
            for hit in hits
        ]
