"""Bound HTTP facts and existing dense PolicyIndex; no Case credential or arbitrary URL fallback."""

from urllib.parse import quote

import httpx

from resolveflow.policies.index import PolicyIndexNotReadyError
from resolveflow.policies.retrieval import EmbeddingUnavailableError
from resolveflow.support.protocol import History, SupportFailure, SupportInput


class BoundSources:
    def __init__(
        self, request: SupportInput, *, case_url: str, token: str, index=None, embedder=None, journal=None, client=None
    ):
        self.request = request
        self.index, self.embedder, self.journal = index, embedder, journal
        self.client = client or httpx.Client(timeout=10, follow_redirects=False)
        self.owns_client = client is None
        self.prefix = case_url.rstrip("/") + "/internal/v1/support/turns/" + quote(request.run_id, safe="")
        self.headers = {"Authorization": "Bearer " + token}
        self.generations = None

    def close(self):
        if self.owns_client:
            self.client.close()

    def _get(self, suffix, parameters=None):
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

    def check_current(self):
        value = self._get("/current")
        if "error" in value:
            raise SupportFailure(value["error"])
        if (
            value.get("conversation_id") != self.request.conversation_id
            or value.get("input_version") != self.request.input_version
        ):
            raise SupportFailure("STALE_INPUT")

    def read(self, name, arguments):
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

    def search(self, query, top_k):
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
            hits = self.index.search(
                merchant_id=self.request.merchant_id,
                bundle_ids=manifest["bundle_ids"],
                manifest_hash=manifest["manifest_hash"],
                query=query,
                path="dense",
                top_k=top_k,
                embedder=self.embedder,
                generation_ids=self.generations,
            )
        except (PolicyIndexNotReadyError, EmbeddingUnavailableError):
            return [{"error": "POLICY_INDEX_UNAVAILABLE", "retryable": False}]
        return [
            {
                "source_type": "POLICY",
                "version": hit.version,
                "title": hit.title,
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
