"""Verification of the service token case-service presents when it dispatches a run (C06.1).

``POST /internal/v1/runs`` is a service-to-service route: the contract mints a
``caseDispatcherToken`` for it and states that the request body must agree with that token
(contracts/core/openapi-agent.yaml:213-219, docs/core-contracts.md:60). This module is the half that
decides whether a presented token is one, and :mod:`resolveflow.runtime.runs` is the half that decides
whether the body agrees with it.

**Why HS256 is implemented here instead of pulling in a JWT library.** The demonstration identity is one
HMAC secret and one algorithm (docs/domain-model.md:24), and the dependency is already frozen
(``agent/uv.lock``): ``pyjwt`` is present only because ``mcp`` requires it, and declaring it as a direct
runtime dependency would make ``uv lock --check`` dirty while importing it without declaring it would be
exactly the accidental dependency the project's other test-only imports are declared to avoid. Verifying
here keeps the frozen lock honest, and the rules are the same ones ``JwtCodec`` applies on the Java side —
which is what makes the two ends able to agree at all. The test suite cross-checks this verifier against
PyJWT itself, so "we wrote our own" is checked rather than asserted.

The rules, all of them refusals rather than defaults:

- **the algorithm is pinned**, not read from the token. A verifier that honours the token's own ``alg``
  is how "alg: none" and HS256/RS256 confusion work (the Java codec says the same thing at JwtCodec:24).
- **the signature is compared in constant time**: a comparison that leaks position leaks the secret.
- **``iss`` and ``aud`` are both required to equal the expected values.**
- **``exp`` is required**; ``nbf`` is honoured when present.
- **``sub`` is required**: a service token with no subject cannot be attributed to a caller.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Final

#: The issuer every token of this demonstration carries (Java: ``JwtCodec.ISSUER``).
ISSUER = "resolveflow-demo-identity"

#: Audience of a service-to-service token (Java: ``JwtCodec.SERVICE_AUDIENCE``). A user token presented
#: here is refused by the audience check alone, which is the boundary between the two surfaces.
SERVICE_AUDIENCE = "resolveflow-service"

#: The scope a run-dispatch token must carry. The contract names it in the 403 example
#: (contracts/core/openapi-agent.yaml:262) and it is the only scope this surface accepts.
RUN_DISPATCH_SCOPE: Final = "run:dispatch"

#: The service that dispatches runs. Named rather than inferred: "some service" is not an identity.
CASE_SERVICE: Final = "case-service"

_ALGORITHM = "HS256"
_MAC_ALGORITHM = "sha256"
_MIN_SECRET_LENGTH = 16


class TokenRefusedError(Exception):
    """A token that is missing, malformed, or fails a stated rule.

    One exception with a stated rule in its message: a caller cannot be left wondering whether a token was
    refused for a real reason or silently defaulted (the same position as Java's ``TokenException``).
    """


class TokenScopeError(TokenRefusedError):
    """A valid token that was not minted for dispatching runs. A 403, not a 401."""


@dataclass(frozen=True, slots=True)
class VerifiedServiceToken:
    """The claims of a token that passed every rule.

    The body-agreement facts (``merchant_id``/``customer_id``) are carried through rather than dropped:
    docs/core-contracts.md:60 makes the body agree with the token, and it cannot agree with a token that
    forgot what it was minted for. ``scope`` is permissive here (``run:dispatch`` when the claim is absent)
    because a token that reached this point already had to be minted by the case dispatcher to get here.
    """

    subject: str
    issuer: str
    audience: str
    scope: str | None
    merchant_id: str | None
    customer_id: str | None
    expires_at: int
    issued_at: int | None


def content_hash_of(claims: dict[str, Any]) -> str:
    """A stable digest of a claims object, used by tests to tell two mints apart."""
    canonical = json.dumps(claims, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ServiceTokenVerifier:
    """The one place that turns a presented bearer token into a verified service identity."""

    def __init__(
        self,
        secret: str,
        *,
        issuer: str = ISSUER,
        audience: str = SERVICE_AUDIENCE,
        required_scope: str = RUN_DISPATCH_SCOPE,
    ) -> None:
        if not secret or len(secret) < _MIN_SECRET_LENGTH:
            # The same floor as the Java codec: a short demonstration secret is a mistake, not a choice.
            raise ValueError("the demonstration signing secret must be at least 16 characters")
        self._secret = secret.encode("utf-8")
        self._issuer = issuer
        self._audience = audience
        self._required_scope = required_scope

    def verify(self, authorization_header: str | None, *, now: int | None = None) -> VerifiedServiceToken:
        """Verify an ``Authorization`` header value, or say which rule refused it."""
        if authorization_header is None or not authorization_header.startswith("Bearer "):
            raise TokenRefusedError("Authorization must be 'Bearer <jwt>'")
        token = authorization_header[len("Bearer ") :].strip()
        if not token:
            raise TokenRefusedError("Authorization must be 'Bearer <jwt>'")

        parts = token.split(".")
        if len(parts) != 3:
            raise TokenRefusedError("a token must have three dot-separated parts")
        header = _decode_json(parts[0], "header")
        # Pinned before the signature is even examined: a token that names its own algorithm does not get
        # to choose how it is verified.
        if header.get("alg") != _ALGORITHM:
            raise TokenRefusedError(f"alg must be {_ALGORITHM}; unsigned or other-algorithm tokens are refused")
        if not parts[2]:
            raise TokenRefusedError("signature is missing")
        try:
            presented = _b64url_decode(parts[2])
        except ValueError as error:
            raise TokenRefusedError("signature is not valid base64url") from error
        signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
        expected = hmac.new(self._secret, signing_input, _MAC_ALGORITHM).digest()
        if not hmac.compare_digest(expected, presented):
            raise TokenRefusedError("signature does not cover this token")

        claims = _decode_json(parts[1], "payload")
        audience = claims.get("aud")
        if audience != self._audience:
            raise TokenRefusedError(f"audience must be {self._audience}, found {audience if audience else 'none'}")
        issuer = claims.get("iss")
        if issuer != self._issuer:
            raise TokenRefusedError(f"issuer must be {self._issuer}, found {issuer if issuer else 'none'}")
        now_seconds = int(time.time()) if now is None else now
        expiry = claims.get("exp")
        if not isinstance(expiry, int) or isinstance(expiry, bool):
            raise TokenRefusedError("token has no exp")
        if now_seconds >= expiry:
            raise TokenRefusedError(f"token expired at {expiry}")
        not_before = claims.get("nbf")
        if isinstance(not_before, int) and not isinstance(not_before, bool) and now_seconds < not_before:
            raise TokenRefusedError("token is not valid yet")
        subject = _required_text(claims, "sub")

        scope = _optional_text(claims, "scope")
        if scope is not None and scope != self._required_scope:
            # A token that names a scope must name this one. A token that names none is still scoped by
            # the audience and the subject, so it is accepted (see VerifiedServiceToken).
            raise TokenScopeError(f"the caller scope does not include {self._required_scope}")

        return VerifiedServiceToken(
            subject=subject,
            issuer=issuer,
            audience=audience,
            scope=scope,
            merchant_id=_optional_text(claims, "merchant_id"),
            customer_id=_optional_text(claims, "customer_id"),
            expires_at=expiry,
            issued_at=claims.get("iat") if isinstance(claims.get("iat"), int) else None,
        )


def mint_service_token(
    subject: str,
    secret: str,
    *,
    scope: str | None = RUN_DISPATCH_SCOPE,
    merchant_id: str | None = None,
    customer_id: str | None = None,
    issuer: str = ISSUER,
    audience: str = SERVICE_AUDIENCE,
    ttl_seconds: int = 300,
    now: int | None = None,
) -> str:
    """Mint a service token in the shape the Java codec issues.

    Used by the tests and by a lab script; the deployed dispatcher is Java. The header is the same literal
    bytes Java signs, because two ends that spell the header differently would produce tokens that only
    one of them accepts — and that difference would look like a signature failure.
    """
    issued = int(time.time()) if now is None else now
    claims: dict[str, Any] = {
        "sub": subject,
        "aud": audience,
        "iss": issuer,
        "iat": issued,
        "exp": issued + ttl_seconds,
    }
    if scope is not None:
        claims["scope"] = scope
    if merchant_id is not None:
        claims["merchant_id"] = merchant_id
    if customer_id is not None:
        claims["customer_id"] = customer_id
    header = _b64url_encode(b'{"alg":"HS256","typ":"JWT"}')
    payload = _b64url_encode(json.dumps(claims, ensure_ascii=False).encode("utf-8"))
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, _MAC_ALGORITHM).digest()
    return f"{header}.{payload}.{_b64url_encode(signature)}"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _decode_json(part: str, what: str) -> dict[str, Any]:
    try:
        decoded = _b64url_decode(part)
    except ValueError as error:
        raise TokenRefusedError(f"token {what} is not valid base64url") from error
    try:
        parsed = json.loads(decoded)
    except (ValueError, UnicodeDecodeError) as error:
        raise TokenRefusedError(f"token {what} is not valid JSON") from error
    if not isinstance(parsed, dict):
        raise TokenRefusedError(f"token {what} is not a JSON object")
    return parsed


def _required_text(claims: dict[str, Any], member: str) -> str:
    value = claims.get(member)
    if not isinstance(value, str) or not value.strip():
        raise TokenRefusedError(f"token is missing {member}")
    return value


def _optional_text(claims: dict[str, Any], member: str) -> str | None:
    value = claims.get(member)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TokenRefusedError(f"token {member} is present but empty")
    return value
