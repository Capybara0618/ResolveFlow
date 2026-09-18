"""Versioned wire contracts shared with the Java services.

Authority order: ``docs/contracts.md`` and ``contracts/*.schema.json`` define the
protocol; the models in this package implement it. Where the two disagree, the
documents win and both are revised together (docs/contracts.md:131).
"""

from __future__ import annotations

from resolveflow.contracts.canonical import (
    REFUND_FIELDS,
    RESHIP_FIELDS,
    CanonicalizationError,
    canonical_bytes,
    canonicalize,
    content_hash,
    payload_hash,
)
from resolveflow.contracts.events import (
    ENVELOPE_KEYS,
    SIGNABLE_KEYS,
    EventSignatureError,
    sign_envelope,
    signing_input_bytes,
    verify_envelope,
)

__all__ = [
    "ENVELOPE_KEYS",
    "REFUND_FIELDS",
    "RESHIP_FIELDS",
    "SIGNABLE_KEYS",
    "CanonicalizationError",
    "EventSignatureError",
    "canonical_bytes",
    "canonicalize",
    "content_hash",
    "payload_hash",
    "sign_envelope",
    "signing_input_bytes",
    "verify_envelope",
]