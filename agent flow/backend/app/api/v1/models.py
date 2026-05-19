from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from app.api.v1.schemas import (
    CreateModelConfigRequest,
    CreateModelProviderRequest,
    UpdateModelConfigRequest,
    UpdateModelProviderRequest,
)
from app.core.config import get_settings
from app.infra.db.session import engine
from app.services.audit import write_audit_log

router = APIRouter(tags=["models"])


@router.post("/model-providers", status_code=status.HTTP_201_CREATED)
async def create_model_provider(payload: CreateModelProviderRequest) -> dict[str, Any]:
    settings = get_settings()
    async with engine.begin() as conn:
        await _ensure_mock_user(conn, settings.mock_user_id)
        await _validate_provider_config(conn, payload.provider_type, payload.status, payload.config)
        try:
            result = await conn.execute(
                _jsonb_stmt(
                    """
                    INSERT INTO model_providers (
                      name,
                      provider_type,
                      base_url,
                      status,
                      config_json
                    )
                    VALUES (
                      :name,
                      :provider_type,
                      :base_url,
                      :status,
                      :config_json
                    )
                    RETURNING
                      id,
                      name,
                      provider_type,
                      base_url,
                      status,
                      config_json,
                      created_at,
                      updated_at
                    """,
                    "config_json",
                ),
                {
                    "name": payload.name,
                    "provider_type": payload.provider_type,
                    "base_url": payload.base_url,
                    "status": payload.status,
                    "config_json": payload.config,
                },
            )
        except Exception as exc:
            _raise_unique_conflict(exc, "model provider name already exists")
            raise
        provider = dict(result.mappings().one())
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="model_provider.create",
            resource_type="model_provider",
            resource_id=provider["id"],
            detail={
                "name": provider["name"],
                "provider_type": provider["provider_type"],
                "status": provider["status"],
            },
        )
        return provider


@router.get("/model-providers")
async def list_model_providers(
    status_filter: Literal["active", "disabled"] | None = None,
) -> dict[str, Any]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if status_filter is not None:
        where.append("status = :status")
        params["status"] = status_filter
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                f"""
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
                {where_sql}
                ORDER BY name ASC, id ASC
                """
            ),
            params,
        )
        return {"items": [dict(row) for row in result.mappings()]}


@router.put("/model-providers/{provider_id}")
async def update_model_provider(
    provider_id: int,
    payload: UpdateModelProviderRequest,
) -> dict[str, Any]:
    if not payload.model_fields_set:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty update")

    settings = get_settings()
    async with engine.begin() as conn:
        current = await _get_model_provider_row(conn, provider_id)
        next_provider_type = (
            payload.provider_type
            if "provider_type" in payload.model_fields_set
            else current["provider_type"]
        )
        next_status = payload.status if "status" in payload.model_fields_set else current["status"]
        next_config = (
            payload.config if "config" in payload.model_fields_set else current["config_json"]
        )
        await _validate_provider_config(conn, next_provider_type, next_status, next_config or {})

        try:
            result = await conn.execute(
                _jsonb_stmt(
                    """
                    UPDATE model_providers
                    SET name = CASE WHEN :has_name THEN :name ELSE name END,
                        provider_type = CASE
                          WHEN :has_provider_type THEN :provider_type
                          ELSE provider_type
                        END,
                        base_url = CASE WHEN :has_base_url THEN :base_url ELSE base_url END,
                        status = CASE WHEN :has_status THEN :status ELSE status END,
                        config_json = CASE
                          WHEN :has_config THEN :config_json
                          ELSE config_json
                        END,
                        updated_at = now()
                    WHERE id = :provider_id
                    RETURNING
                      id,
                      name,
                      provider_type,
                      base_url,
                      status,
                      config_json,
                      created_at,
                      updated_at
                    """,
                    "config_json",
                ),
                {
                    "provider_id": provider_id,
                    "has_name": "name" in payload.model_fields_set,
                    "name": payload.name,
                    "has_provider_type": "provider_type" in payload.model_fields_set,
                    "provider_type": payload.provider_type,
                    "has_base_url": "base_url" in payload.model_fields_set,
                    "base_url": payload.base_url,
                    "has_status": "status" in payload.model_fields_set,
                    "status": payload.status,
                    "has_config": "config" in payload.model_fields_set,
                    "config_json": payload.config,
                },
            )
        except Exception as exc:
            _raise_unique_conflict(exc, "model provider name already exists")
            raise
        provider = dict(result.mappings().one())
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="model_provider.update",
            resource_type="model_provider",
            resource_id=provider["id"],
            detail={
                "name": provider["name"],
                "provider_type": provider["provider_type"],
                "status": provider["status"],
            },
        )
        return provider


@router.post("/model-configs", status_code=status.HTTP_201_CREATED)
async def create_model_config(payload: CreateModelConfigRequest) -> dict[str, Any]:
    settings = get_settings()
    async with engine.begin() as conn:
        await _ensure_mock_user(conn, settings.mock_user_id)
        await _ensure_provider_exists(conn, payload.provider_id)
        try:
            result = await conn.execute(
                _jsonb_stmt(
                    """
                    INSERT INTO model_configs (
                      provider_id,
                      model_name,
                      model_type,
                      display_name,
                      context_window,
                      default_config_json,
                      status
                    )
                    VALUES (
                      :provider_id,
                      :model_name,
                      :model_type,
                      :display_name,
                      :context_window,
                      :default_config_json,
                      :status
                    )
                    RETURNING
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
                    """,
                    "default_config_json",
                ),
                {
                    "provider_id": payload.provider_id,
                    "model_name": payload.model_name,
                    "model_type": payload.model_type,
                    "display_name": payload.display_name,
                    "context_window": payload.context_window,
                    "default_config_json": payload.default_config,
                    "status": payload.status,
                },
            )
        except Exception as exc:
            _raise_unique_conflict(exc, "model config already exists for provider")
            raise
        model_config = dict(result.mappings().one())
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="model_config.create",
            resource_type="model_config",
            resource_id=model_config["id"],
            detail={
                "provider_id": model_config["provider_id"],
                "model_name": model_config["model_name"],
                "model_type": model_config["model_type"],
                "status": model_config["status"],
            },
        )
        return model_config


@router.get("/model-configs")
async def list_model_configs(
    provider_id: int | None = None,
    model_type: Literal["chat", "embedding", "rerank"] | None = None,
    status_filter: Literal["active", "disabled"] | None = None,
) -> dict[str, Any]:
    where = ["1 = 1"]
    params: dict[str, Any] = {}
    if provider_id is not None:
        where.append("provider_id = :provider_id")
        params["provider_id"] = provider_id
    if model_type is not None:
        where.append("model_type = :model_type")
        params["model_type"] = model_type
    if status_filter is not None:
        where.append("status = :status")
        params["status"] = status_filter

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


@router.put("/model-configs/{model_config_id}")
async def update_model_config(
    model_config_id: int,
    payload: UpdateModelConfigRequest,
) -> dict[str, Any]:
    if not payload.model_fields_set:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty update")

    settings = get_settings()
    async with engine.begin() as conn:
        await _get_model_config_row(conn, model_config_id)
        if payload.provider_id is not None:
            await _ensure_provider_exists(conn, payload.provider_id)
        try:
            result = await conn.execute(
                _jsonb_stmt(
                    """
                    UPDATE model_configs
                    SET provider_id = CASE
                          WHEN :has_provider_id THEN :provider_id
                          ELSE provider_id
                        END,
                        model_name = CASE WHEN :has_model_name THEN :model_name ELSE model_name END,
                        model_type = CASE WHEN :has_model_type THEN :model_type ELSE model_type END,
                        display_name = CASE
                          WHEN :has_display_name THEN :display_name
                          ELSE display_name
                        END,
                        context_window = CASE
                          WHEN :has_context_window THEN :context_window
                          ELSE context_window
                        END,
                        default_config_json = CASE
                          WHEN :has_default_config THEN :default_config_json
                          ELSE default_config_json
                        END,
                        status = CASE WHEN :has_status THEN :status ELSE status END,
                        updated_at = now()
                    WHERE id = :model_config_id
                    RETURNING
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
                    """,
                    "default_config_json",
                ),
                {
                    "model_config_id": model_config_id,
                    "has_provider_id": "provider_id" in payload.model_fields_set,
                    "provider_id": payload.provider_id,
                    "has_model_name": "model_name" in payload.model_fields_set,
                    "model_name": payload.model_name,
                    "has_model_type": "model_type" in payload.model_fields_set,
                    "model_type": payload.model_type,
                    "has_display_name": "display_name" in payload.model_fields_set,
                    "display_name": payload.display_name,
                    "has_context_window": "context_window" in payload.model_fields_set,
                    "context_window": payload.context_window,
                    "has_default_config": "default_config" in payload.model_fields_set,
                    "default_config_json": payload.default_config,
                    "has_status": "status" in payload.model_fields_set,
                    "status": payload.status,
                },
            )
        except Exception as exc:
            _raise_unique_conflict(exc, "model config already exists for provider")
            raise
        model_config = dict(result.mappings().one())
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="model_config.update",
            resource_type="model_config",
            resource_id=model_config["id"],
            detail={
                "provider_id": model_config["provider_id"],
                "model_name": model_config["model_name"],
                "model_type": model_config["model_type"],
                "status": model_config["status"],
            },
        )
        return model_config


async def _get_model_provider_row(conn, provider_id: int) -> dict[str, Any]:
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
            WHERE id = :provider_id
            """
        ),
        {"provider_id": provider_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="model provider not found",
        )
    return dict(row)


async def _get_model_config_row(conn, model_config_id: int) -> dict[str, Any]:
    result = await conn.execute(
        text(
            """
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
            WHERE id = :model_config_id
            """
        ),
        {"model_config_id": model_config_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="model config not found",
        )
    return dict(row)


async def _ensure_provider_exists(conn, provider_id: int) -> None:
    result = await conn.execute(
        text("SELECT 1 FROM model_providers WHERE id = :provider_id"),
        {"provider_id": provider_id},
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="provider_id does not reference an existing model provider",
        )


async def _validate_provider_config(
    conn,
    provider_type: str,
    provider_status: str,
    config: dict[str, Any],
) -> None:
    if provider_status != "active" or not _provider_requires_api_key(provider_type):
        return
    secret_key = str((config or {}).get("api_key_secret") or "").strip()
    if not secret_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="config.api_key_secret is required for active API-backed providers",
        )
    result = await conn.execute(
        text(
            """
            SELECT 1
            FROM secrets
            WHERE secret_key = :secret_key
              AND deleted_at IS NULL
              AND status = 'active'
            LIMIT 1
            """
        ),
        {"secret_key": secret_key},
    )
    if result.scalar_one_or_none() is None:
        provider_name = provider_type.strip().lower()
        if provider_name == "openai" and secret_key == "openai_api_key":
            return
        if provider_name == "deepseek" and secret_key == "deepseek_api_key":
            return
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="config.api_key_secret must reference an active secret",
        )


def _provider_requires_api_key(provider_type: str) -> bool:
    return provider_type.strip().lower() not in {"mock", "local", "local-mock"}


async def _ensure_mock_user(conn, user_id: int) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO users (id, email, username, display_name, role, status)
            VALUES (:id, :email, :username, :display_name, 'admin', 'active')
            ON CONFLICT (id) DO UPDATE
            SET status = 'active', updated_at = now()
            """
        ),
        {
            "id": user_id,
            "email": f"mock-user-{user_id}@local.agent-flow",
            "username": f"mock_user_{user_id}",
            "display_name": "Mock User",
        },
    )


def _raise_unique_conflict(exc: Exception, message: str) -> None:
    if "duplicate key value" in str(exc).lower():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message) from exc


def _jsonb_stmt(sql: str, *jsonb_param_names: str):
    statement = text(sql)
    return statement.bindparams(
        *(bindparam(param_name, type_=JSONB) for param_name in jsonb_param_names)
    )
