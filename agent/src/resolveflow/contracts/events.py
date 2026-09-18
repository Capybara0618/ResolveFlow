"""Event envelope signing input and Ed25519 signatures.

docs/contracts.md:17 fixes the rule: sign the canonicalised envelope with the
``signature`` field excluded and ``signing_key_id`` retained, using Ed25519. It
also requires T02 to freeze both the input *and* the resulting bytes with a
cross-language test, which is what this module and
``com.resolveflow.shared.contract.EventSignature`` jointly do.

Two rules here are load-bearing and easy to get subtly wrong:

* The signing input is *normalised*, not "whatever was on the wire". Optional
  envelope members that are absent are filled in as JSON ``null`` before
  canonicalisation, so a producer that omits ``traceparent`` and a producer that
  sends ``"traceparent": null`` sign identical bytes. Without this, Java and
  Python would each be self-consistent and still disagree in production.
* The signature is not an authentication credential by itself.
  docs/contracts.md:127 requires the consumer to also check the fixed
  ``payload_hash``, the target audience and the entitlement state; the signature
  only proves the envelope body was produced by a holder of the key.
"""

from __future__ import annotations

import base64
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from resolveflow.contracts.canonical import canonical_bytes

__all__ = [
    "ENVELOPE_KEYS",
    "SIGNABLE_KEYS",
    "EventSignatureError",
    "sign_envelope",
    "signing_input_bytes",
    "verify_envelope",
]

# Every member declared by contracts/event-envelope.schema.json, required and
# optional. ``additionalProperties: false`` means this list is exhaustive; a new
# optional member must be added here at the same time or the signing bytes drift
# silently between the languages.
ENVELOPE_KEYS = (
    "event_id",
    "event_type",
    "schema_version",
    "aggregate_id",
    "aggregate_version",
    "merchant_id",
    "occurred_at",
    "producer",
    "traceparent",
    "causation_id",
    "payload",
    "signature",
    "signing_key_id",
)

# Signed members: everything except the signature itself.
SIGNABLE_KEYS = tuple(key for key in ENVELOPE_KEYS if key != "signature")


class EventSignatureError(ValueError):
    """The envelope cannot be signed or verified as specified."""


def signing_input_bytes(envelope: dict[str, Any]) -> bytes:
    """Return the canonical bytes covered by ``signature``, per docs/contracts.md:17."""
    unsigned = {key: envelope.get(key) for key in SIGNABLE_KEYS}
    payload = unsigned.get("payload")
    if not isinstance(payload, dict):
        raise EventSignatureError("envelope payload must be a JSON object to be signed")
    return canonical_bytes(unsigned)


def sign_envelope(envelope: dict[str, Any], private_key: Ed25519PrivateKey) -> str:
    """Return the base64 signature over the envelope's normalised signing input."""
    return base64.b64encode(private_key.sign(signing_input_bytes(envelope))).decode("ascii")


def verify_envelope(
    envelope: dict[str, Any],
    signature_b64: str,
    public_key: Ed25519PublicKey,
) -> None:
    """Raise :class:`EventSignatureError` unless ``signature_b64`` covers this envelope."""
    try:
        raw = base64.b64decode(signature_b64, validate=True)
    except (ValueError, TypeError) as error:  # binascii.Error subclasses ValueError
        raise EventSignatureError(f"signature is not valid base64: {error}") from error
    if len(raw) != 64:
        raise EventSignatureError(f"Ed25519 signature must be 64 bytes, got {len(raw)}")
    try:
        public_key.verify(raw, signing_input_bytes(envelope))
    except InvalidSignature as error:
        raise EventSignatureError("envelope signature does not cover this envelope") from error