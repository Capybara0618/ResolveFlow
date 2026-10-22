"""Finite status/source consistency, not a semantic judge or a fixed tool workflow."""

from __future__ import annotations

from typing import Any

from resolveflow.support.protocol import Answer, SupportTask

GUIDE_INTENTS = {"APPLICATION", "HANDOFF"}
RELEVANT_FAILURES = {
    "APPLICATION": {"get_support_guide"}, "HANDOFF": {"get_support_guide"},
    "LOGISTICS": {"get_shipment_trace"},
    "ELIGIBILITY": {"search_policy", "get_order_context", "get_shipment_trace"},
    "PRODUCT": {"get_order_context", "search_policy"},
}


class CompletionError(ValueError):
    def __init__(self, gaps: list[dict[str, Any]]) -> None:
        super().__init__("Task completion needs actual evidence or explicit blocking cause")
        self.gaps = gaps


def requirements(tasks: list[SupportTask], citations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    active = [t for t in tasks if t.status not in {"ANSWERED", "CANCELLED", "SUSPENDED"}]
    if not active:
        return {}
    intents = {t.intent for t in active}
    completion: dict[str, Any] = {}
    if intents & GUIDE_INTENTS:
        completion["APPLICATION/HANDOFF"] = "get_support_guide引用"
    if "ELIGIBILITY" in intents:
        completion["ELIGIBILITY/ANSWERED"] = "search_policy引用"
    if any(t.status == "NEEDS_CUSTOMER" for t in active):
        completion["NEEDS_CUSTOMER"] = {"blocker": {
            "kind": "CUSTOMER_INFO", "detail": "缺口", "question": "本段提问原句"}}
    if any(t.status == "UNAVAILABLE" for t in active):
        completion["UNAVAILABLE"] = {"blocker": {
            "kind": "SOURCE_FAILURE", "detail": "原因", "tool_name": "实际失败工具"}}
    return {"unresolved": [{"task_id": t.id, "status": t.status} for t in active],
            "completion": completion,
            "available_sources": {ref: source.get("source_type") for ref, source in citations.items()}}


def check_completion(
    answer: Answer, tasks: list[SupportTask], citations: dict[str, dict[str, Any]], failures: list[dict[str, Any]],
    lifecycles: dict[str, str] | None = None,
) -> None:
    gaps: list[dict[str, Any]] = []
    failed_tools = {f["tool_name"] for f in failures}
    for task in tasks:
        if task.status in {"CANCELLED", "SUSPENDED"} or (lifecycles or {}).get(task.id) in {"RESOLVED", "CANCELLED"}:
            continue
        blocker = task.blocker
        sources = [citations[ref] for ref in task.evidence_refs if ref in citations]
        if task.status == "UNAVAILABLE":
            relevant = RELEVANT_FAILURES.get(task.intent, failed_tools)
            if (blocker is None or blocker.kind != "SOURCE_FAILURE" or blocker.tool_name not in failed_tools
                    or blocker.tool_name not in relevant):
                gaps.append({"task_id": task.id, "code": "SOURCE_FAILURE_REQUIRED",
                             "failed_tools": sorted(failed_tools & relevant)})
            continue
        if task.intent in GUIDE_INTENTS and not any(
            s.get("source_type") == "KNOWLEDGE" and s.get("data", {}).get("authority") == "APPLICATION_GUIDE"
            for s in sources
        ):
            gaps.append({"task_id": task.id, "code": "SOURCE_REQUIRED", "tool_name": "get_support_guide"})
        if task.intent == "ELIGIBILITY" and task.status == "ANSWERED" and not any(
            s.get("source_type") == "POLICY" for s in sources
        ):
            gaps.append({"task_id": task.id, "code": "SOURCE_REQUIRED", "tool_name": "search_policy"})
        if task.status == "NEEDS_CUSTOMER":
            if (blocker is None or blocker.kind != "CUSTOMER_INFO" or blocker.question is None
                    or blocker.question not in answer.text or blocker.question not in (task.response_excerpt or "")):
                gaps.append({"task_id": task.id, "code": "CUSTOMER_QUESTION_REQUIRED"})
        elif blocker is not None:
            gaps.append({"task_id": task.id, "code": "BLOCKER_STATUS_MISMATCH"})
    if gaps:
        raise CompletionError(gaps)
