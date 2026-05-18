import base64
import hashlib
from typing import Any

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.api.v1.schemas import CreateSecretRequest, UpdateSecretRequest
from app.core.config import get_settings
from app.infra.db.session import engine
from app.services.audit import write_audit_log

router = APIRouter(prefix="/secrets", tags=["secrets"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_secret(payload: CreateSecretRequest) -> dict[str, Any]:
    settings = get_settings()
    encrypted_value = encrypt_secret_value(payload.value, settings.secret_encryption_key)
    async with engine.begin() as conn:
        await _ensure_mock_user(conn, settings.mock_user_id)
        result = await conn.execute(
            text(
                """
                INSERT INTO secrets (
                  secret_key,
                  display_name,
                  encrypted_value,
                  status,
                  key_version,
                  created_by,
                  updated_by
                )
                VALUES (
                  :secret_key,
                  :display_name,
                  :encrypted_value,
                  'active',
                  1,
                  :user_id,
                  :user_id
                )
                RETURNING id, secret_key, display_name, status, key_version, created_at, updated_at
                """
            ),
            {
                "secret_key": payload.secret_key,
                "display_name": payload.display_name,
                "encrypted_value": encrypted_value,
                "user_id": settings.mock_user_id,
            },
        )
        secret = sanitize_secret_row(dict(result.mappings().one()))
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="secret.create",
            resource_type="secret",
            resource_id=secret["id"],
            detail={"secret_key": secret["secret_key"], "status": secret["status"]},
        )
        return secret


@router.get("")
async def list_secrets(page: int = 1, page_size: int = 20) -> dict[str, Any]:
    page, page_size, offset = _pagination(page, page_size)
    async with engine.connect() as conn:
        total = await conn.scalar(
            text("SELECT count(*) FROM secrets WHERE deleted_at IS NULL AND status != 'disabled'")
        )
        result = await conn.execute(
            text(
                """
                SELECT id, secret_key, display_name, status, key_version, created_at, updated_at
                FROM secrets
                WHERE deleted_at IS NULL AND status != 'disabled'
                ORDER BY created_at DESC, id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": page_size, "offset": offset},
        )
        return {
            "items": [sanitize_secret_row(dict(row)) for row in result.mappings()],
            "page": page,
            "page_size": page_size,
            "total": total or 0,
        }


@router.put("/{secret_id}")
async def update_secret(secret_id: int, payload: UpdateSecretRequest) -> dict[str, Any]:
    if not payload.model_fields_set:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty update")

    settings = get_settings()
    encrypted_value = (
        encrypt_secret_value(payload.value, settings.secret_encryption_key)
        if payload.value is not None
        else None
    )
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                UPDATE secrets
                SET display_name = CASE
                      WHEN :has_display_name THEN :display_name
                      ELSE display_name
                    END,
                    encrypted_value = COALESCE(:encrypted_value, encrypted_value),
                    key_version = CASE
                      WHEN :encrypted_value IS NULL THEN key_version
                      ELSE key_version + 1
                    END,
                    updated_by = :user_id,
                    updated_at = now()
                WHERE id = :secret_id AND deleted_at IS NULL
                RETURNING id, secret_key, display_name, status, key_version, created_at, updated_at
                """
            ),
            {
                "secret_id": secret_id,
                "has_display_name": "display_name" in payload.model_fields_set,
                "display_name": payload.display_name,
                "encrypted_value": encrypted_value,
                "user_id": settings.mock_user_id,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="secret not found")
        secret = sanitize_secret_row(dict(row))
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="secret.update",
            resource_type="secret",
            resource_id=secret["id"],
            detail={
                "secret_key": secret["secret_key"],
                "status": secret["status"],
                "rotated": payload.value is not None,
            },
        )
        return secret


def encrypt_secret_value(value: str, encryption_key: str) -> str:
    key_bytes = hashlib.sha256(encryption_key.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret_value(encrypted_value: str, encryption_key: str) -> str:
    key_bytes = hashlib.sha256(encryption_key.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key).decrypt(encrypted_value.encode("utf-8")).decode("utf-8")


def sanitize_secret_row(row: dict[str, Any]) -> dict[str, Any]:
    row.pop("encrypted_value", None)
    row.pop("value", None)
    return row


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


def _pagination(page: int, page_size: int) -> tuple[int, int, int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    return page, page_size, (page - 1) * page_size
