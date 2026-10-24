"""Render a small set of authoritative fields; numeric CNY checks are not a general semantic judge."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from resolveflow.support.protocol import Answer, AnswerFact, AnswerParts, SupportInput

MONEY = re.compile(r"[¥￥]\s*(-?\d[\d,]*(?:\.\d+)?)|(-?\d[\d,]*(?:\.\d+)?)\s*(?:CNY|元)", re.I)
FACT_RENDERING_VERSION = "fields-v1"
FACT_LABELS = {"PAID_AMOUNT": "订单行实付", "ORDER_STATUS": "订单状态",
               "SHIPMENT_STATUS": "物流状态", "CARRIER_CONCLUSION": "承运商记录结论"}
STATUS_LABELS = {"PAID": "已付款", "SHIPPED": "已发货", "IN_TRANSIT": "运输中",
                 "DELIVERED": "已签收", "LOST": "丢失", "DELAYED": "延迟",
                 "UNKNOWN": "未知", "NOT_SHIPPED": "未发货", "DAMAGED": "损坏"}


class GroundingError(ValueError):
    pass


def value_for(field: str, source: dict[str, Any], request: SupportInput) -> str:
    expected = "ORDER" if field in {"PAID_AMOUNT", "ORDER_STATUS"} else "SHIPMENT"
    if source.get("source_type") != expected or source.get("version") is None or "error" in source:
        raise GroundingError(f"{field}须当前{expected}来源，商品展示/历史助手/政策不是该字段的权威。")
    data = source.get("data", {})
    if expected == "ORDER":
        row = data.get("order_line", data)
    elif isinstance(data.get("lines"), list):
        row = next((line for line in data["lines"] if line.get("line_id") == request.line_id), {})
    else:
        row = data
    if row.get("line_id") != request.line_id:
        raise GroundingError("事实来源须对应当前订单行。")
    if field == "PAID_AMOUNT":
        amount = row.get("line_paid_amount")
        if type(amount) is not int or amount < 0 or row.get("currency") != "CNY":
            raise GroundingError("PAID_AMOUNT须ORDER整数分line_paid_amount及CNY币种。")
        return f"{amount // 100}.{amount % 100:02d} CNY"
    key = "carrier_conclusion" if field == "CARRIER_CONCLUSION" else "status"
    value = row.get(key)
    if not isinstance(value, str) or not value or len(value) > 64:
        raise GroundingError(f"来源未提供{field}，不能自行推断。")
    return value


def ground_answer(
    decision: Answer | AnswerParts, request: SupportInput, citations: dict[str, dict[str, Any]]
) -> Answer | AnswerParts:
    structured = decision.fact_rendering == FACT_RENDERING_VERSION

    def render(text: str, facts: list[AnswerFact], refs: list[str]) -> tuple[str, list[str]]:
        refs = list(refs)
        fields = set()
        lines = []
        if structured and ("{{" in text or "}}" in text):
            raise GroundingError("fields-v1正文仅写解释，不混用旧事实占位符；facts独立选field/source。")
        for fact in facts:
            marker = "{{" + fact.field + "}}"
            if structured and fact.field in fields:
                raise GroundingError("fields-v1同段facts.field须唯一。")
            if not structured and (fact.field in fields or marker not in text):
                raise GroundingError("facts.field须唯一且在对应text中有{{FIELD}}占位符。")
            fields.add(fact.field)
            value = value_for(fact.field, citations.get(fact.source, {}), request)
            if structured:
                display = value if fact.field == "PAID_AMOUNT" else STATUS_LABELS.get(value, value)
                lines.append(FACT_LABELS[fact.field] + "：" + display + "。")
            else:
                text = text.replace(marker, value)
            if fact.source not in refs:
                refs.append(fact.source)
        if lines:
            text += "\n\n" + "\n".join(lines)
        if "{{" in text or "}}" in text:
            raise GroundingError("事实占位符须声明field与本run已读source；未知占位符不发布。")
        if len(refs) > 8 or len(text) > 4000:
            raise GroundingError("填充后的回答仍须满足4000字符/8引用限制。")
        return text, refs

    if isinstance(decision, AnswerParts):
        parts = []
        for part in decision.parts:
            text, refs = render(part.text, part.facts, part.citations)
            parts.append(part.model_copy(update={"text": text, "citations": refs}))
        return decision.model_copy(update={"parts": parts})
    text, refs = render(decision.text, decision.facts, decision.citations)
    return decision.model_copy(update={"text": text, "citations": refs})


def check_amounts(decision: Answer | AnswerParts, request: SupportInput,
                  citations: dict[str, dict[str, Any]]) -> None:
    for part in decision.parts if isinstance(decision, AnswerParts) else [decision]:
        amounts = [Decimal((m.group(1) or m.group(2)).replace(",", "")) for m in MONEY.finditer(part.text)]
        if not amounts:
            continue
        allowed = set()
        for ref in part.citations:
            source = citations.get(ref, {})
            if source.get("source_type") == "ORDER":
                allowed.add(Decimal(value_for("PAID_AMOUNT", source, request).split()[0]))
        if any(value not in allowed for value in amounts):
            raise GroundingError("具体CNY金额须引用当前ORDER实付来源且数值一致；可先读取订单，或只说明一般政策。")
