from typing import Annotated, Literal

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
    context: dict


class Read(Closed):
    kind: Literal["READ_TOOL"]
    tool_name: Literal["get_order_context", "get_shipment_trace", "read_history"]
    arguments: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def scope_free_arguments(self):
        if self.tool_name != "read_history":
            if self.arguments:
                raise ValueError("bound order/shipment reads take no identity or arguments")
        else:
            History.model_validate(self.arguments)
        return self


class History(Closed):
    before_sequence: int | None = Field(default=None, ge=1, strict=True)
    limit: int = Field(default=5, ge=1, le=5, strict=True)


class Search(Closed):
    kind: Literal["SEARCH_POLICY"]
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=3, ge=1, le=5, strict=True)


class Answer(Closed):
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
    answer: dict | None

    @model_validator(mode="after")
    def outcome(self):
        if self.status == "SUCCEEDED" and (not self.answer or self.reason or self.mode == "unknown"):
            raise ValueError("success needs an actual model answer and mode")
        if self.status == "FAILED" and self.answer is not None:
            raise ValueError("failure cannot publish an answer")
        return self


DECISION = TypeAdapter(Annotated[Read | Search | Answer, Field(discriminator="kind")])


class SupportFailure(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
