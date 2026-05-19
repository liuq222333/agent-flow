from typing import Any

from sqlalchemy import text

from app.api.v1.secrets import decrypt_secret_value
from app.core.config import get_settings


async def get_secret_value(conn, secret_key: str) -> str | None:
    result = await conn.execute(
        text(
            """
            SELECT encrypted_value
            FROM secrets
            WHERE secret_key = :secret_key
              AND deleted_at IS NULL
              AND status = 'active'
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {"secret_key": secret_key},
    )
    encrypted_value = result.scalar_one_or_none()
    if not encrypted_value:
        return None
    return decrypt_secret_value(str(encrypted_value), get_settings().secret_encryption_key)


async def resolve_openai_api_key(conn, provider_config: dict[str, Any] | None = None) -> str | None:
    settings_key = get_settings().openai_api_key
    if settings_key:
        return settings_key
    secret_key = str((provider_config or {}).get("api_key_secret") or "openai_api_key")
    return await get_secret_value(conn, secret_key)


async def resolve_deepseek_api_key(
    conn,
    provider_config: dict[str, Any] | None = None,
) -> str | None:
    settings_key = get_settings().deepseek_api_key
    if settings_key:
        return settings_key
    secret_key = str((provider_config or {}).get("api_key_secret") or "deepseek_api_key")
    return await get_secret_value(conn, secret_key)
