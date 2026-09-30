"""Revision-bound material and question snapshots from Case, never model-generated facts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MaterialInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    evidence_id: str = Field(min_length=1, max_length=64)
    source_type: Literal["CUSTOMER_STATEMENT", "REVIEWER_VERIFICATION"]
    source_ref: str = Field(min_length=1, max_length=200)
    source_version: str = Field(min_length=1, max_length=64)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_revision: int = Field(ge=1)
    content: str = Field(max_length=8000)
    question_id: str | None = Field(default=None, max_length=128)
    reviewed_evidence_id: str | None = Field(default=None, max_length=64)
    verification_result: Literal["CONFIRMED", "REFUTED", "INCONCLUSIVE"] | None = None


class QuestionInputItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    field: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=2000)


class QuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    question_id: str = Field(min_length=1, max_length=128)
    input_revision: int = Field(ge=1)
    questions: list[QuestionInputItem] = Field(min_length=1, max_length=3)


class ReviewerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    materials: list[MaterialInput] = Field(default_factory=list, max_length=64)
    questions: list[QuestionInput] = Field(default_factory=list, max_length=2)

    def snapshot(self) -> dict:
        return self.model_dump(exclude_none=True)
