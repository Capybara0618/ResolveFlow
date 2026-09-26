"""The run's frozen Harness manifest (``docs/agent-harness.md:33``).

``manifest_id`` is required to be the canonical SHA-256 of the manifest **excluding itself**, and the manifest has
to pin the harness, code revision, AgentScope loop, prompt, tool schema, context policy, verifier, model, budgets,
and the policy manifest and index generation the run was dispatched against.

Until C08.1b the packet carried ``<bundle-id>@<manifest_hash[:16]>``: a *policy reference*, not a manifest, and not
even a hash of one. These tests pin the two properties that make the replacement real rather than decorative — the
manifest satisfies the frozen schema, and its id is genuinely the hash of its own content — and pin the mapping from
the run's own state (budgets, pinned policy, ready index generation) so a manifest cannot silently claim defaults
the run is not actually using.
"""

from __future__ import annotations

from typing import Any

from resolveflow.contracts._schemaio import validator_bundle
from resolveflow.harness.budget import RunBudget
from resolveflow.harness.manifest import (
    CONTEXT_POLICY_VERSION,
    GRAPH_VERSION,
    TOKEN_COUNTER_VERSION,
    build_manifest,
    canonical_manifest_id,
    model_block_for,
)
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.vocabulary import HARNESS_SYSTEM_PROMPT, RunFacts

PIN = {
    "merchant_id": "M-1001",
    "bundle_ids": ["policy-logistics-2026.09"],
    "manifest_hash": "b" * 64,
    "safety_epoch": 2,
}

GENERATION = "88888888-9999-4aaa-8bbb-cccccccccccc"


def facts(**overrides: object) -> RunFacts:
    fields: dict[str, object] = {
        "run_id": "11111111-1111-4111-8111-111111111111",
        "case_id": "22222222-2222-4222-8222-222222222222",
        "input_revision": 1,
        "line_id": "7001",
        "description": "包裹丢了，希望退款",
        "merchant_id": "M-1001",
        "customer_id": "C-2002",
        "policy_manifest": dict(PIN),
    }
    fields.update(overrides)
    return RunFacts(**fields)  # type: ignore[arg-type]


def manifest(**overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "facts": facts(),
        "system_prompt": HARNESS_SYSTEM_PROMPT,
        "tool_schema": {"tools": ["get_order_context"]},
        "budget": RunBudget(),
        "model": model_block_for(MockModelClient(), context_window_tokens=32000),
        "index_generation": GENERATION,
    }
    arguments.update(overrides)
    return build_manifest(**arguments)


def test_the_manifest_satisfies_the_frozen_schema() -> None:
    """The producer must satisfy the schema the project already froze, not a laxer shape of its own.

    ``contracts/harness-manifest.schema.json`` is ``additionalProperties: false`` with every field required, so a
    builder that invented or omitted a member would be caught here rather than by whoever reads the snapshot.
    """
    document = manifest()

    bundle = validator_bundle("urn:resolveflow:harness-manifest:v1")
    errors = list(bundle.validator.iter_errors(document))

    assert not errors, "\n".join(f"{list(error.path)}: {error.message}" for error in errors)
    assert bundle.name.endswith("harness-manifest.schema.json"), "the frozen schema is what was validated"


def test_the_manifest_id_is_the_canonical_hash_of_the_manifest_itself() -> None:
    """The id covers the content and is *derived* from it, so two different manifests cannot share an id."""
    document = manifest()

    assert document["manifest_id"] == canonical_manifest_id(document)
    assert len(document["manifest_id"]) == 64
    assert all(character in "0123456789abcdef" for character in document["manifest_id"])

    # A different run state must produce a different id: an id that ignored the budgets would let C09 resume with
    # a silently different configuration, which is exactly what "同run恢复不静默换manifest" forbids.
    other = manifest(budget=RunBudget(model_calls=11))
    assert other["manifest_id"] != document["manifest_id"]
    assert other["budgets"]["max_model_calls"] == 11


def test_the_manifest_id_excludes_itself_so_the_hash_is_reproducible() -> None:
    """``docs/agent-harness.md:33``: the canonical SHA-256 is taken over the manifest *excluding* ``manifest_id``.

    Otherwise the field would have to hash a value that contains itself. The test states it directly: replacing
    ``manifest_id`` with anything at all leaves the computed id unchanged.
    """
    document = manifest()
    tampered = {**document, "manifest_id": "f" * 64}

    assert canonical_manifest_id(tampered) == document["manifest_id"]


def test_the_manifest_pins_the_agentscope_loop_and_the_real_token_counter() -> None:
    """The frozen fixture's ``graph-1``/``chars-div-4`` are the *old* values; the run must record what it uses.

    ``docs/agent-harness.md:33`` asks for ``agentscope@<精确版本>+resolveflow@<适配版本>``, and the counter is the
    UTF-8 byte allowance actually used — not the retired characters/3 (and not characters/4) label.
    """
    document = manifest()

    assert document["graph_version"] == GRAPH_VERSION
    assert document["graph_version"].startswith("agentscope@2.0.8+"), document["graph_version"]
    assert "langgraph" not in document["graph_version"].lower()
    assert document["graph_version"] != "graph-1"
    assert document["model"]["token_counter_version"] == TOKEN_COUNTER_VERSION
    assert document["model"]["token_counter_version"] != "chars-div-4"
    assert document["context_policy_version"] == CONTEXT_POLICY_VERSION


def test_the_manifest_records_the_pinned_policy_and_the_index_generation() -> None:
    """The two fields that tie the run to the policy it was dispatched against (C07.1's READY generation)."""
    document = manifest()

    assert document["policy_manifest_hash"] == PIN["manifest_hash"]
    assert document["index_generation"] == GENERATION


def test_the_budgets_are_the_run_s_budgets_not_schema_defaults() -> None:
    """A manifest that recorded the schema's ``default`` values would describe a run nobody is running."""
    budget = RunBudget(model_calls=7, tool_attempts=9, local_reads=3, step_output_tokens=256)

    budgets = manifest(budget=budget)["budgets"]

    assert budgets["max_model_calls"] == 7
    assert budgets["max_external_calls"] == 9
    assert budgets["max_local_reads"] == 3
    assert budgets["max_output_tokens"] == 256


def test_the_prompt_and_tool_schema_hashes_are_hashes_of_what_is_sent() -> None:
    """Both hashes must cover the actual prompt and the actual schema document, not a copy that can drift."""
    import hashlib
    import json

    schema = {"tools": ["get_order_context", "get_shipment_trace"]}

    document = manifest(tool_schema=schema)

    expected_prompt = hashlib.sha256(HARNESS_SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    expected_schema = hashlib.sha256(
        json.dumps(schema, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert document["prompt_hash"] == expected_prompt
    assert document["tool_schema_hash"] == expected_schema
    # Changing what is sent must change the manifest: otherwise the snapshot would pin a schema it does not use.
    assert manifest(tool_schema={"tools": ["get_order_context"]})["manifest_id"] != document["manifest_id"]


def test_the_model_block_names_the_client_that_actually_decides() -> None:
    """Mock must not be recorded as a live vendor, and a live client's own declaration wins over any default."""
    mock = model_block_for(MockModelClient(), context_window_tokens=32000)

    assert mock["provider"] == "mock"
    assert mock["model_id"] == "mock-scripted"
    assert mock["context_window_tokens"] == 32000

    class _Live:
        provider = "openai-compatible"
        model_id = "some-model-v2"
        mode = "LIVE"
        model_alias = "provider-alias"

    live = model_block_for(_Live(), context_window_tokens=200000)

    assert live["provider"] == "openai-compatible"
    assert live["model_id"] == "some-model-v2"

    class _Undeclared:
        mode = "LIVE"
        model_alias = "only-an-alias"

    # A live client that will not name its vendor must not be recorded as one; the alias is what is known.
    undeclared = model_block_for(_Undeclared(), context_window_tokens=8000)

    assert undeclared["provider"] == "unknown"
    assert undeclared["model_id"] == "only-an-alias"