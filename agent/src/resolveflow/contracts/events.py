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
from collections.abc import Callable
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from resolveflow.contracts.canonical import canonical_bytes

__all__ = [
    "CORE_ENVELOPE_KEYS",
    "CORE_SIGNABLE_KEYS",
    "ENVELOPE_KEYS",
    "SIGNABLE_KEYS",
    "EventSignatureError",
    "core_signing_input_bytes",
    "sign_core_envelope",
    "sign_envelope",
    "signing_input_bytes",
    "verify_core_envelope",
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

#: The core-v1.2 envelope members (contracts/core/event-envelope.schema.json). Core
#: dropped the compat ``aggregate_id``/``aggregate_version`` members - the business
#: version moved into the result payload, so it has one home instead of two that can
#: disagree - and added the routing ``topic``. Reusing ``SIGNABLE_KEYS`` for a core
#: envelope would therefore sign *different* bytes: it would fill ``aggregate_id`` and
#: ``aggregate_version`` with JSON ``null`` (members the core envelope does not declare)
#: and omit ``topic`` (which it does declare). Both sides would be self-consistent and
#: still disagree, so core signs over this tuple instead. The optional ``traceparent``
#: and ``causation_id`` are kept from v1 and are normalised to ``null`` when absent,
#: exactly as before. A test pins this tuple against the core schema's declared members.
CORE_ENVELOPE_KEYS = (
    "event_id",
    "event_type",
    "schema_version",
    "merchant_id",
    "occurred_at",
    "producer",
    "topic",
    "traceparent",
    "causation_id",
    "payload",
    "signature",
    "signing_key_id",
)

#: Core signed members: everything except the signature itself (docs/core-contracts.md:19).
CORE_SIGNABLE_KEYS = tuple(key for key in CORE_ENVELOPE_KEYS if key != "signature")


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
    _verify(envelope, signature_b64, public_key, signing_input_bytes)


def core_signing_input_bytes(envelope: dict[str, Any]) -> bytes:
    """Return the canonical bytes a core-v1.2 envelope's ``signature`` covers.

    Requires every member of :data:`CORE_SIGNABLE_KEYS` to be declared by the core
    envelope schema and normalises absent optional members to JSON ``null``, exactly as
    the compat rule does, so a producer that omits a member and one that sends an
    explicit ``null`` still sign identical bytes.
    """
    unsigned = {key: envelope.get(key) for key in CORE_SIGNABLE_KEYS}
    payload = unsigned.get("payload")
    if not isinstance(payload, dict):
        raise EventSignatureError("envelope payload must be a JSON object to be signed")
    return canonical_bytes(unsigned)


def sign_core_envelope(envelope: dict[str, Any], private_key: Ed25519PrivateKey) -> str:
    """Return the base64 signature over a core envelope's normalised signing input."""
    return base64.b64encode(private_key.sign(core_signing_input_bytes(envelope))).decode("ascii")


def verify_core_envelope(
    envelope: dict[str, Any],
    signature_b64: str,
    public_key: Ed25519PublicKey,
) -> None:
    """Raise :class:`EventSignatureError` unless the signature covers this core envelope."""
    _verify(envelope, signature_b64, public_key, core_signing_input_bytes)


def _verify(
    envelope: dict[str, Any],
    signature_b64: str,
    public_key: Ed25519PublicKey,
    signing_input: Callable[[dict[str, Any]], bytes],
) -> None:
    try:
        raw = base64.b64decode(signature_b64, validate=True)
    except (ValueError, TypeError) as error:  # binascii.Error subclasses ValueError
        raise EventSignatureError(f"signature is not valid base64: {error}") from error
    if len(raw) != 64:
        raise EventSignatureError(f"Ed25519 signature must be 64 bytes, got {len(raw)}")
    try:
        public_key.verify(raw, signing_input(envelope))
    except InvalidSignature as error:
        raise EventSignatureError("envelope signature does not cover this envelope") from error