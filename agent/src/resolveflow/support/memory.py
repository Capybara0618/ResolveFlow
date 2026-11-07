"""Source-checked customer quotations. Meaning is a model annotation, never a business fact."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from resolveflow.support.context import history_messages
from resolveflow.support.protocol import (
    Closed,
    CustomerClaim,
    CustomerQuote,
    MemoryUpdate,
    SupportFailure,
    SupportInput,
)


class ClaimSource(Closed):
    message_id: str | None
    sequence: int = Field(ge=1, strict=True)
    offset: int = Field(ge=0, strict=True)
    quote: str = Field(min_length=1, max_length=300)


class ClaimEntry(Closed):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    topic: Literal["RECEIPT", "CHECKS", "REQUEST", "MATERIAL", "OTHER"]
    quote: str = Field(min_length=1, max_length=300)
    source: ClaimSource
    status: Literal["ACTIVE", "SUPERSEDED", "RETRACTED"]
    supersedes: list[str] = Field(max_length=8)
    retracts: list[str] = Field(max_length=8)


class ClaimSnapshot(Closed):
    version: Literal["support-claims-v1"]
    origin: Literal["GROUNDED_CUSTOMER_CLAIMS"]
    conversation_id: str
    merchant_id: str
    buyer_id: str
    line_id: str
    input_version: int = Field(ge=1, strict=True)
    entries: list[ClaimEntry] = Field(max_length=24)

    @model_validator(mode="after")
    def provenance(self) -> ClaimSnapshot:
        seen: dict[str, ClaimEntry] = {}
        for entry in self.entries:
            if (entry.id in seen or entry.quote != entry.source.quote
                    or entry.source.sequence > self.input_version):
                raise ValueError("invalid claim identity or source")
            for key in entry.supersedes + entry.retracts:
                target = seen.get(key)
                expected = "SUPERSEDED" if key in entry.supersedes else "RETRACTED"
                if (target is None or target.topic != entry.topic or target.status != expected
                        or target.source.sequence >= entry.source.sequence):
                    raise ValueError("invalid historical correction link")
            seen[entry.id] = entry
        if sum(e.status == "ACTIVE" for e in self.entries) > 12:
            raise ValueError("too many active claims")
        return self


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
    offset = text.find(quote.quote)
    if offset < 0:
        raise MemoryStateError("quote须为reference中的确切原句，不能改写或补造。")
    if text.find(quote.quote, offset + 1) >= 0:
        if "offset" not in quote.model_fields_set or not text.startswith(quote.quote, quote.offset):
            raise MemoryStateError("原句位置有歧义；请给出匹配的offset或引用更完整原句。")
        offset = quote.offset
    return {"message_id": source.get("message_id"), "sequence": sequence,
            "offset": offset, "quote": quote.quote}


class CustomerMemory:
    def __init__(self, request: SupportInput) -> None:
        self.request = request
        self.entries: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        raw = request.context.get("previous_customer_memory")
        if raw is not None:
            try:
                snapshot = ClaimSnapshot.model_validate(raw)
                if any(getattr(snapshot, field) != getattr(request, field)
                       for field in ("conversation_id", "merchant_id", "buyer_id", "line_id")):
                    raise ValueError("scope mismatch")
                if snapshot.input_version >= request.input_version:
                    raise ValueError("nonhistorical snapshot")
                self.entries = [entry.model_dump() for entry in snapshot.entries]
            except (ValidationError, ValueError):
                raise SupportFailure("PREVIOUS_MEMORY_INVALID") from None

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

    def propose(self, proposals: list[dict[str, Any]], observations: list[dict[str, Any]]) -> None:
        """Allocate stable identities; report rejected optional annotations without accepting false provenance."""
        self.warnings = []
        for index, raw in enumerate(proposals):
            try:
                proposal = CustomerClaim.model_validate(raw)
                targets = proposal.correction_ids()
                source = customer_source(proposal, self.request, observations, current_only=True)
                existing = next((e for e in self.entries if e["topic"] == proposal.topic
                                 and e["source"] == source and e["status"] == "ACTIVE"), None)
                if existing is not None:
                    if proposal.change == "APPEND":
                        continue
                    relation = "supersedes" if proposal.change == "REPLACE" else "retracts"
                    pending = [key for key in targets if key not in existing[relation]]
                    if not pending:
                        continue
                    entries = deepcopy(self.entries)
                    for key in pending:
                        target = next((e for e in entries if e["id"] == key), None)
                        if (target is None or target["status"] != "ACTIVE" or target["topic"] != proposal.topic
                                or target["source"]["sequence"] >= source["sequence"]):
                            raise MemoryStateError("替代目标须为更早同主题有效客户陈述。")
                        target["status"] = "SUPERSEDED" if proposal.change == "REPLACE" else "RETRACTED"
                    same = next(e for e in entries if e["id"] == existing["id"])
                    same[relation].extend(pending)
                    ClaimSnapshot.model_validate({**self.snapshot(), "entries": entries})
                    self.entries = entries
                    continue
                identity = json.dumps({"topic": proposal.topic, "source": source}, sort_keys=True)
                key = "c_" + hashlib.sha256(identity.encode()).hexdigest()[:24]
                update = MemoryUpdate(id=key, topic=proposal.topic, reference="CURRENT",
                                      quote=proposal.quote, offset=source["offset"],
                                      supersedes=targets if proposal.change == "REPLACE" else [],
                                      retracts=targets if proposal.change == "RETRACT" else [])
                self.apply([update], observations)
            except (ValidationError, MemoryStateError) as error:
                self.warnings.append({"index": index, "code": "CUSTOMER_CLAIM_NOT_ACCEPTED",
                    "detail": str(error)[:350], "current_message_retained": True})

    def packet(self) -> dict[str, Any]:
        return {"origin": "GROUNDED_CUSTOMER_CLAIMS",
                "active": [deepcopy(e) for e in self.entries if e["status"] == "ACTIVE"],
                **({"correction_targets": [{"id": e["id"], "topic": e["topic"], "quote": e["quote"]}
                                       for e in self.entries if e["status"] == "ACTIVE"
                                       and e["source"]["sequence"] < self.request.input_version]}
                   if self.entries else {}),
                **({"warnings": deepcopy(self.warnings)} if self.warnings else {})}

    def snapshot(self) -> dict[str, Any]:
        request = self.request
        return {"version": "support-claims-v1", "origin": "GROUNDED_CUSTOMER_CLAIMS",
                "conversation_id": request.conversation_id, "merchant_id": request.merchant_id,
                "buyer_id": request.buyer_id, "line_id": request.line_id,
                "input_version": request.input_version, "entries": deepcopy(self.entries)}
