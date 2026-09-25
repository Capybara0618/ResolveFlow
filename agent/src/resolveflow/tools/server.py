"""The MCP stdio server exposing the five whitelisted tools (C06.2b).

``docs/agent-spec.md:34`` asks for the tools "通过真实官方MCP stdio tools/list和tools/call", so this is a real
``mcp`` server on stdio and not a local dispatcher with MCP-shaped names. What that buys, concretely: the
official client performs the handshake, the tool schemas are the ones it publishes, and a model driving an MCP
client reaches the same five tools a deployment exposes.

**Why the server is thin.** It owns the protocol — session state, argument validation, structured results — and
nothing else. Every rule about what a tool reads and how a failure becomes an observation lives in
:mod:`resolveflow.tools.catalog`, which is callable without a subprocess. The split exists so the rules are
tested as rules and the protocol is tested as a protocol; a server holding both would make every rule test pay
for a handshake, and would make "we serve real MCP" provable only by reading the code.

**Per-run state the server does own:** the shipment-trace page count. ``docs/agent-spec.md:29`` caps paging at
two, and the cap belongs to the run rather than to the tool call — a caller that resets a counter by calling
again has no cap at all. It is kept on the MCP session, which is the scope a client conversation corresponds
to, so a new conversation gets a new budget.

Configuration is by environment, because a stdio server is started by whoever is driving it:
``RESOLVEFLOW_CASE_BASE_URL``, ``RESOLVEFLOW_COMMERCE_BASE_URL`` and ``RESOLVEFLOW_TOOL_SERVICE_TOKEN``.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Annotated, Any, Final

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from resolveflow.contracts.core_models import CoreToolError, ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.tools import catalog
from resolveflow.tools.catalog import MAX_TRACE_PAGES, TRACE_PAGE_LIMIT, ToolContext
from resolveflow.tools.upstream import TOOL_CREDENTIAL_ENV, UpstreamClient

__all__ = ["DEFAULT_CASE_BASE_URL", "DEFAULT_COMMERCE_BASE_URL", "build_server", "main"]

LOG = logging.getLogger("resolveflow.tools.server")

CASE_BASE_URL_ENV: Final = "RESOLVEFLOW_CASE_BASE_URL"
COMMERCE_BASE_URL_ENV: Final = "RESOLVEFLOW_COMMERCE_BASE_URL"

#: The same defaults the Agent app uses, so a single-host demonstration needs no configuration.
DEFAULT_CASE_BASE_URL: Final = "http://127.0.0.1:8083"
#: ``8081``, not the ``8084`` this started as. ``8084`` was a guess, and the e2e script is the authority:
#: ``scripts/e2e_refund_chain.py:53`` declares ``COMMERCE_PORT = 8081`` and starts the service there
#: (``java/commerce-service/src/main/resources/application.yml`` agrees). A wrong default is not a loud failure
#: — every read against it is a connection error, which this layer reports as ``UPSTREAM_UNAVAILABLE`` and
#: ``retryable``, so the tools would say "the shop is down" and be believed. ``test_tool_defaults_match_the_
#: declared_ports`` now pins both defaults to the ports the e2e script declares.
DEFAULT_COMMERCE_BASE_URL: Final = "http://127.0.0.1:8081"

#: What the run is about. ``line_id`` is required: the tools read "the current line", and a tool that guessed
#: one would be choosing what to investigate.
LINE_ID_ENV: Final = "RESOLVEFLOW_TOOL_LINE_ID"
RUN_ID_ENV: Final = "RESOLVEFLOW_TOOL_RUN_ID"
CASE_ID_ENV: Final = "RESOLVEFLOW_TOOL_CASE_ID"
#: How many shipment-trace pages the run has already read, as the caller counted them (C06.4③).
#:
#: The page budget belongs to the **run** (``docs/agent-spec.md:29``: 最多2页), and this process is a fresh child
#: per call, so it cannot remember across calls. The count therefore travels in as configuration, exactly as the
#: line does. Without this the cap would mean "two pages per call", which is not a cap: a caller that started a
#: new process per read could page a shipment forever, and ``docs/agent-spec.md:29`` exists to prevent precisely
#: that. Defaulting to 0 keeps the C06.2b usage — one long-lived process serving a whole conversation, where the
#: in-process counter is authoritative — working unchanged.
TRACE_PAGES_ENV: Final = "RESOLVEFLOW_TOOL_TRACE_PAGES"

#: A hostile or corrupt environment must not be able to grant a run more pages than the spec allows, so the
#: starting count is clamped into ``[0, MAX_TRACE_PAGES]`` rather than trusted.
def _starting_trace_pages() -> int:
    raw = os.environ.get(TRACE_PAGES_ENV, "").strip()
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError:
        return 0
    return max(0, min(value, MAX_TRACE_PAGES))


class _RunState:
    """The state one session owns: how many trace pages it has read, and the call counter.

    Riding on the session rather than on a module global is what makes the page cap per run. A global would let
    one run's paging exhaust another's, which is the kind of shared mutable state that shows up as a flaky
    budget in production and never in a single-client test.
    """

    def __init__(self, trace_pages: int = 0) -> None:
        self.trace_pages = trace_pages
        self.calls = 0

    def next_call_id(self, tool_name: str) -> str:
        self.calls += 1
        return f"{tool_name}-{self.calls}"


def _client() -> UpstreamClient:
    """The upstream, read from the environment at call time.

    Read per call rather than captured at import: the base URLs are configuration, and a module-level capture
    would make a test that sets the environment afterwards silently read the default.
    """
    return UpstreamClient(
        case_base_url=os.environ.get(CASE_BASE_URL_ENV, DEFAULT_CASE_BASE_URL),
        commerce_base_url=os.environ.get(COMMERCE_BASE_URL_ENV, DEFAULT_COMMERCE_BASE_URL),
        service_token=os.environ.get(TOOL_CREDENTIAL_ENV) or None,
    )


#: The state of the run this server process is serving.
#:
#: **Why the process and not the MCP session, which would be the obvious scope.** The first version hung this on
#: ``context.session`` so the budget would belong to a client conversation. That does not work here, and the way
#: it fails is worth recording: mcp 2.2.0 hands each request a **different** ``ServerSession`` object, so the
#: attribute is set on one object and looked for on the next — the counter reset to 1 every call and
#: ``docs/agent-spec.md:29``'s "最多2页" was never enforced at all. A run could page a shipment forever, which is
#: exactly the unbounded tool the cap exists to prevent. The test that caught it asserted a third page is
#: refused, not merely that the first two work.
#:
#: A stdio server process is started to serve one client and exits with it, so the process is the conversation
#: for this transport. If a transport that multiplexes conversations is added (streamable-http), this must become
#: a per-conversation key — and this comment is the reminder that the session object is not it.
#:
#: **How the count starts.** ``RESOLVEFLOW_TOOL_TRACE_PAGES`` seeds it (C06.4③), because the Harness starts a
#: fresh server process per tool call and a per-process counter would otherwise reset on every read — turning the
#: run's two-page budget into "two pages per call". When the variable is unset the count starts at 0, which is
#: what a single long-lived process serving one conversation wants.
_RUN_STATE = _RunState(_starting_trace_pages())


def _state_of(context: Context[Any, Any]) -> _RunState:
    """The run's state, and the per-call id counter.

    A fresh ``ToolContext`` is minted per call, so the call counter must live here rather than on the context:
    two calls in one run have to get different observation ids, or the second observation overwrites the first
    under a stable-id scheme (``docs/agent-spec.md:50``).
    """
    return _RUN_STATE


def _failed_observation(tool_name: str, source_type: EvidenceSourceType, code: str, message: str) -> ToolObservation:
    """An error observation for something that went wrong **before** a read could be attempted.

    A tool that returned bare ``None`` on this path would answer a JSON-RPC call with no structured content at
    all, so the caller could not tell "the tool declined" from "the tool is broken". The tools themselves turn
    read failures into observations (:mod:`resolveflow.tools.catalog`); this is for the failures around them, and
    it is an observation for the same reason.
    """
    return ToolObservation(
        observation_id=f"obs-{tool_name[:40]}-unconfigured",
        tool_name=tool_name,
        source_type=source_type,
        source_ref=f"agent:tools/{tool_name}",
        observed_at=dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        error=CoreToolError(
            code=code, message=message[:512], retryable=False, source_ref=f"agent:tools/{tool_name}"
        ),
    )


def _context_or_none(context: Context[Any, Any], tool_name: str) -> ToolContext | None:
    """The run this call belongs to, or ``None`` when the process was never told which run it serves.

    ``line_id`` is required because the tools read "the current line", and a tool that guessed one would be
    choosing what to investigate. The failure is returned rather than raised so the caller gets an observation:
    every tool answers with one, including the answers that say nothing could be read.
    """
    line_id = os.environ.get(LINE_ID_ENV, "").strip()
    if not line_id:
        return None
    state = _state_of(context)
    return ToolContext(
        line_id=line_id,
        run_id=os.environ.get(RUN_ID_ENV, "run-unknown"),
        tool_call_id=state.next_call_id(tool_name),
        case_id=os.environ.get(CASE_ID_ENV) or None,
    )


def _unconfigured(tool_name: str, source_type: EvidenceSourceType) -> dict[str, Any]:
    return _as_result(
        _failed_observation(
            tool_name,
            source_type,
            "RUN_NOT_CONFIGURED",
            f"{LINE_ID_ENV} is not set: this tool reads the line the run is about and cannot guess one",
        )
    )


def build_server() -> MCPServer:
    """The server with the five tools registered. Built rather than module-level so tests get a clean one."""
    server = MCPServer(
        name="resolveflow-agent-tools",
        instructions=(
            "Read-only investigation tools for one order line. Every result is an observation carrying the "
            "source, its version and a content hash; a failure comes back as an observation with an error "
            "instead of as an exception."
        ),
    )

    @server.tool(
        name="get_order_context",
        description=(
            "Read the order line under investigation and its payment facts from Commerce: the amounts Java "
            "recomputes a refund from. Takes no arguments."
        ),
    )
    def get_order_context(context: Context[Any, Any]) -> dict[str, Any]:
        tool_context = _context_or_none(context, "get_order_context")
        if tool_context is None:
            return _unconfigured("get_order_context", EvidenceSourceType.ORDER_LINE)
        return _as_result(catalog.get_order_context(_client(), tool_context))

    @server.tool(
        name="get_shipment_trace",
        description=(
            "Read the synthetic shipment events for the line under investigation: at most "
            f"{TRACE_PAGE_LIMIT} events per page and at most {MAX_TRACE_PAGES} pages per run. Pass the cursor "
            "from the previous page to continue; omit it to start."
        ),
    )
    def get_shipment_trace(
        context: Context[Any, Any],
        cursor: Annotated[str | None, Field(description="The cursor from the previous page, if any.")] = None,
        limit: Annotated[int, Field(ge=1, le=TRACE_PAGE_LIMIT, description="Events per page.")] = TRACE_PAGE_LIMIT,
    ) -> dict[str, Any]:
        state = _state_of(context)
        # Every call is a read and therefore costs budget. The cap in docs/agent-spec.md:29 is on how many times
        # a run may page through a shipment, so a continuation is charged exactly like a fresh page — charging
        # only fresh pages is what made "at most two pages" mean "at most two first pages".
        state.trace_pages += 1
        tool_context = _context_or_none(context, "get_shipment_trace")
        if tool_context is None:
            return _unconfigured("get_shipment_trace", EvidenceSourceType.SHIPMENT_TRACK)
        observation = catalog.get_shipment_trace(
            _client(), tool_context, cursor=cursor, limit=limit, page=state.trace_pages or 1
        )
        return _as_result(observation)

    @server.tool(
        name="get_refund_status",
        description=(
            "Read the current refund state of the line under investigation from Commerce: what has been "
            "refunded and what is reserved. Takes no arguments."
        ),
    )
    def get_refund_status(context: Context[Any, Any]) -> dict[str, Any]:
        tool_context = _context_or_none(context, "get_refund_status")
        if tool_context is None:
            return _unconfigured("get_refund_status", EvidenceSourceType.PAYMENT_LEDGER)
        return _as_result(catalog.get_refund_status(_client(), tool_context))

    @server.tool(
        name="get_case_evidence",
        description=(
            "Read the material the case already holds at its current revision: what the customer said and what "
            "staff recorded. Optionally narrow it with a kind."
        ),
    )
    def get_case_evidence(
        context: Context[Any, Any],
        kind: Annotated[str | None, Field(description="Narrow the material to one kind.")] = None,
    ) -> dict[str, Any]:
        tool_context = _context_or_none(context, "get_case_evidence")
        if tool_context is None:
            return _unconfigured("get_case_evidence", EvidenceSourceType.CUSTOMER_STATEMENT)
        observation = catalog.get_case_evidence(_client(), tool_context, kind=kind)
        return _as_result(observation)

    @server.tool(
        name="get_policy_manifest",
        description=(
            "Read the policy version the case is bound to. The run may not choose a different one. Takes no "
            "arguments."
        ),
    )
    def get_policy_manifest(context: Context[Any, Any]) -> dict[str, Any]:
        tool_context = _context_or_none(context, "get_policy_manifest")
        if tool_context is None:
            return _unconfigured("get_policy_manifest", EvidenceSourceType.POLICY_RULE)
        return _as_result(catalog.get_policy_manifest(_client(), tool_context))

    return server


def _as_result(observation: Any) -> dict[str, Any]:
    """The observation as structured content, JSON-safe.

    ``mode="json"`` so the payload is exactly what a JSON-RPC client receives: a datetime left as a Python
    object would serialise by the SDK's own rules and the test reading it would be testing the SDK.

    ``exclude_none=True`` because the core wire spells "absent" by **omitting** the member and never by sending
    ``null`` (``CoreWireModel.refuse_explicit_null``; ``docs/core-contracts.md:17``). A failed observation
    carries ``source_version: None`` and ``content_hash: None`` in Python, and dumping them made the server
    publish ``null`` for both — which the core DTO then refused, so **every failure observation was unparseable
    by a conforming client**. The C06.2b tests never saw it because they read the structured content as a plain
    dict and asserted on the members by name; it took the Harness actually validating the observation
    (C06.4②) to catch that the failure half of the protocol did not round-trip. Dropping nulls is always correct
    here: every member the DTO requires has no default, so it can never be ``None``.
    """
    return dict(observation.model_dump(mode="json", exclude_none=True))


def main() -> None:
    """Run the stdio server. This is what ``python -m resolveflow.tools.server`` starts."""
    logging.basicConfig(level=os.environ.get("RESOLVEFLOW_TOOL_LOG_LEVEL", "WARNING"))
    build_server().run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover - the entrypoint, exercised by the stdio test as a subprocess
    main()