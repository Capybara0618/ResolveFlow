"""Model-visible capabilities and precise, bounded action feedback; no business route selection."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from resolveflow.support.dialogue import DialogueStateError
from resolveflow.support.memory import MemoryStateError
from resolveflow.support.tasks import TaskStateError

CAPABILITIES: dict[str, dict[str, Any]] = {
    "get_order_context": {
        "purpose": "订单/付款。",
        "action": {"kind": "READ_TOOL", "tool_name": "get_order_context", "arguments": {}},
    },
    "get_shipment_trace": {
        "purpose": "实时物流/事件；失败非丢失。",
        "action": {"kind": "READ_TOOL", "tool_name": "get_shipment_trace", "arguments": {}},
    },
    "read_history": {
        "purpose": "更早原文。",
        "action": {"kind": "READ_TOOL", "tool_name": "read_history", "arguments": {"limit": 5}},
    },
    "read_context": {
        "purpose": "H原文；offset/limit为字符。",
        "action": {"kind": "READ_TOOL", "tool_name": "read_context", "arguments": {"reference": "H1", "limit": 500}},
    },
    "get_support_guide": {
        "purpose": "平台流程/入口/共享；无法读取须说明。",
        "action": {"kind": "READ_TOOL", "tool_name": "get_support_guide", "arguments": {}},
    },
    "search_policy": {
        "purpose": "资格/例外/金额，非入口。",
        "action": {"kind": "READ_TOOL", "tool_name": "search_policy",
                   "arguments": {"query": "当前要了解的资格条件", "top_k": 3}},
    },
}


def capabilities() -> dict[str, Any]:
    return deepcopy(CAPABILITIES)


def tool_schema(name: str) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required = []
    if name == "search_policy":
        properties = {
            "query": {"type": "string", "minLength": 1, "maxLength": 1000},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 5},
        }
        required = ["query"]
    elif name == "read_history":
        properties = {
            "before_sequence": {"type": "integer", "minimum": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 5},
        }
    elif name == "read_context":
        properties = {
            "reference": {"type": "string", "pattern": "^H[1-9][0-9]*$"},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
        }
        required = ["reference"]
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def decision_feedback(error: Exception, payload: Any, references: list[str]) -> str:
    result: dict[str, Any] = {
        "code": "INVALID_DECISION", "remaining_repairs": 0, "resubmit": "FULL_ACTION",
        "rejected_annotations_committed": False,
        "resubmit_note": "被拒动作的标注未保存；重发完整动作及所需tasks/dialogue_events，不只补字段。"
                         "以当前task_state/dialogue_state为准，已有任务不用ADD。",
    }
    if isinstance(error, DialogueStateError):
        result.update(field="dialogue_events", detail=str(error))
        if error.missing_task_ids:
            result.update(
                issue="DIALOGUE_COVERAGE", missing_task_ids=error.missing_task_ids,
                required_on_action=["tasks", "dialogue_events"],
                resubmit_note="被拒标注未提交；按当前task_state重发完整动作。",
                repair_note="同change/原句可用task_ids数组共享一事件，或逐项task_id，两者二选一。"
                            "覆盖所列缺项，reference=CURRENT、offset=0、quote为本轮原文。",
            )
    elif isinstance(error, MemoryStateError):
        result.update(field="memory_updates", detail=str(error))
    elif isinstance(error, TaskStateError):
        result.update(field="tasks", detail=str(error), issue=error.issue, task_ids=error.task_ids)
        if error.issue == "TASKS_REQUIRED":
            result.update(required_on_answer=["tasks", "dialogue_events"],
                          repair_note="只读取证不需标注；发布时同层声明tasks和当前原文dialogue_events，"
                                      "再给覆盖全部事项的parts。不能直接发布无任务的回答。")
        elif error.issue == "ANSWER_PARTS_COVERAGE":
            result.update(field="parts", repair_note="逐项给task_id/status/text/citations；覆盖全部task_state任务。"
                          "首次先声明tasks；不能省略任务或自动完成。")
        elif error.issue in {"ANSWER_TASKS_PENDING", "TASKS_REMOVED"}:
            result.update(
                resubmit_note="被拒标注未保存，沿用已接受task_state。",
                required_on_answer=["tasks"],
                status_choices=["ANSWERED", "NEEDS_CUSTOMER", "NEEDS_MERCHANT", "UNAVAILABLE", "CANCELLED",
                                "SUSPENDED"],
                repair_note="ANSWER同层重发全量tasks，沿用id/intent/request；response_excerpt用text原句，"
                            "evidence_refs须已读并在citations中；依据不足可继续读取，勿虚标完成。",
            )
    elif (isinstance(payload, dict) and isinstance(payload.get("kind"), str)
          and payload["kind"] in CAPABILITIES):
        name = payload["kind"]
        result.update(
            field="kind",
            detail="kind是动作类别，工具名写在tool_name；请重新输出目录中的完整动作。",
            example=CAPABILITIES[name]["action"],
        )
    elif isinstance(error, ValidationError) and any(
        e["type"] in {"union_tag_not_found", "union_tag_invalid"} and not e["loc"]
        for e in error.errors(include_input=False, include_context=False)
    ):
        result.update(
            field="kind", required=True, allowed=["READ_TOOL", "SEARCH_POLICY", "ANSWER", "ANSWER_PARTS"],
            detail="顶层kind缺失或非法。只重发一个完整动作；动作参数和标注在同层，不能嵌套ANSWER或用type替代kind。",
            examples=[CAPABILITIES["get_shipment_trace"]["action"],
                      {"kind": "SEARCH_POLICY", "query": "政策条件", "top_k": 3},
                      {"kind": "ANSWER", "text": "回答或必要追问", "citations": [], "handoff_summary": None},
                      {"kind": "ANSWER_PARTS", "parts": [{"task_id": "t1", "status": "ANSWERED",
                                                          "text": "答复", "citations": []}]}],
        )
    elif isinstance(error, ValidationError) and any(
        "dialogue_events" in e["loc"] and any(key in e["loc"] for key in {"reference", "offset", "quote"})
        for e in error.errors(include_input=False, include_context=False)
    ):
        result.update(
            field="dialogue_events.reference", reference="CURRENT", offset=0,
            detail="对话变化引用本轮客户原文：reference=CURRENT，offset=0，quote取current_request开头最多300字。"
                   "不能用O/P工具编号、sequence:N或null。每任务仅一项当前变化，不能补记整个历史事件。",
        )
    elif isinstance(error, ValidationError):
        result.update(
            field="schema",
            errors=[
                {"path": ".".join(map(str, item["loc"])), "type": item["type"]}
                for item in error.errors(include_input=False, include_context=False)[:4]
            ],
            detail="使用capabilities动作形状，只输出一个JSON，禁未知字段。"
                   "读取可省略tasks/dialogue_events；输入包中的说明键不属于输出。",
        )
    else:
        result.update(
            field="citations", available=references, detail="只能引用已读且存在的编号；缺少依据时先选择相应读取工具。"
        )
    return json.dumps(result, ensure_ascii=False)
