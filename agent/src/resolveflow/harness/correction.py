"""Small, deterministic error taxonomy. Feedback is instructions, never evidence."""

from typing import Any

SECURITY_ERRORS = frozenset({"FORBIDDEN", "SOURCE_MISMATCH", "IDENTITY_REFUSED", "WRITE_TOOL_REFUSED",
                             "ARBITRARY_URL_REFUSED", "CROSS_SCOPE_CITATION"})


def feedback(code: str, detail: str, *, repair: bool = False) -> dict[str, Any]:
    if code in SECURITY_ERRORS:
        category, next_step = "PERMISSION", "Stop; do not change identity or bypass scope. Human review required."
    elif code == "MODEL_JSON_INVALID":
        category, next_step = "FORMAT", ('Return flat JSON, no type wrapper. Handover: '
            '{"kind":"ESCALATE","reason_codes":["NEEDS_HUMAN_VERIFICATION"]}.')
    elif code == "ACTION_REFUSED":
        category, next_step = "FORMAT", ('Use published flat fields; no type/action wrapper. If unable: '
            '{"kind":"ESCALATE","reason_codes":["NEEDS_HUMAN_VERIFICATION"]}.')
    elif code == "FINDING_SOURCE_INVALID":
        category, next_step = "SOURCE", ("Fix the named finding/evidence_refs association or drop unsupported finding; "
            "CONFLICT needs actual disagreeing sources. Never add unrelated sources to meet the count.")
    elif code in {"QUESTION_RESPONSIBILITY_INVALID", "REQUEST_INFO_INCOMPLETE"}:
        category, next_step = "ACTION", ("Customer materials: explicit gaps or ASK_CUSTOMER. System/merchant facts: "
            "bound reads or handover. REQUEST_INFO is a merchant suggestion, not a sent customer question.")
    elif code == "ACTION_CITATION_INVALID":
        category, next_step = "SOURCE", ('Use only the listed P2 aliases of the required kind; '
            'failed reads are not citations. Read another source or ESCALATE.')
    elif code == "FACT_CLAIM_UNSUPPORTED":
        category, next_step = "FACT", "Remove or correct unsupported assertions; read the source or hand over."
    elif code == "UNSHIPPED_FACTS_REQUIRED":
        category, next_step = "FACT", ('Check the named current fields. Occupied/unknown is not refundable; '
            'a failed entitlement condition does not justify REJECT. Missing source: read it. Conflict: '
            '{"kind":"ESCALATE","reason_codes":["NEEDS_HUMAN_VERIFICATION"]}.')
    elif code == "INVESTIGATION_FACTS_REQUIRED":
        category, next_step = "FACT", (
            "未读来源可补查；已读材料但缺关联CONFIRMED时，不能把等待商家最终审批当成已完成核验。"
            "可PROPOSE recommended_action=MANUAL_REVIEW，引用已查事实/政策，summary说明待商家核验及下一步。"
            "商家核验不是客户补证，不让客户提供系统或核验记录；确有客户可补的信息才ASK_CUSTOMER。"
            "若来源失败或无法形成有依据建议，可ESCALATE。只重发一个完整动作，不重复原REFUND。")
    elif "CITATION" in code or "FACTS_REQUIRED" in code or "EVIDENCE" in code:
        category, next_step = "SOURCE", "Use current observed sources; investigate missing facts or hand over."
    elif code in {"TOOL_TRANSIENT", "UPSTREAM_UNAVAILABLE"}:
        category, next_step = "TRANSIENT", "Retry the same bound read at most once, use another source, or hand over."
    elif code in {"TOOL_RESULT_INVALID", "MCP_PROTOCOL_FAILED", "NOT_FOUND", "REQUEST_REFUSED"}:
        category, next_step = "TOOL_DATA", "Do not repeat or treat failure as fact; use another source or hand over."
    else:
        category, next_step = "ACTION", "Fix the named constraint using the published protocol, or hand over."
    return {"reason": code, "category": category, "detail": detail[:600], "next_step": next_step,
            "repair_remaining": int(repair)}


def notice(record: dict[str, Any]) -> str:
    return (f"REFUSED {record['reason']} [{record['category']}]: {record['detail']}. "
            f"{record['next_step']} repair_remaining={record['repair_remaining']}")
