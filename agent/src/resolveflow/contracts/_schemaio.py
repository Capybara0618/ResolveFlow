"""Read the JSON Schema contract files and resolve their ``urn:resolveflow:`` ids.

The four schemas cross-reference each other by ``$id`` rather than by relative
path, so a plain validator cannot resolve ``$ref`` on its own. This registry maps
each id to its document and is shared by the fixture test, the hash freezing
script and any future conformance check, so all three resolve references the same
way.

JSON Schema 2020-12 is used together with OpenAPI 3.1, which embeds exactly this
dialect; ``contracts/openapi-*.yaml`` therefore reuses these component schemas
instead of restating them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

__all__ = [
    "CORE_SCHEMA_FILES",
    "REPO_ROOT",
    "SCHEMA_FILES",
    "ValidatorBundle",
    "component_validator",
    "format_checker",
    "load_json",
    "load_openapi",
    "schema_registry",
]


def _repo_root() -> Path:
    # agent/src/resolveflow/contracts/_schemaio.py -> repository root
    return Path(__file__).resolve().parents[4]


REPO_ROOT = _repo_root()

#: The T02 compat baseline: the hand-authored schemas that make up the v1 protocol.
#: OpenAPI documents are checked separately because they are generated from
#: docs/contracts.md, not derived from these files. Kept as-is after the v1.2 re-scope:
#: ``docs/core-scope.md:34`` keeps the old protocol, fixtures and tests as compat assets.
SCHEMA_FILES = (
    "contracts/event-envelope.schema.json",
    "contracts/execution-command.schema.json",
    "contracts/execution-result-event.schema.json",
    "contracts/agent-proposal.schema.json",
    "contracts/harness-manifest.schema.json",
)

#: The core-v1.2 protocol schemas (docs/core-contracts.md section 1). They live beside
#: the compat baseline instead of replacing it: the old files keep their ``$id``s and
#: version numbers, so an old consumer cannot be silently upgraded into v2. The core
#: set grows as C00 adds documents; every entry here must exist on disk.
CORE_SCHEMA_FILES = (
    "contracts/core/refund-command.schema.json",
    "contracts/core/event-envelope.schema.json",
)

#: RFC 3339, as used by every ``format: date-time`` in the schemas. The
#: ``offset`` may be ``Z`` or a numeric offset; a naive local timestamp is not
#: accepted because event ordering is only meaningful across time zones when the
#: offset is present.
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$"
)


def _is_rfc3339_datetime(value: object) -> bool:
    if not isinstance(value, str) or not _RFC3339.match(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return False
    return True


def format_checker() -> FormatChecker:
    """A checker with every format the schemas actually use.

    jsonschema skips ``format`` entirely unless a checker is supplied, and its
    ``date-time`` check is only registered when the optional ``rfc3339-validator``
    dependency is installed. Without this, a fixture that violates
    ``format: date-time`` would pass by being ignored — the schema would say one
    thing and the test another. ``uuid`` is built in (registered by jsonschema)
    and is left alone.
    """
    checker = FormatChecker()
    checker.checks("date-time")(_is_rfc3339_datetime)
    return checker


def load_json(relative_path: str) -> Any:
    """Load one UTF-8 JSON file from the repository."""
    return json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))


def load_schemas(files: Sequence[str] = SCHEMA_FILES) -> dict[str, dict[str, Any]]:
    return {relative: load_json(relative) for relative in files}


def load_openapi(service: str, directory: str = "contracts") -> dict[str, Any]:
    """Load one OpenAPI document by service suffix, e.g. ``case``.

    ``directory`` selects the T02 compat baseline or the core protocol directory, so
    a core document can never overwrite the document it is migrating away from.
    """
    import yaml

    path = REPO_ROOT / directory / f"openapi-{service}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def schema_registry(
    files: Sequence[str] = SCHEMA_FILES,
) -> tuple[Registry[Any], dict[str, dict[str, Any]]]:
    """Return a ``$ref`` registry keyed by each schema's ``$id``.

    The registry is built from files on disk so a schema edited without being
    saved to the expected path fails loudly here instead of validating against a
    stale copy. ``files`` defaults to the compat baseline; the core protocol passes
    ``CORE_SCHEMA_FILES`` so the two sets never resolve each other's references.
    """
    documents = load_schemas(files)
    registry: Registry[Any] = Registry()
    for document in documents.values():
        registry = registry.with_resource(document["$id"], Resource.from_contents(document))
    return registry, documents


def _resolve_pointer(document: dict[str, Any], pointer: str) -> Any:
    """Resolve a ``/$defs/name`` style JSON pointer inside one schema document."""
    node: Any = document
    for raw in pointer.split("/"):
        if not raw:
            continue
        token = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or token not in node:
            raise KeyError(f"schema pointer '#{pointer}' does not resolve")
        node = node[token]
    return node


class ValidatorBundle:
    """A named validator plus the schema document it came from."""

    def __init__(self, name: str, schema: Any, registry: Registry[Any]) -> None:
        self.name = name
        self.schema = schema
        self.validator = Draft202012Validator(
            schema, registry=registry, format_checker=format_checker()
        )

    def error_messages(self, instance: Any) -> list[str]:
        return [f"{list(error.absolute_path)}: {error.message}" for error in self.validator.iter_errors(instance)]

    def accepts(self, instance: Any) -> bool:
        return self.validator.is_valid(instance)


def validator_bundle(name: str, files: Sequence[str] = SCHEMA_FILES) -> ValidatorBundle:
    """Build the validator for a schema path, ``$id`` or ``$id#/$defs/name``.

    The fragment form is what lets a test validate one payload variant (for
    example ``...#/$defs/reshipResult``) without restating the shared shape. It is
    applied as an absolute ``$ref`` rather than by extracting the sub-schema, so
    that a ``#/$defs/...`` reference *inside* the variant still resolves against
    its own document: extracting it would silently re-base those references on the
    fragment.
    """
    registry, documents = schema_registry(files)
    base, _, pointer = name.partition("#")
    for relative, document in documents.items():
        if relative == base or document["$id"] == base:
            if not pointer:
                return ValidatorBundle(relative, document, registry)
            _resolve_pointer(document, pointer)  # fail here, not inside a test
            return ValidatorBundle(f"{document['$id']}#{pointer}", {"$ref": name}, registry)
    raise KeyError(f"unknown schema: {name}")


def component_validator(
    service: str,
    component: str,
    directory: str = "contracts",
    files: Sequence[str] = SCHEMA_FILES,
) -> ValidatorBundle:
    """Validate against one ``components.schemas`` entry of an OpenAPI document.

    The whole OpenAPI document is registered under a synthetic URI and the
    component is referenced through it, because its own members use
    ``#/components/schemas/...`` references that only resolve against the complete
    document. Extracting the component would leave those references dangling.
    """
    document = load_openapi(service, directory)
    schemas = document.get("components", {}).get("schemas", {})
    if component not in schemas:
        raise KeyError(f"openapi-{service}.yaml declares no component '{component}'")
    registry, _ = schema_registry(files)
    uri = f"urn:resolveflow:openapi:{directory}:{service}"
    registry = registry.with_resource(uri, Resource.from_contents(document, default_specification=DRAFT202012))
    reference = f"{uri}#/components/schemas/{component}"
    return ValidatorBundle(reference, {"$ref": reference}, registry)