"""Deterministic history projection and scoped, exact Unicode readback. No LLM summaries."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from resolveflow.harness.context import canonical_json
from resolveflow.support.protocol import ContextRead, SupportInput

CONTEXT_VERSION = "support-layered-v1"
# Each candidate is measured against the actual provider body, not a characters/token ratio.
LAYOUTS = ((4, 80, 20), (2, 40, 20), (1, 0, 20), (0, 0, 8), (0, 0, 0))


def history_messages(request: SupportInput, observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages = {m["sequence"]: m for m in request.context.get("history", [])
                if isinstance(m, dict) and isinstance(m.get("sequence"), int) and isinstance(m.get("text"), str)}
    for source in observations:
        if source.get("source_type") != "CONVERSATION":
            continue
        for message in source.get("data", {}).get("messages", []):
            if isinstance(message, dict) and isinstance(message.get("sequence"), int):
                # Immutable message text must not be replaced by a quote or a conflicting duplicate.
                if isinstance(message.get("text"), str):
                    prior = messages.get(message["sequence"])
                    if prior is not None and prior != message:
                        raise ValueError("conflicting immutable history")
                    messages[message["sequence"]] = message
    return [messages[key] for key in sorted(messages)]


def _preview(message: dict[str, Any], chars: int) -> dict[str, Any]:
    text = message["text"]
    return {k: message.get(k) for k in ("message_id", "sequence", "author", "recipient")} | {
        "read_ref": "H" + str(message["sequence"]), "total_chars": len(text),
        "truncated": len(text) > chars * 2,
        "excerpt": text if len(text) <= chars * 2 else text[:chars],
        "tail": text[-chars:] if chars and len(text) > chars * 2 else "",
    }


def render_context(
    request: SupportInput,
    base: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    recent: int = 4,
    preview: int = 80,
    index_limit: int = 20,
) -> dict[str, Any]:
    history = [m for m in history_messages(request, observations)
               if not (m["sequence"] == request.input_version and m["author"] == "CUSTOMER"
                       and m["text"] == request.context.get("current_request"))]
    full = history[-recent:] if recent else []
    earlier = history[:-recent] if recent else history
    indexed = earlier[-index_limit:] if index_limit else []
    omitted = earlier[:len(earlier) - len(indexed)]
    unique = []
    seen: set[str] = set()
    for source in observations:
        identity = canonical_json(source)
        if identity in seen:
            continue
        seen.add(identity)
        projected = deepcopy(source)
        if source.get("source_type") == "KNOWLEDGE":
            projected["data"] = {key: source["data"][key] for key in ("authority", "text")}
        elif source.get("source_type") == "CONVERSATION" and "messages" in source.get("data", {}):
            projected["data"]["messages"] = [_preview(m, min(preview, 40)) for m in source["data"]["messages"]]
        unique.append(projected)
    return {
        **base,
        "recent_messages": deepcopy(full),
        "history_index": [_preview(m, preview) for m in indexed],
        "history_read_refs": ["H" + str(m["sequence"]) for m in omitted],
        "observations": unique,
        "context_layout": {"version": CONTEXT_VERSION, "recent_full": len(full),
                           "preview_chars": preview, "indexed": len(indexed), "omitted_indices": len(omitted)},
    }


def read_context(
    request: SupportInput, observations: list[dict[str, Any]], arguments: dict[str, Any]
) -> dict[str, Any]:
    read = ContextRead.model_validate(arguments)
    message = next((m for m in history_messages(request, observations)
                    if "H" + str(m["sequence"]) == read.reference), None)
    if message is None:
        return {"error": "CONTEXT_REFERENCE_NOT_FOUND", "retryable": False}
    text = message["text"]
    if read.offset > len(text):
        return {"error": "CONTEXT_OFFSET_OUT_OF_RANGE", "retryable": False}
    end = min(read.offset + read.limit, len(text))
    return {"source_type": "CONVERSATION", "version": request.input_version, "data": {
        **{k: message.get(k) for k in ("message_id", "sequence", "author", "recipient")},
        "reference": read.reference, "offset": read.offset, "end": end, "total_chars": len(text),
        "text": text[read.offset:end], "complete": read.offset == 0 and end == len(text),
    }}
