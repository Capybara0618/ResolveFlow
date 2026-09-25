"""The Harness's MCP client: one real ``tools/call`` per read (C06.4②).

``docs/agent-spec.md:34`` asks the five tools to be served "通过真实官方MCP stdio tools/list和tools/call", and
C06.2b proved the *server* is one by spawning it as a subprocess. This module is the other half: the executor the
``HarnessRunner`` uses, which starts ``python -m resolveflow.tools.server`` and speaks the protocol to it.

**Why there is no ``get_order_context()`` method.** The executor's whole interface is
``call_tool(tool_name, arguments)``. A Python method per tool would make the MCP path one option among several
and would let a future caller reach a tool without the protocol — and then "the run reaches its tools over MCP"
would be a claim about the default rather than about the only route. It also would not make the run's subject
passable: see below.

**Why the run's line is configuration and not an argument.** ``docs/agent-spec.md:26-32``'s tool signatures have
no line parameter, and C06.4① refuses an action that names one. Which line a tool reads therefore has to arrive
some other way, and here it arrives the way a deployment delivers it: in the child process's environment
(``RESOLVEFLOW_TOOL_LINE_ID`` etc., C06.2b). That makes "the model cannot change the subject" structural rather
than checked — there is no argument it could put it in.

**Why one subprocess per call.** The server's per-run state is kept **per process**: ``tools/server.py`` explains
that mcp 2.2.0 hands every request a different ``ServerSession`` object, so the shipment-trace page budget cannot
live on the session, and the process is what "one conversation" means for stdio. A long-lived executor that
reused one child for the whole run would carry that counter across calls — which is *correct* within a run, but
it also means a second run served by a reused executor would inherit the first run's page count. A fresh process
per call cannot do that, and the cost is bounded by the run's own budget (``docs/agent-spec.md:40``: at most 16
tool attempts). It also keeps this module free of reconnection and liveness logic, which is a real risk in a
worker that may be idle for minutes between calls.

**Why ``is_error`` is the protocol/observation line.** The server reports a tool it *ran* and could not complete
as a successful call carrying an error observation (``docs/agent-spec.md:36``, ``agent-harness.md:51``), while
``is_error=True`` means the tool never ran — an unknown name, or arguments the published schema rejects. The first
must reach the model, the second must not be dressed up as evidence, so the first is returned and the second
raises.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from resolveflow.contracts.core_models import ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.tools.catalog import MAX_TRACE_PAGES

__all__ = [
    "DEFAULT_CALL_TIMEOUT_SECONDS",
    "McpToolExecutor",
    "ToolCallFailedError",
    "server_environment",
]

#: How long one tool call may take, wall clock. Generous because it covers starting a fresh Python interpreter,
#: and it is a *transport* bound rather than the run's deadline: ``docs/agent-spec.md:40``'s 30-second model
#: timeout is about the provider, and the run's own window is enforced by the budget guard.
DEFAULT_CALL_TIMEOUT_SECONDS: Final = 60.0


class ToolCallFailedError(Exception):
    """The tool call did not complete: the server refused the request or could not be reached.

    Deliberately **not** the shape of an unreadable source. A source that could not be read is an
    :class:`~resolveflow.contracts.core_models.ToolObservation` with an ``error`` member, because
    ``docs/agent-harness.md:51`` wants it handed back to the model. This exception is for the calls where there
    is no observation to hand back — a tool name the server does not serve, arguments its schema rejects, or a
    server that never started — and turning those into observations would invent evidence.
    """


def server_environment(
    *,
    line_id: str,
    run_id: str,
    case_id: str | None,
    case_base_url: str,
    commerce_base_url: str,
    service_token: str | None,
    env_extra: dict[str, str] | None = None,
    trace_pages: int = 0,
) -> dict[str, str]:
    """The environment the tool server is started with, as a deployment configures it.

    ``os.environ`` is deliberately **not** inherited wholesale for the members this module sets: a stale
    ``RESOLVEFLOW_TOOL_LINE_ID`` in the parent would silently override the run's own line, and the symptom would
    be a tool reading someone else's order. Everything else is inherited, because a child needs ``PATH``,
    ``PYTHONPATH`` and the platform's own variables.
    """
    env = dict(os.environ)
    env["RESOLVEFLOW_CASE_BASE_URL"] = case_base_url
    env["RESOLVEFLOW_COMMERCE_BASE_URL"] = commerce_base_url
    env["RESOLVEFLOW_TOOL_LINE_ID"] = line_id
    env["RESOLVEFLOW_TOOL_RUN_ID"] = run_id
    if case_id:
        env["RESOLVEFLOW_TOOL_CASE_ID"] = case_id
    else:
        env.pop("RESOLVEFLOW_TOOL_CASE_ID", None)
    if service_token:
        env["RESOLVEFLOW_TOOL_SERVICE_TOKEN"] = service_token
    else:
        env.pop("RESOLVEFLOW_TOOL_SERVICE_TOKEN", None)
    # The page budget is the run's, and it is handed to a fresh process so a restarted tool server does not
    # begin the run's paging again. C06.4③ is what makes this counter meaningful across calls.
    env["RESOLVEFLOW_TOOL_TRACE_PAGES"] = str(int(trace_pages))
    if env_extra:
        env.update(env_extra)
    return env


@dataclass(slots=True)
class McpToolExecutor:
    """Drives the five whitelisted tools over real MCP stdio, one subprocess per call.

    ``python`` is injectable so a test runs the same interpreter the suite runs, and ``env_extra`` is how a test
    puts ``agent/src`` on the child's ``PYTHONPATH`` without this module guessing an install layout.
    """

    line_id: str
    run_id: str
    case_id: str | None = None
    case_base_url: str = "http://127.0.0.1:8083"
    commerce_base_url: str = "http://127.0.0.1:8081"
    service_token: str | None = None
    python: str = field(default_factory=lambda: sys.executable)
    timeout_seconds: float = DEFAULT_CALL_TIMEOUT_SECONDS
    env_extra: dict[str, str] | None = None
    #: How many shipment-trace pages this **run** has already read. The executor owns it because the run does:
    #: the tool server is a fresh process per call and could not remember, and a per-call count would make
    #: ``docs/agent-spec.md:29``'s "最多2页" mean "at most two pages per call", which is no cap at all.
    trace_pages: int = 0
    #: Where each read's credential comes from (C06.4④). A *source* rather than a token, because a run may
    #: outlive its credential: ``docs/contracts.md:96`` gives it five minutes, and an investigation reading its
    #: fifth tool four minutes in has to be able to renew rather than guess. ``None`` means no credential, which
    #: is a deployment that named neither a case service nor a token — say so by sending no header rather than an
    #: empty one, which would look authenticated and answer 401.
    credential_source: Callable[[], str] | None = None
    #: The revision the run's credential is issued for. ``docs/contracts.md:96`` binds the credential to one, so
    #: a renewal that named no revision would not be a renewal of anything.
    input_revision: int = 1
    #: Every call this executor made, in order: the evidence that the tools were reached over MCP rather than
    #: through an import. Kept because a test asserting "the read happened" needs to see the call, not infer it.
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    _closed: bool = False

    # ------------------------------------------------------------------ the one entry point

    def call_tool(self, *, run_id: str, tool_name: str, arguments: dict[str, Any]) -> ToolObservation:
        """Make one ``tools/call`` and return the observation it produced.

        ``run_id`` is accepted because the protocol the runner speaks includes it — the harness passes the run it
        is driving so an executor that multiplexes runs can tell them apart. This executor is per-run, so it
        checks the two agree rather than ignoring the argument: a mismatch means the harness handed this executor
        another run's action, and a tool reading the wrong run's line is exactly the failure
        ``docs/core-scope.md``'s "one order line" invariant exists to prevent.
        """
        if self._closed:
            raise ToolCallFailedError("this executor was closed")
        if run_id != self.run_id:
            raise ToolCallFailedError(
                f"this executor serves run {self.run_id} but was asked to act for {run_id}"
            )
        self.calls.append((tool_name, dict(arguments)))
        try:
            outcome: Any = _run_sync(self._call(tool_name, arguments), timeout=self.timeout_seconds)
        except ToolCallFailedError:
            raise
        except Exception as failure:  # noqa: BLE001 - any transport failure is this module's to report
            raise ToolCallFailedError(f"{tool_name} could not be called over MCP: {failure}") from failure
        observation: ToolObservation = outcome[0]
        kind = outcome[1]
        if kind == "page":
            # The run read a page of the trace, so the run's page budget is one smaller. Counting here rather
            # than asking the caller to remember is the point of C06.4③: a budget a caller has to update is not
            # a bound, and a page the tool *refused* for being over budget did not consume one.
            self.trace_pages += 1
        return observation

    def close(self) -> None:
        """Nothing is held between calls, so closing only stops further use.

        Stated rather than left implicit: a caller might reasonably expect ``close`` to tear down a connection,
        and a reader should not have to read the whole class to learn that there is none to tear down.
        """
        self._closed = True

    # ------------------------------------------------------------------ the protocol

    async def _call(self, tool_name: str, arguments: dict[str, Any]) -> tuple[ToolObservation, str]:
        """One MCP conversation, and whether its answer was a **page** of a paged read.

        The second member is how ``docs/agent-spec.md:29``'s two-page budget is charged. A small closed
        vocabulary rather than a bool, because a paged tool that is not the trace would need its own word for
        this and a bool would then silently mean "count me like the trace".
        """
        params = StdioServerParameters(
            command=self.python,
            args=["-m", "resolveflow.tools.server"],
            env=server_environment(
                line_id=self.line_id,
                run_id=self.run_id,
                case_id=self.case_id,
                case_base_url=self.case_base_url,
                commerce_base_url=self.commerce_base_url,
                service_token=self._token_for_this_read(),
                env_extra=self.env_extra,
                trace_pages=self.trace_pages,
            ),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
        if result.is_error:
            # The tool never ran: an unknown name, or arguments the published schema refuses. There is no
            # observation to hand back, and inventing one would put the harness's guess in the evidence.
            raise ToolCallFailedError(f"{tool_name} was refused by the tool server: {_text_of(result)}")
        observation = _observation_of(result, tool_name)
        return observation, _charge_for(tool_name, observation)

    # ------------------------------------------------------------------ the run's page budget

    def note_trace_page(self) -> None:
        """Count one shipment-trace read against the run's page budget.

        Public because the count belongs to the *run* and this is the object that lives for the run. The runner
        does not need to call it — :meth:`call_tool` charges a page when the server answers with one — but a test
        that drives this executor directly, or a caller that reaches a paged tool by another route, does.
        """
        self.trace_pages += 1

    def _token_for_this_read(self) -> str | None:
        """The credential this read presents: the run's, fetched now, or the configured one.

        Fetched per read rather than held, which is what makes ``docs/contracts.md:96``'s five-minute lifetime
        usable: a run that reads its last tool four minutes in gets a fresh token instead of betting on the first
        one. A source that raises propagates — a read that cannot be authenticated must not quietly become a read
        made under the deployment's own identity (``tools/credential.py`` says why at length).
        """
        if self.credential_source is not None:
            return self.credential_source()
        return self.service_token or None


def _charge_for(tool_name: str, observation: ToolObservation) -> str:
    """Whether an answer consumed one of the run's shipment-trace pages.

    ``get_shipment_trace`` is the only paged tool (``docs/agent-spec.md:29``), so it is named here — and the cap
    it is charged against is imported from :mod:`resolveflow.tools.catalog` rather than restated, so the two
    places that have to agree about "two pages" cannot drift into disagreement.

    A refusal is not charged. The tool answers ``PAGE_LIMIT`` when the budget is already gone, and charging a
    refused read would make the count describe attempts rather than pages — the same confusion C06.2b's
    ``trace_pages`` comment warns about, where counting *reads* rather than *pages* made "at most two pages" mean
    "at most two first pages". Every other tool answers ``"none"``.
    """
    if tool_name != "get_shipment_trace" or observation.error is not None:
        return "none"
    # ``MAX_TRACE_PAGES`` is imported from ``catalog`` so this file cannot disagree with the tool about how many
    # pages a run gets; a page exists only because that cap is at least one.
    return "page" if MAX_TRACE_PAGES >= 1 else "none"  # pragma: no branch - the cap is a non-zero constant


def _observation_of(result: Any, tool_name: str) -> ToolObservation:
    """The structured content of a tool result, as a core observation.

    ``ToolObservation`` rather than ``CoreObservation``: the server answers with the subclass that carries the
    ``error`` member (``contracts/core_models.py`` explains why the extra member lives in a subclass), and
    parsing into the parent would silently drop the reason a read failed.

    **Why ``source_type`` is converted rather than validated straight from the wire.** ``EvidenceSourceType`` is a
    ``StrEnum``; the JSON boundary carries its *value* (``"ORDER_LINE"``) and the core DTO is ``strict=True``,
    which refuses a plain ``str`` for an enum member. That strictness is wanted — it is what stops a Python-side
    typo from becoming a silently-validated string — but applying it to decoded JSON would mean the protocol
    could not be parsed at all. So the conversion happens here, at the one place where JSON becomes a DTO, and it
    is explicit: an unknown source type still raises, because ``EvidenceSourceType(...)`` refuses anything the
    schema's enum does not contain. This is the JSON boundary, and it is the only place that gets to be lenient.
    """
    structured = getattr(result, "structured_content", None)
    if not isinstance(structured, dict):
        raise ToolCallFailedError(
            f"{tool_name} answered with no structured content; a caller cannot tell the version it must cite "
            f"from prose: {_text_of(result)[:300]!r}"
        )
    decoded = dict(structured)
    raw_source = decoded.get("source_type")
    if isinstance(raw_source, str):
        try:
            decoded["source_type"] = EvidenceSourceType(raw_source)
        except ValueError as failure:
            raise ToolCallFailedError(
                f"{tool_name} answered with source_type {raw_source!r}, which the core schema's enum does not "
                "contain"
            ) from failure
    try:
        return ToolObservation.model_validate(decoded)
    except Exception as failure:  # noqa: BLE001 - a malformed observation is a bug at the tool boundary
        raise ToolCallFailedError(
            f"{tool_name} answered with something that is not a core observation: {failure}"
        ) from failure


def _text_of(result: Any) -> str:
    """The textual part of a tool result, for a message. Never used as evidence."""
    blocks = getattr(result, "content", None) or []
    parts = [getattr(block, "text", "") for block in blocks]
    return " ".join(part for part in parts if part).strip()


def _run_sync(coroutine: Any, *, timeout: float) -> Any:
    """Run one coroutine to completion in a private event loop on a worker thread.

    The MCP client is async and the harness is synchronous, so *some* boundary has to exist. A private loop on a
    private thread rather than ``asyncio.run`` because a caller may already be inside a running loop — the Agent
    service is FastAPI — and ``asyncio.run`` refuses there with an error that reads like a bug in this module
    rather than like a scheduling conflict. A fresh loop also means the child's transport is torn down
    deterministically when the loop closes, even if the call timed out.
    """
    outcome: dict[str, Any] = {}

    def target() -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            outcome["value"] = loop.run_until_complete(asyncio.wait_for(coroutine, timeout=timeout))
        except BaseException as failure:  # noqa: BLE001 - re-raised on the caller's thread below
            outcome["error"] = failure
        finally:
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)

    thread = threading.Thread(target=target, name="resolveflow-mcp-call", daemon=True)
    thread.start()
    thread.join(timeout + 30.0)
    if thread.is_alive():
        raise ToolCallFailedError(f"the MCP call did not finish within {timeout + 30.0:.0f}s")
    if "error" in outcome:
        raise outcome["error"]
    if "value" not in outcome:  # pragma: no cover - the thread always sets one of the two
        raise ToolCallFailedError("the MCP call produced no result")
    return outcome["value"]


def tool_arguments_from(payload: dict[str, Any]) -> dict[str, Any]:
    """A JSON-safe copy of a tool call's arguments.

    A helper rather than an inline ``dict(...)`` because the arguments go into a child process's protocol frame:
    anything that is not JSON-serialisable (a datetime a test put in a script) would fail inside the MCP SDK with
    a serialisation error attributed to the server. Failing here names the caller's value.
    """
    try:
        json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError) as failure:
        raise ToolCallFailedError(f"tool arguments are not JSON: {failure}") from failure
    return dict(payload)
