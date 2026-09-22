"""Agent service HTTP surface.

T01 establishes the process and its health contract only. The durable task control
plane (POST /internal/v1/runs, run tokens, leases) is T17, and the callback
outbox that talks back to case-service is T21. Nothing here owns business data:
the Agent reads business facts through scoped, read-only tools (T18).

C04.3 adds the refund provider stub's HTTP surface. It is mounted in this process because the stub is a
Python program (docs/engineering.md:75) and this is the Python service — not because the provider belongs to
the Agent. The routes carry no Agent identity, no scopes and no business data, and Commerce is their only
caller. A fourth deployable would be a service docs/core-scope.md:30 explicitly does not count as core.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from resolveflow import __version__
from resolveflow.provider_stub import NOT_FOUND, ProviderConflictError, RefundProviderStub, RefundResult

SERVICE_NAME = "agent-service"

PROVIDER_DB_ENV = "RESOLVEFLOW_PROVIDER_DB"

LAB_ROUTES_ENV = "RESOLVEFLOW_LAB_ROUTES"

DEFAULT_PROVIDER_DB = "tmp/provider/refund-provider.sqlite3"


class HealthResponse(BaseModel):
    """Health payload. Deliberately minimal: it must not leak internal state."""

    status: str
    service: str
    version: str


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


def provider_of(app: FastAPI) -> RefundProviderStub:
    """The stub this app serves, so an integration test can inspect or arm it without a control endpoint.

    The fault surface stays in-process on purpose: ``inject``/``clear_faults`` are lab tools, and a network
    route that could make the provider misbehave would be a second way to change what the money path sees
    (docs/engineering.md:77 — 故障路由仅lab且受控).
    """
    provider: RefundProviderStub = app.state.provider
    return provider


def create_app(
    *,
    provider_db: str | Path | None = None,
    provider: RefundProviderStub | None = None,
    lab_routes: bool | None = None,
) -> FastAPI:
    """Build the service app, optionally over a given provider store (a test passes a temporary file).

    ``lab_routes`` adds the fault-injection surface (``/provider/v1/_lab/*``). It is off unless asked for, so
    the deployed process has no route that can make the provider misbehave; a separate test process, which
    cannot reach into this one's memory, turns it on explicitly (docs/engineering.md:77 — 故障路由仅lab且受控).
    """
    database = Path(provider_db or os.environ.get(PROVIDER_DB_ENV) or DEFAULT_PROVIDER_DB)
    lab_enabled = lab_routes if lab_routes is not None else os.environ.get(LAB_ROUTES_ENV) == "1"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.provider = provider if provider is not None else RefundProviderStub(database)
        try:
            yield
        finally:
            if provider is None:
                app.state.provider.close()

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

    @app.post("/provider/v1/refunds", response_model=RefundResultBody)
    async def request_refund(body: RefundRequestBody, request: Request) -> RefundResultBody:
        """Ask for one refund. Repeating the same request is a repeat, not a second payment."""
        try:
            result = provider_of(request.app).request_refund(
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
        result = provider_of(request.app).query_refund(key)
        if result.state == NOT_FOUND:
            # 404 is the honest answer for "this provider has nothing", and it is exactly why a
            # delayed-visibility provider must not be read as "the refund did not happen"
            # (fixtures/provider/README.md §2).
            raise HTTPException(status_code=404, detail=f"{key}: no such refund")
        return _as_body(result)

    if lab_enabled:

        @app.post("/provider/v1/_lab/faults", status_code=204)
        async def arm_fault(body: FaultBody, request: Request) -> None:
            """Arm one fault for one operation (or for every operation when the id is omitted)."""
            try:
                provider_of(request.app).inject(
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
            provider_of(request.app).clear_faults()

        @app.post("/provider/v1/_lab/operations/{operation_id}/settle", response_model=RefundResultBody)
        async def settle(operation_id: str, body: SettleBody, request: Request) -> RefundResultBody:
            """Resolve an UNKNOWN by hand, the way a provider's reconciliation window eventually does."""
            try:
                return _as_body(provider_of(request.app).settle(operation_id, state=body.state))
            except KeyError as missing:
                raise HTTPException(status_code=404, detail=f"{operation_id}: no such refund") from missing
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error

    return app


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


app = create_app()
