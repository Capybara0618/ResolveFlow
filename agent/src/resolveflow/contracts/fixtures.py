"""Load the T02 fixture corpus and freeze the values both languages must agree on.

The corpus is written for humans: entries point at each other with ``_ref``
members and leave hash/signature values as ``PLACEHOLDER_*`` tokens. This module
turns that into concrete instances, so a test can validate them against the real
schemas and hash them without every reader having to reassemble the pieces.

The resolver is deliberately strict. A dangling ``_ref`` or an unresolved
placeholder raises instead of being skipped: a fixture that silently loses its
payload would still "pass" and would stop being evidence.
"""

from __future__ import annotations

import copy
from typing import Any

from resolveflow.contracts._schemaio import load_json

__all__ = [
    "CORPUS_PATHS",
    "GENERATED_PATHS",
    "PLACEHOLDER_PREFIX",
    "collect_placeholders",
    "load_corpus",
    "load_reject_corpus",
    "resolve_instance",
    "substitute_values",
]

CORPUS_PATHS = {
    "canonical": "contracts/fixtures/examples/cross-language-canonical-inputs.json",
    "valid": "contracts/fixtures/examples/valid.json",
    "reject": "contracts/fixtures/reject/reject.json",
}

GENERATED_PATHS = {
    "hashes": "contracts/fixtures/expected-hashes.json",
    "enums": "contracts/fixtures/expected-enums.json",
}

PLACEHOLDER_PREFIX = "PLACEHOLDER_"


def load_corpus(name: str) -> dict[str, Any]:
    """Load one corpus file by logical name (``canonical`` / ``valid`` / ``reject``)."""
    try:
        path = CORPUS_PATHS[name]
    except KeyError as error:
        raise KeyError(f"unknown corpus '{name}'; known: {sorted(CORPUS_PATHS)}") from error
    return load_json(path)


def load_reject_corpus() -> dict[str, Any]:
    return load_corpus("reject")


def _lookup(root: dict[str, Any], dotted: str) -> Any:
    node: Any = root
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"fixture reference '{dotted}' does not resolve")
        node = node[part]
    return node


def resolve_instance(section: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    """Inline ``_ref`` members and drop ``_``-prefixed annotations.

    Returns a new dict; the loaded corpus is never mutated, so two tests can
    resolve the same entry differently without leaking state into each other.

    Any key starting with ``_`` is an annotation for the human reader (``_comment``,
    ``_signature_placeholder``) and is removed. It has to be removed rather than
    ignored by the validator, because every schema in this project is
    ``additionalProperties: false``: an annotation left in the instance would make
    a valid fixture look invalid.
    """
    resolved: dict[str, Any] = {}
    for key, value in section.items():
        if key.startswith("_"):
            continue
        if key == "payload_ref":
            if not isinstance(value, str):
                raise TypeError(f"payload_ref must be a string, got {type(value).__name__}")
            resolved["payload"] = copy.deepcopy(_lookup(root, value))
            continue
        if isinstance(value, dict) and "_ref" in value:
            resolved[key] = copy.deepcopy(_lookup(root, value["_ref"]))
            continue
        resolved[key] = copy.deepcopy(value)
    return resolved


def _substitute(node: Any, values: dict[str, str]) -> Any:
    if isinstance(node, str) and node.startswith(PLACEHOLDER_PREFIX):
        if node not in values:
            raise KeyError(f"no frozen value for placeholder '{node}'")
        return values[node]
    if isinstance(node, dict):
        return {key: _substitute(value, values) for key, value in node.items()}
    if isinstance(node, list):
        return [_substitute(item, values) for item in node]
    return copy.deepcopy(node)


def substitute_values(instance: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
    """Replace ``PLACEHOLDER_*`` tokens (recursively) with frozen values.

    A placeholder with no corresponding entry in ``values`` is an error: it means
    the generator and the corpus have drifted and the test would otherwise assert
    against a literal token. Objects and arrays are both walked, so a placeholder
    nested inside an array is resolved (or reported as unresolved) rather than
    copied through as a literal token.
    """
    substituted = _substitute(instance, values)
    if not isinstance(substituted, dict):
        raise TypeError("substitute_values expects an object instance")
    return substituted


def collect_placeholders(node: Any) -> set[str]:
    """Return every ``PLACEHOLDER_*`` token anywhere in a corpus document.

    Used by the freeze script to prove that the values it commits cover exactly
    what the fixtures reference — no dangling token, and no frozen value that
    nothing uses.
    """
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            if value.startswith(PLACEHOLDER_PREFIX):
                found.add(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and key.startswith(PLACEHOLDER_PREFIX):
                    found.add(key)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(node)
    return found