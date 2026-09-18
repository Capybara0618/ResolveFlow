"""C00.2b: the core OpenAPI documents must match the core route table item by item.

docs/core-contracts.md section 3 is the route table and section 6 makes C00 responsible
for ``核心路由与核心OpenAPI逐项对应``. That only means something if the table is read out
of the document instead of being restated here: a route quietly dropped from the table
while the OpenAPI keeps it - or the reverse - has to fail.

This file starts with the commerce document (four routes); the agent and case documents
arrive in the following sub-steps, and their counts are pinned now so the core surface
cannot shrink unnoticed while they are still missing.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

import pytest

from resolveflow.contracts import enums
from resolveflow.contracts._schemaio import (
    CORE_SCHEMA_FILES,
    REPO_ROOT,
    component_validator,
    load_openapi,
)

CORE_DIR = "contracts/core"
COMMERCE = "commerce"

#: docs/core-contracts.md section 3, pinned per owner. C00 delivers all of them; a
#: document that quietly stops covering one is what this number is here to catch.
EXPECTED_ROUTE_COUNTS = {"Case": 18, "Commerce": 4, "Agent": 5}

#: Routes the compat baseline has and core must not expose (docs/core-contracts.md:53).
DEFERRED_PATH_FRAGMENTS = (
    "entitlement",
    "packing",
    "reship",
    "cancel-before-start",
    "fulfillment",
)


class Route(NamedTuple):
    owner: str
    method: str
    path: str


def route_table() -> list[Route]:
    """Parse the route table out of the authority document."""
    text = (REPO_ROOT / "docs" / "core-contracts.md").read_text(encoding="utf-8")
    section = text[text.index("## 3. 核心路由") : text.index("## 4. ")]
    pattern = re.compile(
        r"^\|\s*(?P<owner>Case|Commerce|Agent)\s*\|\s*(?P<method>[A-Z]+)\s+(?P<path>/\S+)\s*\|",
        re.MULTILINE,
    )
    routes = [Route(match["owner"], match["method"], match["path"]) for match in pattern.finditer(section)]
    assert routes, "the core route table is empty or its format changed"
    return routes


def owner_routes(owner: str) -> set[tuple[str, str]]:
    return {(route.method, route.path) for route in route_table() if route.owner == owner}


def document_routes(service: str) -> set[tuple[str, str]]:
    document = load_openapi(service, CORE_DIR)
    return {
        (method.upper(), path)
        for path, item in document["paths"].items()
        for method in item
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    }


def document(service: str) -> dict[str, Any]:
    return load_openapi(service, CORE_DIR)


def resolve_pointer(document_: dict[str, Any], reference: str) -> Any:
    """Resolve a local ``#/...`` reference, following a re-exported ``$ref`` once."""
    seen: set[str] = set()
    current = reference
    while current.startswith("#/"):
        if current in seen:
            raise AssertionError(f"reference cycle at {current}")
        seen.add(current)
        node: Any = document_
        for raw in current[2:].split("/"):
            token = raw.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or token not in node:
                raise AssertionError(f"reference {current} does not resolve inside the document")
            node = node[token]
        if isinstance(node, dict) and set(node) == {"$ref"}:
            current = node["$ref"]
            continue
        return node
    raise AssertionError(f"non-local reference {reference!r}: core documents must be self-contained")


# ----------------------------------------------------------------------- route table


def test_route_table_matches_the_expected_core_surface() -> None:
    routes = route_table()
    counts: dict[str, int] = {}
    for route in routes:
        counts[route.owner] = counts.get(route.owner, 0) + 1
    assert counts == EXPECTED_ROUTE_COUNTS
    assert len(routes) == sum(EXPECTED_ROUTE_COUNTS.values())


def test_route_table_has_no_duplicate_route() -> None:
    routes = [(route.owner, route.method, route.path) for route in route_table()]
    assert len(routes) == len(set(routes))


def test_every_route_is_under_a_versioned_http_prefix() -> None:
    for route in route_table():
        # /health is the one unversioned route in the table (agents are probed by the
        # orchestrator, not by a versioned API client).
        assert route.path.startswith(("/api/v1/", "/internal/v1/")) or route.path == "/health", route
        assert route.method in {"GET", "POST"}, route


# ------------------------------------------------------------------------- commerce


def test_commerce_document_declares_exactly_the_commerce_routes() -> None:
    assert document_routes(COMMERCE) == owner_routes("Commerce")


def test_commerce_document_marks_the_core_profile() -> None:
    info = document(COMMERCE)["info"]
    assert info["version"] == "core-v1.2"
    assert info["x-core-profile"] == "core-v1.2"
    assert info["x-core-schema-version"] == 2


def test_commerce_document_does_not_expose_the_deferred_surface() -> None:
    paths = " ".join(document(COMMERCE)["paths"])
    for fragment in DEFERRED_PATH_FRAGMENTS:
        assert fragment not in paths, f"{fragment} must stay out of the core commerce document"
    schemas = document(COMMERCE)["components"]["schemas"]
    assert "Action" not in schemas, "core has one executable action; an Action enum invites a second"
    assert "EntitlementStateView" not in schemas
    assert "EntitlementState" not in schemas


def test_commerce_document_is_authenticated_by_a_service_token() -> None:
    document_ = document(COMMERCE)
    assert document_["security"] == [{"serviceToken": []}]
    assert document_["components"]["securitySchemes"]["serviceToken"]["bearerFormat"] == "JWT"


def test_every_reference_in_the_commerce_document_resolves_inside_it() -> None:
    document_ = document(COMMERCE)
    references: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref" and isinstance(value, str):
                    references.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(document_)
    assert references, "the commerce document declares no references at all"
    for reference in references:
        assert not reference.startswith("urn:resolveflow:"), f"{reference} couples core to the compat protocol"
        resolve_pointer(document_, reference)


def test_core_error_body_is_unchanged_from_the_compat_baseline() -> None:
    core_error = document(COMMERCE)["components"]["schemas"]["ApiError"]
    compat_error = load_openapi(COMMERCE)["components"]["schemas"]["ApiError"]
    assert core_error == compat_error, "docs/core-contracts.md:15 keeps the error body as it was"


def test_line_refund_state_narrows_the_compat_entitlement_enum() -> None:
    core_states = document(COMMERCE)["components"]["schemas"]["LineRefundState"]["enum"]
    assert core_states == ["FREE", "RESERVED", "CONSUMED"]
    # The compat enum keeps IN_USE for the deferred cross-service protocol; core does not.
    assert "IN_USE" in {member.value for member in enums.EntitlementState}
    assert "IN_USE" not in core_states


def test_synthetic_marker_is_required_and_constant() -> None:
    snapshot = document(COMMERCE)["components"]["schemas"]["ShipmentSnapshot"]
    assert "synthetic" in snapshot["required"]
    assert snapshot["properties"]["synthetic"] == {
        "type": "boolean",
        "const": True,
        "description": snapshot["properties"]["synthetic"]["description"],
    }


def test_commerce_route_summaries_point_at_their_authority() -> None:
    """A target document that does not say where its rules come from cannot be reviewed."""
    for path, item in document(COMMERCE)["paths"].items():
        for method, operation in item.items():
            if method.lower() not in {"get", "post"}:
                continue
            assert operation.get("summary"), f"{method} {path} has no summary"
            description = operation.get("description", "")
            assert "docs/" in description, f"{method} {path} does not cite its authority document"


# -------------------------------------------------------------------------- examples


def operation_examples(service: str) -> list[tuple[str, str, Any]]:
    """Every example in a document, paired with the component it must satisfy."""
    document_ = document(service)
    collected: list[tuple[str, str, Any]] = []

    def from_media(where: str, media: dict[str, Any]) -> None:
        schema = media.get("schema", {})
        reference = schema.get("$ref", "")
        if "example" in media and reference.startswith("#/components/schemas/"):
            collected.append((reference.rsplit("/", 1)[-1], where, media["example"]))

    for path, item in document_["paths"].items():
        for method, operation in item.items():
            if method.lower() not in {"get", "post"}:
                continue
            where = f"{method.upper()} {path}"
            body = operation.get("requestBody", {})
            for media in body.get("content", {}).values():
                from_media(where, media)
            for status, response in operation.get("responses", {}).items():
                if "$ref" in response:
                    continue
                for media in response.get("content", {}).values():
                    from_media(f"{where} -> {status}", media)
    for name, response in document_["components"].get("responses", {}).items():
        for media in response.get("content", {}).values():
            from_media(f"components.responses.{name}", media)
    return collected


def test_commerce_examples_validate_against_their_own_schemas() -> None:
    examples = operation_examples(COMMERCE)
    assert len(examples) >= 7, f"expected the four success views and three error bodies, got {len(examples)}"
    for component, where, example in examples:
        validator = component_validator(COMMERCE, component, CORE_DIR, CORE_SCHEMA_FILES)
        errors = validator.error_messages(example)
        assert not errors, f"example at {where} does not satisfy {component}:\n  " + "\n  ".join(errors)


def test_commerce_success_views_all_carry_an_example() -> None:
    used = {component for component, _, _ in operation_examples(COMMERCE)}
    assert {"LineContext", "ShipmentSnapshot", "LineRefundStatus", "RefundOperationView"} <= used


def test_missing_core_document_fails_loudly() -> None:
    with pytest.raises(FileNotFoundError):
        load_openapi("fulfillment", CORE_DIR)


def test_every_core_openapi_document_declares_the_core_profile() -> None:
    """A compat document copied into contracts/core/ would fail here."""
    core_directory = REPO_ROOT / CORE_DIR
    documents = sorted(core_directory.glob("openapi-*.yaml"))
    assert documents, "contracts/core declares no OpenAPI document"
    for path in documents:
        service = path.name.removeprefix("openapi-").removesuffix(".yaml")
        profile = document(service)["info"].get("x-core-profile")
        assert profile == "core-v1.2", f"{path.name} is not a core protocol document"