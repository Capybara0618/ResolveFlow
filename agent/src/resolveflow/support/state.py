"""One owner for conversation memory, current-turn work and the published answer.

Model packets and callback payloads remain projections of this state, not additional writable copies.
Budget, journal and fence enforcement stay in their existing Harness/runtime boundaries.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from resolveflow.support.activity import ReadActivity
from resolveflow.support.dialogue import DialogueState, event_outcomes
from resolveflow.support.memory import CustomerMemory
from resolveflow.support.orchestration import Orchestration, TurnPlan
from resolveflow.support.protocol import Answer, SupportInput, SupportTask
from resolveflow.support.recovery import SourceRecovery
from resolveflow.support.stages import TurnStage, Understanding
from resolveflow.support.tasks import TaskTracker


@dataclass(slots=True)
class ConversationMemory:
    tasks: DialogueState
    claims: CustomerMemory
    initial_claims: list[dict[str, Any]]


@dataclass(slots=True)
class TurnWork:
    stage: TurnStage
    orchestration: Orchestration | None
    focus_ids: tuple[str, ...] = ()
    observations: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    recovery: SourceRecovery = field(default_factory=SourceRecovery)
    activity: ReadActivity = field(default_factory=ReadActivity)
    read_progress: dict[str, Any] | None = None
    history_compaction: tuple[set[str], list[dict[str, Any]]] | None = None


@dataclass(slots=True)
class SupportState:
    request: SupportInput
    memory: ConversationMemory
    turn: TurnWork
    answer: Answer | None = None
    buyer_view: dict[str, Any] | None = None

    @classmethod
    def create(cls, request: SupportInput, architecture: str) -> SupportState:
        stage = TurnStage(architecture)
        claims = CustomerMemory(request)
        return cls(
            request=request,
            memory=ConversationMemory(DialogueState(request), claims, deepcopy(claims.entries)),
            turn=TurnWork(stage, Orchestration(request) if architecture == "orchestrated-v1" else None),
        )

    @property
    def focus_tasks(self) -> list[SupportTask]:
        # Preserve the existing per-turn wire view: lifecycle is supplied by DialogueState separately.
        # The only retained task records live in memory.tasks.issues; callers receive detached projections.
        return [self.memory.tasks.issues[key].model_copy(deep=True, update={"lifecycle": None})
                for key in self.turn.focus_ids]

    def focus_packet(self) -> dict[str, Any]:
        return {"origin": "MODEL", "tasks": [task.model_dump() for task in self.focus_tasks]}

    def annotation_candidate(self) -> tuple[TaskTracker, CustomerMemory, DialogueState]:
        # Validate on temporary copies. Rejected model output must not partially mutate accepted memory.
        tasks = TaskTracker()
        tasks.tasks = self.focus_tasks
        return tasks, deepcopy(self.memory.claims), deepcopy(self.memory.tasks)

    def commit_annotations(self, tasks: TaskTracker, claims: CustomerMemory, dialogue: DialogueState) -> None:
        # Legacy scripted clients may omit events. Retain their validated tasks without inventing events.
        if not dialogue.started:
            lifecycles = dialogue.lifecycles
            for task in tasks.tasks:
                dialogue.issues[task.id] = task.model_copy(deep=True, update={"lifecycle": lifecycles.get(task.id)})
        self.memory.claims, self.memory.tasks = claims, dialogue
        self.turn.focus_ids = tuple(task.id for task in tasks.tasks)

    def accept_understanding(self, understanding: Understanding, *, plan: TurnPlan | None = None) -> None:
        if not self.turn.stage.pending:
            raise ValueError("本轮理解已接纳，不能重复替换计划。")
        stage, flow = deepcopy(self.turn.stage), deepcopy(self.turn.orchestration)
        if plan is not None:
            plan.check_operation_requests(str(self.request.context.get("current_request", "")))
        elif flow is not None:
            raise ValueError("orchestrated-v1须提供完整TurnPlan。")
        stage.check_context_refs(understanding)
        tasks, claims, dialogue = self.annotation_candidate()
        claims.apply(understanding.memory_updates, self.turn.observations)
        if understanding.customer_claims:
            claims.propose(understanding.customer_claims, self.turn.observations)
        tasks.accept(event_outcomes(understanding.tasks(), understanding.dialogue_events),
                     set(self.turn.evidence), require=True)
        dialogue.apply(understanding.dialogue_events, tasks.tasks, self.turn.observations, require=True)
        stage.accept(understanding)
        if flow is not None and plan is not None:
            flow.accept(plan)
        self.commit_annotations(tasks, claims, dialogue)
        self.turn.stage, self.turn.orchestration = stage, flow

    def readiness(self) -> dict[str, Any]:
        meaning, flow = self.turn.stage.understanding, self.turn.orchestration
        if meaning is None or flow is None:
            return {"phase": "UNDERSTAND"}
        # Missing evidence, READY/BLOCKED and phase are derived every time, never independently stored.
        return flow.snapshot(meaning, self.turn.evidence, self.turn.recovery.packet(), self.memory.tasks.lifecycles)

    def conversation_snapshot(self, *, for_answer: bool = False) -> dict[str, Any]:
        packet = {
            "customer_memory": self.memory.claims.snapshot(),
            "dialogue_state": self.memory.tasks.packet(),
            "memory_warnings": deepcopy(self.memory.claims.warnings),
        }
        if self.turn.focus_ids or not for_answer:
            packet["task_state"] = self.memory.tasks.task_snapshot(self.focus_tasks if for_answer else [])
        return packet

    @property
    def conversation_changed(self) -> bool:
        return bool(self.memory.tasks.events) or self.memory.claims.entries != self.memory.initial_claims
