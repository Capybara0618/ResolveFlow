"""Agent service HTTP surface.

The process is the Python service of docs/engineering.md:8, and it hosts two unrelated surfaces:

- **The run control plane** (C06.1): ``POST /internal/v1/runs`` and its read/cancel siblings. These are
  case-service's routes, authenticated with a service token, and they are the durable entry to an
  investigation (docs/core-contracts.md:38-41). C08.2 optionally starts one resident investigation thread;
  the request itself only queues the durable run, never waits for the model.
- **The refund provider stub** (C04.3): ``/provider/v1/*``. It is mounted in this process because the stub
  is a Python program (docs/engineering.md:75) and this is the Python service — not because the provider
  belongs to the Agent. Those routes carry no Agent identity, no scopes and no business data, and Commerce
  is their only caller. A fourth deployable would be a service docs/core-scope.md:30 explicitly does not
  count as core.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from resolveflow import __version__
from resolveflow.api.identity import (
    CASE_SERVICE,
    ISSUER,
    SERVICE_AUDIENCE,
    UNSET_SCOPE,
    ServiceTokenVerifier,
    TokenRefusedError,
    TokenScopeError,
    VerifiedServiceToken,
)
from resolveflow.provider_stub import NOT_FOUND, ProviderConflictError, RefundProviderStub, RefundResult
from resolveflow.runtime.callbacks import CallbackStore
from resolveflow.runtime.db import DEFAULT_SCHEMA, Database
from resolveflow.runtime.delivery import CallbackDelivery, DeliveryOutcome
from resolveflow.runtime.dispatch import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_INTERVAL_SECONDS,
    CallbackDeliveryLoop,
)
from resolveflow.runtime.factory import DeploymentConfig, build_investigation
from resolveflow.runtime.investigation import InvestigationLoop
from resolveflow.runtime.runs import (
    QUEUED,
    RunConflictError,
    RunIdentityMismatchError,
    RunNotFoundError,
    RunRefusedError,
    RunRequest,
    RunStore,
    VerifiedCaller,
)
from resolveflow.runtime.worker import RunWorker

SERVICE_NAME = "agent-service"

LOG = logging.getLogger(__name__)

PROVIDER_DB_ENV = "RESOLVEFLOW_PROVIDER_DB"

LAB_ROUTES_ENV = "RESOLVEFLOW_LAB_ROUTES"

DB_DSN_ENV = "RESOLVEFLOW_AGENT_DB"

JWT_SECRET_ENV = "RESOLVEFLOW_JWT_SECRET"  # noqa: S105 - the name of an environment variable, not a credential

#: The local demonstration secret, matching case-service's and commerce-service's ``application.yml``.
#: A deployment overrides it; the core profile is meant to be runnable and explainable. ruff reads the
#: assignment as a credential; it is a published local demo value, so the rule is waived for this line.
DEFAULT_JWT_SECRET = "resolveflow-core-demo-identity-secret"  # noqa: S105

DEFAULT_PROVIDER_DB = "tmp/provider/refund-provider.sqlite3"

#: Where the case service is, for the callback delivery worker (C06.3b). The local default matches a JVM
#: run of case-service; compose overrides it with the in-cluster address, the same way case-service's
#: ``AGENT_BASE_URL`` points back at this process.
CASE_BASE_URL_ENV = "RESOLVEFLOW_CASE_BASE_URL"

DEFAULT_CASE_BASE_URL = "http://127.0.0.1:8083"
INVESTIGATION_ENABLED_ENV = "RESOLVEFLOW_INVESTIGATION_ENABLED"


class HealthResponse(BaseModel):
    """Health payload. Deliberately minimal: it must not leak internal state."""

    status: str
    service: str
    version: str


class RunRequestContextShape(BaseModel):
    """The wire's ``context`` object. Nested exactly as the contract spells it."""

    merchant_id: str = Field(min_length=1, max_length=64)
    customer_id: str = Field(min_length=1, max_length=64)
    order_id: str
    line_id: str = Field(min_length=1, max_length=64)


class RunRequestPayloadShape(BaseModel):
    """The wire's ``request`` object."""

    description: str = Field(min_length=1, max_length=4000)
    requested_actions: list[str] = Field(min_length=1, max_length=3)
    evidence_refs: list[str] = Field(default_factory=list, max_length=64)


class PolicyManifestShape(BaseModel):
    """The pinned policy manifest the run will be decided under.

    ``merchant_id`` is required (C07.1, ``contracts/core/openapi-agent.yaml`` 1.2.0). It is required rather
    than defaulted from ``context.merchant_id`` — even though the two must agree — because the manifest is
    the *pin*: "these rules, for this merchant" is one fact, and a dispatcher that omitted the merchant
    would make the filter reconstructible only from a second member that nothing checks against the first.
    A dispatch from an older Case is therefore refused rather than accepted with the filter silently taken
    from elsewhere.
    """

    merchant_id: str = Field(min_length=1, max_length=64)
    bundle_ids: list[str] = Field(min_length=1, max_length=16)
    manifest_hash: str
    safety_epoch: int = Field(ge=0)


class RunRequestShape(BaseModel):
    """``RunRequest``: field set fixed by docs/core-contracts.md:60.

    Validation here is structural (types, lengths, required members). Whether the body is *acceptable* —
    an action core can perform, a subject the token was minted for, a run the database does not already
    have — is decided by the store, which is where those facts live.
    """

    run_id: str
    case_id: str
    input_revision: int = Field(ge=1)
    context: RunRequestContextShape
    request: RunRequestPayloadShape
    policy_manifest: PolicyManifestShape
    deadline_at: str
    traceparent: str | None = None


class RunAcceptedBody(BaseModel):
    """``RunAccepted``: the status of the committed row at accept time."""

    run_id: str
    status: str


class RunViewBody(BaseModel):
    """``RunView``: what case-service reconciles against."""

    run_id: str
    case_id: str
    input_revision: int
    status: str
    version: int
    callback_ids: list[str]
    result_summary: str | None = None


class CancelAckBody(BaseModel):
    """``CancelAck``: the status the run actually holds afterwards."""

    run_id: str
    status: str
    cancellation_requested: bool


class RefundRequestBody(BaseModel):
    """One refund request, in the shape the provider protocol declares.

    ``operation_id`` is the idempotency key and is required: a provider that invented the key itself could
    not be retried, because the retry would look like a new payment (docs/domain-model.md:51).
    """

    operation_id: str = Field(min_length=1, max_length=64)
    line_id: str = Field(min_length=1, max_length=64)
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)


class RefundResultBody(BaseModel):
    """What the provider believes about one refund, as read at one moment."""

    operation_id: str
    state: str
    provider_ref: str | None = None
    amount_minor: int | None = None
    currency: str | None = None
    reason_code: str | None = None
    settled_at: str | None = None
    visible_after: str | None = None
    responded: bool


class FaultBody(BaseModel):
    """One fault to arm, on the lab surface only."""

    fault: str
    operation_id: str | None = None
    reason_code: str | None = None
    visible_after: str | None = None


class SettleBody(BaseModel):
    """How an UNKNOWN operation is to be resolved."""

    state: str


class _FixedStore:
    """A store the caller already owns, presented with the same ``require()`` the holder offers."""

    def __init__(self, store: RunStore) -> None:
        self._store = store

    def require(self) -> RunStore:
        return self._store

    def ready(self) -> RunStore | None:
        """A store the caller supplied is usable by definition — there is nothing to open."""
        return self._store


class _RunStoreHolder:
    """The run store, opened on first use rather than when the app is built.

    Two things an operator wants from a service that owns state, and one thing a test needs:

    - **the tables exist by the time the routes are used** (``ensure()`` applies the append-only migrations);
    - **a database that cannot be reached is announced as 503**, not as a 500 from inside a query;
    - **building the app touches nothing, and so does starting it** (``ready()``). ``create_app()`` used to
      migrate immediately, which meant an offline unit test that merely instantiated the app wrote to the
      shared ``public`` schema — caught by
      ``test_run_store.py::test_the_schema_is_where_the_tables_are``. C06.3b's delivery worker is the second
      thing that starts with the app, and it must not reopen that hole: it asks ``ready()``, which reports
      what is there rather than causing something to be there.
    """

    def __init__(self, database: Database, *, migrate: bool) -> None:
        self.database = database
        self.migrate = migrate
        self._store: RunStore | None = None
        self._failure: Exception | None = None

    def ensure(self) -> None:
        """Open the store, migrating when configured to, and remember why it could not be opened."""
        if self._store is not None or self._failure is not None:
            return
        try:
            if self.migrate:
                self.database.migrations()
            else:
                with self.database.connection():
                    pass
        except Exception as failure:  # noqa: BLE001 - recorded, then reported as 503
            self._failure = failure
            LOG.warning("agent_db is not usable; run routes will answer 503: %s", failure)
            return
        self._store = RunStore(self.database)

    def require(self) -> RunStore:
        """The store, or the 503 that says it is not usable right now."""
        self.ensure()
        if self._failure is not None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"the run store is not available: {self._failure}",
            )
        if self._store is None:  # pragma: no cover - ensure() sets one of the two
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="the run store is not available",
            )
        return self._store

    def ready(self) -> RunStore | None:
        """The store if it is already usable, else ``None`` — asking causes nothing to happen.

        For the delivery worker, which may not be what opens this service's database. ``require()`` migrates
        on first use, and the worker ticks as soon as the app starts: calling it here meant that merely
        starting the Agent wrote the ``public`` schema, which is the exact regression
        ``test_the_schema_is_where_the_tables_are`` was written to catch. A worker that finds no store yet
        has nothing to deliver either — callbacks only exist once a run was dispatched, and dispatching goes
        through :meth:`require`.
        """
        return self._store


class _DeferredCallbackDelivery:
    """The callback delivery, resolved on the first tick rather than when the app is built.

    Two reasons it is deferred, and both were found rather than assumed:

    - ``_RunStoreHolder.require()`` raises the 503 it wants a *route* to answer with, which is the wrong thing
      to raise while a process is starting: an Agent that cannot reach ``agent_db`` must still start and
      report its health, exactly as it does for the run routes.
    - ``require()`` also **migrates on first use**, so a worker that called it would make "start the service"
      and "create the schema" the same act. They are not: the Agent is started by an operator and the tables
      are needed by whoever uses them. This asks :meth:`_RunStoreHolder.ready` instead, and a tick that finds
      no store yet delivers nothing — which is honest, because a callback can only exist after a run was
      dispatched, and dispatching is what opens the store.
    """

    def __init__(self, stores: _FixedStore | _RunStoreHolder, *, case_base_url: str, secret: str) -> None:
        self._stores = stores
        self._case_base_url = case_base_url
        self._secret = secret
        self._delivery: CallbackDelivery | None = None

    def deliver_due(self, *, now: dt.datetime | None = None, limit: int = 50) -> list[DeliveryOutcome]:
        if self._delivery is None:
            store = self._stores.ready()
            if store is None:
                # Nothing has needed the database yet, so there is nothing queued to send. Not a warning:
                # this is the normal state of a freshly started Agent that has not been asked for a run.
                LOG.debug("the callback delivery loop is waiting for the run store to be opened")
                return []
            self._delivery = CallbackDelivery(
                CallbackStore(store.database),
                case_base_url=self._case_base_url,
                secret=self._secret,
            )
        return self._delivery.deliver_due(now=now, limit=limit)


def _app_of(source: FastAPI | Request) -> FastAPI:
    """The app behind either an app or a request.

    Both helpers below are called with whichever one the caller has: routes hold a ``Request``, while
    ``tests/unit/test_provider_stub_http.py`` holds the app and passes it directly (``provider_of(http.app)``).
    Accepting both is deliberate: taking the wrong one used to be a silent bug — a ``Request`` has a
    ``.state`` too, so ``run_store_of(request)`` read the request's empty state and failed with an
    ``AttributeError`` far from the mistake. This function is the one place that tells them apart.
    """
    return source.app if isinstance(source, Request) else source


def provider_of(source: FastAPI | Request) -> RefundProviderStub:
    """The stub this app serves, so an integration test can inspect or arm it without a control endpoint.

    The fault surface stays in-process on purpose: ``inject``/``clear_faults`` are lab tools, and a network
    route that could make the provider misbehave would be a second way to change what the money path sees
    (docs/engineering.md:77 — 故障路由仅lab且受控).
    """
    provider: RefundProviderStub = _app_of(source).state.provider
    return provider


def run_store_of(source: FastAPI | Request) -> RunStore:
    """The run store, or a 503 that says the store is not usable right now.

    A database that is down is an availability problem, not a refusal: a run that was never written must
    not be answered with something that looks like a decision about it. Whether the store can be opened is
    the holder's question, asked here on first use rather than when the app was built.
    """
    holder: _RunStoreHolder | _FixedStore = _app_of(source).state.run_store
    return holder.require()


def service_token_of(
    request: Request, *, required_scope: str | None | object = UNSET_SCOPE
) -> VerifiedServiceToken:
    """Verify the presented service token, mapping each refusal to the status the contract declares.

    A missing or invalid token is 401; a valid token that was not minted for dispatching runs is 403 —
    the same split the case-service filter makes between "who are you" and "you may not".

    ``required_scope`` is what *this route* needs and defaults to the dispatch scope, so the run routes read the
    same as before while a route that requires something else (or nothing) says so at its own call site. It is a
    per-call argument rather than a property of the shared verifier because one verifier serves every route: a
    single construction-time scope described one route and silently mis-described the rest.
    """
    verifier: ServiceTokenVerifier = request.app.state.token_verifier
    try:
        return verifier.verify(request.headers.get("authorization"), required_scope=required_scope)
    except TokenScopeError as refusal:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(refusal)) from refusal
    except TokenRefusedError as refusal:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(refusal)) from refusal


def create_app(
    *,
    provider_db: str | Path | None = None,
    provider: RefundProviderStub | None = None,
    lab_routes: bool | None = None,
    agent_dsn: str | None = None,
    agent_schema: str = DEFAULT_SCHEMA,
    jwt_secret: str | None = None,
    run_store: RunStore | None = None,
    migrate: bool = True,
    delivery_loop: bool | None = None,
    case_base_url: str | None = None,
    delivery_interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    delivery_batch_size: int = DEFAULT_BATCH_SIZE,
    worker_loop: bool | None = None,
    worker_interval_seconds: float = 1.0,
) -> FastAPI:
    """Build the service app.

    ``provider_db``/``provider``/``lab_routes`` configure the provider stub's surface (a test passes a
    temporary file). ``agent_dsn``/``agent_schema`` configure the run store; ``agent_schema`` exists so a
    test can have the run tables to itself (see :mod:`resolveflow.runtime.db`), and production leaves it at
    ``public``. ``run_store``/``migrate`` let a test supply an already-migrated store, or take the
    migrations out of the startup path to assert what happens when the database is not there.

    ``delivery_loop`` controls the resident callback delivery worker (C06.3b). It is **on by default** — the
    Agent is the process that owns the outbox, and an outbox nobody drains is a callback that never arrives.
    A test that wants to drive delivery itself passes ``delivery_loop=False``, and one that wants to see the
    worker's traffic either starts the loop against a real case service or calls
    ``CallbackDeliveryLoop.run_once``. ``case_base_url`` is where the case service is.

    Investigation requires ``worker_loop=True`` or ``RESOLVEFLOW_INVESTIGATION_ENABLED=1`` and explicit model
    configuration. Enabled startup opens the run store to consume preexisting QUEUED runs; disabled startup
    stays lazy. Shutdown joins the investigator before closing this app's database pool.

    Building the app performs no database I/O: the store is opened by the first run request that needs it
    (see :class:`_RunStoreHolder`), so an offline test can construct the app without touching a database.
    The delivery loop does not change that: its first tick is what asks for a connection, and a tick that
    cannot connect is logged and retried rather than failing startup.
    """
    database = Path(provider_db or os.environ.get(PROVIDER_DB_ENV) or DEFAULT_PROVIDER_DB)
    lab_enabled = lab_routes if lab_routes is not None else os.environ.get(LAB_ROUTES_ENV) == "1"
    secret = jwt_secret or os.environ.get(JWT_SECRET_ENV) or DEFAULT_JWT_SECRET
    delivery_loop_enabled = delivery_loop if delivery_loop is not None else True
    worker_enabled = worker_loop if worker_loop is not None else os.environ.get(INVESTIGATION_ENABLED_ENV) == "1"
    case_url = case_base_url or os.environ.get(CASE_BASE_URL_ENV) or DEFAULT_CASE_BASE_URL

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.provider = provider if provider is not None else RefundProviderStub(database)
        app.state.token_verifier = ServiceTokenVerifier(secret)
        holder: _RunStoreHolder | None = None
        if run_store is not None:
            # A caller that already owns a store (the integration tests do) wants exactly that store.
            app.state.run_store = _FixedStore(run_store)
        else:
            holder = _RunStoreHolder(Database(agent_dsn, schema=agent_schema), migrate=migrate)
            app.state.run_store = holder
        # C06.3b: the callback outbox is drained by this process rather than by a human calling
        # deliver_due. Started after the store is bound and stopped before it is closed, so a tick in
        # flight finishes its write instead of racing the shutdown.
        loop: CallbackDeliveryLoop | None = None
        if delivery_loop_enabled:
            loop = CallbackDeliveryLoop(
                _DeferredCallbackDelivery(
                    app.state.run_store, case_base_url=case_url, secret=secret
                ),
                interval_seconds=delivery_interval_seconds,
                batch_size=delivery_batch_size,
            )
        app.state.delivery_loop = loop
        investigation_loop: InvestigationLoop | None = None
        app.state.investigation_loop = None
        try:
            if worker_enabled:
                if run_store is not None:
                    worker_database = run_store.database
                else:
                    assert holder is not None
                    worker_database = holder.database
                investigate = build_investigation(database=worker_database, config=DeploymentConfig.from_environ())
                # Enabling investigation explicitly opts into opening/migrating the store at startup, including
                # QUEUED records from before this process started. Disabled apps retain lazy database access.
                app.state.run_store.require()
                worker = RunWorker(worker_database, investigate=investigate)
                investigation_loop = InvestigationLoop(worker.run_once, interval_seconds=worker_interval_seconds)
                app.state.investigation_loop = investigation_loop
                investigation_loop.start()
            if loop is not None:
                loop.start()
            yield
        finally:
            if investigation_loop is not None:
                await asyncio.to_thread(investigation_loop.close)
            if loop is not None:
                loop.close()
            if provider is None:
                app.state.provider.close()
            if holder is not None:
                holder.database.close()

    app = FastAPI(
        title="ResolveFlow Agent",
        version=__version__,
        # The Agent has no public surface; every route is internal and scoped.
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="UP", service=SERVICE_NAME, version=__version__)

    # --- The run control plane (C06.1) ------------------------------------------------

    @app.post("/internal/v1/runs", response_model=RunAcceptedBody, status_code=status.HTTP_202_ACCEPTED)
    async def create_run(body: RunRequestShape, request: Request, response: Response) -> RunAcceptedBody:
        """Accept a durable investigation run.

        The response is only sent after the row is committed, so a caller that got a 202 can rely on it
        (docs/core-contracts.md:38). Idempotent on ``run_id``; the same key with a different body is 409.
        """
        token = service_token_of(request)
        store = run_store_of(request)
        refusal = _dispatch_refusal(token)
        if refusal is not None:
            raise refusal
        try:
            accepted = store.queue(_as_store_request(body), caller=_as_caller(token))
        except RunConflictError as conflict:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(conflict)) from conflict
        except RunIdentityMismatchError as mismatch:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(mismatch)
            ) from mismatch
        except RunRefusedError as refused:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(refused)) from refused
        # The canonical URL of the resource that now exists (contracts/core/openapi-agent.yaml:91).
        response.headers["Location"] = f"/internal/v1/runs/{accepted.run_id}"
        return RunAcceptedBody(run_id=accepted.run_id, status=accepted.status)

    @app.get("/internal/v1/runs/{run_id}", response_model=RunViewBody)
    async def read_run(run_id: str, request: Request) -> RunViewBody:
        """Run status for case-service reconciliation. Never raw model text, never credentials."""
        service_token_of(request)
        store = run_store_of(request)
        try:
            view = store.read(run_id)
        except RunNotFoundError as missing:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(missing)) from missing
        return RunViewBody(
            run_id=view.run_id,
            case_id=view.case_id,
            input_revision=view.input_revision,
            status=view.status,
            version=view.version,
            callback_ids=list(view.callback_ids),
            result_summary=view.result_summary,
        )

    @app.post("/internal/v1/runs/{run_id}/cancel", response_model=CancelAckBody)
    async def cancel_run(run_id: str, request: Request) -> CancelAckBody:
        """Mark a run cancelled. This stops further investigation; it does not un-send a model request.

        That the answer is the status the run *actually* holds is the whole point of ``CancelAck``
        (contracts/core/openapi-agent.yaml:528).
        """
        service_token_of(request)
        store = run_store_of(request)
        try:
            ack = store.cancel(run_id)
        except RunNotFoundError as missing:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(missing)) from missing
        return CancelAckBody(
            run_id=ack.run_id,
            status=ack.status,
            cancellation_requested=ack.cancellation_requested,
        )

    # --- The refund provider stub (C04.3) ---------------------------------------------

    @app.post("/provider/v1/refunds", response_model=RefundResultBody)
    async def request_refund(body: RefundRequestBody, request: Request) -> RefundResultBody:
        """Ask for one refund. Repeating the same request is a repeat, not a second payment."""
        try:
            result = provider_of(request).request_refund(
                operation_id=body.operation_id,
                line_id=body.line_id,
                amount_minor=body.amount_minor,
                currency=body.currency,
            )
        except ProviderConflictError as conflict:
            # 409 rather than 200 with the stored result: the caller sent a different payment under a key
            # that is already spent, and answering it as a success would hide that (docs/domain-model.md:11).
            raise HTTPException(status_code=409, detail=str(conflict)) from conflict
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _as_body(result)

    @app.get("/provider/v1/refunds/{key}", response_model=RefundResultBody)
    async def query_refund(key: str, request: Request) -> RefundResultBody:
        """Read what the provider currently believes, by operation id or by provider reference."""
        result = provider_of(request).query_refund(key)
        if result.state == NOT_FOUND:
            # 404 is the honest answer for "this provider has nothing", and it is exactly why a
            # delayed-visibility provider must not be read as "the refund did not happen"
            # (fixtures/provider/README.md §2).
            raise HTTPException(status_code=404, detail=f"{key}: no such refund")
        return _as_body(result)

    @app.exception_handler(psycopg.OperationalError)
    async def store_unavailable(request: Request, failure: psycopg.OperationalError) -> JSONResponse:
        """The database went away while a request was in flight.

        Opening the store already reports an unavailable database; this catches the case where the
        connection is lost afterwards, so the caller still gets the availability answer the contract
        declares instead of a 500 that looks like a bug in this service.
        """
        LOG.warning("agent_db became unavailable during a request: %s", failure)
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(failure)})

    if lab_enabled:

        @app.post("/provider/v1/_lab/faults", status_code=204)
        async def arm_fault(body: FaultBody, request: Request) -> None:
            """Arm one fault for one operation (or for every operation when the id is omitted)."""
            try:
                provider_of(request).inject(
                    body.fault,
                    operation_id=body.operation_id,
                    reason_code=body.reason_code,
                    visible_after=dt.datetime.fromisoformat(body.visible_after) if body.visible_after else None,
                )
            except ValueError as error:
                # An unknown fault name is refused, not ignored: a lab tool that silently does nothing would
                # let a fault test pass because no fault was armed.
                raise HTTPException(status_code=422, detail=str(error)) from error

        @app.delete("/provider/v1/_lab/faults", status_code=204)
        async def clear_faults(request: Request) -> None:
            provider_of(request).clear_faults()

        @app.post("/provider/v1/_lab/operations/{operation_id}/settle", response_model=RefundResultBody)
        async def settle(operation_id: str, body: SettleBody, request: Request) -> RefundResultBody:
            """Resolve an UNKNOWN by hand, the way a provider's reconciliation window eventually does."""
            try:
                return _as_body(provider_of(request).settle(operation_id, state=body.state))
            except KeyError as missing:
                raise HTTPException(status_code=404, detail=f"{operation_id}: no such refund") from missing
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error

    return app


def _dispatch_refusal(token: VerifiedServiceToken) -> HTTPException | None:
    """What this surface refuses before the record is even consulted.

    Two refusals, both about the token rather than the body:

    - **the subject must be the case service.** A service token is not a user token and carries no role; the
      only identity this route has is the subject, so "not case-service" is 403 rather than a body mistake.
    - **the token must say whose line it is for.** docs/core-contracts.md:60 requires the body to agree with
      the token, and that is not checkable against a token that forgot its subjects — so such a token (a
      plain ``issueServiceToken`` without the run context) is refused with 422 rather than accepted with the
      agreement silently skipped. Silently skipping it is the failure mode worth naming: it would look like
      a working dispatch while the check that prevents investigating someone else's order had been off.
    """
    if token.subject != CASE_SERVICE:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"the run dispatcher is {CASE_SERVICE}; this token's subject is {token.subject}",
        )
    missing = [name for name in ("merchant_id", "customer_id") if getattr(token, name) is None]
    if missing:
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "the run dispatch token must carry the run context it was minted for; missing " + ", ".join(missing)
            ),
        )
    return None


def _as_caller(token: VerifiedServiceToken) -> VerifiedCaller:
    """The verified identity, in the shape the store checks the body against."""
    return VerifiedCaller(
        service=token.subject,
        scope=token.scope,
        merchant_id=token.merchant_id,
        customer_id=token.customer_id,
    )


def _as_store_request(body: RunRequestShape) -> RunRequest:
    """The wire body, in the flat shape the record stores."""
    return RunRequest(
        run_id=body.run_id,
        case_id=body.case_id,
        input_revision=body.input_revision,
        merchant_id=body.context.merchant_id,
        customer_id=body.context.customer_id,
        order_id=body.context.order_id,
        line_id=body.context.line_id,
        description=body.request.description,
        requested_actions=tuple(body.request.requested_actions),
        evidence_refs=tuple(body.request.evidence_refs),
        policy_manifest={
            "merchant_id": body.policy_manifest.merchant_id,
            "bundle_ids": list(body.policy_manifest.bundle_ids),
            "manifest_hash": body.policy_manifest.manifest_hash,
            "safety_epoch": body.policy_manifest.safety_epoch,
        },
        deadline_at=body.deadline_at,
        traceparent=body.traceparent,
    )


def _as_body(result: RefundResult) -> RefundResultBody:
    return RefundResultBody(
        operation_id=result.operation_id,
        state=result.state,
        provider_ref=result.provider_ref,
        amount_minor=result.amount_minor,
        currency=result.currency,
        reason_code=result.reason_code,
        settled_at=result.settled_at.isoformat() if result.settled_at else None,
        visible_after=result.visible_after.isoformat() if result.visible_after else None,
        responded=result.responded,
    )


#: The identity constants this module re-exports for a reader who greps here first.
SERVICE_TOKEN_ISSUER = ISSUER
SERVICE_TOKEN_AUDIENCE = SERVICE_AUDIENCE
QUEUED_STATUS = QUEUED


def __getattr__(name: str) -> object:
    """Build the service app on first use, so importing this module has no side effects.

    The entry point stays ``resolveflow.api.app:app`` (scripts/verify.ps1 runs
    ``uvicorn resolveflow.api.app:app``, and tests/unit/test_contracts_core_startup.py asserts that exact
    command), but the app is no longer constructed at import time. It used to be, and that made an innocent
    ``import resolveflow.api.app`` run the migrations against whatever schema the environment pointed at —
    in a test run that was ``public``, which is exactly what
    ``test_run_store.py::test_the_schema_is_where_the_tables_are`` catches. Building the app now happens
    when something actually asks for it (uvicorn at startup, or a test calling ``create_app`` itself).
    """
    if name == "app":
        return create_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
