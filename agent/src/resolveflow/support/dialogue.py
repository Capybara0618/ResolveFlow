"""Source-anchored task changes; explicit pauses and cancellations, no keyword router."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from resolveflow.support.memory import MemoryStateError, customer_source
from resolveflow.support.protocol import DialogueEvent, SupportInput, SupportTask
from resolveflow.support.tasks import previous_hint


class DialogueStateError(ValueError):
    def __init__(self, message: str, *, missing_task_ids: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing_task_ids = list(missing_task_ids or [])


class DialogueState:
    def __init__(self, request: SupportInput) -> None:
        self.request = request
        hint = previous_hint(request.context, request.input_version)
        self.before = {t["id"]: t["previous_status"] for t in (hint or {}).get("tasks", [])}
        self.lifecycles = {t["id"]: t["previous_lifecycle"] for t in (hint or {}).get("tasks", [])}
        self.started = False
        self.events: list[dict[str, Any]] = []

    def apply(
        self, events: list[DialogueEvent], tasks: list[SupportTask], observations: list[dict[str, Any]],
        *, require: bool,
    ) -> None:
        if not events and not self.started and not require:
            return  # Old scripted clients remain compatible; this does not demonstrate understanding.
        after = {t.id: t.status for t in tasks}
        # Expand only explicit targets, never guess an omitted change from a task status.
        expanded = [(event, key) for event in events for key in event.targets()]
        changes = {key: event.change for event, key in expanded}
        if len(changes) != len(expanded):
            raise DialogueStateError("同次每个task最多一项变化。")
        missing = [key for key in after if key not in changes]
        if not self.started and (not events or missing):
            raise DialogueStateError("首次任务声明须dialogue_events覆盖新增/继续/纠正/撤回/暂停/恢复/澄清。",
                                     missing_task_ids=missing)
        required = {key for key, status in self.before.items()
                    if self.lifecycles[key] == "PAUSED" or
                    (status != "ANSWERED" and self.lifecycles[key] not in {"CANCELLED", "RESOLVED"})}
        if required - set(after):
            raise DialogueStateError("前轮未完成任务不能消失；临时插问用PAUSE/SUSPENDED，撤回用CANCEL/CANCELLED。")
        recorded = []
        lifecycles = {key: value for key, value in self.lifecycles.items() if key in after}
        for event, task_id in expanded:
            old, new = self.before.get(task_id), after.get(task_id)
            lifecycle = self.lifecycles.get(task_id)
            if new is None:
                raise DialogueStateError("对话变化须关联本次tasks中的任务。")
            try:
                source = customer_source(event, self.request, observations, current_only=True)
            except MemoryStateError as error:
                raise DialogueStateError(str(error)) from error
            valid = {
                "ADD": old is None,
                "CONTINUE": lifecycle in {"OPEN", "PAUSED"},
                "CORRECT": lifecycle in {"OPEN", "PAUSED"},
                "CANCEL": old is not None and new == "CANCELLED",
                "PAUSE": lifecycle in {"OPEN", "PAUSED"} and new == "SUSPENDED",
                "RESUME": lifecycle == "PAUSED" and new not in {"SUSPENDED", "CANCELLED"},
                "CLARIFY": lifecycle not in {"RESOLVED", "CANCELLED"} and new == "NEEDS_CUSTOMER",
                "RESOLVE": lifecycle in {"OPEN", "PAUSED", "RESOLVED"} and new == "ANSWERED",
                "REOPEN": lifecycle in {"RESOLVED", "CANCELLED"} and new not in {"SUSPENDED", "CANCELLED"},
            }[event.change]
            if not valid:
                raise DialogueStateError("事项事件与lifecycle不一致；ANSWERED不关闭事项；"
                                         "暂停用RESUME，已结束用REOPEN。")
            lifecycles[task_id] = {"ADD": "OPEN", "CANCEL": "CANCELLED", "PAUSE": "PAUSED",
                                   "RESUME": "OPEN", "RESOLVE": "RESOLVED", "REOPEN": "OPEN"}.get(
                                       event.change, lifecycle or "OPEN")
            recorded.append({"change": event.change, "task_id": task_id, "source": source})
        for key, status in after.items():
            old = self.before.get(key)
            if old is None and changes.get(key) not in {"ADD", "CLARIFY"}:
                raise DialogueStateError("新增任务须ADD或CLARIFY，不能静默替换旧任务。", missing_task_ids=[key])
            if status == "CANCELLED" and lifecycles.get(key) != "CANCELLED":
                raise DialogueStateError("撤回任务须CANCEL事件和客户当前原句。")
            if status == "SUSPENDED" and lifecycles.get(key) != "PAUSED":
                raise DialogueStateError("暂停任务须PAUSE事件。")
            if self.lifecycles.get(key) == "PAUSED" and status not in {"SUSPENDED", "CANCELLED"}:
                if changes.get(key) not in {"RESUME", "CORRECT", "RESOLVE"}:
                    raise DialogueStateError("恢复暂停事项须RESUME；仅CORRECT不自动恢复。")
        for task in tasks:
            if task.lifecycle is not None and task.lifecycle != lifecycles.get(task.id):
                raise DialogueStateError("lifecycle由已验证事件更新，不能通过任务字段静默覆盖。")
        self.before, self.started = after, True
        self.lifecycles = lifecycles
        self.events.extend(recorded)

    def packet(self) -> dict[str, Any]:
        return {"origin": "MODEL_WITH_CUSTOMER_ANCHORS", "events": deepcopy(self.events),
                "carried_tasks": dict(self.before), "lifecycles": dict(self.lifecycles)}
