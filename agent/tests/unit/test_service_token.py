"""C06.1: the service token that guards ``POST /internal/v1/runs``.

The token is the only thing standing between "case-service dispatches a run" and "anything holding the
demonstration secret does". Every rule below is a refusal rather than a default, and the last test checks
this verifier against PyJWT — so "we verify HS256 ourselves instead of adding a dependency" is a claim that
is tested rather than asserted (see the module docstring of ``api/identity.py`` for why it is written here).

These are unit tests: no database and no network. The HTTP surface that uses the verifier is in
``tests/integration/test_run_api.py``.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json

import jwt
import pytest

from resolveflow.api.identity import (
    ISSUER,
    RUN_DISPATCH_SCOPE,
    SERVICE_AUDIENCE,
    ServiceTokenVerifier,
    TokenRefusedError,
    TokenScopeError,
    mint_service_token,
)

SECRET = "resolveflow-core-demo-identity-secret"


def verifier() -> ServiceTokenVerifier:
    return ServiceTokenVerifier(SECRET)


def header(token: str) -> str:
    return f"Bearer {token}"


def test_an_honest_dispatch_token_is_accepted_and_carries_its_context() -> None:
    """The token must say who called and whose line it is for: the body has to agree with something."""
    token = mint_service_token(
        "case-service",
        SECRET,
        scope=RUN_DISPATCH_SCOPE,
        merchant_id="M-1001",
        customer_id="C-2002",
    )

    claims = verifier().verify(header(token))

    assert claims.subject == "case-service"
    assert claims.issuer == ISSUER
    assert claims.audience == SERVICE_AUDIENCE
    assert claims.scope == RUN_DISPATCH_SCOPE
    assert claims.merchant_id == "M-1001"
    assert claims.customer_id == "C-2002"


def test_a_user_audience_token_is_not_a_service_token() -> None:
    """The audience is the boundary between the two surfaces (JwtCodec.SERVICE_AUDIENCE)."""
    token = mint_service_token("demo-customer", SECRET, audience="resolveflow-user", scope=None)

    with pytest.raises(TokenRefusedError, match="audience"):
        verifier().verify(header(token))


def test_a_token_from_another_issuer_is_refused() -> None:
    """C05.4c: the issuer half of "issuer and audience are validated" used to be missing on the Java side.

    It is checked here from the start, so the two ends agree on what "our own token" means.
    """
    token = mint_service_token("case-service", SECRET, issuer="someone-else")

    with pytest.raises(TokenRefusedError, match="issuer"):
        verifier().verify(header(token))


def test_another_projects_secret_is_not_accepted() -> None:
    token = mint_service_token("case-service", "another-project-secret-value")

    with pytest.raises(TokenRefusedError, match="signature"):
        verifier().verify(header(token))


def test_alg_none_is_refused_before_the_signature_is_examined() -> None:
    """A verifier that honours the token's own ``alg`` is how "alg: none" works."""
    header_part = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload_part = _b64(
        json.dumps({"sub": "case-service", "aud": SERVICE_AUDIENCE, "iss": ISSUER, "exp": 4_000_000_000}).encode()
    )
    token = f"{header_part}.{payload_part}."

    with pytest.raises(TokenRefusedError, match="alg"):
        verifier().verify(header(token))


def test_an_expired_token_is_refused() -> None:
    token = mint_service_token("case-service", SECRET, ttl_seconds=60, now=1_700_000_000)

    with pytest.raises(TokenRefusedError, match="expired"):
        verifier().verify(header(token), now=1_700_000_100)


def test_a_token_without_an_expiry_is_refused() -> None:
    """Java requires ``exp`` (``JwtCodec.verifiedClaims``); a token that never expires is not a token."""
    token = _sign({"sub": "case-service", "aud": SERVICE_AUDIENCE, "iss": ISSUER})

    with pytest.raises(TokenRefusedError, match="no exp"):
        verifier().verify(header(token))


def test_a_token_that_is_not_valid_yet_is_refused() -> None:
    claims = {
        "sub": "case-service",
        "aud": SERVICE_AUDIENCE,
        "iss": ISSUER,
        "iat": 1_700_000_000,
        "exp": 1_700_003_600,
        "nbf": 1_700_000_500,
    }
    token = _sign(claims)

    with pytest.raises(TokenRefusedError, match="not valid yet"):
        verifier().verify(header(token), now=1_700_000_100)


def test_a_token_without_a_subject_is_refused() -> None:
    token = _sign({"aud": SERVICE_AUDIENCE, "iss": ISSUER, "exp": 4_000_000_000})

    with pytest.raises(TokenRefusedError, match="missing sub"):
        verifier().verify(header(token))


def test_a_scope_that_is_not_run_dispatch_is_forbidden_rather_than_unauthenticated() -> None:
    """403 and 401 are different answers: "you may not" versus "who are you" (openapi-agent.yaml:262)."""
    token = mint_service_token("case-service", SECRET, scope="commerce:read")

    with pytest.raises(TokenScopeError, match="run:dispatch"):
        verifier().verify(header(token))


def test_a_token_that_names_no_scope_is_accepted_and_says_so() -> None:
    """The Java codec's service token carries no scope claim today, and the dispatcher cannot mint one.

    The identity boundary is then the audience plus the subject, and the claims record ``scope=None`` so a
    reader can tell "no scope was named" from "the right scope was named".
    """
    token = mint_service_token("case-service", SECRET, scope=None)

    assert verifier().verify(header(token)).scope is None


@pytest.mark.parametrize(
    "presented",
    [None, "", "Bearer", "Bearer ", "not-a-token", "a.b", "a.b.c", "Bearer a.b.c.d"],
)
def test_a_broken_authorization_header_is_refused(presented: str | None) -> None:
    with pytest.raises(TokenRefusedError):
        verifier().verify(presented)


def test_a_lowercase_bearer_scheme_is_refused() -> None:
    """``bearer`` is not the scheme this route accepts, and guessing would be a silent widening."""
    token = mint_service_token("case-service", SECRET)

    with pytest.raises(TokenRefusedError, match="Bearer"):
        verifier().verify(f"bearer {token}")


def test_a_short_signing_secret_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="at least 16"):
        ServiceTokenVerifier("too-short")


def test_the_verifier_agrees_with_pyjwt_on_tokens_this_repository_mints() -> None:
    """Cross-check: PyJWT's own verification of the same rules must accept what this verifier accepts.

    PyJWT is present because ``mcp`` depends on it, which is exactly why it is used as an independent check
    instead of being declared as a runtime dependency (``uv lock --check`` stays clean).
    """
    token = mint_service_token(
        "case-service",
        SECRET,
        scope=RUN_DISPATCH_SCOPE,
        merchant_id="M-1001",
        customer_id="C-2002",
        now=int(dt.datetime.now(dt.UTC).timestamp()),
    )

    decoded = jwt.decode(
        token,
        SECRET,
        algorithms=["HS256"],
        audience=SERVICE_AUDIENCE,
        issuer=ISSUER,
        options={"require": ["exp", "sub"]},
    )

    assert decoded["sub"] == "case-service"
    assert decoded["scope"] == RUN_DISPATCH_SCOPE
    assert decoded["merchant_id"] == "M-1001"
    # and this verifier accepts the very same token
    assert verifier().verify(header(token)).subject == "case-service"


def _sign(claims: dict[str, object]) -> str:
    header_part = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload_part = _b64(json.dumps(claims).encode())
    signing_input = f"{header_part}.{payload_part}".encode("ascii")
    signature = hmac.new(SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_part}.{payload_part}.{_b64(signature)}"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")