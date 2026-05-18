from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.models import router as models_router
from app.api.v1.node_types import router as node_types_router
from app.api.v1.runs import router as runs_router
from app.api.v1.secrets import router as secrets_router
from app.api.v1.tools import router as tools_router
from app.api.v1.workflows import router as workflows_router
from app.core.config import get_settings
from app.infra.db.session import engine

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "agent-workflow-api",
        "version": "0.1.0",
    }


@router.get("/ready")
async def ready() -> JSONResponse:
    settings = get_settings()
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - diagnostic endpoint
        checks["database"] = f"error:{exc.__class__.__name__}"

    try:
        client = redis.from_url(settings.redis_url)
        await client.ping()
        await client.aclose()
        checks["redis"] = "ok"
    except Exception as exc:  # pragma: no cover - diagnostic endpoint
        checks["redis"] = f"error:{exc.__class__.__name__}"

    checks["encryption_key"] = (
        "ok" if len(settings.secret_encryption_key) >= 32 else "error:too_short"
    )
    checks["default_model_provider"] = "ok" if settings.default_model_provider else "error:empty"

    is_ready = all(value == "ok" for value in checks.values())
    payload = {"status": "ready" if is_ready else "not_ready", "checks": checks}
    return JSONResponse(
        payload,
        status_code=status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


router.include_router(workflows_router)
router.include_router(runs_router)
router.include_router(knowledge_router)
router.include_router(tools_router)
router.include_router(models_router)
router.include_router(secrets_router)
router.include_router(node_types_router)
