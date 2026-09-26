"""C08.2 — the deployment seam: settings in, one callable that investigates a run out.

The worker (``runtime/worker.py``) owns the queue, the run's status and the outbox, and it takes the investigation as
an injected callable. Something has to build that callable from a deployment's settings: which model, which tools,
which policy index, which budget. That is this module, and keeping it separate is what lets a test drive the whole
pipeline with a scripted model and stub tools while a deployment gets the real MCP executor and a live client.

Three decisions are deliberate and are the reason this module has tests of its own:

* **The mode must be named.** There is no default. A deployment that never said whether it runs a mock or a live
  model would otherwise silently become one of them: as ``mock`` it would file proposals no model produced, and as
  ``live`` it would start spending money on a configuration nobody wrote. Refusing is the only answer that cannot be
  misread. (A mock run is still *distinguishable* after the fact — ``RunResult.modes`` carries ``"mock"`` — but that
  is a record of what happened, not a licence to guess beforehand.)
* **Mock mode will not invent a model.** ``mode=mock`` requires a scripted client to be passed in. A factory that
  manufactured a script would be manufacturing decisions.
* **Live mode refuses before it can call out.** No endpoint or no model id is a configuration error, and the refusal
  happens while *building* the investigation, so a misconfigured deployment cannot send a request and then fail.

The API key lives in the config and reaches exactly one place: the ``LiveModelClient``'s ``Authorization`` header. It
is never written into the run row, the callback or the request record (``LiveModelClient`` stores no headers at all,
which C08.1b-2 pinned).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from resolveflow.harness.actions import ActionRefusedError, validate_decision
from resolveflow.harness.budget import RunBudget
from resolveflow.harness.live_model import LiveModelClient
from resolveflow.harness.mcp_client import McpToolExecutor
from resolveflow.harness.model import MODEL_MODE_LIVE, MODEL_MODE_MOCK, MockModelClient, ModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.harness.vocabulary import RunFacts, RunResult
from resolveflow.policies.index import PolicyIndex
from resolveflow.policies.retrieval import Embedder, embedder
from resolveflow.runtime.db import Database
from resolveflow.tools.credential import credential_source

__all__ = ["DeploymentConfig", "DeploymentRefusedError", "build_investigation"]

#: Which model answers. Named explicitly, always.
MODE_ENV: Final = "RESOLVEFLOW_MODEL_MODE"
ENDPOINT_ENV: Final = "RESOLVEFLOW_MODEL_ENDPOINT"
MODEL_ID_ENV: Final = "RESOLVEFLOW_MODEL_ID"
PROVIDER_ENV: Final = "RESOLVEFLOW_MODEL_PROVIDER"
#: ruff reads "API_KEY" as a credential. It is the *name* of the variable that holds one.
API_KEY_ENV: Final = "RESOLVEFLOW_MODEL_API_KEY"  # noqa: S105
TIMEOUT_ENV: Final = "RESOLVEFLOW_MODEL_TIMEOUT_SECONDS"
CEILING_PARAMETER_ENV: Final = "RESOLVEFLOW_MODEL_CEILING_PARAMETER"
CASE_BASE_URL_ENV: Final = "RESOLVEFLOW_CASE_BASE_URL"
COMMERCE_BASE_URL_ENV: Final = "RESOLVEFLOW_COMMERCE_BASE_URL"
#: The run's tool credential is a **source**: the tool server is passed it per call, and the client never stores it.
TOOL_CREDENTIAL_ENV: Final = "RESOLVEFLOW_TOOL_SERVICE_TOKEN"  # noqa: S105
POLICY_INDEX_ENV: Final = "RESOLVEFLOW_POLICY_INDEX"
EMBEDDING_PATH_ENV: Final = "RESOLVEFLOW_EMBEDDING_PATH"
MOCK_SCRIPT_ENV: Final = "RESOLVEFLOW_MOCK_SCRIPT"

DEFAULT_CASE_BASE_URL: Final = "http://127.0.0.1:8083"
DEFAULT_COMMERCE_BASE_URL: Final = "http://127.0.0.1:8081"
DEFAULT_MODEL_TIMEOUT_SECONDS: Final = 30.0

#: The modes a deployment may name. Spelled from the clients' own constants rather than copied.
MODES: Final = frozenset({MODEL_MODE_MOCK, MODEL_MODE_LIVE})


class DeploymentRefusedError(ValueError):
    """The configuration cannot produce an investigation, and saying so beats guessing."""


@dataclass(frozen=True, slots=True)
class DeploymentConfig:
    """One deployment's settings, as data, so a test can state them without an environment."""

    mode: str
    provider: str = "openai-compatible"
    endpoint: str | None = None
    model_id: str | None = None
    api_key: str = ""
    timeout_seconds: float = DEFAULT_MODEL_TIMEOUT_SECONDS
    ceiling_parameter: str = "max_tokens"
    case_base_url: str = DEFAULT_CASE_BASE_URL
    commerce_base_url: str = DEFAULT_COMMERCE_BASE_URL
    service_token: str | None = None
    #: Whether this deployment offers policy search at all. Off means the run cannot search, which the packet says
    #: honestly rather than advertising a tool the gate would refuse (C07.1).
    policy_index: bool = False
    embedding_path: str | None = None
    mock_script: str | None = None

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> DeploymentConfig:
        """Read a deployment's settings, refusing anything it did not say.

        ``environ`` is injectable for the same reason ``default_dsn``'s is: a test of a refusal must not depend on
        the machine it runs on, and a test that set the real environment would leak into every other test.
        """
        env = os.environ if environ is None else environ
        mode = (env.get(MODE_ENV) or "").strip().lower()
        if mode not in MODES:
            raise DeploymentRefusedError(
                f"{MODE_ENV} must name one of {sorted(MODES)}; it is unset or {mode!r}. A deployment that does not "
                "say which model answers cannot be given a default: mock would file proposals no model produced, "
                "live would start spending on a configuration nobody wrote"
            )
        timeout_raw = (env.get(TIMEOUT_ENV) or "").strip()
        try:
            timeout = float(timeout_raw) if timeout_raw else DEFAULT_MODEL_TIMEOUT_SECONDS
        except ValueError as refusal:
            raise DeploymentRefusedError(f"{TIMEOUT_ENV} is not a number: {timeout_raw!r}") from refusal
        return cls(
            mode=mode,
            provider=(env.get(PROVIDER_ENV) or "").strip() or "openai-compatible",
            endpoint=(env.get(ENDPOINT_ENV) or "").strip() or None,
            model_id=(env.get(MODEL_ID_ENV) or "").strip() or None,
            api_key=env.get(API_KEY_ENV) or "",
            timeout_seconds=timeout,
            ceiling_parameter=(env.get(CEILING_PARAMETER_ENV) or "").strip() or "max_tokens",
            case_base_url=(env.get(CASE_BASE_URL_ENV) or "").strip() or DEFAULT_CASE_BASE_URL,
            commerce_base_url=(env.get(COMMERCE_BASE_URL_ENV) or "").strip() or DEFAULT_COMMERCE_BASE_URL,
            service_token=env.get(TOOL_CREDENTIAL_ENV) or None,
            policy_index=(env.get(POLICY_INDEX_ENV) or "").strip() == "1",
            embedding_path=(env.get(EMBEDDING_PATH_ENV) or "").strip() or None,
            mock_script=(env.get(MOCK_SCRIPT_ENV) or "").strip() or None,
        )


def build_investigation(
    *,
    database: Database,
    config: DeploymentConfig,
    model: ModelClient | None = None,
    tools: Any = None,
    policy_embedder: Embedder | None = None,
    budget: RunBudget | None = None,
    service_identity_source: Callable[[], str] | None = None,
) -> Callable[[RunFacts], RunResult]:
    """Build the callable a :class:`~resolveflow.runtime.worker.RunWorker` investigates with.

    ``model`` and ``tools`` are injectable so a test can drive the **whole** pipeline — queue, worker, harness loop,
    callback — without a provider or an MCP subprocess. What is *not* injectable is the mode check: a mock
    deployment has to be told which model to use.
    """
    script = None
    if config.mode == MODEL_MODE_MOCK and model is None and config.mock_script is not None:
        script = _mock_script(config.mock_script)
    _require_mode_is_usable(config, model=model if script is None else MockModelClient(script=script))

    # Built once, because the index is a database-backed object; the *clients* below are built per run instead (see
    # the closure). The embedder is only needed when search is offered.
    index = PolicyIndex(database) if config.policy_index else None
    embedder_for_run = policy_embedder
    if index is not None and embedder_for_run is None:
        embedder_for_run = embedder(local_path=config.embedding_path)
    run_budget = budget or RunBudget()

    def investigate(facts: RunFacts) -> RunResult:
        # A client per run, deliberately: `LiveModelClient` records every request it sent, and a client shared
        # between runs would mix one run's audit trail into another's. It also keeps `calls` per run, which is what
        # the budget counts.
        client = (
            MockModelClient(script=deepcopy(script), repeat_last=False)
            if script is not None
            else model if model is not None else _live_client(config)
        )
        executor = tools if tools is not None else _mcp_executor(
            config, facts,
            identity_token=service_identity_source() if service_identity_source is not None else config.service_token,
        )
        try:
            runner = AgentScopeRunner(
                model=client,
                tools=executor,
                facts=facts,
                budget=run_budget,
                policy_index=index,
                policy_embedder=embedder_for_run,
            )
            return runner.run()
        finally:
            _close(executor)

    return investigate


def _mock_script(path: str) -> list[dict[str, Any]]:
    """Explicit synthetic decisions, bounded and loaded once; each run receives a fresh client/copy."""
    try:
        with Path(path).open("rb") as source:
            raw = source.read(65537)
        if len(raw) > 65536:
            raise ValueError("script exceeds 64KiB")
        value = json.loads(raw)
        if (
            not isinstance(value, list)
            or not 1 <= len(value) <= 12
            or any(not isinstance(item, dict) for item in value)
        ):
            raise ValueError("script must be 1-12 decision objects")
        for item in value:
            validate_decision(item)
    except (OSError, ValueError, ActionRefusedError) as error:
        raise DeploymentRefusedError(
            "mock script must be a readable JSON array of 1-12 decisions, at most 64KiB"
        ) from error
    return value


def _require_mode_is_usable(config: DeploymentConfig, *, model: ModelClient | None) -> None:
    if config.mode == MODEL_MODE_MOCK:
        if model is None:
            raise DeploymentRefusedError(
                "a mock deployment must be handed the scripted model it runs: a factory that wrote the script "
                "would be writing the decisions"
            )
        return
    missing = [name for name, value in (("endpoint", config.endpoint), ("model_id", config.model_id)) if not value]
    if missing:
        raise DeploymentRefusedError(
            f"a live deployment needs {', '.join(missing)} before it can investigate: refusing here means a "
            "misconfigured deployment cannot send a request and then find out"
        )


def _live_client(config: DeploymentConfig) -> LiveModelClient:
    """The provider client. The key reaches the ``Authorization`` header and nothing else."""
    return LiveModelClient(
        endpoint=str(config.endpoint),
        model_id=str(config.model_id),
        provider=config.provider,
        api_key=config.api_key,
        timeout_seconds=config.timeout_seconds,
        ceiling_parameter=config.ceiling_parameter,
    )


def _mcp_executor(config: DeploymentConfig, facts: RunFacts, *, identity_token: str | None = None) -> McpToolExecutor:
    """One executor per run: the tool server is told which line to read, and that is per-run state."""
    return McpToolExecutor(
        line_id=facts.line_id,
        run_id=facts.run_id,
        case_id=facts.case_id,
        case_base_url=config.case_base_url,
        commerce_base_url=config.commerce_base_url,
        # Only the credential fetcher holds the deployment identity. The MCP executor has no fallback token
        # to present to Commerce/Case if the fetch fails.
        service_token=None,
        input_revision=facts.input_revision,
        credential_source=credential_source(
            case_base_url=config.case_base_url,
            run_id=facts.run_id,
            case_id=facts.case_id,
            input_revision=facts.input_revision,
            service_token=identity_token or config.service_token,
            static_token=None,
        ),
    )


def _close(executor: Any) -> None:
    """Close the executor if it has something to close.

    Guarded rather than assumed: ``ToolExecutor`` requires ``close``, but an injected test double may be a bare
    object, and a factory that crashed on the way *out* of a finished investigation would lose its result.
    """
    close = getattr(executor, "close", None)
    if callable(close):
        close()
