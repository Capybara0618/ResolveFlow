"""Closed operation-purpose classification; quotes and scope remain owned by the Harness."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from resolveflow.support.jev import JevConfig
from resolveflow.support.orchestration_prompts import REQUEST_CHECK_SYSTEM
from resolveflow.support.request_check import RequestCheck

VERSION = "jev-operation-purpose-v1"
OPTIONS = {
    "INFORMATION": "仅咨询条件、进度、方法、入口或协助对象，没有要求准备操作材料。",
    "PREPARE_REFUND": "本轮要求准备退款原因/申请材料，或明确要求申请退款；先不提交仍可准备。",
    "MERCHANT_REVIEW": "本轮要求准备给商家的核查摘要/说明，或请商家核查；先不发送仍可准备。",
    "DECLINED": "本事项明确暂缓、撤回或仅假设以后再办；不把另一事项的拒绝扩散到本事项。",
    "UNCLEAR": "本轮与必要历史不足以判断该事项的用途，存在未消解指代或冲突。",
}
# Keep the same semantic policy as the existing LLM; only the transport/output schema changes.
POLICY = REQUEST_CHECK_SYSTEM.split("只输出单JSON：", 1)[0]


@dataclass(frozen=True)
class IntentPolicy:
    enabled: bool = False
    minimum_confidence: float = .70

    def manifest(self) -> dict[str, Any]:
        return {"version": VERSION, "enabled": self.enabled, "minimum_confidence": self.minimum_confidence,
                "fallback": "original-model", "whole_batch": True}


def pending_tasks(packet: dict[str, Any]) -> list[dict[str, str]]:
    tasks = packet.get("orchestration", {}).get("request_check", {}).get("tasks", [])
    current = packet.get("current_request", "")
    if not isinstance(current, str) or not isinstance(tasks, list) or not 1 <= len(tasks) <= 2:
        raise ValueError("bounded request check tasks required")
    ids = set()
    for task in tasks:
        if (not isinstance(task, dict) or not isinstance(task.get("task_id"), str)
                or task["task_id"] in ids or not isinstance(task.get("quote"), str)
                or not 0 < len(task["quote"]) <= 300 or task["quote"] not in current):
            raise ValueError("task quote must match the current customer text")
        ids.add(task["task_id"])
    return tasks


def build_intent_request(config: JevConfig, packet: dict[str, Any]) -> dict[str, Any]:
    tasks = pending_tasks(packet)
    # Never pass proposed goals, order anomalies or generated answers as proof of intent.
    state: dict[str, Any] = {k: deepcopy(packet[k]) for k in ("current_request", "recent_messages", "history_index",
                                            "history_read_refs", "feedback") if k in packet}
    state["tasks"] = [{"task_id": t["task_id"], "quote": t["quote"]} for t in tasks]
    return {"model": config.model, "state": state, "questions": {
        f"purpose_{i}": {"type": "choice", "instructions": POLICY +
                       f"\n本题只选择state.tasks[{i}]对应事项的purpose，结合本轮完整原话理解，不能继承其他事项的用途。",
                       "criteria": OPTIONS} for i, _ in enumerate(tasks)}}


def intent_decision(packet: dict[str, Any], result: dict[str, Any], policy: IntentPolicy) -> dict[str, Any] | None:
    tasks = pending_tasks(packet)
    answers = result["answers"]
    if set(answers) != {f"purpose_{i}" for i in range(len(tasks))}:
        raise ValueError("question coverage mismatch")
    assessments = []
    for i, task in enumerate(tasks):
        answer = answers[f"purpose_{i}"]
        if answer["confidence"] < policy.minimum_confidence or answer["choice"] == "UNCLEAR":
            return None
        assessments.append({"task_id": task["task_id"], "purpose": answer["choice"], "quote": task["quote"],
                            "reason": "Jev用途分类：" + answer["choice"] + "；原话由程序保留，最终提交须本人确认。"})
    return cast(dict[str, Any], RequestCheck(kind="CHECK_REQUEST", assessments=assessments).model_dump())
