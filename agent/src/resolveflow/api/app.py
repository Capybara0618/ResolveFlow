"""Agent service HTTP surface.

T01 establishes the process and its health contract only. The durable task control
plane (POST /internal/v1/runs, run tokens, leases) is T17, and the callback
outbox that talks back to case-service is T21. Nothing here owns business data:
the Agent reads business facts through scoped, read-only tools (T18).
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from resolveflow import __version__

SERVICE_NAME = "agent-service"


class HealthResponse(BaseModel):
    """Health payload. Deliberately minimal: it must not leak internal state."""

    status: str
    service: str
    version: str


def create_app() -> FastAPI:
    app = FastAPI(
        title="ResolveFlow Agent",
        version=__version__,
        # The Agent has no public surface; every route is internal and scoped.
        docs_url=None,
        redoc_url=None,
    )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="UP", service=SERVICE_NAME, version=__version__)

    return app


app = create_app()