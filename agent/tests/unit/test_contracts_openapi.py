"""Prove the four OpenAPI documents describe the contract docs/contracts.md fixes.

docs/contracts.md:131 makes T02 responsible for generating
contracts/openapi-{case,commerce,fulfillment,agent}.yaml with "the required/enum/error and
examples for every interface in the tables", and for the documents and the JSON Schemas to
agree. This module checks the parts a JSON Schema cannot: that every documented route
exists in the right service document, that no route was invented, that error bodies are
the one shared shape, and that the documents are closed by default.

The route list is *parsed from docs/contracts.md* rather than copied here, so a new row in
the table fails this suite until the document implements it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from resolveflow.contracts._schemaio import REPO_ROOT, component_validator, load_json, load_openapi
from resolveflow.contracts.canonical import canonicalize
from resolveflow.contracts.corpus import OPENAPI_COMPONENTS
from resolveflow.contracts.fixtures import GENERATED_PATHS

SERVICES = ("case", "commerce", "fulfillment", "agent")
HTTP_METHODS = ("get", "post", "put", "patch", "delete")

EXPECTED_ENUMS: dict[str, Any] = load_json(GENERATED_PATHS["enums"])
FROZEN_ENUM_VALUES = {value for members in EXPECTED_ENUMS["enums"].values() for value in members}

#: Which service document owns each route docs/contracts.md documents. Section 2 (the
#: external API) is case-service's; sections 3-5 split the internal surfaces by the service
#: that owns the data. A route appears twice when the document says both commerce and
#: fulfillment answer it for their own operation.
OWNER: frozenset[tuple[str, str, str]] = frozenset(
    {
        # docs/contracts.md section 2, external API. case-service also fronts login and the
        # read-only order views; the gateway is not a separate contract.
        ("case", "POST", "/api/v1/auth/login"),
        ("case", "GET", "/api/v1/orders"),
        ("case", "GET", "/api/v1/orders/{order_id}"),
        ("case", "POST", "/api/v1/cases"),
        ("case", "GET", "/api/v1/cases/{case_id}"),
        ("case", "POST", "/api/v1/cases/{case_id}/evidence"),
        ("case", "POST", "/api/v1/cases/{case_id}/cancel"),
        ("case", "GET", "/api/v1/cases/{case_id}/events"),
        ("case", "GET", "/api/v1/review/cases"),
        ("case", "POST", "/api/v1/cases/{case_id}/reviews"),
        ("case", "POST", "/api/v1/cases/{case_id}/manual-proposals"),
        ("case", "POST", "/api/v1/cases/{case_id}/reviewed-evidence"),
        ("case", "POST", "/api/v1/operations/{operation_id}/reconcile"),
        ("case", "POST", "/api/v1/policies/import"),
        ("case", "POST", "/api/v1/policies/{bundle_id}/publish"),
        ("case", "POST", "/api/v1/policies/{bundle_id}/revoke"),
        # docs/contracts.md section 3, the agent control plane.
        ("agent", "POST", "/internal/v1/runs"),
        ("agent", "GET", "/internal/v1/runs/{run_id}"),
        ("agent", "GET", "/internal/v1/runs/{run_id}/observations/{observation_id}"),
        ("agent", "POST", "/internal/v1/runs/{run_id}/cancel"),
        ("case", "POST", "/internal/v1/cases/{case_id}/agent-callbacks"),
        ("case", "POST", "/internal/v1/runs/{run_id}/tool-credential"),
        # docs/contracts.md section 4, business read-only interfaces.
        ("commerce", "GET", "/internal/v1/order-lines/{line_id}/context"),
        ("commerce", "GET", "/internal/v1/order-lines/{line_id}/entitlement"),
        ("fulfillment", "GET", "/internal/v1/order-lines/{line_id}/shipment"),
        ("fulfillment", "GET", "/internal/v1/order-lines/{line_id}/packing"),
        ("case", "GET", "/internal/v1/cases/{case_id}/evidence"),
        ("case", "GET", "/internal/v1/cases/{case_id}/policy-manifest"),
        ("case", "GET", "/internal/v1/policies/{bundle_id}"),
        # docs/contracts.md section 5, entitlement and operation interfaces.
        ("commerce", "POST", "/internal/v1/entitlements/reserve"),
        ("commerce", "POST", "/internal/v1/entitlements/{operation_id}/start"),
        ("commerce", "POST", "/internal/v1/entitlements/{operation_id}/commit"),
        ("commerce", "POST", "/internal/v1/entitlements/{operation_id}/release"),
        ("commerce", "GET", "/internal/v1/entitlements/{operation_id}"),
        ("commerce", "GET", "/internal/v1/operations/{operation_id}"),
        ("fulfillment", "GET", "/internal/v1/operations/{operation_id}"),
        ("commerce", "POST", "/internal/v1/operations/{operation_id}/cancel-before-start"),
        ("fulfillment", "POST", "/internal/v1/operations/{operation_id}/cancel-before-start"),
    }
)

#: Endpoints the documents add beyond the tables. Kept explicit so an invented route fails
#: the suite instead of quietly becoming part of the contract.
EXTRA_ROUTES: frozenset[tuple[str, str, str]] = frozenset({("agent", "GET", "/health")})

#: Objects that are deliberately open, with the reason. Every other object schema must
#: refuse unknown members (docs/contracts.md:131).
OPEN_OBJECTS: frozenset[str] = frozenset(
    {
        # The error body's details carry service-specific context (docs/contracts.md:14).
        "case/components/schemas/ApiError/properties/details",
        "commerce/components/schemas/ApiError/properties/details",
        "fulfillment/components/schemas/ApiError/properties/details",
        "agent/components/schemas/ApiError/properties/details",
        # An imported policy bundle is an operator-supplied document; its own schema is the
        # bundle contract, not this API's shape.
        "case/components/schemas/PolicyImportRequest/properties/bundle_json",
        # A callback payload is validated per callback kind by the callback handler.
        "case/components/schemas/AgentCallbackRequest/properties/payload",
        # A tool observation result is the tool's own output, not this API's shape.
        "agent/components/schemas/ObservationRecord/properties/result",
    }
)

#: Writes that modify an existing resource and therefore require If-Match
#: (docs/contracts.md:9), from the "returns/permissions" column of the section 2 table.
IF_MATCH_OPERATIONS: frozenset[str] = frozenset(
    {"appendEvidence", "cancelCase", "decideReview", "createManualProposal", "recordReviewedEvidence"}
)

ROUTE_PATTERN = re.compile(r"(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_\-/{}]+)")


def documented_routes() -> set[tuple[str, str]]:
    """Every method/path pair named in docs/contracts.md, tables and prose alike."""
    text = (REPO_ROOT / "docs" / "contracts.md").read_text(encoding="utf-8")
    return {(match.group(1), match.group(2)) for match in ROUTE_PATTERN.finditer(text)}


def operations(doc: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Every operation in a document as (method, path, operation)."""
    return [
        (method, path, operation)
        for path, item in doc["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    ]


def deref(doc: dict[str, Any], node: Any) -> Any:
    """Resolve an in-document ``$ref`` chain, asserting that it does resolve."""
    seen: set[str] = set()
    while isinstance(node, dict) and "$ref" in node:
        reference = node["$ref"]
        assert reference not in seen, f"circular $ref: {reference}"
        seen.add(reference)
        assert reference.startswith("#/"), f"external $ref is not allowed: {reference}"
        target: Any = doc
        for part in reference[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            assert isinstance(target, dict) and part in target, f"unresolved $ref: {reference}"
            target = target[part]
        node = target
    return node


def walk(node: Any, path: str = "") -> Any:
    """Yield (json-pointer, node) for every mapping in a document."""
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from walk(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{path}/{index}")


def parameter_names(doc: dict[str, Any], path: str, operation: dict[str, Any], location: str) -> list[str]:
    """Parameter names of one location, resolving the items that are ``$ref``s."""
    names = []
    for parameter in list(doc["paths"][path].get("parameters", [])) + list(operation.get("parameters", [])):
        resolved = deref(doc, parameter)
        assert "name" in resolved and "in" in resolved, f"malformed parameter in {path}: {parameter}"
        if resolved["in"] == location:
            names.append(resolved["name"])
    return names


@pytest.fixture(params=SERVICES)
def service(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def test_every_documented_route_is_owned_by_a_named_service() -> None:
    # If the Markdown gains a row, this fails until someone decides which service owns it
    # and which document implements it. A route is never silently dropped.
    documented = documented_routes()
    assert documented == {(method, path) for _, method, path in OWNER}
    assert len(documented) >= 35


def test_no_document_invents_a_route() -> None:
    implemented = {
        (name, method.upper(), path) for name in SERVICES for method, path, _ in operations(load_openapi(name))
    }
    assert implemented - OWNER == set(EXTRA_ROUTES)
    assert OWNER - implemented == set()


def test_documents_declare_openapi_31_and_a_real_info_block(service: str) -> None:
    doc = load_openapi(service)
    assert doc["openapi"].startswith("3.1")
    assert doc["info"]["title"] and doc["info"]["version"]
    assert len(doc["info"]["description"].strip()) > 40
    assert doc["servers"] and doc["servers"][0]["url"]


def test_documents_declare_both_security_schemes(service: str) -> None:
    # docs/contracts.md:9-10: bearer JWT externally, service JWT internally. The
    # document-level requirement is what every operation inherits.
    doc = load_openapi(service)
    schemes = doc["components"]["securitySchemes"]
    assert schemes, service
    assert any(entry.get("scheme") == "bearer" for entry in schemes.values()), service
    assert doc.get("security"), service


def test_every_operation_is_described(service: str) -> None:
    for method, path, operation in operations(load_openapi(service)):
        for field in ("operationId", "summary", "description", "tags"):
            assert operation.get(field), f"{service} {method.upper()} {path} has no {field}"


def test_operation_ids_are_unique_within_a_document(service: str) -> None:
    identifiers = [operation["operationId"] for _, _, operation in operations(load_openapi(service))]
    assert len(set(identifiers)) == len(identifiers), service


def test_every_templated_path_parameter_is_declared_and_required(service: str) -> None:
    doc = load_openapi(service)
    for method, path, operation in operations(doc):
        declared = parameter_names(doc, path, operation, "path")
        for token in [part for part in path.split("/") if part.startswith("{")]:
            assert token.strip("{}") in declared, f"{service} {method.upper()} {path} does not declare {token}"
        for parameter in list(doc["paths"][path].get("parameters", [])) + list(operation.get("parameters", [])):
            resolved = deref(doc, parameter)
            if resolved["in"] == "path":
                assert resolved.get("required") is True, f"{service} {path}: {resolved['name']} is not required"


def test_every_operation_documents_an_error_response(service: str) -> None:
    # /health is the one exception: a liveness probe has no error body to describe.
    doc = load_openapi(service)
    for method, path, operation in operations(doc):
        if path == "/health":
            continue
        errors = {str(code): response for code, response in operation["responses"].items() if str(code)[0] in "45"}
        assert errors, f"{service} {method.upper()} {path} documents no error response"
        for code, response in errors.items():
            media = deref(doc, response).get("content", {}).get("application/json", {})
            reference = media.get("schema", {}).get("$ref", "")
            assert reference.endswith("ErrorResponse"), f"{service} {method.upper()} {path} {code} is not ErrorResponse"


def test_external_writes_require_an_idempotency_key(service: str) -> None:
    # docs/contracts.md:9: external writes require Idempotency-Key. Login is exempt: it
    # creates no resource, so replaying it is harmless.
    doc = load_openapi(service)
    for method, path, operation in operations(doc):
        if method != "post" or not path.startswith("/api/v1") or path == "/api/v1/auth/login":
            continue
        assert "Idempotency-Key" in parameter_names(doc, path, operation, "header"), f"{method.upper()} {path}"


def test_keyed_writes_document_the_conflict_they_can_return(service: str) -> None:
    # docs/contracts.md:13: the same key with a different payload is 409. A keyed write
    # that cannot return 409 would leave that case undocumented.
    doc = load_openapi(service)
    for method, path, operation in operations(doc):
        if "Idempotency-Key" not in parameter_names(doc, path, operation, "header"):
            continue
        assert "409" in {str(code) for code in operation["responses"]}, f"{method.upper()} {path}"


def test_resource_modifications_require_if_match(service: str) -> None:
    doc = load_openapi(service)
    for method, path, operation in operations(doc):
        if operation["operationId"] not in IF_MATCH_OPERATIONS:
            continue
        assert "If-Match" in parameter_names(doc, path, operation, "header"), f"{method.upper()} {path}"


def test_every_response_component_has_an_example(service: str) -> None:
    # docs/contracts.md:131 asks for examples, and an error body is the response a client
    # author actually writes code against.
    doc = load_openapi(service)
    for name, response in doc["components"]["responses"].items():
        media = response.get("content", {}).get("application/json", {})
        assert media.get("example") or media.get("examples"), f"{service}.{name} has no example"


def test_every_request_body_has_an_example(service: str) -> None:
    doc = load_openapi(service)
    for method, path, operation in operations(doc):
        body = operation.get("requestBody")
        if not body:
            continue
        media = deref(doc, body).get("content", {}).get("application/json", {})
        assert media.get("example") or media.get("examples"), f"{method.upper()} {path} has no request example"


def test_error_examples_use_a_frozen_error_code(service: str) -> None:
    # An example with a code the enum does not declare teaches clients a value the server
    # will never send.
    codes = set(EXPECTED_ENUMS["enums"]["error_code"])
    doc = load_openapi(service)
    for name, response in doc["components"]["responses"].items():
        example = response.get("content", {}).get("application/json", {}).get("example")
        if not example:
            continue
        assert example["code"] in codes, f"{service}.{name}: {example['code']}"
        assert example["trace_id"], f"{service}.{name} has no trace_id"
        assert isinstance(example["retryable"], bool), f"{service}.{name}"


def test_every_enum_value_is_a_frozen_wire_value(service: str) -> None:
    # Catches the typo class of bug: RefundRequested misspelled in one document would be
    # emitted by no consumer and would appear in no frozen enum group.
    doc = load_openapi(service)
    for pointer, node in walk(doc):
        members = node.get("enum") if isinstance(node, dict) else None
        if not members:
            continue
        for value in members:
            assert value in FROZEN_ENUM_VALUES, f"{service}{pointer}: {value!r} is not a frozen wire value"


def test_object_schemas_are_closed_unless_listed_as_open(service: str) -> None:
    # Two rules. A declared object must say whether it is open, because silently relying
    # on the JSON Schema default is how a field added by one service disappears at the
    # next hop. And anything that *is* open has to be listed above with its reason, so
    # "we forgot additionalProperties: false" cannot hide as an open object.
    doc = load_openapi(service)
    open_objects = set()
    for pointer, node in walk(doc["components"]["schemas"]):
        types = node.get("type")
        is_object = types == "object" or (isinstance(types, list) and "object" in types)
        if "properties" in node or is_object:
            assert "additionalProperties" in node, (
                f"{service}/components/schemas{pointer} has properties but never says whether it is open"
            )
        if node.get("additionalProperties") is True:
            open_objects.add(f"{service}/components/schemas{pointer}")
    assert open_objects == {path for path in OPEN_OBJECTS if path.startswith(service)}


def test_api_error_components_are_identical_across_services() -> None:
    # docs/contracts.md:14 fixes one error body. Four hand-written copies is how they start
    # to differ, so the copies are compared rather than trusted.
    errors = {name: canonicalize(load_openapi(name)["components"]["schemas"]["ApiError"]) for name in SERVICES}
    assert len(set(errors.values())) == 1, errors
    responses = {name: canonicalize(load_openapi(name)["components"]["schemas"]["ErrorResponse"]) for name in SERVICES}
    assert len(set(responses.values())) == 1, responses


def test_error_response_is_the_flat_body_the_spec_and_java_use() -> None:
    # docs/contracts.md:14 gives {code,message,retryable,trace_id,details} as the body, and
    # com.resolveflow.shared.error.ApiError serialises exactly that. An envelope around it
    # would disagree with both.
    for name in SERVICES:
        doc = load_openapi(name)
        schemas = doc["components"]["schemas"]
        assert deref(doc, schemas["ErrorResponse"]) == schemas["ApiError"], name
        assert set(schemas["ApiError"]["properties"]) == {"code", "message", "retryable", "trace_id", "details"}, name
        assert schemas["ApiError"]["required"] == ["code", "message", "retryable"], name


def test_every_reference_resolves_within_its_document(service: str) -> None:
    doc = load_openapi(service)
    for _, node in walk(doc):
        if isinstance(node, dict) and "$ref" in node:
            deref(doc, node)


def test_status_codes_are_three_digit_strings(service: str) -> None:
    # YAML turns 200 into an integer; OpenAPI requires the string form, and a document that
    # mixes them is a trap for every generator.
    doc = load_openapi(service)
    for method, path, operation in operations(doc):
        for code in operation["responses"]:
            assert isinstance(code, str) and re.fullmatch(r"[1-5][0-9]{2}", code), f"{method.upper()} {path}: {code!r}"


def test_the_route_list_is_parsed_from_the_markdown_not_hand_copied() -> None:
    # Guards the guard: if the parser stopped matching, the ownership test above would
    # compare two empty sets and pass.
    routes = documented_routes()
    assert ("POST", "/internal/v1/runs") in routes
    assert ("GET", "/internal/v1/order-lines/{line_id}/context") in routes
    assert ("POST", "/internal/v1/runs/{run_id}/tool-credential") in routes


def test_the_documents_are_valid_yaml_at_their_expected_paths() -> None:
    found = {path.name for path in Path(REPO_ROOT / "contracts").glob("openapi-*.yaml")}
    assert found == {f"openapi-{name}.yaml" for name in SERVICES}
    for name in SERVICES:
        document = yaml.safe_load((REPO_ROOT / "contracts" / f"openapi-{name}.yaml").read_text(encoding="utf-8"))
        assert document["info"]["title"].startswith("ResolveFlow")
        assert len(document["info"]["description"].strip()) > 40


def test_component_names_used_by_the_corpus_exist() -> None:
    # The corpus maps samples to (service, component); a rename would otherwise surface as a
    # confusing "unknown component" error in the generator.
    for section, (name, component) in OPENAPI_COMPONENTS.items():
        assert component in load_openapi(name)["components"]["schemas"], f"{section} -> {name}.{component}"

def component_name(media: dict[str, Any]) -> str:
    """The ``components.schemas`` name a media type's example is an instance of."""
    return str(media.get("schema", {}).get("$ref", "")).split("/")[-1]


def assert_example_validates(service: str, component: str, media: dict[str, Any], where: str) -> None:
    """Fail if the media type carries an example that its own schema rejects."""
    example = media.get("example")
    if not component or example is None:
        return
    errors = component_validator(service, component).error_messages(example)
    assert not errors, f"{service} {where} example is not a valid {component}: " + "; ".join(errors[:3])


def test_every_request_example_satisfies_its_schema(service: str) -> None:
    # An example that does not validate is worse than no example: it is the shape a client
    # author copies. This also catches YAML quietly typing a 64-digit hash as a number.
    doc = load_openapi(service)
    for method, path, operation in operations(doc):
        body = operation.get("requestBody")
        if not body:
            continue
        media = deref(doc, body).get("content", {}).get("application/json", {})
        assert_example_validates(service, component_name(media), media, f"{method.upper()} {path} request")


def test_every_response_example_satisfies_its_schema(service: str) -> None:
    # Success bodies are the ones a client parses; the error bodies are covered separately
    # so a violation says which of the two broke.
    doc = load_openapi(service)
    for method, path, operation in operations(doc):
        for code, response in operation["responses"].items():
            if str(code)[0] not in "23":
                continue
            media = deref(doc, response).get("content", {}).get("application/json", {})
            assert_example_validates(service, component_name(media), media, f"{method.upper()} {path} {code}")


def test_error_examples_satisfy_the_shared_error_body(service: str) -> None:
    doc = load_openapi(service)
    for name, response in doc["components"]["responses"].items():
        media = response.get("content", {}).get("application/json", {})
        component = component_name(media) or "ApiError"
        assert_example_validates(service, component, media, f"responses.{name}")


def test_every_error_response_example_satisfies_the_error_body(service: str) -> None:
    doc = load_openapi(service)
    for method, path, operation in operations(doc):
        for code, response in operation["responses"].items():
            if str(code)[0] not in "45":
                continue
            media = deref(doc, response).get("content", {}).get("application/json", {})
            component = component_name(media) or "ApiError"
            assert_example_validates(service, component, media.get("example"), f"{method.upper()} {path} {code}")
