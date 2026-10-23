from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SupportInput(Closed):
    run_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    conversation_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    input_version: int = Field(ge=1, strict=True)
    merchant_id: str = Field(min_length=1, max_length=64)
    customer_id: str = Field(min_length=1, max_length=64)
    line_id: str = Field(min_length=1, max_length=64)
    deadline_at: AwareDatetime
    context: dict[str, Any]


class TaskBlocker(Closed):
    kind: Literal["CUSTOMER_INFO", "SOURCE_FAILURE"]
    detail: str = Field(min_length=1, max_length=200)
    question: str | None = Field(default=None, min_length=1, max_length=200, exclude_if=lambda v: v is None)
    tool_name: str | None = Field(default=None, min_length=1, max_length=64, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def explicit_cause(self) -> TaskBlocker:
        if self.kind == "CUSTOMER_INFO" and (self.question is None or self.tool_name is not None):
            raise ValueError("CUSTOMER_INFO requires question, not tool_name")
        if self.kind == "SOURCE_FAILURE" and (self.tool_name is None or self.question is not None):
            raise ValueError("SOURCE_FAILURE requires tool_name, not question")
        return self


class SupportTask(Closed):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    intent: Literal["LOGISTICS", "ELIGIBILITY", "APPLICATION", "HANDOFF", "PRODUCT", "OTHER"]
    request: str = Field(min_length=1, max_length=200)
    status: Literal["PENDING", "ANSWERED", "NEEDS_CUSTOMER", "NEEDS_MERCHANT", "UNAVAILABLE", "CANCELLED", "SUSPENDED"]
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    response_excerpt: str | None = Field(default=None, min_length=1, max_length=400)
    blocker: TaskBlocker | None = Field(default=None, exclude_if=lambda v: v is None)
    assessment: Literal["CONDITIONS", "CASE_ASSESSMENT"] | None = Field(
        default=None, exclude_if=lambda v: v is None)
    lifecycle: Literal["OPEN", "PAUSED", "RESOLVED", "CANCELLED"] | None = Field(
        default=None, exclude_if=lambda v: v is None)


class CustomerQuote(Closed):
    reference: str = Field(pattern=r"^(CURRENT|H[1-9][0-9]*)$")
    offset: int = Field(default=0, ge=0, strict=True)
    quote: str = Field(min_length=1, max_length=300)


class MemoryUpdate(CustomerQuote):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    topic: Literal["RECEIPT", "CHECKS", "REQUEST", "MATERIAL", "OTHER"]
    supersedes: list[str] = Field(default_factory=list, max_length=8)
    retracts: list[str] = Field(default_factory=list, max_length=8)


class CustomerClaim(CustomerQuote):
    topic: Literal["RECEIPT", "CHECKS", "REQUEST", "MATERIAL", "OTHER"]
    change: Literal["APPEND", "REPLACE", "RETRACT"] = "APPEND"
    target: str | None = Field(default=None, min_length=1, max_length=32)

    @model_validator(mode="after")
    def target_only_for_correction(self) -> CustomerClaim:
        if (self.change == "APPEND") != (self.target is None):
            raise ValueError("APPEND不带target；REPLACE/RETRACT须选择已提供的客户陈述id。")
        return self


class DialogueEvent(CustomerQuote):
    change: Literal["ADD", "CONTINUE", "CORRECT", "CANCEL", "PAUSE", "RESUME", "CLARIFY", "RESOLVE", "REOPEN"]
    task_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    task_ids: list[Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")]] | None = Field(
        default=None, min_length=1, max_length=8,
    )

    @model_validator(mode="after")
    def unambiguous_targets(self) -> DialogueEvent:
        if (self.task_id is None) == (self.task_ids is None):
            raise ValueError("use either task_id or task_ids")
        if self.task_ids is not None and len(self.task_ids) != len(set(self.task_ids)):
            raise ValueError("task_ids must be distinct")
        return self

    def targets(self) -> list[str]:
        if self.task_ids is not None:
            return list(self.task_ids)
        assert self.task_id is not None
        return [self.task_id]


class TaskAction(Closed):
    # Old mock scripts remain readable; live runs require initial understanding in the engine.
    tasks: list[SupportTask] | None = Field(default=None, min_length=1, max_length=8)
    memory_updates: list[MemoryUpdate] = Field(default_factory=list, max_length=8)
    # Optional annotations are individually validated; malformed proposals never become claims.
    customer_claims: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    dialogue_events: list[DialogueEvent] = Field(default_factory=list, max_length=8)


class ContextRead(Closed):
    reference: str = Field(pattern=r"^H[1-9][0-9]*$")
    offset: int = Field(default=0, ge=0, strict=True)
    limit: int = Field(default=500, ge=1, le=1000, strict=True)


class Read(TaskAction):
    kind: Literal["READ_TOOL"]
    # Documentation/rationale is nonexecuting metadata. Identity stays bound by the server.
    purpose: str | None = Field(default=None, min_length=1, max_length=200, exclude_if=lambda v: v is None)
    tool_name: Literal["get_order_context", "get_shipment_trace", "read_history", "get_support_guide", "read_context",
                       "search_policy"]
    arguments: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def scope_free_arguments(self) -> Read:
        if self.tool_name == "search_policy":
            SearchArguments.model_validate(self.arguments)
        elif self.tool_name == "read_context":
            ContextRead.model_validate(self.arguments)
        elif self.tool_name != "read_history":
            if self.arguments:
                raise ValueError("bound reads take no identity or arguments")
        else:
            History.model_validate(self.arguments)
        return self


class History(Closed):
    before_sequence: int | None = Field(default=None, ge=1, strict=True)
    limit: int = Field(default=5, ge=1, le=5, strict=True)


class SearchArguments(Closed):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=3, ge=1, le=5, strict=True)


class Search(TaskAction, SearchArguments):
    kind: Literal["SEARCH_POLICY"]


class AnswerFact(Closed):
    field: Literal["PAID_AMOUNT", "ORDER_STATUS", "SHIPMENT_STATUS", "CARRIER_CONCLUSION"]
    source: str = Field(pattern=r"^O[1-9][0-9]*$")


class NextStep(Closed):
    action: Literal["MERCHANT_REVIEW", "REFUND_APPLICATION"]
    source: str = Field(pattern=r"^O[1-9][0-9]*$")


class Answer(TaskAction):
    kind: Literal["ANSWER"]
    text: str = Field(min_length=1, max_length=4000)
    citations: list[str] = Field(default_factory=list, max_length=8)
    handoff_summary: str | None = Field(default=None, min_length=1, max_length=2000)
    facts: list[AnswerFact] = Field(default_factory=list, max_length=8)
    next_steps: list[NextStep] = Field(default_factory=list, max_length=2, exclude_if=lambda v: not v)


class AnswerPart(Closed):
    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    status: Literal["ANSWERED", "NEEDS_CUSTOMER", "NEEDS_MERCHANT", "UNAVAILABLE", "CANCELLED", "SUSPENDED"]
    text: str = Field(min_length=1, max_length=4000)
    citations: list[str] = Field(default_factory=list, max_length=8)
    blocker: TaskBlocker | None = Field(default=None, exclude_if=lambda v: v is None)
    facts: list[AnswerFact] = Field(default_factory=list, max_length=8)
    next_steps: list[NextStep] = Field(default_factory=list, max_length=2, exclude_if=lambda v: not v)
    assessment: Literal["CONDITIONS", "CASE_ASSESSMENT"] | None = Field(
        default=None, exclude_if=lambda v: v is None)


class AnswerParts(TaskAction):
    kind: Literal["ANSWER_PARTS"]
    parts: list[AnswerPart] = Field(min_length=1, max_length=8)
    handoff_summary: str | None = Field(default=None, min_length=1, max_length=2000)


class ConversationUpdate(Closed):
    version: Literal["support-state-v1"]
    run_id: str
    conversation_id: str
    input_version: int = Field(ge=1, strict=True)
    merchant_id: str
    customer_id: str
    line_id: str
    task_state: dict[str, Any]
    customer_memory: dict[str, Any]
    dialogue_state: dict[str, Any]
    memory_warnings: list[dict[str, Any]] = Field(max_length=8)


class SupportResult(Closed):
    run_id: str
    conversation_id: str
    input_version: int = Field(ge=1)
    status: Literal["SUCCEEDED", "FAILED"]
    reason: str | None
    mode: Literal["mock", "live", "unknown"]
    spend: dict[str, int]
    answer: dict[str, Any] | None
    conversation_update: ConversationUpdate | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def outcome(self) -> SupportResult:
        if self.conversation_update is not None and any(
            getattr(self.conversation_update, key) != getattr(self, key)
            for key in ("run_id", "conversation_id", "input_version")
        ):
            raise ValueError("conversation update must match this run/input")
        if self.status == "SUCCEEDED" and (not self.answer or self.reason or self.mode == "unknown"):
            raise ValueError("success needs an actual model answer and mode")
        if self.status == "FAILED" and self.answer is not None:
            raise ValueError("failure cannot publish an answer")
        return self


DECISION: TypeAdapter[Read | Search | Answer | AnswerParts] = TypeAdapter(
    Annotated[Read | Search | Answer | AnswerParts, Field(discriminator="kind")]
)


class SupportFailure(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
