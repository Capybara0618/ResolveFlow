"""Source-anchored task changes; explicit pauses and cancellations, no keyword router."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from resolveflow.support.memory import MemoryStateError, customer_source
from resolveflow.support.protocol import DialogueEvent, SupportInput, SupportTask
from resolveflow.support.tasks import previous_hint


class DialogueStateError(ValueError):
    pass


class DialogueState:
    def __init__(self, request: SupportInput) -> None:
        self.request = request
        hint = previous_hint(request.context, request.input_version)
        self.before = {t["id"]: t["previous_status"] for t in (hint or {}).get("tasks", [])
                       if t["previous_status"] not in {"ANSWERED", "CANCELLED"}}
        self.started = False
        self.events: list[dict[str, Any]] = []

    def apply(
        self, events: list[DialogueEvent], tasks: list[SupportTask], observations: list[dict[str, Any]],
        *, require: bool,
    ) -> None:
        if not events and not self.started and not require:
            return  # Old scripted clients remain compatible; this does not demonstrate understanding.
        after = {t.id: t.status for t in tasks}
        changes = {e.task_id: e.change for e in events}
        if len(changes) != len(events):
            raise DialogueStateError("同次每个task最多一项变化。")
        if not self.started and (not events or set(after) - set(changes)):
            raise DialogueStateError("首次决策须dialogue_events逐项标记新增/继续/纠正/撤回/暂停/恢复/澄清。")
        if set(self.before) - set(after):
            raise DialogueStateError("前轮未完成任务不能消失；临时插问用PAUSE/SUSPENDED，撤回用CANCEL/CANCELLED。")
        recorded = []
        for event in events:
            old, new = self.before.get(event.task_id), after.get(event.task_id)
            if new is None:
                raise DialogueStateError("对话变化须关联本次tasks中的任务。")
            try:
                source = customer_source(event, self.request, observations, current_only=True)
            except MemoryStateError as error:
                raise DialogueStateError(str(error)) from error
            valid = {
                "ADD": old is None,
                "CONTINUE": old is not None,
                "CORRECT": old is not None,
                "CANCEL": old is not None and new == "CANCELLED",
                "PAUSE": old is not None and old not in {"ANSWERED", "CANCELLED", "SUSPENDED"} and new == "SUSPENDED",
                "RESUME": old == "SUSPENDED" and new not in {"SUSPENDED", "CANCELLED"},
                "CLARIFY": new == "NEEDS_CUSTOMER",
            }[event.change]
            if not valid:
                raise DialogueStateError("变化与任务前后状态不一致；RESUME仅用于暂停任务，PAUSE/CANCEL须对应终态。")
            recorded.append({"change": event.change, "task_id": event.task_id, "source": source})
        for key, status in after.items():
            old = self.before.get(key)
            if old is None and changes.get(key) not in {"ADD", "CLARIFY"}:
                raise DialogueStateError("新增任务须ADD或CLARIFY，不能静默替换旧任务。")
            if status == "CANCELLED" and old != status and changes.get(key) != "CANCEL":
                raise DialogueStateError("撤回任务须CANCEL事件和客户当前原句。")
            if status == "SUSPENDED" and old != status and changes.get(key) != "PAUSE":
                raise DialogueStateError("暂停任务须PAUSE事件。")
            if old == "SUSPENDED" and status not in {"SUSPENDED", "CANCELLED"} and changes.get(key) != "RESUME":
                raise DialogueStateError("恢复暂停任务须RESUME事件。")
        self.before, self.started = after, True
        self.events.extend(recorded)

    def packet(self) -> dict[str, Any]:
        return {"origin": "MODEL_WITH_CUSTOMER_ANCHORS", "events": deepcopy(self.events),
                "carried_tasks": dict(self.before)}
