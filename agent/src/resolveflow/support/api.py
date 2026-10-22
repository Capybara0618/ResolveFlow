from __future__ import annotations

from typing import Any, cast

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, SecretStr

from resolveflow.runtime.factory import DeploymentConfig, DeploymentRefusedError
from resolveflow.support.protocol import SupportFailure, SupportInput, SupportResult
from resolveflow.support.service import SupportRuntime


class SupportDispatch(SupportInput):
    tool_token: SecretStr = Field(min_length=1, max_length=8192)


def router_for(authenticate: Any, run_store: Any) -> APIRouter:
    router = APIRouter()

    @router.post("/internal/v1/support-runs", response_model=SupportResult)
    def execute(body: SupportDispatch, request: Request) -> dict[str, Any]:
        identity = authenticate(request, required_scope="support:run")
        if (
            identity.subject != "case-service"
            or identity.merchant_id != body.merchant_id
            or identity.customer_id != body.customer_id
        ):
            raise HTTPException(403, detail="support identity does not match the bound dispatch")
        try:
            runtime = request.app.state.support_runtime
            if runtime is None:
                runtime = SupportRuntime(
                    run_store(request).database,
                    DeploymentConfig.from_environ(),
                    embeddings=request.app.state.support_embeddings,
                    architecture=request.app.state.support_architecture,
                )
            context = SupportInput.model_validate(body.model_dump(exclude={"tool_token"}))
            return cast(dict[str, Any], runtime.run(context, body.tool_token.get_secret_value()))
        except SupportFailure as error:
            raise HTTPException(409, detail=error.reason) from error
        except DeploymentRefusedError as error:
            raise HTTPException(503, detail="consultation model not configured") from error
        except (psycopg.Error, OSError, ValueError) as error:
            raise HTTPException(503, detail="consultation runtime unavailable") from error

    return router
