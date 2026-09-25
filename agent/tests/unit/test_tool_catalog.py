"""C06.2b: the tool rules, exercised without a protocol handshake.

``docs/agent-spec.md:36`` has two size rules that no protocol test can reach cheaply — 给模型的excerpt<=8KiB and
原始响应<=256KiB — plus the stable-id rule of ``docs/agent-spec.md:50``. Those are rules about *values*, so they
are tested here by calling the functions, while :mod:`tests.integration.test_mcp_tools` proves the same functions
are reachable as real MCP tools. The split is deliberate: a rule test that had to spawn a server would be run
less often, and a protocol test that had to build a 300KiB body to exercise a limit would be slow for a reason
unrelated to what it checks.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.tools import catalog
from resolveflow.tools.catalog import MAX_TRACE_PAGES, ToolContext
from resolveflow.tools.upstream import (
    MAX_EXCERPT_BYTES,
    MAX_RAW_BYTES,
    UpstreamClient,
    UpstreamRefusedError,
    UpstreamUnavailableError,
)

SOURCE_REF = "commerce:/internal/v1/order-lines/7001/context"


def context(call_id: str = "call-1") -> ToolContext:
    return ToolContext(line_id="7001", run_id="run-1", tool_call_id=call_id, case_id="case-1")


def client_for(payload: Any, *, raw: bytes | None = None) -> UpstreamClient:
    """A client whose transport returns one canned answer, so the rules are the only thing under test."""
    body = json.dumps(payload).encode() if raw is None else raw

    def transport(request: Any) -> tuple[int, bytes]:
        return 200, body

    return UpstreamClient(
        case_base_url="http://case", commerce_base_url="http://commerce", service_token="t", _get=transport
    )


def failing_client(error: Exception) -> UpstreamClient:
    def transport(request: Any) -> tuple[int, bytes]:
        raise error

    return UpstreamClient(
        case_base_url="http://case", commerce_base_url="http://commerce", service_token="t", _get=transport
    )


# --------------------------------------------------------------- the two size rules


def test_an_excerpt_over_8kib_is_stated_rather_than_silently_cut() -> None:
    """``docs/agent-spec.md:36``: 给模型的excerpt<=8KiB.

    The raw body is what is stored and hashed; this bound is only about what the model reads. What matters is
    that an over-size result is **labelled**: a model handed half a document cannot tell that it is half, and
    would reason about it as though it were whole.
    """
    # A payload well over the excerpt limit but under the raw limit: the tool layer must not refuse it, only
    # excerpt it.
    huge = {"line_id": "7001", "note": "x" * (MAX_EXCERPT_BYTES * 2), "version": 3}
    observation = catalog.get_order_context(client_for(huge), context())

    assert observation.error is None
    assert observation.result is not None
    assert observation.result["truncated"] is True
    assert "note" in observation.result["members"] or "line_id" in observation.result["members"]
    # The hash still covers the bytes that were read, not the excerpt: a citation is checked against the source.
    assert observation.content_hash is not None and len(observation.content_hash) == 64


def test_a_body_over_256kib_is_refused_rather_than_truncated() -> None:
    """``docs/agent-spec.md:36``: 原始响应<=256KiB；过大返回明确错误并分页.

    Refused, not cut: a truncated document hashes to something no later check can reproduce, so every citation
    built on it would fail its own verification for a reason nobody could see.
    """
    oversized = json.dumps({"line_id": "7001", "note": "x" * (MAX_RAW_BYTES + 1024)}).encode()
    observation = catalog.get_order_context(client_for({}, raw=oversized), context())

    assert observation.result is None
    assert observation.error is not None
    assert observation.error.code == "UPSTREAM_UNAVAILABLE"
    assert observation.error.retryable is True, "the same read may fit after paging, so it is worth retrying"
    # No hash: nothing was kept, so nothing may be cited.
    assert observation.content_hash is None


# --------------------------------------------------------------- stable ids


def test_the_same_tool_call_yields_the_same_observation_id() -> None:
    """``docs/agent-spec.md:50``: 已落库模型/工具结果用稳定call_id复用.

    Retrying one call must not mint a second observation id: two ids for one attempt is how a stored result gets
    overwritten by its own replay, and how a reader sees two pieces of evidence where there was one.
    """
    client = client_for({"line_id": "7001", "version": 3})
    first = catalog.get_order_context(client, context("call-7"))
    again = catalog.get_order_context(client, context("call-7"))
    other = catalog.get_order_context(client, context("call-8"))

    assert first.observation_id == again.observation_id
    assert first.observation_id != other.observation_id


def test_two_tools_treat_the_same_call_id_as_two_observations() -> None:
    """The id names a (call, tool) pair, not a call: one id shared by two tools would collide in the ledger."""
    client = client_for({"line_id": "7001", "version": 3})
    order = catalog.get_order_context(client, context("call-1"))
    refund = catalog.get_refund_status(client, context("call-1"))
    assert order.observation_id != refund.observation_id


# --------------------------------------------------------------- failure classification


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (UpstreamRefusedError(403, "not yours"), "FORBIDDEN", False),
        (UpstreamRefusedError(404, "no such line"), "NOT_FOUND", False),
        (UpstreamRefusedError(400, "bad request"), "REQUEST_REFUSED", False),
        (UpstreamUnavailableError("upstream is down"), "UPSTREAM_UNAVAILABLE", True),
    ],
)
def test_a_failure_becomes_the_code_that_says_what_to_do(error: Exception, code: str, retryable: bool) -> None:
    """The code and ``retryable`` are the decision, so the mapping is asserted rather than the message.

    ``docs/agent-spec.md:36``: FORBIDDEN 停止 and NOT_FOUND 不是否定事实 — neither is retryable, because neither
    answer changes on a second attempt. An outage is the opposite case, and conflating the two is how a refusal
    turns into a retry loop or an outage turns into a permanent failure.
    """
    observation = catalog.get_order_context(failing_client(error), context())
    assert observation.error is not None
    assert observation.error.code == code
    assert observation.error.retryable is retryable
    assert observation.result is None
    assert observation.source_version is None and observation.content_hash is None


def test_a_failed_observation_is_still_an_observation_of_the_right_source() -> None:
    """Even a failure names what was being read: the trajectory has to show the attempt, not just the verdict.

    ``docs/agent-harness.md:51`` hands the error observation back to the model, and the model can only reason
    about it if it knows which source failed.
    """
    observation = catalog.get_shipment_trace(failing_client(UpstreamRefusedError(404, "none")), context())
    assert observation.tool_name == "get_shipment_trace"
    assert observation.source_type == EvidenceSourceType.SHIPMENT_TRACK
    assert observation.source_ref == "commerce:/internal/v1/order-lines/7001/shipment"
    assert observation.error is not None and observation.error.source_ref == observation.source_ref


# --------------------------------------------------------------- the trace budget


def test_the_trace_refuses_a_page_beyond_the_cap() -> None:
    """The cap is on reads (``docs/agent-spec.md:29`` 最多2页), and the refusal is its own code.

    ``PAGE_LIMIT`` rather than ``NOT_FOUND``: the shipment exists and was read; what ran out is the budget for
    reading it, and a model told "not found" would conclude the parcel has no trace.
    """
    observation = catalog.get_shipment_trace(
        client_for({"line_id": "7001", "events": [], "source_version": 1}), context(), page=MAX_TRACE_PAGES + 1
    )
    assert observation.error is not None
    assert observation.error.code == "PAGE_LIMIT"
    assert observation.error.retryable is False


def test_a_limit_over_the_cap_is_clamped_rather_than_trusted() -> None:
    """The schema caps ``limit`` at 20, and the function must not depend on the caller arriving through it.

    A tool reachable another way (a future HTTP surface, a test, a script) would otherwise be able to ask for
    everything at once, and the cap would hold only for callers that respected the schema.
    """
    events = [{"code": f"E{i}", "occurred_at": "2026-09-10T00:00:00Z", "source_version": i} for i in range(1, 51)]
    observation = catalog.get_shipment_trace(
        client_for({"line_id": "7001", "events": events, "source_version": 50}), context(), limit=1000
    )
    assert observation.result is not None
    assert len(observation.result["events"]) == catalog.TRACE_PAGE_LIMIT