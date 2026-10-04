"""The run's frozen Harness manifest: what configuration a run is pinned to (``docs/agent-harness.md:33``).

``docs/agent-harness.md:33`` fixes a list of things a run must not silently change — code revision, orchestration,
state schema, prompt, context policy, tool schema, verifier, model and its parameters, counting, budgets, and the
policy manifest and index generation. This module turns that list into one object with a derived id.

Two properties are the reason this exists at all rather than a string in the packet:

* **The id is the content.** ``manifest_id`` is the canonical SHA-256 of the manifest *excluding itself*, so two
  configurations cannot collide and a resume can compare one value to decide "same manifest" — which is what
  ``docs/agent-harness.md:35``'s 同run恢复不静默换manifest needs. Before C08.1b the packet carried
  ``<bundle-id>@<manifest_hash[:16]>``: a policy reference with a truncated digest, describing none of the above.
* **The values are the run's own.** Budgets come from the run's :class:`~resolveflow.harness.budget.RunBudget`, the
  policy hash from the dispatch's pin, the loop version from the AgentScope build actually installed. The frozen
  schema's ``default`` values describe a run nobody is running, and a manifest of defaults would be a claim, not a
  record.

Two fields are recorded honestly rather than optimistically, because both are still in flight:

* ``verifier_version`` — the proposal verifier landed in C08.1c-1, so this is :data:`VERIFIER_VERSION`'s
  ``"python-citations-v1"``: the Python-side check exists and is wired into the run, while Java's independent
  re-read and approval (``docs/agent-harness.md:13``) is a different component and not claimed here. It read
  ``"unimplemented"`` before that, and the value changing changed the id — which is correct: a run verified by
  nothing is not the same configuration as a run verified by something.
* ``index_generation`` — resolved from the policy index's READY generation for the pinned bundle when one exists
  (C07.1), falling back to a deterministic identity of the pin itself. The fallback is **not** a store row id and
  is named as such in :func:`resolveflow.harness.sdk_runner.AgentScopeRunner.index_generation`.

Only ``parameters`` the client actually declares are recorded: the schema forbids additional members, and a
parameter nobody sent is not part of the configuration. Credentials are not representable here at all — the schema
has no field for them, and ``docs/agent-harness.md:33`` requires the manifest to carry none.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from resolveflow.harness.budget import RunBudget
from resolveflow.harness.context import hash_document
from resolveflow.harness.model import MODEL_MODE_MOCK
from resolveflow.harness.vocabulary import RunFacts

__all__ = [
    "CONTEXT_POLICY_VERSION",
    "GRAPH_VERSION",
    "HARNESS_VERSION",
    "STATE_SCHEMA_VERSION",
    "TOKEN_COUNTER_VERSION",
    "VERIFIER_VERSION",
    "build_manifest",
    "canonical_manifest_id",
    "model_block_for",
]

#: The P0-P4 policy in :mod:`resolveflow.harness.context` and ``docs/context-engineering.md``. Named so a snapshot
#: taken under a later layering cannot be read as if it were assembled by this one.
CONTEXT_POLICY_VERSION: Final = "p0-p4-v5-commerce-facts"

#: The counter actually applied to model input. :func:`~resolveflow.harness.context.estimate_tokens` is a UTF-8 byte
#: allowance marked ESTIMATED — deliberately not the retired characters/3 (which undercounted Chinese) and not the
#: frozen fixture's ``chars-div-4``, neither of which is in use.
TOKEN_COUNTER_VERSION: Final = "utf8-json-bytes-v2"  # noqa: S105 - this is a counting rule, not a credential

#: The persisted run/snapshot shape this harness writes. C09's recovery distinguishes snapshots by this value.
STATE_SCHEMA_VERSION: Final = 2

#: The Python-side proposal verifier that exists as of C08.1c: it checks the frozen schema, that every citation
#: names bytes *this run* actually read, version/hash agreement, the missing-evidence rule and cross-scope policy
#: refs. The name says **Python-side** on purpose — ``docs/agent-harness.md:13`` has Java re-read the sources and
#: approve the proposal, and that half is not this value's to claim. A run whose proposal was never verified, or
#: one judged by a different rule set, therefore cannot share a ``manifest_id`` with one that was.
VERIFIER_VERSION: Final = "python-citations-v3-unshipped-conditions"

#: ``docs/agent-spec.md:42``'s ceiling on how long a run may hold a case. The manifest records the **configured
#: ceiling**, not ``deadline_at - now``: a remaining-time value would change every second and make the manifest id
#: unstable, and a manifest that cannot be recomputed cannot be compared on resume.
MAX_ACTIVE_DEADLINE_SECONDS: Final = 120

#: The only ``model.parameters`` the frozen schema admits (``additionalProperties: false``).
_DECLARED_PARAMETERS: Final = ("temperature", "top_p", "seed", "reasoning_effort", "thinking", "response_format")


def _distribution_version(name: str) -> str:
    """The installed version of ``name``, or a plain statement that it is not installed.

    ``"uninstalled"`` is not a version and is not meant to look like one: it is what a checkout that never installed
    the distribution can honestly say, and it is visible in the manifest rather than hidden behind a default.
    """
    import importlib.metadata

    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "uninstalled"


def code_revision() -> str:
    """Use the deployment stamp, or fingerprint source and lock for an unstamped checkout.

    No git call or credential is needed. Wheels without the lock fingerprint actual installed distributions.
    """
    from resolveflow.runtime.build_identity import source_identity

    stamp = os.environ.get("RESOLVEFLOW_CODE_REVISION", "")
    package = Path(__file__).resolve().parents[1]
    return stamp or source_identity(package, package.parent.parent / "uv.lock")


#: The exact AgentScope build the loop runs on. Read from the installed distribution rather than typed in, because
#: ``docs/agent-harness.md:33`` asks for the **precise** version: a hand-written string is one dependency bump away
#: from describing a loop the run is not using. Defined here, below the helper it calls, so importing this module
#: cannot fail on definition order.
AGENTSCOPE_VERSION: Final = _distribution_version("agentscope")

#: This adapter's own version, from the same source.
RESOLVEFLOW_VERSION: Final = _distribution_version("resolveflow-agent")

#: ``docs/agent-harness.md:33``: ``agentscope@<精确版本>+resolveflow@<适配版本>``. The frozen fixture's ``graph-1``
#: is the retired LangGraph value; this is the value the AgentScope migration replaces it with.
GRAPH_VERSION: Final = f"agentscope@{AGENTSCOPE_VERSION}+resolveflow@{RESOLVEFLOW_VERSION}"

HARNESS_VERSION: Final = f"resolveflow-harness-{RESOLVEFLOW_VERSION}"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_manifest_id(document: Mapping[str, Any]) -> str:
    """The canonical SHA-256 of ``document`` with ``manifest_id`` excluded.

    Excluding the field is not a shortcut: including it would mean hashing a value derived from the hash. The test
    states it as the property it is — replacing ``manifest_id`` with any other value leaves this result unchanged.
    """
    body = {key: value for key, value in document.items() if key != "manifest_id"}
    return hash_document(body)


def model_block_for(client: Any, *, context_window_tokens: int) -> dict[str, Any]:
    """The manifest's ``model`` member, described by the client that actually decides.

    A client that declares ``provider``/``model_id`` is taken at its word; one that does not is described by what is
    known instead of a guess — a mock is ``mock``, and an undeclared live client is ``unknown`` with the alias it
    reports. Recording an assumed vendor for a live client would be the kind of unverifiable claim
    ``docs/agent-harness.md:35`` refuses (a drifting alias is a limitation to record, not to smooth over).
    """
    provider = getattr(client, "provider", None)
    model_id = getattr(client, "model_id", None)
    alias = getattr(client, "model_alias", None)
    mode = getattr(client, "mode", MODEL_MODE_MOCK)

    if not isinstance(provider, str) or not provider:
        provider = "mock" if mode == MODEL_MODE_MOCK else "unknown"
    if not isinstance(model_id, str) or not model_id:
        if isinstance(alias, str) and alias:
            model_id = alias
        else:
            model_id = "mock" if mode == MODEL_MODE_MOCK else "unknown"

    return {
        "provider": provider,
        "model_id": model_id,
        "context_window_tokens": int(context_window_tokens),
        "token_counter_version": TOKEN_COUNTER_VERSION,
        "parameters": _declared_parameters(client),
    }


def _declared_parameters(client: Any) -> dict[str, Any]:
    """Only the parameters the client declares, and only ones the frozen schema admits."""
    declared = getattr(client, "parameters", None)
    if not isinstance(declared, Mapping):
        return {}
    return {name: declared[name] for name in _DECLARED_PARAMETERS if name in declared}


def _policy_manifest_hash(facts: RunFacts) -> str:
    """The dispatch's pinned ``manifest_hash`` (Java's own value), or a digest of its absence.

    The dispatch always carries the pin — ``runtime.runs`` refuses one that does not (C07.1) — so the fallback is
    reachable only in a run assembled by hand. It digests the *absence* so the field stays a stable sha-256 and the
    id still changes when a pin appears, rather than borrowing a bundle hash the run never pinned.
    """
    pinned = facts.policy_manifest or {}
    value = pinned.get("manifest_hash")
    if isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value):
        return value
    return hash_document({"pinned_policy_manifest": "none"})


def build_manifest(
    *,
    facts: RunFacts,
    system_prompt: str,
    tool_schema: Mapping[str, Any],
    budget: RunBudget,
    model: Mapping[str, Any],
    index_generation: str,
) -> dict[str, Any]:
    """Assemble the frozen manifest for one run and derive its ``manifest_id``.

    The result is a plain mapping rather than a model object because that is what the frozen schema validates and
    what a snapshot stores; :func:`canonical_manifest_id` is the only thing that interprets it.
    """
    document: dict[str, Any] = {
        "schema_version": 1,
        "manifest_id": "",
        "harness_version": HARNESS_VERSION,
        "code_revision": code_revision(),
        "graph_version": GRAPH_VERSION,
        "state_schema_version": STATE_SCHEMA_VERSION,
        "prompt_hash": _hash_text(system_prompt),
        "context_policy_version": CONTEXT_POLICY_VERSION,
        "tool_schema_hash": hash_document(dict(tool_schema)),
        "verifier_version": VERIFIER_VERSION,
        "policy_manifest_hash": _policy_manifest_hash(facts),
        "index_generation": index_generation,
        "model": dict(model),
        "budgets": {
            "max_model_calls": budget.model_calls,
            "max_external_calls": budget.tool_attempts,
            "max_local_reads": budget.local_reads,
            "max_total_input_tokens": budget.input_tokens,
            "max_total_output_tokens": budget.output_tokens,
            "max_prompt_tokens": budget.step_input_tokens,
            "max_output_tokens": budget.step_output_tokens,
            "active_deadline_seconds": MAX_ACTIVE_DEADLINE_SECONDS,
            "model_timeout_seconds": int(round(budget.timeout_seconds)),
        },
    }
    document["manifest_id"] = canonical_manifest_id(document)
    return document
