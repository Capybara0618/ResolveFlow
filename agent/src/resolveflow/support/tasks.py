"""Small observable task annotations, rebuilt from saved decisions; never authoritative facts."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from resolveflow.support.protocol import Answer, AnswerParts, SupportTask


def render_answer(decision: AnswerParts, accepted: list[SupportTask]) -> Answer:
    """Render explicit model outcomes once; metadata comes from declared/current tasks, never guessed."""
    initial = decision.tasks if decision.tasks is not None else accepted
    if not initial:
        raise TaskStateError("发布回答前须同层声明tasks及客户原文dialogue_events；只读取证不需要标注。",
                             issue="TASKS_REQUIRED")
    ids = [p.task_id for p in decision.parts]
    if (len(ids) != len(set(ids)) or len(initial) != len({t.id for t in initial})
            or set(ids) != {t.id for t in initial}):
        raise TaskStateError("parts须逐项覆盖当前tasks.id，不重复/增删；首次须先声明tasks。",
                             issue="ANSWER_PARTS_COVERAGE", task_ids=[t.id for t in initial])
    by_id = {t.id: t for t in initial}
    tasks = []
    for part in decision.parts:
        data = by_id[part.task_id].model_dump()
        data.update(status=part.status, evidence_refs=list(part.citations), response_excerpt=part.text[:400])
        if part.blocker and part.blocker.question and part.blocker.question in part.text:
            data["response_excerpt"] = part.blocker.question
        data["blocker"] = part.blocker
        tasks.append(SupportTask.model_validate(data))
    return Answer(kind="ANSWER", text="\n\n".join(p.text for p in decision.parts), tasks=tasks,
                  citations=list(dict.fromkeys(ref for p in decision.parts for ref in p.citations)),
                  handoff_summary=decision.handoff_summary, memory_updates=decision.memory_updates,
                  dialogue_events=decision.dialogue_events)


class TaskStateError(ValueError):
    def __init__(self, message: str, *, issue: str = "TASK_STATE_INVALID", task_ids: list[str] | None = None) -> None:
        super().__init__(message)
        self.issue = issue
        self.task_ids = list(task_ids or [])


class TaskTracker:
    def __init__(self) -> None:
        self.tasks: list[SupportTask] = []

    def accept(
        self,
        proposed: list[SupportTask] | None,
        references: set[str],
        *,
        answer: Answer | None = None,
        require: bool = False,
    ) -> None:
        candidate = proposed if proposed is not None else self.tasks
        if require and not candidate:
            raise TaskStateError("声明任务或发布回答前须用tasks列出诉求及intent；只读取证可不带标注。",
                                 issue="TASKS_REQUIRED")
        ids = [t.id for t in candidate]
        if len(ids) != len(set(ids)):
            raise TaskStateError("tasks.id必须唯一。")
        removed = [t.id for t in self.tasks if t.id not in ids]
        if removed:
            raise TaskStateError("不能删除已记录子问题；撤回的诉求须明确标记CANCELLED。",
                                 issue="TASKS_REMOVED", task_ids=removed)
        for task in candidate:
            if set(task.evidence_refs) - references:
                raise TaskStateError("tasks.evidence_refs只能关联当前run已经读取的O/P依据，旧run编号不能复用。")
            if answer is not None:
                if task.status == "PENDING":
                    raise TaskStateError("仍有PENDING子问题；继续取得依据或明确缺信息/不可查询/需商家后再回答。",
                                         issue="ANSWER_TASKS_PENDING",
                                         task_ids=[t.id for t in candidate if t.status == "PENDING"])
                if task.status != "CANCELLED" and (
                    not task.response_excerpt or task.response_excerpt not in answer.text
                ):
                    raise TaskStateError("每个非取消任务须用response_excerpt定位本次回答中的实际原句。")
                if set(task.evidence_refs) - set(answer.citations):
                    raise TaskStateError("回答引用必须包含tasks关联的已读依据。")
        # Failed validation cannot replace a valid prior state. Decisions, including annotations, are journaled.
        self.tasks = [task.model_copy(deep=True) for task in candidate]

    def packet(self, lifecycles: dict[str, str] | None = None) -> dict[str, Any]:
        values = [task.model_dump() for task in self.tasks]
        if lifecycles is not None:
            for task, value in zip(self.tasks, values, strict=True):
                value["lifecycle"] = lifecycles.get(task.id, lifecycle_for(task))
        return {"origin": "MODEL", "tasks": values}


def lifecycle_for(task: SupportTask) -> str:
    return task.lifecycle or {"CANCELLED": "CANCELLED", "SUSPENDED": "PAUSED"}.get(task.status, "OPEN")


def previous_hint(context: dict[str, Any], input_version: int) -> dict[str, Any] | None:
    raw = context.get("previous_tasks")
    if not isinstance(raw, dict) or raw.get("origin") != "MODEL_PREVIOUS_TURN":
        return None
    version = raw.get("input_version")
    values = raw.get("tasks")
    if type(version) is not int or not 0 < version < input_version or not isinstance(values, list):
        return None
    if not 1 <= len(values) <= 8:
        return None
    try:
        tasks = [SupportTask.model_validate(task) for task in values]
    except ValidationError:
        return None  # Old or unknown model state is not a substitute for the actual conversation.
    return {"origin": "MODEL_PREVIOUS_TURN", "input_version": version, "needs_recheck": True,
            "tasks": [{"id": t.id, "intent": t.intent, "request": t.request, "previous_status": t.status,
                       "previous_lifecycle": lifecycle_for(t),
                       **({"previous_blocker": t.blocker.model_dump()} if t.blocker else {})}
                      for t in tasks]}
