"""Pinned, offline input estimates; provider usage remains authoritative.

Only the supported DeepSeek Flash identity uses the official V4.1 tokenizer.
No network, fallback after asset corruption, or mutable tokenizer selection in a run.
"""

import gzip
import hashlib
import importlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from resolveflow.harness.context import canonical_json, estimate_tokens

ASSET = Path(__file__).resolve().parents[1] / "assets/deepseek-v41/tokenizer.json.gz"
RAW_SHA256 = "81f64d1248a68ce3663e07ab3ee48b851e5df0e32d27cb98e4c9a268151e8d99"
GZIP_SHA256 = "a06de40d7aa5f5f2486dea7d0d516420edfe07e1d946b5ad2c57e73851de3008"
BYTE_VERSION = "utf8-json-bytes-v3-single-wrapper"
FLASH_VERSION = "deepseek-v41-json-v1-" + RAW_SHA256


@lru_cache(maxsize=1)
def load_tokenizer(path: Path = ASSET) -> Any:
    # Existing retrieval dependency has no typing stubs; load it only for the Flash profile.
    Tokenizer = importlib.import_module("tokenizers").Tokenizer

    try:
        compressed = path.read_bytes()
        if hashlib.sha256(compressed).hexdigest() != GZIP_SHA256:
            raise ValueError("compressed hash mismatch")
        raw = gzip.decompress(compressed)
        if hashlib.sha256(raw).hexdigest() != RAW_SHA256:
            raise ValueError("raw hash mismatch")
        tokenizer = Tokenizer.from_str(raw.decode("utf-8"))
        # Neither a tokenizer config's padding nor truncation may undercount a request.
        tokenizer.no_padding()
        tokenizer.no_truncation()
        return tokenizer
    except (OSError, ValueError) as error:
        raise ValueError("DeepSeek tokenizer integrity check failed") from error


@dataclass(frozen=True)
class InputCounter:
    version: str = BYTE_VERSION
    mode: str = "ESTIMATED_UTF8_BYTES"  # noqa: S105

    def count(self, body: dict[str, Any]) -> int:
        wire = canonical_json(body)
        if self.version == BYTE_VERSION:
            return estimate_tokens(wire)
        tokenizer = load_tokenizer()
        wire_count = len(tokenizer.encode(wire, add_special_tokens=False).ids)
        # Separate message encoding avoids token merges across role boundaries.
        content_count = sum(len(tokenizer.encode(message["content"], add_special_tokens=False).ids)
                            for message in body.get("messages", [])
                            if isinstance(message.get("content"), str))
        return max(wire_count, content_count)


def counter_for(client: Any) -> InputCounter:
    if getattr(client, "provider", None) == "deepseek" and getattr(client, "model_id", None) == "deepseek-flash":
        return InputCounter(FLASH_VERSION, "ESTIMATED_DEEPSEEK_V41_JSON")
    return InputCounter()
