"""The five whitelisted tools (``docs/agent-spec.md:26-32``) as plain Python, with no MCP in sight.

Keeping the tools here and the protocol in :mod:`resolveflow.tools.server` means the *rules* can be tested by
calling a function — no subprocess, no JSON-RPC — while the claim "these are MCP tools" is tested separately by
actually speaking MCP. A module that did both would make every rule test pay for a protocol handshake, and the
temptation to test the protocol by calling a function is how "real MCP" quietly becomes a local function.

Every tool answers with a :class:`~resolveflow.contracts.core_models.ToolObservation`: the evidence fields a
citation is checked against, plus an ``error`` member when nothing could be observed. Three rules are shared
and live in :mod:`resolveflow.tools.upstream`; the ones that belong to a *specific* tool are stated here:

- ``get_shipment_trace`` pages **at most twice** (``docs/agent-spec.md:29``). The budget is the reason: a tool
  that can extend its own paging forever is not bounded, and the run's tool-attempt budget
  (``docs/agent-spec.md:40``) would be spent re-reading one shipment.
- the cursor is **opaque and per-tool-call state**, not an offset a caller can guess. Handing out a number
  would make "page 3" expressible, and the two-page cap is the property being protected.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final

from resolveflow.contracts.core_models import CoreToolError, ToolObservation
from resolveflow.contracts.enums import EvidenceSourceType
from resolveflow.tools.result_validation import InvalidToolResult, validate_result
from resolveflow.tools.upstream import (
    MAX_EXCERPT_BYTES,
    UpstreamClient,
    UpstreamRefusedError,
    UpstreamUnavailableError,
)

__all__ = [
    "MAX_TRACE_PAGES",
    "TRACE_PAGE_LIMIT",
    "ToolContext",
    "get_case_evidence",
    "get_order_context",
    "get_policy_manifest",
    "get_refund_status",
    "get_shipment_trace",
    "observation_id_for",
]

#: ``docs/agent-spec.md:29``: limit<=20.
TRACE_PAGE_LIMIT: Final = 20

#: ``docs/agent-spec.md:29``: 最多2页.
MAX_TRACE_PAGES: Final = 2


@dataclass(frozen=True, slots=True)
class ToolContext:
    """What every tool needs to know about the run it is serving.

    ``line_id`` is the subject of the whole investigation and comes from the run, never from the model: the
    model choosing which line to read would be the model choosing what to investigate, and the case already
    fixed that (``docs/core-scope.md:9`` — one order line). ``tool_call_id`` is the stable id
    ``docs/agent-spec.md:50`` reuses a stored result by, so the same call does not produce a second observation.
    """

    line_id: str
    run_id: str
    tool_call_id: str
    case_id: str | None = None
    now: dt.datetime | None = None

    def observed_at(self) -> str:
        moment = self.now or dt.datetime.now(dt.UTC)
        return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def observation_id_for(tool_name: str, context: ToolContext) -> str:
    """A stable, readable id for one tool call: the same call twice yields the same id.

    Derived from the call id rather than from a counter, because ``docs/agent-spec.md:50`` wants a stored result
    reused by a stable id — and a counter would hand the same call a new identity on every retry, which is how a
    duplicate attempt becomes a second piece of evidence.

    Public because the MCP layer needs it too: a tool that never reached this module (the line is not
    configured, so there was nothing to read) still owes the caller an observation with an id, and it must not
    invent a second scheme for one.
    """
    digest = hashlib.sha256(f"{context.tool_call_id}:{tool_name}".encode()).hexdigest()[:16]
    return f"obs-{tool_name[:40]}-{digest}"


def _observation_id(context: ToolContext, tool_name: str) -> str:
    return observation_id_for(tool_name, context)


def _excerpt(body: dict[str, Any]) -> dict[str, Any]:
    """The part of a result the model may see: ``docs/agent-spec.md:36`` 给模型的excerpt<=8KiB.

    The raw body was already stored and hashed by the caller. This only bounds what is handed to the model, and
    it is done by serialising and if necessary replacing the payload with a stated truncation marker rather than
    silently cutting it: a model given half a document cannot tell it is half.
    """
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, default=str).encode()
    if len(encoded) <= MAX_EXCERPT_BYTES:
        return body
    return {
        "truncated": True,
        "note": f"the stored result is {len(encoded)} bytes; this excerpt shows its shape only",
        "members": sorted(body),
    }


def _observed(
    tool_name: str,
    source_type: EvidenceSourceType,
    source_ref: str,
    source_version: str,
    content_hash: str,
    result: dict[str, Any],
    context: ToolContext,
) -> ToolObservation:
    return ToolObservation(
        observation_id=_observation_id(context, tool_name),
        tool_name=tool_name,
        source_type=source_type,
        source_ref=source_ref,
        source_version=source_version,
        content_hash=content_hash,
        observed_at=context.observed_at(),
        result=_excerpt(result),
    )


def _failed(
    tool_name: str,
    source_type: EvidenceSourceType,
    source_ref: str,
    error: CoreToolError,
    context: ToolContext,
) -> ToolObservation:
    """An observation with no source version and no hash, because nothing was observed.

    This is the shape ``docs/agent-harness.md:51`` needs to hand back to the model. Inventing a version or a
    hash here would make an unread source look citable, which is the one thing a citation check cannot catch
    after the fact — it would compare a hash the Agent made up against itself. Both members are left out rather
    than validated away, and :class:`~resolveflow.contracts.core_models.CoreObservation` refuses to carry just
    one of them.
    """
    return ToolObservation(
        observation_id=_observation_id(context, tool_name),
        tool_name=tool_name,
        source_type=source_type,
        source_ref=source_ref,
        observed_at=context.observed_at(),
        error=error,
    )


def _code_for(error: Exception) -> tuple[str, bool]:
    """The observation code and whether another attempt could change the answer.

    ``docs/agent-spec.md:36``: NOT_FOUND 不是否定事实；FORBIDDEN 停止，不更换ID重试. So a refusal is
    ``FORBIDDEN`` and not retryable, a missing source is ``NOT_FOUND`` and not retryable either — the source
    being absent is not something another attempt fixes — while a 5xx or a timeout is ``UPSTREAM_UNAVAILABLE``
    and *is* worth another attempt. The distinction is the whole reason ``retryable`` is on the wire.
    """
    if isinstance(error, UpstreamRefusedError):
        if error.status == 404:
            return "NOT_FOUND", False
        if error.status in (401, 403):
            return "FORBIDDEN", False
        return "REQUEST_REFUSED", False
    if isinstance(error, UpstreamUnavailableError):
        return "UPSTREAM_UNAVAILABLE", True
    return "TOOL_FAILED", False


def _read_or_fail(
    tool_name: str,
    source_type: EvidenceSourceType,
    source_ref: str,
    context: ToolContext,
    read: Any,
) -> tuple[Any, ToolObservation | None]:
    """Run one upstream read, turning a failure into an error observation instead of an exception.

    A tool that raised would lose the attempt: the run would have no observation to show the model or the
    trajectory. ``docs/agent-harness.md:51`` requires the error observation back, so every failure here becomes
    one.
    """
    try:
        answer = read()
        validate_result(tool_name, answer.body, line_id=context.line_id, case_id=context.case_id)
        return answer, None
    except InvalidToolResult as error:
        return None, _failed(tool_name, source_type, source_ref,
                            CoreToolError(code=error.code, message=str(error), retryable=False,
                                          source_ref=source_ref), context)
    except (UpstreamRefusedError, UpstreamUnavailableError) as error:
        code, retryable = _code_for(error)
        return None, _failed(
            tool_name,
            source_type,
            source_ref,
            CoreToolError(code=code, message=str(error)[:512], retryable=retryable, source_ref=source_ref),
            context,
        )


# ------------------------------------------------------------------ the five tools


def _order_source_version(body: dict[str, Any]) -> str:
    if not any(key in body for key in ("payment_version", "fulfillment_version", "fulfillment_status")):
        return str(body.get("version", ""))
    version = (f"order-{body.get('version', '')}:payment-{body.get('payment_version', 'missing')}:"
               f"fulfillment-{body.get('fulfillment_version', 'missing')}")
    # Preserve all component versions in result/P2; the citation identity itself is capped at 64 characters.
    return version if len(version) <= 64 else hashlib.sha256(version.encode()).hexdigest()


def get_order_context(client: UpstreamClient, context: ToolContext) -> ToolObservation:
    """The current line's order and payment facts (``docs/agent-spec.md:28``).

    This is the authority for the amount, which is why it is a read of Commerce rather than of the case: Java
    recomputes the refundable amount from the same row (``docs/product-spec.md:25``), and a tool that returned
    its own arithmetic would be a second opinion about money.
    """
    tool = "get_order_context"
    source = EvidenceSourceType.ORDER_LINE
    source_ref = f"commerce:/internal/v1/order-lines/{context.line_id}/context"
    answer, failure = _read_or_fail(
        tool,
        source,
        source_ref,
        context,
        lambda: client.read("commerce", f"/internal/v1/order-lines/{context.line_id}/context"),
    )
    if failure is not None:
        return failure
    body = answer.body
    return _observed(
        tool,
        source,
        source_ref,
        _order_source_version(body),
        answer.content_hash,
        body,
        context,
    )


def get_shipment_trace(
    client: UpstreamClient,
    context: ToolContext,
    *,
    cursor: str | None = None,
    limit: int = TRACE_PAGE_LIMIT,
    page: int = 1,
) -> ToolObservation:
    """The synthetic shipment events, at most two pages of at most 20 (``docs/agent-spec.md:29``).

    ``page`` is how many times this tool has read for this run, and it is the budget: the cap is on reads, so a
    continuation costs one. The page *number* returned is a different fact and travels in the cursor, because
    counting reads and numbering pages diverge the moment a page is continued.

    The cursor is opaque and carries the event version to resume after, so a caller cannot ask for an arbitrary
    offset — and a cursor this tool did not issue is refused rather than interpreted.
    """
    tool = "get_shipment_trace"
    source = EvidenceSourceType.SHIPMENT_TRACK
    source_ref = f"commerce:/internal/v1/order-lines/{context.line_id}/shipment"

    # `page` is how many times this tool has run for this run, and that is the budget: the cap is on reads, so
    # continuing a page costs one. Two things this must not be confused with: the *number* of the page being
    # returned (2 for the first continuation, which the cursor carries) and the number of fresh pages.
    if page > MAX_TRACE_PAGES:
        return _failed(
            tool,
            source,
            source_ref,
            CoreToolError(
                code="PAGE_LIMIT",
                message=f"a shipment trace may be read at most {MAX_TRACE_PAGES} times per run",
                retryable=False,
                source_ref=source_ref,
            ),
            context,
        )
    bounded = max(1, min(int(limit), TRACE_PAGE_LIMIT))
    after: int | None = None
    page_number = page
    if cursor is not None:
        decoded = _decode_cursor(cursor)
        if decoded is None:
            return _failed(
                tool,
                source,
                source_ref,
                CoreToolError(
                    code="INVALID_CURSOR",
                    message="this cursor was not issued by get_shipment_trace",
                    retryable=False,
                    source_ref=source_ref,
                ),
                context,
            )
        # The page number travels in the cursor rather than being counted here, because the count of *reads* and
        # the number of the page returned are different numbers as soon as a page is continued.
        after, page_number = decoded

    answer, failure = _read_or_fail(
        tool,
        source,
        source_ref,
        context,
        lambda: client.read("commerce", f"/internal/v1/order-lines/{context.line_id}/shipment"),
    )
    if failure is not None:
        return failure

    body = answer.body
    events = [event for event in body.get("events", []) if isinstance(event, dict)]
    # A late event that arrived with a lower version must not be shown as newer: the same rule the snapshot's
    # source_version exists for. Ordering by version here keeps the page meaningful even if the upstream order
    # ever changes.
    events.sort(key=lambda event: event.get("source_version", 0))
    if after is not None:
        events = [event for event in events if event.get("source_version", 0) > after]
    window = events[:bounded]
    more = len(events) > len(window)

    result: dict[str, Any] = {
        "line_id": body.get("line_id", context.line_id),
        "synthetic": body.get("synthetic", True),
        "status": body.get("status"),
        "carrier_conclusion": body.get("carrier_conclusion"),
        "events": window,
        "source_version": body.get("source_version"),
        "updated_at": body.get("updated_at"),
        "page": page_number,
        "next_cursor": _encode_cursor(window[-1]["source_version"], page_number + 1) if more and window else None,
    }
    return _observed(
        tool, source, source_ref, str(body.get("source_version", "")), answer.content_hash, result, context
    )


def get_refund_status(client: UpstreamClient, context: ToolContext) -> ToolObservation:
    """The current line's refund state (``docs/agent-spec.md:30``).

    The refundable amount is deliberately **not** returned by Commerce and not derived here: it is paid minus
    refunded minus reserved, and a stored or re-derived copy is how two services start disagreeing about the same
    money (contracts/core/openapi-commerce.yaml readLineRefundStatus).
    """
    tool = "get_refund_status"
    source = EvidenceSourceType.PAYMENT_LEDGER
    source_ref = f"commerce:/internal/v1/order-lines/{context.line_id}/refund-status"
    answer, failure = _read_or_fail(
        tool,
        source,
        source_ref,
        context,
        lambda: client.read("commerce", f"/internal/v1/order-lines/{context.line_id}/refund-status"),
    )
    if failure is not None:
        return failure
    body = answer.body
    return _observed(tool, source, source_ref, str(body.get("version", "")), answer.content_hash, body, context)


def get_case_evidence(
    client: UpstreamClient,
    context: ToolContext,
    *,
    kind: str | None = None,
) -> ToolObservation:
    """The case's material at its current revision (``docs/agent-spec.md:31``).

    ``kind`` narrows the material the case already holds — it does not let the caller ask for material the case
    does not have. The revision is the source version: evidence belongs to a revision, and a decision made
    against revision 3 must not be recorded against revision 4 (``docs/domain-model.md``).
    """
    tool = "get_case_evidence"
    source = EvidenceSourceType.CUSTOMER_STATEMENT
    if context.case_id is None:
        raise ValueError("reading case evidence needs the case this run belongs to")
    source_ref = f"case:/internal/v1/cases/{context.case_id}/evidence"
    answer, failure = _read_or_fail(
        tool,
        source,
        source_ref,
        context,
        lambda: client.read(
            "case",
            f"/internal/v1/cases/{context.case_id}/evidence",
            {"kind": kind} if kind else None,
        ),
    )
    if failure is not None:
        return failure
    body = answer.body
    version = body.get("input_revision", body.get("revision", body.get("version", "")))
    return _observed(tool, source, source_ref, str(version), answer.content_hash, body, context)


def get_policy_manifest(client: UpstreamClient, context: ToolContext) -> ToolObservation:
    """The policy version the case is bound to (``docs/agent-spec.md:32``).

    Bound, not chosen: the run must not silently swap its manifest (``docs/core-scope.md`` invariants), so this
    reads the case's pinned manifest rather than letting a caller name a bundle.

    **The version is ``bundles[0].manifest_hash``.** Case answers the contract's ``PolicyManifestResponse``:
    ``{bundles: [{bundle_ids, manifest_hash, safety_epoch}], effective_from, effective_to}``. There is no
    top-level ``version`` or ``bundle_version``. Until C06.4⑤ this read the latter two, and the *stub* answered
    ``version`` — so the tool and the stub agreed with each other and disagreed with the service, and against the
    real Case every read produced ``source_version == ""``. That is not a cosmetic bug: the core wire requires a
    non-empty ``source_version``, so the observation could not even be constructed, and a run that read its policy
    would have died at the DTO instead of deciding anything. The hash is the right member anyway — it is what a
    ``CorePolicyRef`` is checked against, and the only member of the answer that identifies which policy decided
    this case.
    """
    tool = "get_policy_manifest"
    source = EvidenceSourceType.POLICY_RULE
    if context.case_id is None:
        raise ValueError("reading the policy manifest needs the case this run belongs to")
    source_ref = f"case:/internal/v1/cases/{context.case_id}/policy-manifest"
    answer, failure = _read_or_fail(
        tool,
        source,
        source_ref,
        context,
        lambda: client.read("case", f"/internal/v1/cases/{context.case_id}/policy-manifest"),
    )
    if failure is not None:
        return failure
    body = answer.body
    version = _manifest_hash_of(body, source_ref)
    return _observed(tool, source, source_ref, version, answer.content_hash, body, context)


def _manifest_hash_of(body: dict[str, Any], source_ref: str) -> str:
    """The bound manifest's hash, or a refusal naming what was wrong with the answer.

    A malformed answer is reported as an unavailable upstream rather than as an empty version. The service is
    reachable and answered, but with something this tool cannot read, and the two available lies are worse: an
    empty version makes an uncitable manifest look citable, and inventing one makes the citation check compare a
    made-up hash against itself.
    """
    bundles = body.get("bundles")
    if not isinstance(bundles, list) or not bundles:
        raise UpstreamUnavailableError(f"{source_ref} answered no bundles, so there is no manifest to cite")
    first = bundles[0]
    if not isinstance(first, dict):
        raise UpstreamUnavailableError(f"{source_ref} answered a bundle that is not an object")
    manifest_hash = first.get("manifest_hash")
    if not isinstance(manifest_hash, str) or not manifest_hash:
        raise UpstreamUnavailableError(f"{source_ref} answered a bundle with no manifest_hash")
    return manifest_hash


# ------------------------------------------------------------------ cursors


def _encode_cursor(source_version: Any, next_page: int) -> str:
    """An opaque cursor naming the version to resume after, and which page that continuation is.

    Opaque on purpose: a readable offset would let a caller ask for page 3 of a two-page budget, and it would
    make the paging contract look like an API a caller may drive rather than a bound the run enforces.
    """
    payload = json.dumps({"after": int(source_version), "page": int(next_page)}).encode()
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_cursor(cursor: str) -> tuple[int, int] | None:
    """The version and page a cursor names, or ``None`` if it is not one this tool issued."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    after = payload.get("after")
    page = payload.get("page")
    if not isinstance(after, int) or isinstance(after, bool) or after < 0:
        return None
    if not isinstance(page, int) or isinstance(page, bool) or page < 2:
        # A continuation is never page 1: a first page has no cursor to arrive on.
        return None
    return after, page
