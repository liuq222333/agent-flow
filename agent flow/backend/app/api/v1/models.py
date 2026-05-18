from typing import Any, Literal

from fastapi import APIRouter
from sqlalchemy import text

from app.infra.db.session import engine

router = APIRouter(tags=["models"])


@router.get("/model-providers")
async def list_model_providers() -> dict[str, Any]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT
                  id,
                  name,
                  provider_type,
                  base_url,
                  status,
                  config_json,
                  created_at,
                  updated_at
                FROM model_providers
                ORDER BY name ASC, id ASC
                """
            )
        )
        return {"items": [dict(row) for row in result.mappings()]}


@router.get("/model-configs")
async def list_model_configs(
    provider_id: int | None = None,
    model_type: Literal["chat", "embedding", "rerank"] | None = None,
) -> dict[str, Any]:
    where = ["1 = 1"]
    params: dict[str, Any] = {}
    if provider_id is not None:
        where.append("provider_id = :provider_id")
        params["provider_id"] = provider_id
    if model_type is not None:
        where.append("model_type = :model_type")
        params["model_type"] = model_type

    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                f"""
                SELECT
                  id,
                  provider_id,
                  model_name,
                  model_type,
                  display_name,
                  context_window,
                  default_config_json AS default_config,
                  status,
                  created_at,
                  updated_at
                FROM model_configs
                WHERE {" AND ".join(where)}
                ORDER BY provider_id ASC, model_type ASC, model_name ASC
                """
            ),
            params,
        )
        return {"items": [dict(row) for row in result.mappings()]}
