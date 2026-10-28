"""Program-owned buyer projection after grounding; never an execution command or prose classifier."""

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from resolveflow.support.protocol import AnswerParts, Closed


class BuyerPart(Closed):
    task_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,32}$')
    text: str = Field(min_length=1, max_length=4000)
    guidance: str | None = Field(default=None, min_length=1, max_length=1000)
    action: Literal['REFUND_APPLICATION', 'MERCHANT_REVIEW'] | None = None

    @model_validator(mode='after')
    def one_application_surface(self) -> Self:
        if not self.text.strip() or self.guidance is not None and (not self.guidance.strip() or self.action):
            raise ValueError('买家正文须非空；办理指引与操作卡片不能竞争同一事项。')
        return self


class BuyerView(Closed):
    version: Literal['buyer-view-v1'] = 'buyer-view-v1'
    parts: list[BuyerPart] = Field(min_length=1, max_length=8)


def buyer_view(decision: AnswerParts) -> dict[str, Any]:
    parts = []
    actions = set()
    for part in decision.parts:
        if len(part.next_steps) > 1:
            raise ValueError('每个买家事项最多一个操作卡片。')
        action = part.next_steps[0].action if part.next_steps else None
        if action:
            if action in actions:
                raise ValueError('同类操作卡片不能重复。')
            actions.add(action)
        parts.append(BuyerPart(task_id=part.task_id, text=part.text, guidance=part.guidance, action=action))
    if (('REFUND_APPLICATION' in actions) != bool(decision.refund_summary)
            or ('MERCHANT_REVIEW' in actions) != bool(decision.handoff_summary)):
        raise ValueError('操作提示须与本轮有效申请原因一致。')
    if len('\n\n'.join(t for p in parts for t in (p.text, p.guidance) if t)) > 4000:
        raise ValueError('买家正文和按需指引合计不超过4000字符。')
    return BuyerView(parts=parts).model_dump(exclude_none=True)
