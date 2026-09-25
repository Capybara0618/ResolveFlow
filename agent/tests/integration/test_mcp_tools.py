"""C06.2b: the whitelist served over real MCP stdio, driven by a real MCP client.

``docs/agent-spec.md:34`` is explicit that the five tools are provided "通过真实官方MCP stdio tools/list和
tools/call" — through the real official MCP handshake, not a local function that happens to be named like a
tool. So this test does not import the tool functions and call them: it **spawns the server as a subprocess**,
speaks the protocol to it, lists the tools and calls them. That is the only way to know the server is one — a
Python function returning the right dict, with no server around it, would pass everything except the claim being
made.

The upstream services are a stub (:mod:`stub_upstream`), because this step is about the **tool boundary** and
not about Java. What is asserted: the exact whitelist (no more, no fewer), the argument shape of each tool, that
every result is a core observation rather than a bare dict, and the cap and failure rules of
``docs/agent-spec.md:29,36``.

The two failure rules are checked as *counts of requests*, not as codes alone. "FORBIDDEN 停止，不更换ID重试"
is a statement about what the tool did **not** do, and a code on its own cannot show the absence of a second
attempt — the stub's request log can.

One thing worth stating because it is easy to get backwards: a tool that cannot observe answers with a
**successful** MCP call carrying an error observation, not with a protocol error. ``docs/agent-spec.md:36``
wants the error *inside* the observation so ``docs/agent-harness.md:51`` can hand it back to the model, and a
protocol-level failure would instead read as "the transport hiccuped" — something a model should retry, which is
the wrong lesson for a refusal.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Any

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tests.integration import stub_upstream

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
AGENT_SRC = REPO_ROOT / "agent" / "src"

#: The whitelist of docs/agent-spec.md:26-32, written out rather than imported from the implementation: a test
#: that reads the list from the thing it is testing cannot notice a tool disappearing from it.
EXPECTED_TOOLS = {
    "get_order_context",
    "get_shipment_trace",
    "get_refund_status",
    "get_case_evidence",
    "get_policy_manifest",
}

#: 404 for its shipment (an unobserved source) and 403 for everything (a refusal). The stub keys on these.
NO_SHIPMENT_LINE = "7001"
REFUSED_LINE = "7002"
ORDINARY_LINE = "7100"
#: The case the tools are told they are working on; the contract's route table spells it {case_id}.
CASE_ID = "case-demo"


def server_parameters(upstream_url: str, line_id: str) -> StdioServerParameters:
    """The server as a child process, configured the way a deployment configures it."""
    env = dict(os.environ)
    env["RESOLVEFLOW_CASE_BASE_URL"] = upstream_url
    env["RESOLVEFLOW_COMMERCE_BASE_URL"] = upstream_url
    env["RESOLVEFLOW_TOOL_LINE_ID"] = line_id
    env["RESOLVEFLOW_TOOL_RUN_ID"] = "5f2b1c3d-0000-4000-8000-000000000001"
    env["RESOLVEFLOW_TOOL_CASE_ID"] = "case-demo"
    # The five tools each call an internal route, which wants a service token.
    env["RESOLVEFLOW_TOOL_SERVICE_TOKEN"] = "stub-service-token"
    env["PYTHONPATH"] = str(AGENT_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return StdioServerParameters(command=sys.executable, args=["-m", "resolveflow.tools.server"], env=env)


@pytest.fixture()
def upstream(tmp_path: pathlib.Path) -> Any:
    """A stub Case+Commerce on a loopback port, with its request log in this test's own directory."""
    log = tmp_path / "upstream.log"
    server = stub_upstream.start(log)
    try:
        yield server.url, log
    finally:
        server.stop()


def requests_to(log: pathlib.Path) -> list[dict[str, Any]]:
    """Every request the stub answered, in order."""
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def observation_of(result: Any) -> dict[str, Any]:
    """The structured payload of a tool result.

    The server answers with the observation as **structured content**, so a caller does not have to parse a
    sentence to find the version it must cite. ``structured_content`` is the protocol's field for that.
    """
    structured = getattr(result, "structured_content", None)
    assert structured is not None, f"the result carried no structured content: {result!r}"
    return structured


def run_session(upstream_url: str, line_id: str, body: Any) -> Any:
    async def with_session() -> Any:
        params = server_parameters(upstream_url, line_id)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await body(session)

    return anyio.run(with_session)


# --------------------------------------------------------------- the whitelist itself


def test_the_server_lists_exactly_the_whitelist(upstream: Any) -> None:
    server, _ = upstream

    async def body(session: ClientSession) -> Any:
        return await session.list_tools()

    tools = run_session(server, NO_SHIPMENT_LINE, body)
    assert {tool.name for tool in tools.tools} == EXPECTED_TOOLS


def test_every_tool_declares_the_shape_its_arguments_must_have(upstream: Any) -> None:
    server, _ = upstream

    async def body(session: ClientSession) -> Any:
        return await session.list_tools()

    tools = run_session(server, NO_SHIPMENT_LINE, body)
    by_name = {tool.name: tool for tool in tools.tools}

    # docs/agent-spec.md:26-32: three take no arguments, one takes a cursor and a bounded limit, one takes an
    # optional kind. A tool that grew an argument the spec does not allow is a permission change.
    for name in ("get_order_context", "get_refund_status", "get_policy_manifest"):
        schema = by_name[name].input_schema
        assert not schema.get("properties"), f"{name} takes no arguments but declares {schema.get('properties')}"

    trace = by_name["get_shipment_trace"].input_schema
    assert set(trace["properties"]) == {"cursor", "limit"}
    assert trace["properties"]["limit"]["maximum"] == 20, "the spec caps the page at 20"

    evidence = by_name["get_case_evidence"].input_schema
    assert set(evidence["properties"]) == {"kind"}

    # Every tool's description has to say what it reads, or a model chooses between five opaque names.
    for name, tool in by_name.items():
        assert tool.description and len(tool.description) > 20, f"{name} has no useful description"


# --------------------------------------------------------------- a successful observation


def test_a_tool_call_answers_with_a_core_observation(upstream: Any) -> None:
    """The result is the contract's observation, not a bare dict with the right-looking keys."""
    server, log = upstream

    async def body(session: ClientSession) -> Any:
        return await session.call_tool("get_order_context", {})

    result = run_session(server, ORDINARY_LINE, body)
    observation = observation_of(result)

    assert result.is_error is False, f"the call failed: {observation}"
    # The members a citation is later checked against (ObservationRecord, openapi-agent.yaml).
    for member in (
        "observation_id",
        "tool_name",
        "source_type",
        "source_ref",
        "source_version",
        "content_hash",
        "observed_at",
    ):
        assert member in observation, f"the observation has no {member}"
    assert observation["tool_name"] == "get_order_context"
    assert observation["source_type"] == "ORDER_LINE"
    assert observation["source_version"] == "3"
    # A reference is a controlled value, never a requestable URL (docs/core-contracts.md:61).
    assert not observation["source_ref"].startswith("http")
    assert len(observation["content_hash"]) == 64
    # The stored result is the body the upstream sent, so a citation has something to re-read.
    assert observation["result"]["line_paid_amount"] == 2599

    # The token travelled, and the route is the contract's: the backend re-checks the subject
    # (docs/agent-spec.md:34 — HTTP后端再次检查主体).
    sent = requests_to(log)
    assert len(sent) == 1
    assert sent[0]["authorization"] == "Bearer stub-service-token"
    assert f"/internal/v1/order-lines/{ORDINARY_LINE}/context" in sent[0]["path"]


def test_every_tool_reads_a_route_and_answers_with_an_observation(upstream: Any) -> None:
    """All five, not just the easy one: a tool that exists but cannot run is not a tool."""
    server, log = upstream

    async def body(session: ClientSession) -> Any:
        order = observation_of(await session.call_tool("get_order_context", {}))
        shipment = observation_of(await session.call_tool("get_shipment_trace", {"limit": 3}))
        refund = observation_of(await session.call_tool("get_refund_status", {}))
        evidence = observation_of(await session.call_tool("get_case_evidence", {}))
        policy = observation_of(await session.call_tool("get_policy_manifest", {}))
        return order, shipment, refund, evidence, policy

    order, shipment, refund, evidence, policy = run_session(server, ORDINARY_LINE, body)

    assert [order["source_type"], shipment["source_type"], refund["source_type"]] == [
        "ORDER_LINE",
        "SHIPMENT_TRACK",
        "PAYMENT_LEDGER",
    ]
    assert evidence["source_type"] == "CUSTOMER_STATEMENT"
    assert policy["source_type"] == "POLICY_RULE"
    # The contract's synthetic marker is carried through the tool rather than dropped: a model reading this
    # evidence has to be able to tell it is simulated (docs/core-scope.md:30).
    assert shipment["result"]["synthetic"] is True
    assert shipment["result"]["carrier_conclusion"] == "IN_TRANSIT"
    assert len(shipment["result"]["events"]) == 3

    # Five calls, five reads, and every observation id is distinct: two tools in one run must not collide.
    assert len(requests_to(log)) == 5
    ids = {
        order["observation_id"],
        shipment["observation_id"],
        refund["observation_id"],
        evidence["observation_id"],
        policy["observation_id"],
    }
    assert len(ids) == 5


# --------------------------------------------------------------- the failure rules


def test_a_not_found_is_a_failed_observation_and_not_a_negative_fact(upstream: Any) -> None:
    """``docs/agent-spec.md:36``: NOT_FOUND 不是否定事实.

    A missing shipment must not come back as "there is no shipment" — a claim about the world — but as a failure
    to observe. The distinction matters downstream: a negative fact can support a decision, an unobserved one
    cannot.
    """
    server, _ = upstream

    async def body(session: ClientSession) -> Any:
        return await session.call_tool("get_shipment_trace", {"limit": 5})

    result = run_session(server, NO_SHIPMENT_LINE, body)
    observation = observation_of(result)

    # The call itself **succeeded**: the tool did its job, and its job included reporting that it could not
    # observe. A protocol-level error would mean the argument or the server was wrong — a different thing, and
    # one a model would be right to read as a transport hiccup worth retrying.
    assert result.is_error is False
    assert observation["error"]["code"] == "NOT_FOUND"
    assert observation["error"]["retryable"] is False
    # Nothing was observed, so there is no version and no hash that could be cited. A made-up hash would make an
    # unread source look citable to a check that compares it against itself.
    assert observation.get("result") is None
    assert observation.get("source_version") is None
    assert observation.get("content_hash") is None


def test_a_forbidden_stops_and_does_not_retry_with_another_id(upstream: Any) -> None:
    """``docs/agent-spec.md:36``: FORBIDDEN 停止，不更换ID重试.

    Checked as a count of requests, because the rule is about what did **not** happen. A second attempt — with
    the same id or another — would show up in the stub's log, and a code alone would not show its absence.
    """
    server, log = upstream

    async def body(session: ClientSession) -> Any:
        return await session.call_tool("get_order_context", {})

    result = run_session(server, REFUSED_LINE, body)
    observation = observation_of(result)

    assert result.is_error is False
    assert observation["error"]["code"] == "FORBIDDEN"
    assert observation["error"]["retryable"] is False
    sent = requests_to(log)
    assert len(sent) == 1, f"the tool made {len(sent)} requests to a refusal: {sent}"
    assert REFUSED_LINE in sent[0]["path"]


# --------------------------------------------------------------- paging


def test_the_shipment_trace_pages_and_stops_at_two_pages(upstream: Any) -> None:
    """``docs/agent-spec.md:29``: cursor optional, limit <= 20, 最多2页.

    The cap is the interesting part: without it a run could page a shipment forever, and a budget a tool can
    extend on its own is not a budget.
    """
    server, _ = upstream

    async def body(session: ClientSession) -> Any:
        first = observation_of(await session.call_tool("get_shipment_trace", {"limit": 2}))
        second = observation_of(
            await session.call_tool("get_shipment_trace", {"cursor": first["result"]["next_cursor"], "limit": 2})
        )
        third = await session.call_tool("get_shipment_trace", {"cursor": second["result"]["next_cursor"], "limit": 2})
        return first, second, third

    first, second, third = run_session(server, ORDINARY_LINE, body)

    assert [event["source_version"] for event in first["result"]["events"]] == [1, 2]
    assert [event["source_version"] for event in second["result"]["events"]] == [3, 4]
    assert first["result"]["page"] == 1 and second["result"]["page"] == 2
    # The second page still has more to give, and the third call is refused as a *page* rather than as a source:
    # the trace is there, what ran out is the budget for reading it.
    assert second["result"]["next_cursor"] is not None
    assert observation_of(third)["error"]["code"] == "PAGE_LIMIT"
    assert observation_of(third)["error"]["retryable"] is False


def test_a_cursor_this_server_did_not_issue_is_refused(upstream: Any) -> None:
    """A cursor is per-call state, not an offset a caller can invent.

    If a forged cursor were accepted, "page 3 of 2" would be expressible and the cap would be decorative.
    """
    server, _ = upstream

    async def body(session: ClientSession) -> Any:
        return await session.call_tool("get_shipment_trace", {"cursor": "3", "limit": 2})

    result = run_session(server, ORDINARY_LINE, body)
    assert observation_of(result)["error"]["code"] == "INVALID_CURSOR"


def test_a_limit_over_the_cap_is_refused_by_the_protocol(upstream: Any) -> None:
    """``limit<=20`` is enforced by the published schema, so a caller cannot even ask for more.

    This is the difference between a cap a client is told about and one it is trusted to respect: the schema the
    server publishes says ``maximum: 20``, and the SDK refuses the call before the tool runs.
    """
    server, log = upstream

    async def body(session: ClientSession) -> Any:
        return await session.call_tool("get_shipment_trace", {"limit": 200})

    result = run_session(server, ORDINARY_LINE, body)
    assert result.is_error is True
    assert requests_to(log) == [], "an over-limit request still reached the upstream"


# --------------------------------------------------------------- the tools against the contract


def test_every_tool_reads_a_route_the_contract_declares(upstream: Any) -> None:
    """Each tool's declared source has to be a route the contract actually declares.

    C06.2b shipped five tools while one of their routes — ``refund-status`` — existed in the contract and in no
    Java service. Nothing caught that, because the tools were only ever tested against a stub: a stub answers
    whatever it is told to, so a tool reading a route nobody serves looks exactly like a working tool. This test
    closes that gap from the Python side by checking each tool's ``source_ref`` against the contract's route
    table, so the next such gap is a red test rather than a discovery during a demo.

    It cannot prove Java *serves* the route — that is what the Java controller tests are for — but it does prove
    the tools depend on nothing undocumented, which is the half that was missing.
    """
    import yaml

    declared: set[str] = set()
    for service, document_path in (
        ("commerce", REPO_ROOT / "contracts" / "core" / "openapi-commerce.yaml"),
        ("case", REPO_ROOT / "contracts" / "core" / "openapi-case.yaml"),
    ):
        document = yaml.safe_load(document_path.read_text(encoding="utf-8"))
        for route in document["paths"]:
            filled = route.replace("{line_id}", ORDINARY_LINE).replace("{case_id}", CASE_ID)
            declared.add(f"{service}:{filled}")

    server, log = upstream

    async def body(session: ClientSession) -> Any:
        return {
            name: observation_of(await session.call_tool(name, {}))
            for name in ("get_order_context", "get_refund_status", "get_case_evidence", "get_policy_manifest")
        }

    observations = run_session(server, ORDINARY_LINE, body)
    for name, observation in observations.items():
        # The source is the request path, character for character, so a citation can be grepped into the contract.
        assert observation["source_ref"] in declared, (
            f"{name} cites {observation['source_ref']}, which no contract route declares"
        )
    # And the reads really happened against those paths, rather than the citation being right by luck.
    requested = {entry["path"].split("?")[0] for entry in requests_to(log)}
    for name, observation in observations.items():
        _, _, path = observation["source_ref"].partition(":")
        assert path in requested, f"{name} cites {path} but read {sorted(requested)}"