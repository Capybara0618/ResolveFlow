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
    elif code == "ACTION_CITATION_INVALID":
        category, next_step = "SOURCE", ('Use only the listed P2 aliases of the required kind; '
            'failed reads are not citations. Read another source or ESCALATE.')
    elif code == "FACT_CLAIM_UNSUPPORTED":
        category, next_step = "FACT", "Remove or correct unsupported assertions; read the source or hand over."
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
