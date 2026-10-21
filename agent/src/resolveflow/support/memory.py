"""Source-checked customer quotations. Meaning is a model annotation, never a business fact."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from resolveflow.support.context import history_messages
from resolveflow.support.protocol import CustomerQuote, MemoryUpdate, SupportInput


class MemoryStateError(ValueError):
    pass


def customer_source(
    quote: CustomerQuote, request: SupportInput, observations: list[dict[str, Any]], *, current_only: bool = False
) -> dict[str, Any]:
    if quote.reference == "CURRENT":
        source = {"sequence": request.input_version, "text": request.context.get("current_request", ""),
                  "message_id": None, "author": "CUSTOMER"}
    else:
        source = next((m for m in history_messages(request, observations)
                       if "H" + str(m["sequence"]) == quote.reference), {})
    sequence = source.get("sequence")
    if (source.get("author") != "CUSTOMER" or type(sequence) is not int
            or sequence > request.input_version or (current_only and sequence != request.input_version)):
        raise MemoryStateError("引用须为已知客户原文；对话变化须引用当前客户输入，不能用助手或未来消息。")
    text = source.get("text", "")
    if text[quote.offset:quote.offset + len(quote.quote)] != quote.quote:
        raise MemoryStateError("quote必须与reference原文offset处完全相同；不能改写或补造。")
    return {"message_id": source.get("message_id"), "sequence": sequence,
            "offset": quote.offset, "quote": quote.quote}


class CustomerMemory:
    def __init__(self, request: SupportInput) -> None:
        self.request = request
        self.entries: list[dict[str, Any]] = []

    def apply(self, updates: list[MemoryUpdate], observations: list[dict[str, Any]]) -> None:
        entries = deepcopy(self.entries)
        for update in updates:
            source = customer_source(update, self.request, observations)
            prior = next((e for e in entries if e["id"] == update.id), None)
            proposed = {"id": update.id, "topic": update.topic, "quote": update.quote, "source": source,
                        "status": "ACTIVE", "supersedes": update.supersedes, "retracts": update.retracts}
            if prior is not None:
                if prior == proposed:
                    continue
                raise MemoryStateError("陈述id不可覆盖；纠正须新id并显式supersedes/retracts。")
            replaced = update.supersedes + update.retracts
            if len(replaced) != len(set(replaced)):
                raise MemoryStateError("替代/撤回目标不可重复。")
            for key in replaced:
                target = next((e for e in entries if e["id"] == key), None)
                if (target is None or target["status"] != "ACTIVE" or target["topic"] != update.topic
                        or target["source"]["sequence"] >= source["sequence"]):
                    raise MemoryStateError("只可纠正/撤回同主题且更早的有效陈述，保留旧原文和替代关系。")
                target["status"] = "SUPERSEDED" if key in update.supersedes else "RETRACTED"
            entries.append(proposed)
        if len(entries) > 24 or sum(e["status"] == "ACTIVE" for e in entries) > 12:
            raise MemoryStateError("陈述容量不足；不能静默删除有效信息，停止新增并整理必要询问。")
        self.entries = entries

    def packet(self) -> dict[str, Any]:
        return {"origin": "GROUNDED_CUSTOMER_CLAIMS",
                "active": [deepcopy(e) for e in self.entries if e["status"] == "ACTIVE"]}

    def snapshot(self) -> dict[str, Any]:
        request = self.request
        return {"version": "support-claims-v1", "origin": "GROUNDED_CUSTOMER_CLAIMS",
                "conversation_id": request.conversation_id, "merchant_id": request.merchant_id,
                "customer_id": request.customer_id, "line_id": request.line_id,
                "input_version": request.input_version, "entries": deepcopy(self.entries)}
