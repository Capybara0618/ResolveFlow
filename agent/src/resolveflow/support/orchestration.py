"""Evidence readiness and presentation compilation inside the existing SDK loop."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from resolveflow.harness.context import canonical_json
from resolveflow.support.grounding import GroundingError, value_for
from resolveflow.support.guide import guide_source
from resolveflow.support.protocol import (
    AnswerFact,
    AnswerPart,
    AnswerParts,
    Closed,
    SupportFailure,
    SupportInput,
    TaskBlocker,
)
from resolveflow.support.stages import Focus, Understanding

TOOLS = {"ORDER": "get_order_context", "SHIPMENT": "get_shipment_trace",
         "POLICY": "search_policy", "GUIDE": "get_support_guide"}
INACTIVE = {"PAUSED", "CANCELLED", "RESOLVED"}
GOAL_ACTIONS = {"PREPARE_REFUND": "REFUND_APPLICATION", "MERCHANT_REVIEW": "MERCHANT_REVIEW"}


class PlannedFocus(Focus):
    goal: Literal["EXPLAIN", "PREPARE_REFUND", "MERCHANT_REVIEW"]
    operation_request: str | None = Field(default=None, min_length=1, max_length=300)


class TurnPlan(Understanding):
    focus: list[PlannedFocus] = Field(min_length=1, max_length=8)  # type: ignore[assignment]

    @model_validator(mode="after")
    def consistent_goals(self) -> TurnPlan:
        actions = []
        for focus in self.focus:
            if focus.goal == "EXPLAIN" and focus.operation_request is not None:
                raise ValueError("EXPLAIN不带operation_request；话题不等于操作请求")
            if focus.goal != "EXPLAIN" and not (focus.operation_request or "").strip():
                raise ValueError("操作目标须operation_request引用客户本轮明确准备请求的原文；仅咨询用EXPLAIN")
            if (focus.goal == "PREPARE_REFUND" and focus.intent != "APPLICATION"
                    or focus.goal == "MERCHANT_REVIEW" and focus.intent != "HANDOFF"):
                raise ValueError("goal须与APPLICATION/HANDOFF意图一致")
            if focus.goal != "EXPLAIN":
                actions.append(focus.goal)
        if len(actions) != len(set(actions)):
            raise ValueError("同一订单行每种操作目标只能有一个焦点")
        return self

    def check_operation_requests(self, current_request: str) -> None:
        for focus in self.focus:
            if focus.operation_request is not None and focus.operation_request not in current_request:
                raise ValueError("operation_request须来自本轮原文，不能取历史、助手话语或改写文本")

    def meaning(self) -> Understanding:
        value = self.model_dump()
        for focus in value["focus"]:
            goal = focus.pop("goal")
            focus.pop("operation_request", None)
            floor = {"LOGISTICS": "SHIPMENT", "ELIGIBILITY": "POLICY"}.get(focus["intent"])
            for need in [floor, "ORDER" if goal == "PREPARE_REFUND" else None]:
                if need and need not in focus["needs"]:
                    focus["needs"].append(need)
        return Understanding.model_validate(value)


class ResponsePart(Closed):
    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    text: str = Field(min_length=1, max_length=4000)
    citations: list[Annotated[str, Field(pattern=r"^[OP][1-9][0-9]*$")]] = Field(
        default_factory=list, max_length=8)
    status: Literal["ANSWERED", "NEEDS_CUSTOMER", "NEEDS_MERCHANT"] = "ANSWERED"
    blocker: TaskBlocker | None = None


class Response(Closed):
    kind: Literal["RESPOND"]
    parts: list[ResponsePart] = Field(min_length=1, max_length=8)
    refund_reason: str | None = Field(default=None, min_length=1, max_length=2000)
    handoff_reason: str | None = Field(default=None, min_length=1, max_length=2000)


class Orchestration:
    def __init__(self, request: SupportInput) -> None:
        self.request = request
        self.goals: dict[str, str] = {}
        self.last_missing = ""
        self.early_finishes = 0

    def accept(self, plan: TurnPlan) -> None:
        if self.goals:
            raise ValueError("turn plan already accepted")
        self.goals = {f.id: f.goal for f in plan.focus}

    def required(self, focus: Focus) -> set[str]:
        return set(focus.needs) | ({"GUIDE"} if focus.intent in {"APPLICATION", "HANDOFF"} else set())

    def application_context(self, refs: dict[str, dict[str, Any]]) -> dict[str, Any]:
        state = self.request.context.get("conversation_state")
        state = state if isinstance(state, dict) else {}
        return {"guide_refs": self.valid_refs("GUIDE", refs), "interaction": {
            "has_ticket": state.get("has_ticket") if type(state.get("has_ticket")) is bool else None,
            **{key: state[key] if state.get(key) in {"ASSISTANT", "MERCHANT"} else "UNKNOWN"
               for key in ("current_recipient", "default_recipient")},
        }}

    def valid_refs(self, need: str, refs: dict[str, dict[str, Any]]) -> list[str]:
        accepted = []
        for ref, source in refs.items():
            if source.get("version") is None or "error" in source:
                continue
            if need in {"ORDER", "SHIPMENT"}:
                fields = ["ORDER_STATUS", "PAID_AMOUNT"] if need == "ORDER" else ["SHIPMENT_STATUS"]
                try:
                    for field in fields:
                        value_for(field, source, self.request)
                except GroundingError:
                    continue
            elif need == "GUIDE":
                guide = guide_source()
                if any(source.get(key) != guide[key] for key in ("source_type", "version", "data")):
                    continue
            elif (source.get("source_type") != "POLICY"
                  or not isinstance(source.get("data", {}).get("text"), str)
                  or not source["data"]["text"].strip()):
                continue
            accepted.append(ref)
        return accepted

    def needs_ui(self, meaning: Understanding, refs: dict[str, dict[str, Any]], lives: dict[str, str]) -> bool:
        return not self.valid_refs("GUIDE", refs) and any(
            lives.get(f.id) not in INACTIVE and "GUIDE" in self.required(f) for f in meaning.focus)

    def snapshot(self, meaning: Understanding, refs: dict[str, dict[str, Any]],
                 failures: list[dict[str, Any]], lives: dict[str, str]) -> dict[str, Any]:
        tasks = []
        for focus in meaning.focus:
            required = set() if lives.get(focus.id) in INACTIVE else self.required(focus)
            found = {need: self.valid_refs(need, refs) for need in sorted(required)}
            missing = sorted(need for need, sources in found.items() if not sources)
            blocked = {need: next((failure for failure in reversed(failures)
                                   if failure["tool_name"] == TOOLS[need]
                                   and failure.get("retry_allowed") is False), None) for need in missing}
            waiting = [need for need in missing if blocked[need] is None]
            tasks.append({"task_id": focus.id, "goal": self.goals[focus.id],
                          "state": "WAITING" if waiting else "BLOCKED" if missing else "READY",
                          "missing": missing, "refs_by_need": found,
                          "blocked": [value for value in blocked.values() if value is not None]})
        return {"phase": "INVESTIGATE" if any(t["state"] == "WAITING" for t in tasks) else "COMPOSE",
                "tasks": tasks}

    def defer(self, state: dict[str, Any]) -> None:
        fingerprint = canonical_json(state)
        self.early_finishes = self.early_finishes + 1 if fingerprint == self.last_missing else 1
        self.last_missing = fingerprint
        if self.early_finishes > 2:
            raise SupportFailure("NO_PROGRESS")

    def failure_tools(self, meaning: Understanding) -> dict[str, set[str]]:
        return {f.id: {TOOLS[need] for need in self.required(f)} for f in meaning.focus}

    def required_actions(self, lives: dict[str, str]) -> dict[str, str]:
        return {task_id: GOAL_ACTIONS[goal] for task_id, goal in self.goals.items()
                if goal in GOAL_ACTIONS and lives.get(task_id) not in INACTIVE}

    def response_contract(self, meaning: Understanding, refs: dict[str, dict[str, Any]],
                          failures: list[dict[str, Any]], lives: dict[str, str]) -> dict[str, Any]:
        """Compile the accepted goals into the exact output shape, never into invented customer reasons."""
        state = self.snapshot(meaning, refs, failures, lives)
        if state["phase"] != "COMPOSE":
            raise ValueError("response contract requires evidence readiness")
        example: dict[str, Any] = {"kind": "RESPOND", "parts": [
            {"task_id": focus.id, "text": "替换为本事项的直接解释，不将待共享原因只写在正文。", "citations": []}
            for focus in meaning.focus]}
        fields = []
        for task in state["tasks"]:
            if task["state"] != "READY" or lives.get(task["task_id"]) in INACTIVE:
                continue
            field = {"PREPARE_REFUND": "refund_reason", "MERCHANT_REVIEW": "handoff_reason"}.get(task["goal"])
            if field:
                fields.append({"field": field, "task_id": task["task_id"], "type": "nonempty string",
                               "required_for_status": ["ANSWERED", "NEEDS_MERCHANT"],
                               "omit_for_status": ["NEEDS_CUSTOMER"]})
                example[field] = ("替换为待本人核对的退款原因，区分客户陈述与已核实事实。"
                                  if field == "refund_reason" else
                                  "替换为待本人确认共享给商家的核查摘要，区分客户陈述与已核实事实。")
        return {"reason_fields": fields, "example": example}

    def compose(self, response: Response, meaning: Understanding, refs: dict[str, dict[str, Any]],
                failures: list[dict[str, Any]], lives: dict[str, str]) -> AnswerParts:
        state = self.snapshot(meaning, refs, failures, lives)
        if state["phase"] != "COMPOSE":
            raise ValueError("evidence not ready")
        by_id = {part.task_id: part for part in response.parts}
        if len(by_id) != len(response.parts) or set(by_id) != {f.id for f in meaning.focus}:
            raise ValueError("parts须逐一覆盖本轮焦点且不重复")
        parts = []
        usable_goals = set()
        for focus, task in zip(meaning.focus, state["tasks"], strict=True):
            part = by_id[focus.id]
            if not set(part.citations) <= refs.keys():
                raise ValueError("citations须本run已读O/P编号")
            status: Any = part.status
            blocker = part.blocker
            life = lives.get(focus.id)
            if life in INACTIVE:
                status = {"PAUSED": "SUSPENDED", "CANCELLED": "CANCELLED", "RESOLVED": "ANSWERED"}[life]
                blocker = None
            elif task["state"] == "BLOCKED":
                status = "UNAVAILABLE"
                failure = task["blocked"][0]
                blocker = TaskBlocker(kind="SOURCE_FAILURE", detail=str(failure["error"])[:200],
                                      tool_name=failure["tool_name"])
            elif status == "NEEDS_CUSTOMER":
                if (blocker is None or blocker.kind != "CUSTOMER_INFO"
                        or blocker.question is None or blocker.question not in part.text):
                    raise ValueError("NEEDS_CUSTOMER须在正文询问实际缺少的客户信息")
            elif blocker is not None:
                raise ValueError("blocker须匹配NEEDS_CUSTOMER或实际来源失败")
            citations = list(dict.fromkeys(part.citations))
            facts: list[AnswerFact] = []
            steps = []
            active = life not in INACTIVE and task["state"] != "BLOCKED"
            if active:
                for need in ("ORDER", "SHIPMENT", "POLICY", "GUIDE"):
                    sources = task["refs_by_need"].get(need)
                    if not sources:
                        continue
                    if need == "POLICY":
                        if not set(sources).intersection(citations):
                            raise ValueError("POLICY须选择与本轮问题相关的实际条款引用")
                        continue
                    ref = sources[-1]
                    if ref not in citations:
                        citations.append(ref)
                    fields = {"ORDER": ["ORDER_STATUS", "PAID_AMOUNT"],
                              "SHIPMENT": ["SHIPMENT_STATUS", "CARRIER_CONCLUSION"]}.get(need, [])
                    for field in fields:
                        try:
                            value_for(field, refs[ref], self.request)
                        except GroundingError:
                            continue
                        facts.append(AnswerFact.model_validate({"field": field, "source": ref}))
                if status in {"ANSWERED", "NEEDS_MERCHANT"}:
                    action = self.required_actions(lives).get(focus.id)
                    if action:
                        steps = [{"action": action, "source": task["refs_by_need"]["GUIDE"][-1]}]
                    usable_goals.add(task["goal"])
            assessment = None
            if focus.intent == "ELIGIBILITY" and active:
                assessment = "CASE_ASSESSMENT" if "ORDER" in focus.needs else "CONDITIONS"
            parts.append(AnswerPart.model_validate({"task_id": focus.id, "status": status, "text": part.text,
                         "citations": citations, "facts": facts, "next_steps": steps,
                         "blocker": blocker, "assessment": assessment}))
        for field, goal in [("refund_reason", "PREPARE_REFUND"), ("handoff_reason", "MERCHANT_REVIEW")]:
            reason = getattr(response, field)
            if goal in usable_goals:
                if reason is None or not reason.strip():
                    raise ValueError(f"{field}须给出待客户核对的非空原因")
            elif reason is not None:
                raise ValueError(f"{field}仅用于本轮仍可办理的明确操作目标")
        return AnswerParts(kind="ANSWER_PARTS", fact_rendering="fields-v1", parts=parts,
                           refund_summary=response.refund_reason, handoff_summary=response.handoff_reason)
