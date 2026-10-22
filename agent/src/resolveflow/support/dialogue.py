"""Source-anchored task changes; explicit pauses and cancellations, no keyword router."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from resolveflow.support.memory import MemoryStateError, customer_source
from resolveflow.support.protocol import DialogueEvent, SupportInput, SupportTask
from resolveflow.support.tasks import lifecycle_for, previous_hint


class DialogueStateError(ValueError):
    def __init__(self, message: str, *, missing_task_ids: list[str] | None = None,
                 state_conflict: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.missing_task_ids = list(missing_task_ids or [])
        self.state_conflict = state_conflict


def event_outcomes(tasks: list[SupportTask], events: list[DialogueEvent]) -> list[SupportTask]:
    """An explicit anchored event owns closure/pause; response metadata is derived, never model authority."""
    derived = {key: {"PAUSE": "SUSPENDED", "CANCEL": "CANCELLED", "RESOLVE": "ANSWERED"}[event.change]
               for event in events if event.change in {"PAUSE", "CANCEL", "RESOLVE"} for key in event.targets()}
    return [task.model_copy(deep=True, update={"status": derived[task.id], "blocker": None})
            if task.id in derived else task.model_copy(deep=True) for task in tasks]


class DialogueState:
    def __init__(self, request: SupportInput) -> None:
        self.request = request
        hint = previous_hint(request.context, request.input_version)
        self.before = {t["id"]: t["previous_status"] for t in (hint or {}).get("tasks", [])}
        self.lifecycles = {t["id"]: t["previous_lifecycle"] for t in (hint or {}).get("tasks", [])}
        self.issues = {t["id"]: SupportTask.model_validate({
            "id": t["id"], "intent": t["intent"], "request": t["request"], "status": t["previous_status"],
            **({"blocker": t["previous_blocker"]} if "previous_blocker" in t else {}),
        }) for t in (hint or {}).get("tasks", [])}
        self.started = False
        self.events: list[dict[str, Any]] = []

    def apply(
        self, events: list[DialogueEvent], tasks: list[SupportTask], observations: list[dict[str, Any]],
        *, require: bool,
    ) -> None:
        if not events and not self.started and not require:
            return  # Old scripted clients remain compatible; this does not demonstrate understanding.
        tasks = event_outcomes(tasks, events)
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
        if len(set(self.before) | set(after)) > 8:
            raise DialogueStateError("会话事项最多8项，不能通过省略删除已有事项。")
        recorded = []
        lifecycles = dict(self.lifecycles)
        issues = deepcopy(self.issues)
        for event, task_id in expanded:
            old, new = self.before.get(task_id), after.get(task_id)
            lifecycle = self.lifecycles.get(task_id)
            if new is None:
                if old is None:
                    raise DialogueStateError("对话变化须关联已保存事项或本次声明的新事项。")
                new = {"PAUSE": "SUSPENDED", "CANCEL": "CANCELLED", "RESOLVE": "ANSWERED"}.get(
                    event.change, old)
                issues[task_id] = issues[task_id].model_copy(update={"status": new, "blocker": None})
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
                "RESUME": lifecycle in {"OPEN", "PAUSED"} and new not in {"SUSPENDED", "CANCELLED"},
                "CLARIFY": lifecycle not in {"RESOLVED", "CANCELLED"} and new == "NEEDS_CUSTOMER",
                "RESOLVE": lifecycle in {"OPEN", "PAUSED", "RESOLVED"} and new == "ANSWERED",
                "REOPEN": lifecycle in {"RESOLVED", "CANCELLED"} and new not in {"SUSPENDED", "CANCELLED"},
            }[event.change]
            if not valid:
                allowed = (["REOPEN"] if lifecycle in {"RESOLVED", "CANCELLED"}
                           else ["RESUME", "CORRECT", "CANCEL", "RESOLVE"] if lifecycle == "PAUSED"
                           else ["CONTINUE", "CORRECT", "PAUSE", "CANCEL", "RESOLVE"] if lifecycle == "OPEN"
                           else ["ADD"])
                raise DialogueStateError("事件与实际前态不一致；暂停用PAUSE，恢复/继续用RESUME，结束后须REOPEN。",
                    state_conflict={"task_id": task_id, "actual_lifecycle": lifecycle,
                                    "proposed_change": event.change, "allowed_changes": allowed})
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
        issues.update({task.id: task.model_copy(deep=True) for task in tasks})
        self.issues = issues
        self.before, self.started = {key: task.status for key, task in issues.items()}, True
        self.lifecycles = lifecycles
        self.events.extend(recorded)

    def task_snapshot(self, focus: list[SupportTask]) -> dict[str, Any]:
        """Persist all issues while citations/outcomes describe only this turn's focus."""
        issues = {**self.issues, **{task.id: task for task in focus}}
        values = []
        focused = {task.id for task in focus}
        for key, task in issues.items():
            value = task.model_dump()
            if key not in focused:
                value.update(evidence_refs=[], response_excerpt=None)
            value["lifecycle"] = self.lifecycles.get(key, lifecycle_for(task))
            values.append(value)
        return {"origin": "MODEL", "tasks": values, "focus_ids": [task.id for task in focus]}

    def packet(self) -> dict[str, Any]:
        return {"origin": "MODEL_WITH_CUSTOMER_ANCHORS", "events": deepcopy(self.events),
                "carried_tasks": dict(self.before), "lifecycles": dict(self.lifecycles)}
