"""Versioned, public application instructions; never merchant refund eligibility or live facts."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from typing import Any

GUIDE_VERSION = "2026.10.22-v2"


def guide_source() -> dict[str, Any]:
    raw = files("resolveflow.assets").joinpath("support-guide-v2.json").read_bytes()
    value = json.loads(raw)
    if (
        value["version"] != GUIDE_VERSION
        or value["authority"] != "APPLICATION_GUIDE"
        or hashlib.sha256(value["text"].encode()).hexdigest() != value["text_sha256"]
    ):
        raise ValueError("application guide version or source text differs")
    return {
        "source_type": "KNOWLEDGE",
        "version": GUIDE_VERSION,
        "title": "售后咨询使用指南",
        "data": {
            **{k: v for k, v in value.items() if k != "version"},
            "knowledge_sha256": hashlib.sha256(raw).hexdigest(),
        },
    }
