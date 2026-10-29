"""Evidence readiness and presentation compilation inside the existing SDK loop."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from resolveflow.harness.context import canonical_json
from resolveflow.support.grounding import GroundingError, ground_summary, value_for
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
from resolveflow.support.refund_result import render_refund_result
from resolveflow.support.request_check import RequestCheck
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
        inactive = {key for event in self.dialogue_events if event.change in {"PAUSE", "CANCEL", "RESOLVE"}
                    for key in event.targets()}
        for focus in self.focus:
            if focus.id in inactive and (focus.needs or focus.goal != "EXPLAIN"):
                raise ValueError("暂停/撤回/结束焦点仅确认旧事项，不得带新取证需求或操作目标；"
                                 "本轮新问题请用独立焦点ADD，保留旧事项的状态事件。")
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
    text: str | None = Field(default=None, min_length=1, max_length=4000)
    presentation: Literal["REFUND_RESULT"] | None = None
    guidance: str | None = Field(default=None, min_length=1, max_length=1000)
    citations: list[Annotated[str, Field(pattern=r"^[OP][1-9][0-9]*$")]] = Field(
        default_factory=list, max_length=8)
    status: Literal["ANSWERED", "NEEDS_CUSTOMER", "NEEDS_MERCHANT"] = "ANSWERED"
    blocker: TaskBlocker | None = None

    @model_validator(mode="after")
    def result_or_model_text(self) -> ResponsePart:
        if self.presentation == "REFUND_RESULT":
            if (self.text is not None or self.guidance is not None or self.blocker is not None
                    or self.status != "ANSWERED"):
                raise ValueError("REFUND_RESULT由程序生成正文及下一步，不接受text/guidance/blocker。"
                                 "其他问题单独用普通part。")
        elif not self.text or not self.text.strip():
            raise ValueError("普通答复须非空text。")
        return self


class SummaryDraft(Closed):
    customer_quotes: list[Annotated[str, Field(min_length=1, max_length=300)]] | None = Field(
        default=None, min_length=1, max_length=4)
    customer_refs: list[Annotated[str, Field(min_length=1, max_length=64)]] | None = Field(
        default=None, min_length=1, max_length=4)

    @model_validator(mode="after")
    def unique_quotes(self) -> SummaryDraft:
        if (self.customer_quotes is None) == (self.customer_refs is None):
            raise ValueError("摘要须选择customer_refs；兼容customer_quotes不能与引用混用。")
        values = self.customer_quotes or self.customer_refs or []
        if any(not quote.strip() for quote in values) or len(set(values)) != len(values):
            raise ValueError("摘要客户原话须非空且不重复")
        return self

    def quotes(self, candidates: list[dict[str, str]]) -> list[str]:
        if self.customer_quotes is not None:
            return self.customer_quotes
        allowed = {c["ref"]: c["quote"] for c in candidates}
        invalid = [ref for ref in self.customer_refs or [] if ref not in allowed]
        if invalid:
            raise ValueError(f"未知或失效customer_refs={invalid}；仅选择summary_candidates，合法引用={list(allowed)}")
        return list(dict.fromkeys(allowed[ref] for ref in self.customer_refs or []))


class FactReadBatch(Closed):
    kind: Literal["READ_FACTS"]
    tools: list[Literal["get_order_context", "get_shipment_trace"]] = Field(min_length=1, max_length=2)
    policy_query: str | None = Field(default=None, min_length=1, max_length=1000, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def distinct_facts(self) -> FactReadBatch:
        if len(set(self.tools)) != len(self.tools):
            raise ValueError("READ_FACTS中每个绑定只读事实工具仅选择一次，不接受其他工具、参数或主体")
        if self.policy_query is not None and not self.policy_query.strip():
            raise ValueError("policy_query须为模型选择的非空政策条件问题")
        if len(self.tools) + (self.policy_query is not None) < 2:
            raise ValueError("READ_FACTS至少两项独立读取；单个事实用READ_TOOL，单个政策用search_policy")
        return self


class Response(Closed):
    kind: Literal["RESPOND"]
    parts: list[ResponsePart] = Field(min_length=1, max_length=8)
    refund_reason: SummaryDraft | None = None
    handoff_reason: SummaryDraft | None = None


class GoalConflict(ValueError):
    """Artifact and accepted goal disagree; recheck purpose instead of coercing a field."""


class GoalReview(Closed):
    kind: Literal["REVIEW_GOAL"]
    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    previous_goal: Literal["EXPLAIN", "PREPARE_REFUND", "MERCHANT_REVIEW"]
    goal: Literal["EXPLAIN", "PREPARE_REFUND", "MERCHANT_REVIEW"]
    operation_request: str | None = Field(default=None, min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=300)


class Orchestration:
    def __init__(self, request: SupportInput) -> None:
        self.request = request
        self.goals: dict[str, str] = {}
        self.last_missing = ""
        self.early_finishes = 0
        self.operation_requests: dict[str, str | None] = {}
        self.goal_review: dict[str, Any] | None = None
        self.goal_reviews: list[dict[str, Any]] = []
        self.request_checks: list[dict[str, Any]] = []
        self.checked_requests: set[tuple[str, str, str | None]] = set()
        self.request_check_rounds = 0

    def accept(self, plan: TurnPlan) -> None:
        if self.goals:
            raise ValueError("turn plan already accepted")
        self.goals = {f.id: f.goal for f in plan.focus}
        self.operation_requests = {f.id: f.operation_request for f in plan.focus}

    def pending_requests(self, meaning: Understanding, lives: dict[str, str]) -> list[dict[str, Any]]:
        return [{"task_id": f.id, "quote": self.operation_requests[f.id]}
                for f in meaning.focus if self.goals[f.id] in GOAL_ACTIONS
                and lives.get(f.id) not in INACTIVE
                and (f.id, self.goals[f.id], self.operation_requests[f.id]) not in self.checked_requests]

    def check_requests(self, payload: dict[str, Any], meaning: Understanding, lives: dict[str, str]) -> None:
        """Gate every proposed operation, including later goal corrections, before composition.

        The separate assessment is still model reasoning, not proof of human intent. Code can
        enforce coverage, provenance, compatible purpose and fail-closed uncertainty, not semantics.
        """
        check = RequestCheck.model_validate(payload)
        pending = {item["task_id"] for item in self.pending_requests(meaning, lives)}
        ids = [item.task_id for item in check.assessments]
        if not pending or len(set(ids)) != len(ids) or set(ids) != pending:
            raise ValueError("CHECK_REQUEST须且仅须逐一核对当前待核对事项，不重复、不遗漏")
        if self.request_check_rounds >= 2:
            raise SupportFailure("REQUEST_CHECK_EXHAUSTED")
        current = str(self.request.context.get("current_request", ""))
        if any(not item.quote.strip() or item.quote not in current for item in check.assessments):
            raise ValueError("核对quote须为客户本轮原文，历史意愿和助手建议不能代替本轮请求")
        # Validate the entire batch first; an invalid sibling must not partially approve another task.
        for item in check.assessments:
            goal = self.goals[item.task_id]
            approved = item.purpose == goal
            self.request_checks.append({**item.model_dump(), "proposed_goal": goal,
                                        "applied_goal": goal if approved else "EXPLAIN"})
            if approved:
                self.checked_requests.add((item.task_id, goal, self.operation_requests[item.task_id]))
            else:
                self.goals[item.task_id] = "EXPLAIN"
                self.operation_requests[item.task_id] = None
        self.request_check_rounds += 1

    def quote_candidates(self, claims: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Only current text and source-checked active claims can become operation reasons."""
        current = str(self.request.context.get("current_request", ""))
        values = [("CURRENT", current)] if 0 < len(current) <= 300 else []
        values.extend(("REQUEST-" + key, quote) for key, quote in self.operation_requests.items() if quote)
        values.extend((c["id"], c["quote"]) for c in claims
                      if isinstance(c.get("id"), str) and c["id"] and c.get("status") == "ACTIVE"
                      and c.get("quote") == c.get("source", {}).get("quote")
                      and type(c.get("source", {}).get("sequence")) is int
                      and 0 < c["source"]["sequence"] <= self.request.input_version)
        seen = set()
        candidates = []
        for ref, quote in values:
            if quote.strip() and quote not in seen:
                seen.add(quote)
                candidates.append({"ref": ref, "quote": quote})
        return candidates

    def required(self, focus: Focus) -> set[str]:
        required = set(focus.needs) | ({"GUIDE"} if focus.intent in {"APPLICATION", "HANDOFF"} else set())
        # A fulfilment-based refund draft needs the handling conditions, not only a page guide.
        # Derive this at readiness time so later REFINE_NEEDS also receives the same floor.
        if self.goals.get(focus.id) == "PREPARE_REFUND" and "SHIPMENT" in required:
            required.add("POLICY")
        return required

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
        pending = self.pending_requests(meaning, lives)
        if pending and self.request_check_rounds >= 2:
            raise SupportFailure("REQUEST_CHECK_EXHAUSTED")
        return {"phase": "INVESTIGATE" if self.goal_review else "CHECK_REQUEST" if pending else
                "INVESTIGATE" if any(t["state"] == "WAITING" for t in tasks)
                else "COMPOSE", "tasks": tasks,
                **({"request_check": {"tasks": pending}} if pending else {}),
                **({"request_checks": self.request_checks} if self.request_checks else {}),
                **({"goal_review": self.goal_review} if self.goal_review is not None else {}),
                **({"goal_reviews": self.goal_reviews} if self.goal_reviews else {})}

    def review_goal(self, payload: dict[str, Any], meaning: Understanding, lives: dict[str, str]) -> Understanding:
        change = GoalReview.model_validate(payload)
        if (self.goal_review is None or self.goal_reviews or change.task_id not in self.goal_review["task_ids"]
                or lives.get(change.task_id) in INACTIVE or self.goals.get(change.task_id) != change.previous_goal):
            raise ValueError("仅目标冲突后可核对当前活跃事项一次，previous_goal须匹配当前目标")
        value = meaning.model_dump()
        for focus in value["focus"]:
            selected = focus["id"] == change.task_id
            focus["goal"] = change.goal if selected else self.goals[focus["id"]]
            focus["operation_request"] = (change.operation_request if selected else
                                          self.operation_requests[focus["id"]])
            if selected and change.goal != "EXPLAIN":
                focus["intent"] = {"PREPARE_REFUND": "APPLICATION", "MERCHANT_REVIEW": "HANDOFF"}[change.goal]
        checked = TurnPlan.model_validate(value)
        checked.check_operation_requests(str(self.request.context.get("current_request", "")))
        updated = checked.meaning()  # Adds a newly required ORDER, never removes prior evidence requirements.
        self.goals[change.task_id] = change.goal
        self.operation_requests[change.task_id] = change.operation_request
        self.goal_reviews.append(change.model_dump())
        self.goal_review = None
        return updated

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
                if goal in GOAL_ACTIONS and lives.get(task_id) not in INACTIVE
                and (task_id, goal, self.operation_requests[task_id]) in self.checked_requests}

    def response_contract(self, meaning: Understanding, refs: dict[str, dict[str, Any]],
                          failures: list[dict[str, Any]], lives: dict[str, str]) -> dict[str, Any]:
        """Compile the accepted goals into the exact output shape, never into invented customer reasons."""
        state = self.snapshot(meaning, refs, failures, lives)
        if state["phase"] != "COMPOSE":
            raise ValueError("response contract requires evidence readiness")
        example: dict[str, Any] = {"kind": "RESPOND", "parts": [
            {"task_id": focus.id, "text": (
                "用日常中文回答买家的问题，仅说明相关条件与待核实处；选择实际相关条款引用。"
                if "POLICY" in self.required(focus) else "替换为本事项的直接解释，不将待共享原因只写在正文。"),
             "citations": []}
            for focus in meaning.focus]}
        fields = []
        for task in state["tasks"]:
            if task["state"] != "READY" or lives.get(task["task_id"]) in INACTIVE:
                continue
            field = {"PREPARE_REFUND": "refund_reason", "MERCHANT_REVIEW": "handoff_reason"}.get(task["goal"])
            if field:
                fields.append({"field": field, "task_id": task["task_id"], "type": "customer_refs object",
                               "required_for_status": ["ANSWERED", "NEEDS_MERCHANT"],
                               "omit_for_status": ["NEEDS_CUSTOMER"]})
                candidates = self.quote_candidates([])
                example[field] = {"customer_refs": [candidates[0]["ref"]] if candidates else []}
        return {"reason_fields": fields, "example": example,
                "refund_result_option": {"when": "只回答当前退款办理进度/已退金额/该申请下一步的EXPLAIN事项",
                    "shape": {"task_id": "实际id", "presentation": "REFUND_RESULT", "citations": ["已读ORDER编号"]},
                    "rule": "程序读取refund_application生成整段，不提供text/guidance；其他问题仍用普通text"}}

    def compose(self, response: Response, meaning: Understanding, refs: dict[str, dict[str, Any]],
                failures: list[dict[str, Any]], lives: dict[str, str], *,
                customer_claims: list[dict[str, Any]] | None = None) -> AnswerParts:
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
            text = part.text or ""
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
                        or blocker.question is None or blocker.question not in text):
                    raise ValueError("NEEDS_CUSTOMER须在正文询问实际缺少的客户信息")
            elif blocker is not None:
                raise ValueError("blocker须匹配NEEDS_CUSTOMER或实际来源失败")
            citations = list(dict.fromkeys(part.citations))
            facts: list[AnswerFact] = []
            steps = []
            active = life not in INACTIVE and task["state"] != "BLOCKED"
            if part.presentation == "REFUND_RESULT":
                orders = task["refs_by_need"].get("ORDER", [])
                if not active or task["goal"] != "EXPLAIN" or not orders:
                    raise ValueError("REFUND_RESULT须活动EXPLAIN事项和本run已读ORDER，不执行准备或修改申请。")
                text = render_refund_result(refs[orders[-1]], self.request)
            # A failed required source blocks completion/actions, not independently observed facts.
            # Keep valid partial fields available for an honest unavailable answer; never invent the missing ones.
            if life not in INACTIVE:
                for need in ("ORDER", "SHIPMENT", "POLICY", "GUIDE"):
                    sources = task["refs_by_need"].get(need)
                    if not sources:
                        continue
                    if need == "POLICY":
                        if active and not set(sources).intersection(citations):
                            raise ValueError("POLICY须选择与本轮问题相关的实际条款引用")
                        continue
                    ref = sources[-1]
                    if ref not in citations:
                        citations.append(ref)
                    fields = {"ORDER": ["ORDER_STATUS", "PAID_AMOUNT", "REFUND_STATUS", "REFUNDED_AMOUNT"],
                              "SHIPMENT": ["SHIPMENT_STATUS", "CARRIER_CONCLUSION"]}.get(need, [])
                    for field in fields:
                        try:
                            value_for(field, refs[ref], self.request)
                        except GroundingError:
                            continue
                        facts.append(AnswerFact.model_validate({"field": field, "source": ref}))
                if active and status in {"ANSWERED", "NEEDS_MERCHANT"}:
                    action = self.required_actions(lives).get(focus.id)
                    if action:
                        steps = [{"action": action, "source": task["refs_by_need"]["GUIDE"][-1]}]
                    usable_goals.add(task["goal"])
            assessment = None
            if focus.intent == "ELIGIBILITY" and active:
                assessment = "CASE_ASSESSMENT" if "ORDER" in focus.needs else "CONDITIONS"
            # Application instructions are visible only for a guide-focused explanation. Accepted
            # operations have their own confirmed cards; a source failure/paused task has no UI advice.
            guidance = (part.guidance if active and status in {"ANSWERED", "NEEDS_MERCHANT"}
                        and task["goal"] == "EXPLAIN" and "GUIDE" in self.required(focus) else None)
            parts.append(AnswerPart.model_validate({"task_id": focus.id, "status": status, "text": text,
                         "guidance": guidance,
                         "citations": citations, "facts": facts, "next_steps": steps,
                         "blocker": blocker, "assessment": assessment}))
        reasons = [("refund_reason", "PREPARE_REFUND"), ("handoff_reason", "MERCHANT_REVIEW")]
        unexpected = [goal for field, goal in reasons if getattr(response, field) is not None
                      and goal not in usable_goals]
        eligible = [task["task_id"] for task in state["tasks"] if task["state"] == "READY"
                    and lives.get(task["task_id"]) not in INACTIVE
                    and by_id[task["task_id"]].status in {"ANSWERED", "NEEDS_MERCHANT"}]
        if unexpected and eligible:
            if self.goal_reviews:
                raise SupportFailure("GOAL_REVIEW_EXHAUSTED")
            self.goal_review = {"task_ids": eligible, "candidate_goals": unexpected,
                                "accepted_goals": {key: self.goals[key] for key in eligible}}
            raise GoalConflict("GOAL_CONFLICT：候选产物与已接受目标不同，先核对本轮原话，不能只改原因字段")
        summaries: dict[str, str] = {}
        for field, goal in reasons:
            reason = getattr(response, field)
            if goal in usable_goals:
                if reason is None:
                    raise ValueError(f"{field}须给出待客户核对的非空原因")
                task_id = next(task["task_id"] for task in state["tasks"] if task["goal"] == goal)
                summary_part = next(piece for piece in parts if piece.task_id == task_id)
                quotes = reason.quotes(self.quote_candidates(customer_claims or []))
                summaries[field] = ground_summary(
                    quotes, summary_part.facts, self.request, refs, customer_claims or [],
                    refund=goal == "PREPARE_REFUND", buyer_view=True)
            elif reason is not None:
                raise ValueError(f"{field}仅用于本轮仍可办理的明确操作目标")
        return AnswerParts(kind="ANSWER_PARTS", fact_rendering="fields-v1", parts=parts,
                           refund_summary=summaries.get("refund_reason"),
                           handoff_summary=summaries.get("handoff_reason"))
