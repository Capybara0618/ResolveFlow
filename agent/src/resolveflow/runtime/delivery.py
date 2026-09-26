"""Delivering a queued callback to the case service, and recording what happened.

The outbox (``callbacks.py``) made a callback durable. This module is the other half: it takes the rows
that are due and tries to hand them over, then writes down what the case service said. Three rules are the
whole point:

- **the row is the source of truth, not the attempt.** A delivery that fails leaves the callback queued
  with a reason and a time; nothing is deleted because a network call went wrong.
- **the answer decides whether to retry.** ``ACCEPTED``/``DUPLICATE``/``STALE`` all mean the case service
  has the callback, so the row finishes. A 5xx, a timeout or a connection that never opened means it does
  not yet, so the row stays queued with a scheduled retry.
- **a refusal that cannot change is not retried.** A wrong service token, an unknown case, or a payload
  the contract refuses will be just as wrong in five minutes. Retrying forever would look like a healthy
  queue that never drains, and it would hide an Agent bug behind what looks like a flaky case service.

The transport is injected (``post=``) rather than hard-wired, so the rules above are tested against real
database rows without needing a running Java service; the default transport is plain ``urllib``
(docs/agent-harness.md:27 — 外部网络调用不放长事务, which is why each attempt is its own short
transaction and no connection is held across the call).
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from resolveflow.api.identity import mint_service_token
from resolveflow.runtime.callbacks import CallbackRecord, CallbackStore
from resolveflow.runtime.runs import RunStore

__all__ = [
    "AGENT_SERVICE",
    "DEFAULT_TIMEOUT_SECONDS",
    "CallbackDelivery",
    "DeliveryOutcome",
    "DeliveryRefusedError",
    "DeliveryResult",
    "DeliveryUnavailableError",
    "post_delivery",
]

#: The subject the Agent presents. Case's ``/internal/**`` filter accepts any service-audience token, and
#: the Java tests mint theirs as ``agent-service`` (AgentCallbackApiTest:76), so the two ends agree.
AGENT_SERVICE = "agent-service"

# The callback token is minted with ``scope=None`` (see ``deliver_due``): Case's callback route requires no
# scope — that is a decision recorded in ``ServiceTokenFilter.requiredScope``, not an absence of one — so the
# Agent names none rather than naming a scope it would not be checked against. A `CALLBACK_SCOPE = ""` constant
# used to sit here saying the same thing while being referenced nowhere and reading as "the callback scope is
# the empty string"; deleted rather than left as an unused second answer to the same question.

DEFAULT_TIMEOUT_SECONDS = 5.0

#: The longest a retry is ever postponed. A case service that is down should be retried patiently, but a
#: callback that is hours late is worse than one retried a few extra times.
MAX_RETRY_SECONDS = 300


class DeliveryRefusedError(Exception):
    """The case service refused this delivery and will refuse it again.

    Raises for 401/403/404/409/422: nothing this Agent can wait out. A ``LookupError``-style permanent
    failure, so the row is recorded as DEAD rather than left in the retry queue.
    """


class DeliveryUnavailableError(Exception):
    """The delivery did not happen for a reason that a later attempt can change."""


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """What the case service answered: its disposition, and the case version only when it made one."""

    disposition: str
    case_version: int | None = None


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """One delivery attempt, as recorded.

    ``status`` is the row's status *after* the attempt, which is not the same thing as the disposition: a
    failed attempt leaves the row PENDING, a refusal leaves it DEAD, and only the case service's own answer
    produces DELIVERED.
    """

    callback_id: str
    status: str
    disposition: str | None = None
    case_version: int | None = None
    error: str | None = None
    retry_at: dt.datetime | None = None

    #: True when a stored callback was actually handed to the transport (injected posters record calls).
    attempted: bool = True


def callback_delivery(
    store: CallbackStore,
    *,
    case_base_url: str,
    secret: str,
    post: Callable[..., DeliveryResult] | None = None,
    ttl_seconds: int = 300,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> CallbackDelivery:
    """The delivery loop over one outbox, with the transport named once."""
    return CallbackDelivery(
        store,
        case_base_url=case_base_url,
        secret=secret,
        post=post or _urllib_post,
        ttl_seconds=ttl_seconds,
        timeout=timeout,
    )


class CallbackDelivery:
    """Sends the outbox's due rows to the case service and records each answer."""

    def __init__(
        self,
        store: CallbackStore,
        *,
        case_base_url: str,
        secret: str,
        post: Callable[..., DeliveryResult] | None = None,
        ttl_seconds: int = 300,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._store = store
        self._base_url = case_base_url.rstrip("/")
        self._secret = secret
        self._post = post or _urllib_post
        self._ttl_seconds = ttl_seconds
        self._timeout = timeout

    @property
    def store(self) -> CallbackStore:
        return self._store

    def deliver_due(self, *, now: dt.datetime | None = None, limit: int = 50) -> list[DeliveryOutcome]:
        """Deliver every callback that is due, oldest first, and return one outcome per attempt.

        The list is fetched once: a callback that fails is rescheduled into the future, so it cannot be
        picked up again by this same pass, and the loop is therefore bounded by ``limit`` rather than by
        how unreachable the case service is.
        """
        moment = now or dt.datetime.now(dt.UTC)
        outcomes: list[DeliveryOutcome] = []
        for record in self._store.pending(now=moment, limit=limit):
            outcomes.append(self.deliver_one(record))
        return outcomes

    def deliver_one(self, record: CallbackRecord) -> DeliveryOutcome:
        """Attempt one callback and record exactly one of: delivered, retry later, or dead."""
        try:
            result = self._post(
                self._base_url,
                record,
                secret=self._secret,
                ttl_seconds=self._ttl_seconds,
                timeout=self._timeout,
            )
        except DeliveryRefusedError as refusal:
            # Permanent: kept as history with its reason, and no longer queued work.
            dead = self._store.record_dead(record.callback_id, error=str(refusal))
            return DeliveryOutcome(
                callback_id=record.callback_id,
                status=dead.status,
                error=str(refusal),
            )
        except DeliveryUnavailableError as unavailable:
            delay = retry_delay_seconds(record.attempts + 1)
            failed = self._store.record_failure(
                record.callback_id,
                error=str(unavailable),
                retry_after_seconds=delay,
            )
            return DeliveryOutcome(
                callback_id=record.callback_id,
                status=failed.status,
                error=str(unavailable),
                retry_at=failed.next_attempt_at,
            )
        # The answer and the run status it implies commit together (AGENTS.md: 业务结果和本地事件同事务): a
        # callback marked delivered while its run still says CALLBACK_PENDING is a run waiting for an answer that
        # already arrived. The run is named by the callback's own row, never by a caller.
        with self._store.transaction() as connection:
            delivered = self._store.record_delivery(
                record.callback_id, disposition=result.disposition, connection=connection
            )
            RunStore(self._store.database).apply_callback_disposition(
                record.run_id,
                kind=record.kind,
                disposition=result.disposition,
                connection=connection,
            )
        return DeliveryOutcome(
            callback_id=record.callback_id,
            status=delivered.status,
            disposition=delivered.disposition,
            case_version=result.case_version,
        )


def retry_delay_seconds(attempts: int) -> int:
    """Exponential backoff with a ceiling: 5s, 10s, 20s … up to ``MAX_RETRY_SECONDS``.

    Counted from the attempt that just failed, so the first delay is short (the case service may simply be
    restarting) and a long outage is not hammered.
    """
    exponent = max(0, attempts - 1)
    return int(min(5 * (2**exponent), MAX_RETRY_SECONDS))


#: Statuses that will never change by trying again: the token is wrong, the case is unknown, or the
#: contract refuses the body (contracts/core/openapi-case.yaml:804-812).
_PERMANENT_STATUSES = frozenset({401, 403, 404, 409, 422})

#: ``disposition`` values the case service may answer with (contracts/core/openapi-case.yaml:1282).
_DISPOSITIONS = frozenset({"ACCEPTED", "DUPLICATE", "STALE"})


def post_delivery(
    base_url: str,
    record: Any,
    *,
    secret: str,
    ttl_seconds: int,
    timeout: float,
    transport: Callable[[Any, float], Any] | None = None,
) -> DeliveryResult:
    """Send one callback and turn the answer into a result or a stated failure.

    The token is minted **per attempt** rather than cached: a long outage outlives any reasonable token
    lifetime, and a cached token would turn a retry into a 401 that looks like a permissions bug.
    """
    body = {
        "callback_id": record.callback_id,
        "run_id": record.run_id,
        "input_revision": record.input_revision,
        "kind": record.kind,
        "payload": record.payload,
        "traceparent": record.traceparent,
    }
    url = f"{base_url.rstrip('/')}/internal/v1/cases/{urllib.parse.quote(str(record.case_id))}/agent-callbacks"
    token = mint_service_token(AGENT_SERVICE, secret, scope=None, ttl_seconds=ttl_seconds)
    request = urllib.request.Request(  # noqa: S310 - the scheme is fixed by the caller, not by input
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    send = transport or _default_transport
    try:
        with send(request, timeout) as response:
            status = int(response.status)
            raw = response.read()
    except urllib.error.HTTPError as error:
        # HTTPError is also a response; read it so the reason is stated rather than guessed.
        detail = _error_detail(error)
        if error.code in _PERMANENT_STATUSES:
            raise DeliveryRefusedError(f"{error.code}: {detail}") from error
        raise DeliveryUnavailableError(f"{error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise DeliveryUnavailableError(f"the case service could not be reached: {error}") from error

    if status != 200:
        detail = raw.decode("utf-8", "replace")[:400]
        if status in _PERMANENT_STATUSES:
            raise DeliveryRefusedError(f"{status}: {detail}")
        raise DeliveryUnavailableError(f"{status}: {detail}")

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        # An answer we cannot read must not be recorded as delivered: that would lose the callback with
        # nothing to show for it.
        raise DeliveryUnavailableError(f"the case service answered 200 with unreadable JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise DeliveryUnavailableError("the case service answered 200 with something that is not an object")
    disposition = parsed.get("disposition")
    if disposition not in _DISPOSITIONS:
        raise DeliveryUnavailableError(f"the case service answered 200 without a disposition: {parsed!r}")
    version = parsed.get("case_version")
    return DeliveryResult(
        disposition=str(disposition),
        case_version=int(version) if isinstance(version, int) and not isinstance(version, bool) else None,
    )


def _default_transport(request: Any, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - the URL is built above, not user input


def _error_detail(error: urllib.error.HTTPError) -> str:
    try:
        return error.read().decode("utf-8", "replace")[:400]
    except Exception:  # noqa: BLE001 - the body is a nicety; the status is the fact
        return error.reason if error.reason else "no body"


def _urllib_post(
    base_url: str,
    record: Any,
    *,
    secret: str,
    ttl_seconds: int,
    timeout: float,
) -> DeliveryResult:
    """The real transport, in the shape ``callback_delivery`` expects."""
    return post_delivery(
        base_url,
        record,
        secret=secret,
        ttl_seconds=ttl_seconds,
        timeout=timeout,
    )