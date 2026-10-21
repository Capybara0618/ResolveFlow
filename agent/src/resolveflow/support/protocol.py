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


class SupportTask(Closed):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    intent: Literal["LOGISTICS", "ELIGIBILITY", "APPLICATION", "HANDOFF", "PRODUCT", "OTHER"]
    request: str = Field(min_length=1, max_length=200)
    status: Literal["PENDING", "ANSWERED", "NEEDS_CUSTOMER", "NEEDS_MERCHANT", "UNAVAILABLE", "CANCELLED", "SUSPENDED"]
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    response_excerpt: str | None = Field(default=None, min_length=1, max_length=400)


class CustomerQuote(Closed):
    reference: str = Field(pattern=r"^(CURRENT|H[1-9][0-9]*)$")
    offset: int = Field(default=0, ge=0, strict=True)
    quote: str = Field(min_length=1, max_length=300)


class MemoryUpdate(CustomerQuote):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    topic: Literal["RECEIPT", "CHECKS", "REQUEST", "MATERIAL", "OTHER"]
    supersedes: list[str] = Field(default_factory=list, max_length=8)
    retracts: list[str] = Field(default_factory=list, max_length=8)


class DialogueEvent(CustomerQuote):
    change: Literal["ADD", "CONTINUE", "CORRECT", "CANCEL", "PAUSE", "RESUME", "CLARIFY"]
    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")


class TaskAction(Closed):
    # Old mock scripts remain readable; live runs require initial understanding in the engine.
    tasks: list[SupportTask] | None = Field(default=None, min_length=1, max_length=8)
    memory_updates: list[MemoryUpdate] = Field(default_factory=list, max_length=8)
    dialogue_events: list[DialogueEvent] = Field(default_factory=list, max_length=8)


class ContextRead(Closed):
    reference: str = Field(pattern=r"^H[1-9][0-9]*$")
    offset: int = Field(default=0, ge=0, strict=True)
    limit: int = Field(default=500, ge=1, le=1000, strict=True)


class Read(TaskAction):
    kind: Literal["READ_TOOL"]
    tool_name: Literal["get_order_context", "get_shipment_trace", "read_history", "get_support_guide", "read_context"]
    arguments: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def scope_free_arguments(self) -> Read:
        if self.tool_name == "read_context":
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


class Search(TaskAction):
    kind: Literal["SEARCH_POLICY"]
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=3, ge=1, le=5, strict=True)


class Answer(TaskAction):
    kind: Literal["ANSWER"]
    text: str = Field(min_length=1, max_length=4000)
    citations: list[str] = Field(default_factory=list, max_length=8)
    handoff_summary: str | None = Field(default=None, min_length=1, max_length=2000)


class SupportResult(Closed):
    run_id: str
    conversation_id: str
    input_version: int = Field(ge=1)
    status: Literal["SUCCEEDED", "FAILED"]
    reason: str | None
    mode: Literal["mock", "live", "unknown"]
    spend: dict[str, int]
    answer: dict[str, Any] | None

    @model_validator(mode="after")
    def outcome(self) -> SupportResult:
        if self.status == "SUCCEEDED" and (not self.answer or self.reason or self.mode == "unknown"):
            raise ValueError("success needs an actual model answer and mode")
        if self.status == "FAILED" and self.answer is not None:
            raise ValueError("failure cannot publish an answer")
        return self


DECISION: TypeAdapter[Read | Search | Answer] = TypeAdapter(
    Annotated[Read | Search | Answer, Field(discriminator="kind")]
)


class SupportFailure(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
