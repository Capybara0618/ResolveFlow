"""Retrieval-only spans; complete authority-owned rules remain the citation unit."""

from __future__ import annotations

import hashlib
import re
from typing import Any

TARGET_ENCODER_TOKENS = 384
RETRIEVAL_LAYOUT = "token-children-v1"


def encoder_tokens(text: str, tokenizer: Any) -> int:
    return len(tokenizer(text, truncation=False, add_special_tokens=True)["input_ids"])


def split_for_encoder(text: str, tokenizer: Any, target: int, encoder_limit: int) -> list[dict[str, Any]]:
    if (
        type(target) is not int
        or type(encoder_limit) is not int
        or not 3 <= target <= encoder_limit
        or not isinstance(text, str)
        or not text
    ):
        raise ValueError("invalid text or encoder token limit")
    output = []
    start = 0
    while start < len(text):
        remaining = text[start:]
        encoded = tokenizer(remaining, truncation=False, add_special_tokens=True, return_offsets_mapping=True)
        if len(encoded["input_ids"]) <= target:
            end = len(remaining)
        else:
            offsets = [(a, b) for a, b in encoded["offset_mapping"] if 0 <= a < b <= len(remaining)]
            capacity = target - (len(encoded["input_ids"]) - len(offsets))
            if capacity < 1 or not offsets:
                raise ValueError("encoder offsets cannot satisfy token limit")
            end = offsets[min(capacity, len(offsets)) - 1][1]
            stops = [m.end() for m in re.finditer(r"[。！？!?；;\n]|\.(?=\s|$)", remaining[:end])]
            if stops and stops[-1] >= end // 2:
                end = stops[-1]
            while end > 0 and encoder_tokens(remaining[:end], tokenizer) > target:
                end -= 1
            if end <= 0:
                raise ValueError("encoder cannot make progress without truncation")
        part = remaining[:end]
        output.append(
            {
                "text": part,
                "start": start,
                "end": start + end,
                "encoder_tokens": encoder_tokens(part, tokenizer),
                "text_sha256": hashlib.sha256(part.encode()).hexdigest(),
            }
        )
        start += end
    return output
