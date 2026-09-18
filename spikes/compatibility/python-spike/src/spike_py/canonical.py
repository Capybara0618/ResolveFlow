"""RFC 8785 (JCS) canonical JSON and the execution payload hash.

docs/contracts.md:13 requires request hashing over canonicalised JSON, not raw
bytes; :17 fixes exactly which fields the execution ``payload_hash`` covers.
This module is the Python half of a cross-language fixture — the Java half must
produce identical bytes.

Scope note: the domain forbids float money (contracts.md:19 caps amounts at
1_000_000_000 minor units and revisions at 2^53-1), so non-integer numbers are
rejected rather than serialised. That keeps the Java/Python/JavaScript number
question closed instead of hoped-for.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Fields covered by execution payload_hash, per docs/contracts.md:17.
# Deliberately excluded: payload_hash itself (self-reference), entitlement_id
# (filled in after reservation), trace and send time.
REFUND_FIELDS = (
    "operation_id",
    "case_id",
    "authorization_id",
    "input_revision",
    "line_id",
    "merchant_id",
    "action",
    "quantity",
    "currency",
    "amount_minor",
    "policy_version",
    "target_service",
)

RESHIP_FIELDS = (
    "operation_id",
    "case_id",
    "authorization_id",
    "input_revision",
    "line_id",
    "merchant_id",
    "action",
    "quantity",
    "currency",
    "address_hash",
    "policy_version",
    "target_service",
)


class CanonicalizationError(ValueError):
    """Raised when a value has no RFC 8785 representation in this constrained subset."""


def _utf16_sort_key(text: str) -> bytes:
    """JCS sorts object keys by UTF-16 code unit.

    Python compares by code point, which disagrees with UTF-16 ordering for
    supplementary characters (U+10000+) versus U+E000..U+FFFF. Encoding to
    UTF-16BE and comparing bytes reproduces the specified order.
    """
    return text.encode("utf-16-be")


def _serialize(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        # ensure_ascii=False emits raw UTF-8; JCS escapes only what JSON requires.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        # int is checked before float so bools (handled above) and ints are exact.
        return str(value)
    if isinstance(value, float):
        raise CanonicalizationError(
            "floating point is not canonicalisable in this domain; use integer minor units"
        )
    if isinstance(value, list):
        return "[" + ",".join(_serialize(item) for item in value) + "]"
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise CanonicalizationError(f"object key must be a string, got {type(key).__name__}")
        keys = sorted(value.keys(), key=_utf16_sort_key)
        return "{" + ",".join(
            json.dumps(key, ensure_ascii=False) + ":" + _serialize(value[key]) for key in keys
        ) + "}"
    raise CanonicalizationError(f"unsupported type: {type(value).__name__}")


def canonicalize(value: Any) -> str:
    """Return the RFC 8785 canonical JSON text for ``value``."""
    return _serialize(value)


def canonical_bytes(value: Any) -> bytes:
    return canonicalize(value).encode("utf-8")


def payload_hash(payload: dict[str, Any]) -> str:
    """SHA-256 over the canonicalised execution payload field set.

    ``payload_hash`` and ``entitlement_id`` are dropped if present so the hash of a
    fully-built command matches the hash computed before entitlement reservation.
    """
    action = payload.get("action")
    if action == "REFUND":
        fields = REFUND_FIELDS
    elif action == "RESHIP":
        fields = RESHIP_FIELDS
    else:
        raise CanonicalizationError(f"unknown action for payload hash: {action!r}")

    missing = [name for name in fields if name not in payload]
    if missing:
        raise CanonicalizationError(f"missing field(s) for {action} payload hash: {missing}")

    subset = {name: payload[name] for name in fields}
    return hashlib.sha256(canonical_bytes(subset)).hexdigest()


def content_hash(value: Any) -> str:
    """SHA-256 over canonical bytes, for evidence/policy content hashes."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()