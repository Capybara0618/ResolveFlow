"""Closed semantic assessment ABI; a quoted sentence alone is not a preparation request."""

from typing import Literal

from pydantic import Field

from resolveflow.support.protocol import Closed


class RequestAssessment(Closed):
    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    purpose: Literal["INFORMATION", "PREPARE_REFUND", "MERCHANT_REVIEW", "UNCLEAR", "DECLINED"]
    quote: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=300)


class RequestCheck(Closed):
    kind: Literal["CHECK_REQUEST"]
    assessments: list[RequestAssessment] = Field(min_length=1, max_length=2)
