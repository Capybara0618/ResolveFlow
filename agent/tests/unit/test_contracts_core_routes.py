"""C00.2b: the core OpenAPI documents must match the core route table item by item.

docs/core-contracts.md section 3 is the route table and section 6 makes C00 responsible
for ``核心路由与核心OpenAPI逐项对应``. That only means something if the table is read out
of the document instead of being restated here: a route quietly dropped from the table
while the OpenAPI keeps it - or the reverse - has to fail.

The commerce and agent documents are covered here; the case document arrives in the last
sub-step of C00.2b, and every owner's route count is pinned now so the core surface cannot
shrink unnoticed while it is still missing.
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

#: docs/core-contracts.md section 3, pinned per owner. C00 delivers all of them; a
#: document that quietly stops covering one is what these numbers are here to catch.
#: Commerce went 4 -> 5 in C01.2: the Case row already said its order view calls
#: Commerce internally, but no listing route existed for it to call (see the C01.2
#: record in tasks/todo.md).
EXPECTED_ROUTE_COUNTS = {"Case": 18, "Commerce": 5, "Agent": 5}

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


class DocumentSpec(NamedTuple):
    """What one core document owes: its owner's routes plus its own protocol facts."""

    owner: str
    security_scheme: str
    min_examples: int
    example_components: frozenset[str]


DOCUMENTS: dict[str, DocumentSpec] = {
    "commerce": DocumentSpec(
        owner="Commerce",
        security_scheme="serviceToken",
        min_examples=7,
        example_components=frozenset(
            {"LineContext", "ShipmentSnapshot", "LineRefundStatus", "RefundOperationView"}
        ),
    ),
    "agent": DocumentSpec(
        owner="Agent",
        security_scheme="caseDispatcherToken",
        min_examples=11,
        example_components=frozenset(
            {"HealthResponse", "RunRequest", "RunAccepted", "RunView", "CancelAck", "ObservationRecord"}
        ),
    ),
    "case": DocumentSpec(
        owner="Case",
        security_scheme="bearerAuth",
        min_examples=14,
        example_components=frozenset(
            {
                "LoginResponse",
                "OrderLinePage",
                "CaseSnapshot",
                "AgentCallbackRequest",
                "AgentCallbackResponse",
                "ToolCredentialResponse",
                "EvidenceListResponse",
                "PolicyManifestResponse",
            }
        ),
    ),
}


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


def document(service: str) -> dict[str, Any]:
    return load_openapi(service, CORE_DIR)


def document_routes(service: str) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, item in document(service)["paths"].items()
        for method in item
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    }


def operation_ids(service: str) -> list[str]:
    return [
        operation["operationId"]
        for item in document(service)["paths"].values()
        for method, operation in item.items()
        if method.lower() in {"get", "post"}
    ]


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
    counts: dict[str, int] = {}
    for route in route_table():
        counts[route.owner] = counts.get(route.owner, 0) + 1
    assert counts == EXPECTED_ROUTE_COUNTS
    assert len(route_table()) == sum(EXPECTED_ROUTE_COUNTS.values())


def test_route_table_has_no_duplicate_route() -> None:
    routes = [(route.owner, route.method, route.path) for route in route_table()]
    assert len(routes) == len(set(routes))


def test_every_route_is_under_a_versioned_http_prefix() -> None:
    for route in route_table():
        # /health is the one unversioned route in the table (agents are probed by the
        # orchestrator, not by a versioned API client).
        assert route.path.startswith(("/api/v1/", "/internal/v1/")) or route.path == "/health", route
        assert route.method in {"GET", "POST"}, route


# ------------------------------------------------------------------ per document


@pytest.mark.parametrize("service", sorted(DOCUMENTS))
def test_document_declares_exactly_the_routes_of_its_owner(service: str) -> None:
    assert document_routes(service) == owner_routes(DOCUMENTS[service].owner)


@pytest.mark.parametrize("service", sorted(DOCUMENTS))
def test_document_marks_the_core_profile(service: str) -> None:
    info = document(service)["info"]
    assert info["version"] == "core-v1.2"
    assert info["x-core-profile"] == "core-v1.2"
    assert info["x-core-schema-version"] == 2


@pytest.mark.parametrize("service", sorted(DOCUMENTS))
def test_document_does_not_expose_the_deferred_surface(service: str) -> None:
    paths = " ".join(document(service)["paths"])
    for fragment in DEFERRED_PATH_FRAGMENTS:
        assert fragment not in paths, f"{fragment} must stay out of contracts/core/openapi-{service}.yaml"
    schemas = document(service)["components"]["schemas"]
    if "Action" in schemas:
        # Naming an Action enum is allowed only while it stays single-valued.
        assert schemas["Action"]["enum"] == ["REFUND"], f"{service} declares more than one executable action"
    assert "EntitlementStateView" not in schemas
    assert "EntitlementState" not in schemas


@pytest.mark.parametrize("service", sorted(DOCUMENTS))
def test_document_is_authenticated_by_its_service_token(service: str) -> None:
    document_ = document(service)
    scheme = DOCUMENTS[service].security_scheme
    assert document_["security"] == [{scheme: []}]
    assert document_["components"]["securitySchemes"][scheme]["bearerFormat"] == "JWT"


@pytest.mark.parametrize("service", sorted(DOCUMENTS))
def test_every_reference_in_the_document_resolves_inside_it(service: str) -> None:
    document_ = document(service)
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
    assert references, f"openapi-{service}.yaml declares no references at all"
    for reference in references:
        assert not reference.startswith("urn:resolveflow:"), f"{reference} couples core to the compat protocol"
        resolve_pointer(document_, reference)


@pytest.mark.parametrize("service", sorted(DOCUMENTS))
def test_core_error_body_is_unchanged_from_the_compat_baseline(service: str) -> None:
    core_error = document(service)["components"]["schemas"]["ApiError"]
    compat_error = load_openapi(service)["components"]["schemas"]["ApiError"]
    assert core_error == compat_error, "docs/core-contracts.md:15 keeps the error body as it was"


@pytest.mark.parametrize("service", sorted(DOCUMENTS))
def test_operations_have_ids_and_cite_their_authority(service: str) -> None:
    """A target document that does not say where its rules come from cannot be reviewed."""
    identifiers = operation_ids(service)
    assert len(identifiers) == len(set(identifiers)), f"duplicate operationId in openapi-{service}.yaml"
    for path, item in document(service)["paths"].items():
        for method, operation in item.items():
            if method.lower() not in {"get", "post"}:
                continue
            assert operation.get("summary"), f"{method} {path} has no summary"
            if path == "/health":
                # Liveness has no business rule to cite, and inventing one would be worse
                # than the missing pointer.
                continue
            description = operation.get("description", "")
            assert "docs/" in description, f"{method} {path} does not cite its authority document"


@pytest.mark.parametrize("service", sorted(DOCUMENTS))
def test_every_core_openapi_document_declares_the_core_profile(service: str) -> None:
    directory = REPO_ROOT / CORE_DIR
    names = {path.name for path in directory.glob("openapi-*.yaml")}
    assert f"openapi-{service}.yaml" in names


def test_no_compat_document_was_copied_into_the_core_directory() -> None:
    directory = REPO_ROOT / CORE_DIR
    for path in directory.glob("openapi-*.yaml"):
        service = path.name.removeprefix("openapi-").removesuffix(".yaml")
        assert document(service)["info"].get("x-core-profile") == "core-v1.2", f"{path.name} is not a core document"
    assert not (directory / "openapi-fulfillment.yaml").exists()


# -------------------------------------------------------------------------- examples


def operation_examples(service: str) -> list[tuple[str, str, Any]]:
    """Every example in a document, paired with the component it must satisfy."""
    document_ = document(service)
    collected: list[tuple[str, str, Any]] = []

    def from_media(where: str, media: dict[str, Any]) -> None:
        reference = media.get("schema", {}).get("$ref", "")
        if "example" in media and reference.startswith("#/components/schemas/"):
            collected.append((reference.rsplit("/", 1)[-1], where, media["example"]))

    for path, item in document_["paths"].items():
        for method, operation in item.items():
            if method.lower() not in {"get", "post"}:
                continue
            where = f"{method.upper()} {path}"
            for media in operation.get("requestBody", {}).get("content", {}).values():
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


@pytest.mark.parametrize("service", sorted(DOCUMENTS))
def test_examples_validate_against_their_own_schemas(service: str) -> None:
    examples = operation_examples(service)
    expected = DOCUMENTS[service].min_examples
    assert len(examples) >= expected, (
        f"expected at least {expected} examples in openapi-{service}.yaml, got {len(examples)}"
    )
    for component, where, example in examples:
        validator = component_validator(service, component, CORE_DIR, CORE_SCHEMA_FILES)
        errors = validator.error_messages(example)
        assert not errors, f"example at {where} does not satisfy {component}:\n  " + "\n  ".join(errors)
    used = {component for component, _, _ in examples}
    assert DOCUMENTS[service].example_components <= used


# --------------------------------------------------------- core-only narrowing rules


def core_operation_states_from_authority() -> list[str]:
    """The five-state core vocabulary, read from docs/domain-model.md rather than copied."""
    text = (REPO_ROOT / "docs" / "domain-model.md").read_text(encoding="utf-8")
    match = re.search(r"核心退款operation用([A-Z_/]+)", text)
    assert match, "docs/domain-model.md no longer states which refund operation states core uses"
    return match.group(1).split("/")


def operation_state_values(service: str) -> list[str]:
    """The operation-state vocabulary of a document, wherever it keeps it."""
    schemas = document(service)["components"]["schemas"]
    if "OperationState" in schemas:
        return schemas["OperationState"]["enum"]
    state = schemas["OperationView"]["properties"]["state"]
    assert "$ref" not in state, "OperationView.state points at a component this test cannot see"
    return state["enum"]


@pytest.mark.parametrize("service", ["commerce", "case"])
def test_operation_state_is_the_core_five(service: str) -> None:
    states = operation_state_values(service)
    assert states == core_operation_states_from_authority()
    compat_states = {member.value for member in enums.OperationState}
    assert {"STARTING", "CANCELLED", "TARGET_SUCCEEDED"} <= compat_states, "compat keeps the two-phase protocol"
    assert not {"STARTING", "CANCELLED", "TARGET_SUCCEEDED"} & set(states)


def test_commerce_line_refund_state_narrows_the_compat_entitlement_enum() -> None:
    core_states = document("commerce")["components"]["schemas"]["LineRefundState"]["enum"]
    assert core_states == ["FREE", "RESERVED", "CONSUMED"]
    # The compat enum keeps IN_USE for the deferred cross-service protocol; core does not.
    assert "IN_USE" in {member.value for member in enums.EntitlementState}
    assert "IN_USE" not in core_states


def test_commerce_synthetic_marker_is_required_and_constant() -> None:
    snapshot = document("commerce")["components"]["schemas"]["ShipmentSnapshot"]
    assert "synthetic" in snapshot["required"]
    synthetic = snapshot["properties"]["synthetic"]
    assert synthetic["type"] == "boolean" and synthetic["const"] is True
    assert synthetic["description"]


@pytest.mark.parametrize("name", ["OrderLineSummary", "OrderLinePage", "PageMeta"])
def test_the_internal_order_view_is_the_public_order_view(name: str) -> None:
    """Case's public order view and Commerce's internal one must be the same shape.

    Case owns the public Order API (docs/core-contracts.md:53) and builds it from Commerce's
    listing route (docs/core-contracts.md:26), which C01.2 added because the table named the
    dependency without giving it a route. Two documents describing one payload is how a member ends
    up added on one side only, so the two definitions are compared literally: the shared primitives
    they point at (Uuid/AmountMinor/Version) are byte-identical apart from the URN prefix, so any
    difference here is a real divergence rather than a naming artifact.
    """
    public = document("case")["components"]["schemas"][name]
    internal = document("commerce")["components"]["schemas"][name]

    assert internal == public


def test_the_order_listing_route_takes_its_scope_from_the_caller_not_the_client() -> None:
    op = document("commerce")["paths"]["/internal/v1/order-lines"]["get"]
    names = [param["$ref"].rsplit("/", 1)[-1] for param in op["parameters"]]
    assert names == ["MerchantId", "CustomerId", "OrderId", "LineId", "Cursor", "Limit"]
    params = document("commerce")["components"]["parameters"]
    assert params["MerchantId"]["required"] is True
    assert params["CustomerId"]["required"] is False, "a merchant-scoped caller lists the whole merchant"
    # order_id and line_id narrow the same scope; both are filters, not a second scope
    assert params["OrderId"]["required"] is False
    assert params["LineId"]["required"] is False, (
        "Case asks whether one line is inside the caller's scope before opening a case; a required"
        " line_id would make that a listing by line instead of a scoped narrowing"
    )
    # The scope exists only on the internal route. If the public Case route offered merchant_id or
    # customer_id, a customer could ask for someone else's lines (docs/core-contracts.md:15).
    public = document("case")["paths"]["/api/v1/orders"]["get"]
    public_names = {
        document("case")["components"]["parameters"][param["$ref"].rsplit("/", 1)[-1]]["name"]
        for param in public["parameters"]
        if "$ref" in param
    }
    assert not {"merchant_id", "customer_id", "scope"} & public_names
    assert "内部请求Commerce" in (
        REPO_ROOT / "docs" / "core-contracts.md"
    ).read_text(encoding="utf-8"), "the authority that made this route necessary moved"


@pytest.mark.parametrize("service", ["agent", "case"])
def test_requested_action_is_refund_only(service: str) -> None:
    requested = document(service)["components"]["schemas"]["RequestedAction"]["enum"]
    assert requested == ["REFUND"]
    compat = load_openapi(service)["components"]["schemas"]["RequestedAction"]["enum"]
    assert "RESHIP" in compat, "the compat document keeps the v1 vocabulary"


def test_agent_evidence_source_types_are_all_re_readable_in_core() -> None:
    core_types = document("agent")["components"]["schemas"]["EvidenceSourceType"]["enum"]
    assert "LINE_ENTITLEMENT" not in core_types
    assert "PACKING_MANIFEST" not in core_types
    assert "SHIPMENT" in core_types and "POLICY_RULE" in core_types
    compat_types = load_openapi("agent")["components"]["schemas"]["EvidenceSourceType"]["enum"]
    assert "LINE_ENTITLEMENT" in compat_types and "PACKING_MANIFEST" in compat_types


def test_agent_health_needs_no_service_token() -> None:
    assert document("agent")["paths"]["/health"]["get"]["security"] == []


def test_agent_run_accepted_does_not_borrow_case_vocabulary() -> None:
    accepted = document("agent")["components"]["schemas"]["RunAccepted"]
    status = accepted["properties"]["status"]
    assert status["const"] == "QUEUED"
    assert "enum" not in status, "a single committed status does not need an enum"
    assert "ANALYZING" not in {status["const"]}
    compat_status = load_openapi("agent")["components"]["schemas"]["RunAccepted"]["properties"]["status"]
    assert "ANALYZING" in compat_status["enum"], "the compat document keeps the v1 vocabulary"
    # CaseStatus.ANALYZING stays a case value; RunStatus never contains it.
    assert "ANALYZING" in {member.value for member in enums.CaseStatus}
    assert "ANALYZING" not in {member.value for member in enums.RunStatus}


def test_agent_run_view_status_is_the_run_state_machine() -> None:
    status = document("agent")["components"]["schemas"]["RunView"]["properties"]["status"]["enum"]
    assert status == [member.value for member in enums.RunStatus]


def test_missing_core_document_fails_loudly() -> None:
    with pytest.raises(FileNotFoundError):
        load_openapi("fulfillment", CORE_DIR)


def test_case_internal_routes_require_the_service_token() -> None:
    for path, item in document("case")["paths"].items():
        for method, operation in item.items():
            if method.lower() not in {"get", "post"}:
                continue
            if path.startswith("/internal/"):
                declared = operation.get("security")
                assert declared == [{"serviceToken": []}], f"{method} {path} must not accept a user token"
            elif path == "/api/v1/auth/login":
                assert operation.get("security") == [], "login cannot require the token it hands out"
            else:
                declared = operation.get("security", [{"bearerAuth": []}])
                assert declared == [{"bearerAuth": []}], f"{method} {path} must accept the user token"


def test_case_has_no_policy_management_route() -> None:
    paths = list(document("case")["paths"])
    assert "/api/v1/policies/import" not in paths
    assert not [path for path in paths if path.endswith(("/publish", "/revoke"))]
    # The read-only policy surfaces core does keep:
    assert "/internal/v1/policies/{bundle_id}" in paths
    assert "/internal/v1/cases/{case_id}/policy-manifest" in paths


def test_every_internal_route_declares_both_refusals_of_the_service_filter() -> None:
    """An internal route can refuse a request in two ways, and both are part of its contract.

    The filter answers a missing or broken token with 401 and a valid *user* token with 403
    (docs/core-contracts.md:15) before any handler runs. A route that declares only 404 leaves a
    caller unable to tell "my service token is wrong" from "that case does not exist" — and the
    policy read route shipped that way until C03.1a, so this asserts it for every internal route
    rather than for the one that was noticed.
    """
    offenders: list[str] = []
    for service in ("case", "commerce", "agent"):
        for path, item in document(service)["paths"].items():
            if not path.startswith("/internal/"):
                continue
            for method, operation in item.items():
                if method.lower() not in {"get", "post"}:
                    continue
                responses = operation.get("responses", {})
                if not {"401", "403"} <= set(responses):
                    offenders.append(f"{method.upper()} {path} ({service})")
    assert offenders == [], f"internal routes must declare 401 and 403: {offenders}"


def test_the_policy_read_route_serves_the_text_a_citation_is_checked_against() -> None:
    """The bundle route is the source of truth for a citation (docs/core-contracts.md:51).

    Two things have to be true of it: it is service-only, and the rules it returns are the rules
    themselves. The effective window is deliberately absent from the response — it decides *which*
    version applies (by payment time, docs/core-contracts.md:50), and the schema forbids extra
    members, so a window in the response would be a contract violation, not extra information.
    """
    operation = document("case")["paths"]["/internal/v1/policies/{bundle_id}"]["get"]
    assert operation["security"] == [{"serviceToken": []}]
    assert {"200", "401", "403", "404"} <= set(operation["responses"])

    bundle = document("case")["components"]["schemas"]["PolicyBundle"]
    assert bundle["additionalProperties"] is False
    assert set(bundle["required"]) == {"bundle_id", "version", "manifest_hash", "rules"}
    assert "effective_from" not in bundle["properties"], (
        "the window is how the version is chosen, not something the reader of the rules needs"
    )
    assert bundle["properties"]["rules"]["minItems"] >= 1, "a bundle with no rules decides nothing"


def test_case_question_callback_is_limited_to_three_questions() -> None:
    def collect(node: Any, trail: str) -> list[tuple[str, Any]]:
        found: list[tuple[str, Any]] = []
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "questions" and isinstance(value, dict) and "maxItems" in value:
                    found.append((f"{trail}/questions", value["maxItems"]))
                found.extend(collect(value, f"{trail}/{key}"))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                found.extend(collect(item, f"{trail}/{index}"))
        return found

    limits = collect(document("case")["components"], "components")
    assert limits, "no questions array declares a maxItems bound in the core case document"
    for where, limit in limits:
        assert limit <= 3, f"{where} allows {limit} questions; docs/core-contracts.md:59 allows at most 3"

def test_the_order_view_declares_what_its_dependency_can_do_to_it() -> None:
    """The public order view is a call to Commerce, so its failure modes are part of the contract.

    A downstream outage must be a declared, retryable 503 rather than an undeclared 500: a caller
    that reads a timeout as \"this order does not exist\" would quietly turn an outage into a
    refund-path surprise (docs/core-contracts.md:27). The listing needs 401 (the scope comes from
    the token), the single order needs 404 (another tenant's order is not disclosed).
    """
    paths = document("case")["paths"]
    listing = paths["/api/v1/orders"]["get"]["responses"]
    single = paths["/api/v1/orders/{order_id}"]["get"]["responses"]

    assert "503" in listing and "503" in single, "an unavailable Commerce is an answer both routes declare"
    assert "401" in listing, "the listing is scoped by the token, so it can refuse one"
    assert "401" not in single, "the single-order route says 404 rather than telling on the token"
    assert "404" in single, "an order the principal cannot see is 404, never 403"
    forbidden = paths["/api/v1/orders"]["get"].get("parameters", [])
    names = [parameter.get("$ref", "").rsplit("/", 1)[-1] for parameter in forbidden]
    assert names == ["Cursor", "Limit"], (
        "the public listing takes paging and nothing else: a scope parameter would let a caller name one"
    )

def test_a_case_is_opened_by_its_customer_and_never_by_merchant_staff() -> None:
    """The create route is a customer action, and the contract says so in its responses.

    Merchant staff work the review queue (docs/core-contracts.md:33); a merchant-scoped token
    carries no customer to attribute a case to, so the route declares 403 rather than inventing
    one. It also declares 409 for the second attempt on a line that already has an open case
    (docs/domain-model.md:26) and 404 for a line outside the caller's scope, so \"not yours\" and
    \"does not exist\" stay one answer (docs/core-contracts.md:27).
    """
    responses = document("case")["paths"]["/api/v1/cases"]["post"]["responses"]
    for code in ("201", "401", "403", "404", "409", "422"):
        assert code in responses, f"POST /api/v1/cases must declare {code}"
    assert "503" in responses, "the line check calls Commerce, so an outage is declared here too"

def test_the_case_view_is_bounded_and_declares_its_refusals() -> None:
    """The trajectory is a view, not a dump: it is capped, and the route says how it refuses.

    A trajectory endpoint without a bound is an endpoint that eventually returns a case file nobody
    can render (the review UI reads this). The bound is in the contract because the reader needs to
    know how much of a history it will be asked to show, and because \"read the whole timeline\"
    is not a promise any service can keep.
    """
    route = document("case")["paths"]["/api/v1/cases/{case_id}"]["get"]
    assert "401" in route["responses"], "the scope comes from the token, so it can refuse one"
    assert "404" in route["responses"], "another tenant's case is not disclosed"

    snapshot = document("case")["components"]["schemas"]["CaseSnapshot"]
    assert snapshot["required"] == ["case"], (
        "only the case itself is always present; proposal/authorisation/operation appear when they exist"
    )
    assert snapshot["properties"]["timeline"]["maxItems"] <= 200
    assert snapshot["properties"]["evidence"]["maxItems"] <= 64
    event = document("case")["components"]["schemas"]["TimelineEvent"]["properties"]
    assert "revision" in event, "an event reports the input revision it belongs to"

def test_evidence_provenance_is_part_of_the_protocol() -> None:
    """Material is provenance: who asserted it decides what it can mean.

    The evidence route accepts an evidence_kind, and the kind list mixes two very different things —
    what a person says, and what the system read from Commerce or policy. A protocol that let a
    client submit SHIPMENT would let it fabricate a carrier fact, so the route declares 403 for the
    kinds a client may not assert, and the enum member that records the append exists so the
    trajectory shows a revision change with a reason (docs/core-contracts.md:30).
    """
    route = document("case")["paths"]["/api/v1/cases/{case_id}/evidence"]["post"]
    for code in ("200", "401", "403", "404", "409", "422"):
        assert code in route["responses"], f"POST evidence must declare {code}"

    kinds = document("case")["components"]["schemas"]["EvidenceSourceType"]["enum"]
    person = {"CUSTOMER_STATEMENT", "REVIEWER_VERIFICATION"}
    machine = {"ORDER_LINE", "PAYMENT_LEDGER", "SHIPMENT", "SHIPMENT_TRACK", "POLICY_RULE"}
    assert person | machine == set(kinds), "every declared kind is either a person's or a machine's"
    assert not (person & machine), "a kind cannot be both somebody's statement and a system fact"

    events = document("case")["components"]["schemas"]["TimelineEventType"]["enum"]
    assert "EVIDENCE_APPENDED" in events, (
        "an input revision that moved with nothing in the trajectory would leave the case view unable"
        " to explain why"
    )

def test_cancellation_is_a_terminal_transition_the_contract_describes() -> None:
    """The first terminal edge in the core, and the contract has to say what it frees.

    A cancelled case stops occupying its line (docs/domain-model.md:26), which is a promise a client can
    observe by asking about the line again. The route also has to refuse a second cancel: a terminal case
    has no further transition, and answering 200 twice would claim two cancellations happened.
    """
    route = document("case")["paths"]["/api/v1/cases/{case_id}/cancel"]["post"]
    for code in ("200", "401", "404", "409"):
        assert code in route["responses"], f"POST cancel must declare {code}"
    description = route["description"]
    assert "releases the line" in description or "release" in description, (
        "the freed line is the part a client can check"
    )

    reason = document("case")["components"]["schemas"]["ReasonRequest"]
    assert reason["required"] == ["reason"], "a cancellation without a reason is not a cancellation"
    assert reason["properties"]["reason"]["minLength"] == 1

def test_the_event_stream_is_a_read_of_the_same_trajectory() -> None:
    """The stream must not be a second source of truth, and the token must not be in the URL.

    Two things are easy to get wrong here and both are visible in the document: an example that invents
    an event vocabulary the enum does not have (the stream then teaches clients a name the case view will
    never return), and a credential carried in the query string, where it ends up in logs and referrers
    (docs/core-contracts.md:32).
    """
    route = document("case")["paths"]["/api/v1/cases/{case_id}/events"]["get"]
    for code in ("200", "401", "404"):
        assert code in route["responses"], f"GET events must declare {code}"

    last_event = next(p for p in route["parameters"] if p.get("name") == "Last-Event-ID")
    assert last_event["in"] == "header", "resumption travels in a header, not a query parameter"
    assert last_event["required"] is False, "a client with no history yet can still subscribe"
    assert last_event["schema"]["maxLength"] == 64

    example = route["responses"]["200"]["content"]["text/event-stream"]["example"]
    event_name = next(line.split(":", 1)[1].strip() for line in example.splitlines() if line.startswith("event:"))
    events = document("case")["components"]["schemas"]["TimelineEventType"]["enum"]
    assert event_name in events, f"the example teaches {event_name}, which is not a timeline event type"
    assert "event_id" in example and "occurred_at" in example, (
        "the frame data is the case view's event object, not a smaller private shape"
    )


def test_no_route_carries_a_credential_in_the_query_string() -> None:
    """A token in a URL ends up in logs and referrers (docs/core-contracts.md:32).

    This is asserted across every core document rather than only the stream, because the rule is not about
    the stream: one route accepting `?token=` would be enough to put credentials in access logs.
    """
    suspicious = ("token", "secret", "password", "authorization", "api_key", "apikey")
    for name in ("case", "commerce", "agent"):
        for path, operations in document(name)["paths"].items():
            for method, operation in operations.items():
                for parameter in operation.get("parameters", []):
                    if isinstance(parameter, dict) and "name" in parameter:
                        lowered = parameter["name"].lower()
                    else:
                        lowered = str(parameter).lower()
                    assert not any(word in lowered for word in suspicious) or (
                        isinstance(parameter, dict) and parameter.get("in") == "header"
                    ), f"{method.upper()} {path} takes {parameter} outside a header"
