"""Request-driven consultation runtime; no new resident loop and no default mock decisions."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

from resolveflow.harness.budget import RunBudget
from resolveflow.harness.live_model import LiveModelClient
from resolveflow.harness.model import MockModelClient
from resolveflow.policies.index import PolicyIndex
from resolveflow.runtime.db import Database
from resolveflow.runtime.factory import DeploymentConfig
from resolveflow.support.embeddings import SupportEmbeddings
from resolveflow.support.engine import SYSTEM, SupportAgent
from resolveflow.support.protocol import DECISION, SupportFailure, SupportInput
from resolveflow.support.retrieval import CANDIDATE_K, RETRIEVAL_VERSION, RRF_CONSTANT
from resolveflow.support.sources import BoundSources
from resolveflow.support.store import SupportStore


class SupportRuntime:
    def __init__(
        self,
        database: Database,
        config: DeploymentConfig,
        *,
        model_factory: Any = None,
        sources_factory: Any = None,
        embeddings: SupportEmbeddings | None = None,
    ) -> None:
        self.database, self.config = database, config
        self.model_factory, self.sources_factory = model_factory, sources_factory
        self.embeddings = embeddings if embeddings is not None else SupportEmbeddings()

    def _model(self) -> Any:
        config = self.config
        if self.model_factory:
            return self.model_factory()
        if config.mode == "mock":
            path = os.environ.get("RESOLVEFLOW_SUPPORT_MOCK_SCRIPT")
            if not path:
                raise SupportFailure("MOCK_SCRIPT_REQUIRED")
            raw = Path(path).read_bytes()
            if len(raw) > 65536:
                raise SupportFailure("MOCK_SCRIPT_TOO_LARGE")
            script = json.loads(raw)
            if not isinstance(script, list) or not 1 <= len(script) <= 12:
                raise SupportFailure("MOCK_SCRIPT_INVALID")
            for decision in script:
                DECISION.validate_python(decision)
            return MockModelClient(script=script)
        if config.mode != "live" or not config.endpoint or not config.model_id:
            raise SupportFailure("MODEL_NOT_CONFIGURED")
        return LiveModelClient(
            endpoint=config.endpoint,
            model_id=config.model_id,
            provider=config.provider,
            api_key=config.api_key,
            timeout_seconds=config.timeout_seconds,
            ceiling_parameter=config.ceiling_parameter,
            parameters={"thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}, "temperature": 0}
            if config.provider == "deepseek"
            else {},
        )

    def run(self, request: SupportInput, token: str) -> dict[str, Any]:
        model = self._model()
        root = Path(__file__).parent
        manifest = {
            "version": "support-agent-v1",
            "sdk": version("agentscope"),
            "budget": asdict(RunBudget()),
            "provider_capacity": self.config.context_window_tokens,
            "mode": self.config.mode,
            "provider": self.config.provider,
            "model_id": self.config.model_id,
            "endpoint": self.config.endpoint,
            "retrieval": {
                "version": RETRIEVAL_VERSION,
                "candidate_k": CANDIDATE_K,
                "rrf_constant": RRF_CONSTANT,
                "lexical_positive_only": True,
            },
            "parameters": getattr(model, "parameters", {}),
            "mock_script": getattr(model, "script", None),
            "code": {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in [
                    "engine.py",
                    "protocol.py",
                    "sources.py",
                    "store.py",
                    "service.py",
                    "embeddings.py",
                    "retrieval.py",
                    "../policies/retrieval.py",
                    "../policies/index.py",
                    "../policies/child_index.py",
                ]
            },
            "prompt_hash": hashlib.sha256(SYSTEM.encode()).hexdigest(),
        }
        journal, cached = SupportStore(self.database).claim(request, manifest)
        if cached is not None:
            return cached
        assert journal is not None
        if self.sources_factory:
            sources = self.sources_factory(request, token, journal)
        else:
            # Local weights are lazy; a logistics-only question does not load the embedder or require an index.
            encoder = self.embeddings.get(self.config.embedding_path) if self.config.policy_index else None
            sources = BoundSources(
                request,
                case_url=self.config.case_base_url,
                token=token,
                index=PolicyIndex(self.database) if self.config.policy_index else None,
                embedder=encoder,
                journal=journal,
            )
        try:
            result = SupportAgent(
                request, model, sources, journal=journal, provider_capacity=self.config.context_window_tokens
            ).run()
            journal.finish(result)
            return result
        finally:
            close = getattr(sources, "close", None)
            if close:
                close()
