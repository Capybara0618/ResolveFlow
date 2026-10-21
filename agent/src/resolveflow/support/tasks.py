"""Small observable task annotations, rebuilt from saved decisions; never authoritative facts."""

from __future__ import annotations

from typing import Any

from resolveflow.support.protocol import Answer, SupportTask


class TaskStateError(ValueError):
    pass


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
            raise TaskStateError("首次决策须用tasks列出当前诉求及intent；与本次动作一起输出，不新增分类调用。")
        ids = [t.id for t in candidate]
        if len(ids) != len(set(ids)):
            raise TaskStateError("tasks.id必须唯一。")
        if set(t.id for t in self.tasks) - set(ids):
            raise TaskStateError("不能删除已记录子问题；撤回的诉求须明确标记CANCELLED。")
        for task in candidate:
            if set(task.evidence_refs) - references:
                raise TaskStateError("tasks.evidence_refs只能关联当前run已经读取的O/P依据，旧run编号不能复用。")
            if answer is not None:
                if task.status == "PENDING":
                    raise TaskStateError("仍有PENDING子问题；继续取得依据或明确缺信息/不可查询/需商家后再回答。")
                if task.status != "CANCELLED" and (
                    not task.response_excerpt or task.response_excerpt not in answer.text
                ):
                    raise TaskStateError("每个非取消任务须用response_excerpt定位本次回答中的实际原句。")
                if set(task.evidence_refs) - set(answer.citations):
                    raise TaskStateError("回答引用必须包含tasks关联的已读依据。")
        # Failed validation cannot replace a valid prior state. Decisions, including annotations, are journaled.
        self.tasks = [task.model_copy(deep=True) for task in candidate]

    def packet(self) -> dict[str, Any]:
        return {"origin": "MODEL", "tasks": [task.model_dump() for task in self.tasks]}
