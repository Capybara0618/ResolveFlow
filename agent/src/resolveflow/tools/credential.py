"""The run-scoped tool credential, and where the tools get it (C06.4④).

``docs/contracts.md:96`` says the tool credential is issued per run and renewed through Case
(``POST /internal/v1/runs/{run_id}/tool-credential``), and ``docs/core-contracts.md:74`` lists what it is bound
to: run/case/revision/merchant/customer/line/aud/scope. Before this module the five tools presented a token read
out of ``RESOLVEFLOW_TOOL_SERVICE_TOKEN`` — one credential for every run a deployment ever served. That is a
different thing from what the contract describes, and the differences are not cosmetic:

- **a deployment-wide token is not bound to a run**, so nothing can refuse it when the run stops describing the
  case, and it carries no line, so "may this token read this line" has no answer;
- **it never expires in practice**, because a token that had to be kept valid for every future run cannot be
  given a short life;
- **it cannot be renewed**, so the only way to keep tools working is to make the token long-lived.

So the credential is *fetched* rather than configured, once per run, and this module is the fetch.

**Why a callable and not just a client object.** The executor's contract is a token *per read*, because a run may
outlive its credential: ``docs/contracts.md:96`` gives it five minutes, and an investigation that reads its fifth
tool four minutes in has three guesses left about whether the first token is still good. Making the executor hold
a token would put the renewal decision somewhere with no view of the clock; making it hold a *source* of tokens
lets the renewal happen exactly when a read needs one, and lets a test substitute a two-line function instead of
a fake HTTP server.

**Why the failure is loud.** A run whose credential cannot be minted has no business reading business data with
the deployment's own token instead. Falling back to ``RESOLVEFLOW_TOOL_SERVICE_TOKEN`` when the route answers 503
would be the worst of both: the tools would keep working, so nobody would notice, and every read would be made
under a credential that is not the run's. The fallback exists only for a deployment that has not been pointed at
a case service at all, and it is a *configuration* answer, not a runtime one.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol

__all__ = [
    "CREDENTIAL_ROUTE",
    "CredentialUnavailableError",
    "HttpToolCredentialClient",
    "ToolCredential",
    "ToolCredentialClient",
    "credential_source",
    "credential_token_source",
]

#: The route that mints one, character for character as ``contracts/core/openapi-case.yaml:814`` declares it, so
#: a citation of the route can be grepped into the contract and a rename there breaks this test rather than
#: producing a 404 at run time.
CREDENTIAL_ROUTE: Final = "/internal/v1/runs/{run_id}/tool-credential"


class CredentialUnavailableError(RuntimeError):
    """The run's credential could not be obtained.

    Raised rather than returned as a failed observation, because a credential is not evidence: a tool that could
    not authenticate has learned nothing about the order, and an observation saying "FORBIDDEN" would tell the
    model the source refused it — a claim about the world made out of this process's own configuration problem.
    """


@dataclass(frozen=True, slots=True)
class ToolCredential:
    """What Case answered: the token, when it expires, and the scopes it carries.

    All three are kept even though only the token is presented, because the other two are what a caller checks
    before deciding the credential is one it can use: presenting a credential without looking at its scopes is
    how a run ends up making a read it was never granted.
    """

    token: str
    expires_at: str
    scopes: tuple[str, ...]

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> ToolCredential:
        """Parse the contract's ``ToolCredentialResponse``, refusing anything missing.

        No defaults: a credential without an expiry cannot be renewed before it lapses, and one without scopes
        cannot be checked at all. Filling those in would make a malformed answer look like a working credential.
        """
        token = payload.get("token")
        expires_at = payload.get("expires_at")
        scopes = payload.get("scopes")
        if not isinstance(token, str) or not token:
            raise CredentialUnavailableError("the credential response carries no token")
        if not isinstance(expires_at, str) or not expires_at:
            raise CredentialUnavailableError("the credential response carries no expires_at")
        if not isinstance(scopes, list) or not scopes or not all(isinstance(item, str) for item in scopes):
            raise CredentialUnavailableError("the credential response carries no scopes")
        return cls(token=token, expires_at=expires_at, scopes=tuple(scopes))


class ToolCredentialClient(Protocol):
    """Somewhere to ask for the run's credential."""

    def issue(self, *, run_id: str, case_id: str, input_revision: int) -> ToolCredential: ...


@dataclass(slots=True)
class HttpToolCredentialClient:
    """Fetches the credential from Case, over the route the contract declares.

    A fresh request each time rather than a cached credential, for the reason the callback delivery gives about
    its own token (``runtime/delivery.py``): a run may outlive any reasonable credential lifetime, and a cached
    token would turn a renewal into a 401 that reads like a permissions bug.
    """

    case_base_url: str
    service_token: str | None = None
    timeout_seconds: float = 5.0
    _opener: Callable[[urllib.request.Request, float], tuple[int, bytes]] | None = None

    def issue(self, *, run_id: str, case_id: str, input_revision: int) -> ToolCredential:
        path = CREDENTIAL_ROUTE.format(run_id=run_id)
        url = f"{self.case_base_url.rstrip('/')}{path}"
        body = json.dumps({"case_id": case_id, "input_revision": input_revision}).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")  # noqa: S310 - our own base URL
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        if self.service_token:
            # The route is on the /internal surface, which requires a service token: a credential must not be
            # obtainable by anything that merely reached the port.
            request.add_header("Authorization", f"Bearer {self.service_token}")
        try:
            if self._opener is not None:
                status, raw = self._opener(request, self.timeout_seconds)
            else:
                status, raw = _post(request, self.timeout_seconds)
        except urllib.error.HTTPError as error:
            raise CredentialUnavailableError(
                f"case refused the credential request for run {run_id} with {error.code}"
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise CredentialUnavailableError(f"case could not be reached for run {run_id}: {error}") from error
        if status != 200:
            raise CredentialUnavailableError(f"case answered {status} for the credential of run {run_id}")
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise CredentialUnavailableError("the credential response is not JSON") from error
        if not isinstance(payload, dict):
            raise CredentialUnavailableError("the credential response is not an object")
        return ToolCredential.from_response(payload)


def _post(request: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - our own base URL
        return response.status, response.read()


def credential_source(
    *,
    case_base_url: str | None,
    run_id: str,
    case_id: str | None,
    input_revision: int,
    service_token: str | None,
    static_token: str | None,
) -> Callable[[], str] | None:
    """The per-read source of the token the tools present, or ``None`` when there is none.

    Two ways to have a credential, and only one of them is the contract's:

    - **the run's own**, fetched from Case when ``case_base_url`` and ``case_id`` are known. This is the path a
      deployment takes, and the reason this module exists.
    - **a configured token**, when no case service has been named. Kept because a deployment that runs the tools
      against a stub, or against one of the Java services directly, has no Case to ask; it is a configuration
      answer rather than a silent fallback at run time (see the module docstring).

    ``static_token`` also serves as the identity to ask *with* when no dedicated ``service_token`` was supplied,
    because in a real deployment they are the same value and the distinction is one this function should not force
    a caller to spell out. The two are kept separate in :class:`HttpToolCredentialClient` so that "what we
    authenticate as" and "what we were granted" cannot be confused for one another.
    """
    identity = service_token or static_token
    if case_base_url and case_id:
        client = HttpToolCredentialClient(case_base_url=case_base_url, service_token=identity)

        def fetch() -> str:
            return client.issue(run_id=run_id, case_id=case_id, input_revision=input_revision).token

        return fetch
    if static_token:
        def configured() -> str:
            return static_token

        return configured
    return None


def credential_token_source(source: Callable[[], str] | None) -> Callable[[], str | None] | None:
    """Adapt a token source for a caller that wants "no credential" as ``None`` rather than as an absence.

    ``None`` in, ``None`` out — the same shape, so a caller that holds a source does not have to branch on
    whether one exists.
    """
    if source is None:
        return None

    def token() -> str | None:
        return source()

    return token
