"""C06.4②: the Harness drives the five tools over **real MCP stdio**, not by importing them.

``docs/agent-spec.md:34`` asks for the tools "通过真实官方MCP stdio tools/list和tools/call". C06.2b proved the
*server* speaks MCP by spawning it as a subprocess in a test. This file proves the *Harness* reaches it the same
way: the runner's ``READ_TOOL`` actions go through :class:`~resolveflow.harness.mcp_client.McpToolExecutor`,
which starts ``python -m resolveflow.tools.server`` and makes a real ``tools/call``.

That distinction is the whole point of the slice. An executor that called
``resolveflow.tools.catalog.get_order_context`` directly would produce identical observations and would prove
nothing about the deployed path: the MCP handshake, the argument schema the server publishes, and the fact that
the run's subject reaches the tools as *configuration* rather than as an argument would all be untested.

Two properties are asserted that only the subprocess path can show:

- **the run's line is not an argument.** The model's action carries no ``line_id`` (C06.4① refuses it), so the
  tool can only learn which line it is reading from how the executor was configured. The test reads the stub's
  request log to see which line was actually fetched.
- **a tool failure is a successful MCP call.** ``docs/agent-spec.md:36`` puts the error *inside* the
  observation, so an unreadable source must not arrive as a protocol error — that would tell a model the
  transport hiccuped, which is the wrong lesson for a refusal.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Any

import pytest
from resolveflow.contracts.core_models import ToolObservation
from resolveflow.harness.mcp_client import McpToolExecutor, ToolCallFailedError
from resolveflow.harness.model import MockModelClient
from resolveflow.harness.sdk_runner import AgentScopeRunner
from resolveflow.harness.vocabulary import REASON_COMPLETED, RunFacts
from resolveflow.tools.credential import credential_source

from tests.conftest import input_text_of
from tests.integration import stub_upstream

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
AGENT_SRC = REPO_ROOT / "agent" / "src"

RUN_ID = "5f2b1c3d-0000-4000-8000-000000000001"
CASE_ID = "9c858abd-0000-4000-8000-0000000000cc"
#: The line the run is about. ``7100`` answers normally; ``7001`` has no shipment and ``7002`` is refused.
LINE_ID = "7100"
NO_SHIPMENT_LINE = "7001"
REFUSED_LINE = "7002"


def facts(line_id: str = LINE_ID) -> RunFacts:
    return RunFacts(
        run_id=RUN_ID,
        case_id=CASE_ID,
        input_revision=1,
        line_id=line_id,
        merchant_id="M-1001",
        customer_id="C-2002",
        description="the parcel never arrived",
    )


def executor(upstream_url: str, line_id: str = LINE_ID) -> McpToolExecutor:
    """An executor that starts the real tool server against a stub upstream.

    The environment is how a deployment tells the server which run it is serving. Nothing here passes the line
    as a tool argument, because the ABI has no such argument.
    """
    return McpToolExecutor(
        python=sys.executable,
        case_base_url=upstream_url,
        commerce_base_url=upstream_url,
        service_token="stub-service-token",  # noqa: S106 - synthetic test credential
        line_id=line_id,
        run_id=RUN_ID,
        case_id=CASE_ID,
        env_extra={"PYTHONPATH": str(AGENT_SRC) + os.pathsep + os.environ.get("PYTHONPATH", "")},
    )


@pytest.fixture()
def upstream(tmp_path: pathlib.Path) -> Any:
    server = stub_upstream.start(tmp_path / "upstream.log")
    try:
        yield server.url, tmp_path / "upstream.log"
    finally:
        server.stop()


def requests_to(log: pathlib.Path) -> list[dict[str, Any]]:
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def read(tool_name: str, **arguments: Any) -> dict[str, Any]:
    return {"kind": "READ_TOOL", "tool_name": tool_name, "arguments": arguments, "reasoning": "looking"}


def propose(action: str = "REFUND") -> dict[str, Any]:
    return {
        "kind": "PROPOSE",
        "case_type": "LOGISTICS",
        "recommended_action": action,
        "reason_codes": ["LOST_IN_TRANSIT"],
        "summary": "the trace shows the parcel was never delivered",
    }


# ------------------------------------------------------------------ the executor on its own


def test_a_call_comes_back_as_a_core_observation(upstream: Any) -> None:
    """The executor's answer is the contract's observation, over a real handshake.

    The members checked are the ones a citation is later validated against (``ObservationRecord``); an executor
    that returned the server's raw dict would make the citation check depend on the server's spelling.
    """
    url, log = upstream
    tool = executor(url)
    try:
        observation = tool.call_tool(run_id=RUN_ID, tool_name="get_order_context", arguments={})
    finally:
        tool.close()

    assert isinstance(observation, ToolObservation)
    assert observation.tool_name == "get_order_context"
    assert observation.source_type == "ORDER_LINE"
    assert observation.source_version == "3"
    assert len(observation.content_hash or "") == 64
    assert (observation.result or {}).get("line_paid_amount") == 2599
    # The route is the contract's, and the token travelled: the backend re-checks the subject
    # (docs/agent-spec.md:34 — HTTP后端再次检查主体).
    sent = requests_to(log)
    assert len(sent) == 1, f"expected exactly one upstream read: {sent}"
    assert sent[0]["authorization"] == "Bearer stub-service-token"
    assert f"/internal/v1/order-lines/{LINE_ID}/context" in sent[0]["path"]


def test_the_line_is_configuration_and_never_an_argument(upstream: Any) -> None:
    """Which line a tool reads comes from the run, not from the caller of ``call_tool``.

    The executor has no ``line_id`` parameter on ``call_tool`` at all — this test pins that by reading the
    route the *server* actually fetched: the executor was built for ``7100``, so ``7100`` is what was read,
    even though nothing in the call mentions a line.
    """
    url, log = upstream
    tool = executor(url, line_id=LINE_ID)
    try:
        observation = tool.call_tool(run_id=RUN_ID, tool_name="get_refund_status", arguments={})
    finally:
        tool.close()

    assert (observation.result or {}).get("line_id") == LINE_ID
    assert LINE_ID in requests_to(log)[0]["path"]


def test_an_unreadable_source_is_a_successful_call_with_an_error_observation(upstream: Any) -> None:
    """``docs/agent-spec.md:36``: the error is *in* the observation, not a protocol failure.

    The server answers ``is_error=False`` for a failure it reported itself, and this executor must not turn that
    into an exception: an exception would stop the run, and a model told "the transport failed" would retry a
    refusal — the wrong lesson (``docs/agent-spec.md:36``: FORBIDDEN 停止).
    """
    url, _ = upstream
    tool = executor(url, line_id=NO_SHIPMENT_LINE)
    try:
        observation = tool.call_tool(run_id=RUN_ID, tool_name="get_shipment_trace", arguments={"limit": 5})
    finally:
        tool.close()

    assert observation.error is not None
    assert observation.error.code == "NOT_FOUND"
    assert observation.error.retryable is False
    # Nothing was observed, so there is no version and no hash that could be cited.
    assert observation.source_version is None
    assert observation.content_hash is None


def test_a_refusal_arrives_as_a_forbidden_observation(upstream: Any) -> None:
    """A 403 from the upstream is FORBIDDEN and not retryable, all the way through the MCP boundary."""
    url, log = upstream
    tool = executor(url, line_id=REFUSED_LINE)
    try:
        observation = tool.call_tool(run_id=RUN_ID, tool_name="get_order_context", arguments={})
    finally:
        tool.close()

    assert observation.error is not None
    assert observation.error.code == "FORBIDDEN"
    assert observation.error.retryable is False
    # And the tool did not try again with another id: the rule is about what did not happen.
    assert len(requests_to(log)) == 1


def test_a_tool_that_does_not_exist_is_a_protocol_error_not_an_observation(upstream: Any) -> None:
    """Asking the server for a sixth tool is a genuine protocol failure and raises.

    The distinction from the tests above is the point: a tool that *ran* and could not observe answers with an
    observation, while a tool that does not exist is a caller error and has no observation to give. Collapsing
    the two would let a harness bug look like evidence.
    """
    url, _ = upstream
    tool = executor(url)
    try:
        with pytest.raises(ToolCallFailedError):
            tool.call_tool(run_id=RUN_ID, tool_name="get_shipment_trace_v2", arguments={})
    finally:
        tool.close()


def test_the_published_schema_still_bounds_the_arguments(upstream: Any) -> None:
    """``limit<=20`` is enforced by the server's published schema, across the real boundary.

    C06.2b asserted this against its own client. This asserts it through the executor the Harness actually uses,
    because "the cap is published" and "the Harness cannot exceed it" are different claims, and only the second
    one bounds a run.
    """
    url, log = upstream
    tool = executor(url)
    try:
        with pytest.raises(ToolCallFailedError):
            tool.call_tool(run_id=RUN_ID, tool_name="get_shipment_trace", arguments={"limit": 200})
    finally:
        tool.close()
    assert requests_to(log) == [], "an over-limit request reached the upstream"


# ------------------------------------------------------------------ the Harness over MCP


def test_the_runner_reads_through_mcp_and_decides(upstream: Any) -> None:
    """The whole of C06.4's first two slices together: model → MCP tool → observation → model → decision.

    This is the claim the slice exists for. The model is a script and the upstream is a stub, but the hop
    between them is a real MCP subprocess, and the assertions are about what that hop actually did.
    """
    url, log = upstream
    tool = executor(url)
    model = MockModelClient([read("get_order_context"), propose("MANUAL_REVIEW")])
    try:
        result = AgentScopeRunner(model=model, tools=tool, facts=facts()).run()
    finally:
        tool.close()

    assert result.completed is True
    assert result.reason_code == REASON_COMPLETED
    assert [entry["action"] for entry in result.trajectory] == ["get_order_context", "PROPOSE"]
    assert len(requests_to(log)) == 1

    # The observation the tool produced is the one the model was shown: a harness that talked to MCP but handed the
    # model something else would pass every other assertion here. Read through the **request** the model received
    # (C08.1a) rather than the structured `packets` channel, which under the formal builder path is the script's own
    # view — a channel the model never sees cannot carry a claim about what it saw.
    observation = result.observations[0]
    sent = input_text_of(model, 1)
    assert observation.tool_name in sent, f"the observation is not in the request the model received: {sent}"
    assert observation.source_version in sent, f"its version is part of what makes it citable: {sent}"
    # The identity a citation needs stays in the run's own record. The rendered packet carries source and version but
    # no hash, so this asserts what the run kept — not something the model was supposedly shown.
    assert len(result.observations) == 1
    assert len(observation.content_hash) == 64


def test_a_tool_failure_does_not_stop_the_run(upstream: Any) -> None:
    """``docs/agent-harness.md:51``: the error observation goes back to the model, and the run continues.

    The model reads a shipment that does not exist, is told so, and decides on what it has. A harness that ended
    the run at the first unreadable source would turn "the shop has no record" into a conclusion.
    """
    url, _ = upstream
    tool = executor(url, line_id=NO_SHIPMENT_LINE)
    model = MockModelClient([read("get_shipment_trace", limit=5), propose("MANUAL_REVIEW")])
    try:
        result = AgentScopeRunner(model=model, tools=tool, facts=facts(NO_SHIPMENT_LINE)).run()
    finally:
        tool.close()

    assert result.completed is True
    assert result.decision is not None and result.decision.recommended_action == "MANUAL_REVIEW"
    assert result.spend.tool_attempts == 1, "a failed read is still an attempt and is counted"
    # `docs/agent-harness.md:51` is about what the *model* is handed, so the assertion reads the request. The error
    # code has to survive into it: a code that only existed in the script's structured view would let this claim pass
    # while the model was told nothing (C08.1a).
    sent = input_text_of(model, 1)
    assert "NOT_FOUND" in sent, f"the failed read was not handed back to the model: {sent}"


def test_the_runner_can_read_two_different_tools_in_one_run(upstream: Any) -> None:
    """Two tools, two subprocesses, two observations, and two distinct citation ids.

    Each ``call_tool`` is its own MCP conversation, so this also pins the thing that would be easy to get wrong:
    the observation ids must not collide, or the second read would overwrite the first under the stable-id scheme
    of ``docs/agent-spec.md:50``.
    """
    url, log = upstream
    tool = executor(url)
    model = MockModelClient(
        [
            read("get_order_context"),
            read("get_refund_status"),
            propose("MANUAL_REVIEW"),
        ]
    )
    try:
        result = AgentScopeRunner(model=model, tools=tool, facts=facts()).run()
    finally:
        tool.close()

    assert result.completed is True
    assert [entry["action"] for entry in result.trajectory] == [
        "get_order_context",
        "get_refund_status",
        "PROPOSE",
    ]
    ids = [observation.observation_id for observation in result.observations]
    assert len(ids) == 2 and len(set(ids)) == 2, f"observation ids collided: {ids}"
    paths = [entry["path"] for entry in requests_to(log)]
    assert len(paths) == 2 and paths[0] != paths[1]


def test_every_read_goes_to_a_route_the_contract_declares(upstream: Any) -> None:
    """The five tools are reachable through the Harness, and each reads a declared route.

    C06.2c closed the gap where a tool cited a route nobody served. This closes the other half: the Harness's
    executor reaches all five, so no tool is unreachable from the loop that is supposed to use it — a tool that
    exists but that the executor cannot call is, from the run's point of view, not a tool.
    """
    import yaml

    declared: set[str] = set()
    for service, document_path in (
        ("commerce", REPO_ROOT / "contracts" / "core" / "openapi-commerce.yaml"),
        ("case", REPO_ROOT / "contracts" / "core" / "openapi-case.yaml"),
    ):
        document = yaml.safe_load(document_path.read_text(encoding="utf-8"))
        for route in document["paths"]:
            filled = route.replace("{line_id}", LINE_ID).replace("{case_id}", CASE_ID)
            declared.add(f"{service}:{filled}")

    url, log = upstream
    tool = executor(url)
    try:
        observations = {
            name: tool.call_tool(run_id=RUN_ID, tool_name=name, arguments={})
            for name in (
                "get_order_context",
                "get_shipment_trace",
                "get_refund_status",
                "get_case_evidence",
                "get_policy_manifest",
            )
        }
    finally:
        tool.close()

    assert len(observations) == 5
    for name, observation in observations.items():
        assert observation.source_ref in declared, (
            f"{name} cites {observation.source_ref}, which no contract route declares"
        )
    assert len(requests_to(log)) == 5


# ------------------------------------------------------------------ the run's page budget (C06.4③)


def test_the_two_page_budget_survives_the_process_boundary(upstream: Any) -> None:
    """``docs/agent-spec.md:29``: 最多2页 — and it is the **run's** two pages, not each call's.

    This is the failure C06.4③ exists to close. The executor starts a fresh tool-server process per call, and the
    server's page counter is per process (``tools/server.py`` explains why it cannot be per session). So before
    this step every read arrived at a server that had read nothing, saw ``page=1``, and the cap meant "two pages
    per call" — which, with a process per call, is no cap at all: a run could page one shipment forever, spending
    its whole tool budget re-reading it.

    The assertion is on the *third* read, because "the first two work" passes in both the broken and the fixed
    implementation.
    """
    url, log = upstream
    tool = executor(url)
    try:
        first = tool.call_tool(run_id=RUN_ID, tool_name="get_shipment_trace", arguments={"limit": 2})
        cursor = (first.result or {}).get("next_cursor")
        assert cursor is not None, "the stub has six events, so the first page must offer a continuation"
        # The executor counted that page itself — the test never had to tell it to. That is the property: a
        # budget a caller has to remember to update is not a bound.
        assert tool.trace_pages == 1

        second = tool.call_tool(
            run_id=RUN_ID, tool_name="get_shipment_trace", arguments={"limit": 2, "cursor": cursor}
        )
        assert (second.result or {}).get("page") == 2
        assert tool.trace_pages == 2

        cursor2 = (second.result or {}).get("next_cursor")
        assert cursor2 is not None, "there are still events left, so the third read is about budget, not data"
        third = tool.call_tool(
            run_id=RUN_ID, tool_name="get_shipment_trace", arguments={"limit": 2, "cursor": cursor2}
        )
    finally:
        tool.close()

    assert third.error is not None, f"the third page should have been refused: {third}"
    assert third.error.code == "PAGE_LIMIT"
    assert third.error.retryable is False
    # A refused read did not consume a page: the count describes pages the run *read*, not calls it made.
    assert tool.trace_pages == 2
    # And the refusal happened before any read: **two** requests reached the upstream, not three. This is the
    # sharper half of "the cap is on the run" — the third call was refused by the tool from the count the
    # executor handed it, so the run stopped paging without spending an upstream read on the attempt.
    assert len(requests_to(log)) == 2, f"the over-budget page should not have been read: {requests_to(log)}"


def test_the_harness_counts_the_runs_pages_without_being_told_to(upstream: Any) -> None:
    """The runner, not the test, keeps the run's page count.

    A budget a caller has to remember to update is not a budget: the whole point of C06.4③ is that the *run*
    owns the count. The second read continues the **real** cursor from the first page, which is why the script's
    second entry is a callable: a cursor is opaque and issued per call, so a fixed script could only invent one,
    and an invented cursor is refused — the rule working rather than a test limitation.
    """
    url, log = upstream
    tool = executor(url)

    def continue_the_page(packet: dict[str, Any]) -> dict[str, Any]:
        """Ask for the next page, using the cursor the first page actually answered with."""
        first = [entry for entry in packet["observations"] if entry.get("result")]
        assert first, f"the continuation was asked for before any page was read: {packet}"
        cursor = first[-1]["result"]["next_cursor"]
        assert cursor, "the first page offered no continuation, so this script cannot continue it"
        return {"kind": "READ_TOOL", "tool_name": "get_shipment_trace", "arguments": {"limit": 2, "cursor": cursor}}

    model = MockModelClient([read("get_shipment_trace", limit=2), continue_the_page, propose("MANUAL_REVIEW")])
    try:
        result = AgentScopeRunner(model=model, tools=tool, facts=facts()).run()
    finally:
        tool.close()

    assert result.completed is True
    # Two shipment reads happened, so the run's page budget is now spent — and the runner never had to say so.
    assert tool.trace_pages == 2, f"the runner did not count the run's pages: {result.trajectory}"
    assert len(requests_to(log)) == 2
    assert [entry["action"] for entry in result.trajectory] == [
        "get_shipment_trace",
        "get_shipment_trace",
        "PROPOSE",
    ]
    # The second read really was the continuation, not a repeat of the first page.
    pages = [
        (observation.model_dump(mode="json").get("result") or {}).get("page")
        for observation in result.observations
    ]
    assert pages == [1, 2]


def test_a_repeated_failing_read_is_not_progress(upstream: Any) -> None:
    """``docs/agent-spec.md:36``'s ``retryable`` is an invitation, and the retry budget bounds it.

    A source that keeps failing must not be re-read forever. Before C06.4③ a *failed* observation was always
    treated as new information — "I could not read it" is a fresh fact each time — so a model retrying an
    unreachable source made "progress" on every attempt and ran until its model-call budget. The honest rule is
    narrower: an identical action that keeps failing has told the run nothing new, so it counts against the
    two-repeat rule. The run then stops with NO_PROGRESS and *zero* upstream reads for the repeats that were
    refused rather than attempted.
    """
    url, log = upstream
    tool = executor(url, line_id=NO_SHIPMENT_LINE)
    # The same read, forever. The source has no shipment, which is a permanent answer: NOT_FOUND is not
    # retryable at all, so a model that kept asking would be making the mistake the rule exists to stop.
    model = MockModelClient.always(read("get_shipment_trace", limit=5))
    try:
        result = AgentScopeRunner(model=model, tools=tool, facts=facts(NO_SHIPMENT_LINE)).run()
    finally:
        tool.close()

    assert result.completed is False
    assert result.reason_code == "TOOL_NOT_RETRYABLE", f"stopped for the wrong reason: {result.reason_code}"
    # NOT_FOUND is nonretryable: the new correction gate refuses its very first repeat.
    assert len(requests_to(log)) == 1, f"a permanent failure was repeated: {requests_to(log)}"
    assert result.spend.tool_attempts == 1


# ------------------------------------------------------------------ the run's credential (C06.4④)


def test_a_read_presents_the_runs_own_credential(upstream: Any) -> None:
    """The token a read presents is the one Case minted for **this run**, not a configured one.

    ``docs/contracts.md:96`` issues the tool credential per run through Case. This is the join that makes that
    real: the executor asks the credential route, the stub mints a token naming the run it was minted for, and the
    upstream read carries that token. A test asserting only "a credential was fetched" would pass for an executor
    that fetched one and then presented something else — which is exactly the shape of the bug this replaces,
    where the tools presented a deployment-wide token and nothing noticed.

    The credential is fetched per read rather than once, so the assertion is also that the source was consulted
    for the read that needed it.
    """
    url, log = upstream
    tool = executor(url)
    tool.credential_source = credential_source(
        case_base_url=url,
        run_id=RUN_ID,
        case_id=CASE_ID,
        input_revision=1,
        service_token="tool-service-token",  # noqa: S106 - synthetic test credential
        static_token=None,
    )
    try:
        observation = tool.call_tool(run_id=RUN_ID, tool_name="get_order_context", arguments={})
    finally:
        tool.close()

    assert observation.error is None, observation
    sent = requests_to(log)
    # Two requests: the credential, then the read. The order is the evidence that the token was fetched *for*
    # this read rather than remembered from somewhere.
    assert [entry["path"] for entry in sent] == [
        f"/internal/v1/runs/{RUN_ID}/tool-credential",
        f"/internal/v1/order-lines/{LINE_ID}/context",
    ]
    # The credential was asked for with the identity the tools present when they have none of their own.
    assert sent[0]["authorization"] == "Bearer tool-service-token"
    # And the read carried what Case minted, not the identity used to ask for it.
    assert sent[1]["authorization"] == f"Bearer token-for-{RUN_ID}"


def test_a_run_credential_that_cannot_be_minted_stops_the_read(upstream: Any) -> None:
    """No credential, no read — and specifically not a read under the deployment's own token.

    This is the failure mode worth a test of its own: a fallback would leave the tools working, so nobody would
    notice, and every read would be made under an identity that is not the run's. The run stops with TOOL_FAILED
    (the environment failed, not the source), and **nothing reaches the upstream order route**.
    """
    url, log = upstream
    tool = executor(url)
    # A credential source that cannot reach Case: the tools must not present `stub-service-token` instead.
    tool.credential_source = credential_source(
        case_base_url="http://127.0.0.1:1",
        run_id=RUN_ID,
        case_id=CASE_ID,
        input_revision=1,
        service_token="tool-service-token",  # noqa: S106 - synthetic test credential
        static_token="stub-service-token",  # noqa: S106 - synthetic test credential
    )
    model = MockModelClient([read("get_order_context"), propose("MANUAL_REVIEW")])
    try:
        result = AgentScopeRunner(model=model, tools=tool, facts=facts()).run()
    finally:
        tool.close()

    assert result.completed is False
    assert result.reason_code == "TOOL_FAILED", result.reason_code
    reads = [entry for entry in requests_to(log) if "order-lines" in entry["path"]]
    assert reads == [], f"a read was made without the run's credential: {reads}"
