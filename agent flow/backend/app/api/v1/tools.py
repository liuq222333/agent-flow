import re
import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from app.api.v1.schemas import CreateToolRequest, TestToolRequest
from app.core.config import get_settings
from app.infra.db.session import engine
from app.services.audit import write_audit_log
from app.services.secrets import get_secret_value

router = APIRouter(prefix="/tools", tags=["tools"])
_PLACEHOLDER_RE = re.compile(r"{{\s*([^}]+)\s*}}")


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_tool(payload: CreateToolRequest) -> dict[str, Any]:
    settings = get_settings()
    async with engine.begin() as conn:
        await _ensure_mock_user(conn, settings.mock_user_id)
        result = await conn.execute(
            _jsonb_stmt(
                """
                INSERT INTO tools (name, type, description, config_json, status, created_by)
                VALUES (:name, :type, :description, :config_json, 'active', :created_by)
                RETURNING *
                """,
                "config_json",
            ),
            {
                "name": payload.name,
                "type": payload.type,
                "description": payload.description,
                "config_json": payload.config,
                "created_by": settings.mock_user_id,
            },
        )
        tool = dict(result.mappings().one())
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="tool.create",
            resource_type="tool",
            resource_id=tool["id"],
            detail={"name": tool["name"], "type": tool["type"], "status": tool["status"]},
        )
        return tool


@router.get("")
async def list_tools(
    type: Literal["api"] | None = None,  # noqa: A002 - OpenAPI query name
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    page, page_size, offset = _pagination(page, page_size)
    where = ["deleted_at IS NULL", "status != 'deleted'"]
    params: dict[str, Any] = {"limit": page_size, "offset": offset}
    if type is not None:
        where.append("type = :type")
        params["type"] = type
    where_sql = " AND ".join(where)

    async with engine.connect() as conn:
        total = await conn.scalar(text(f"SELECT count(*) FROM tools WHERE {where_sql}"), params)
        result = await conn.execute(
            text(
                f"""
                SELECT *
                FROM tools
                WHERE {where_sql}
                ORDER BY updated_at DESC, id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        return {
            "items": [dict(row) for row in result.mappings()],
            "page": page,
            "page_size": page_size,
            "total": total or 0,
        }


@router.get("/{tool_id}")
async def get_tool(tool_id: int) -> dict[str, Any]:
    async with engine.connect() as conn:
        return await _get_tool_row(conn, tool_id)


@router.put("/{tool_id}")
async def update_tool(tool_id: int, payload: CreateToolRequest) -> dict[str, Any]:
    settings = get_settings()
    async with engine.begin() as conn:
        result = await conn.execute(
            _jsonb_stmt(
                """
                UPDATE tools
                SET name = :name,
                    type = :type,
                    description = :description,
                    config_json = :config_json,
                    updated_at = now()
                WHERE id = :tool_id AND deleted_at IS NULL AND status != 'deleted'
                RETURNING *
                """,
                "config_json",
            ),
            {
                "tool_id": tool_id,
                "name": payload.name,
                "type": payload.type,
                "description": payload.description,
                "config_json": payload.config,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tool not found")
        tool = dict(row)
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="tool.update",
            resource_type="tool",
            resource_id=tool["id"],
            detail={"name": tool["name"], "type": tool["type"], "status": tool["status"]},
        )
        return tool


@router.post("/{tool_id}/test")
async def test_tool(tool_id: int, payload: TestToolRequest) -> dict[str, Any]:
    started = time.perf_counter()
    settings = get_settings()
    async with engine.begin() as conn:
        tool = await _get_tool_row(conn, tool_id)
        resolved_config = await _resolve_tool_value(
            conn,
            tool.get("config_json") or {},
            payload.input,
        )
        safe_config = await _resolve_tool_value(
            conn,
            tool.get("config_json") or {},
            payload.input,
            redact_secrets=True,
        )
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="tool.test",
            resource_type="tool",
            resource_id=tool_id,
            detail={"input_keys": sorted(payload.input.keys())},
        )
    return mock_tool_test_result(
        tool,
        payload.input,
        started_at=started,
        resolved_config=resolved_config,
        safe_config=safe_config,
    )


def mock_tool_test_result(
    tool: dict[str, Any],
    tool_input: dict[str, Any],
    *,
    started_at: float | None = None,
    resolved_config: dict[str, Any] | None = None,
    safe_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    duration_ms = int((time.perf_counter() - (started_at or time.perf_counter())) * 1000)
    return {
        "success": True,
        "status_code": 200,
        "duration_ms": duration_ms,
        "response": {
            "mode": "mock",
            "tool_id": tool.get("id"),
            "tool_name": tool.get("name"),
            "input": tool_input,
            "config": safe_config if safe_config is not None else tool.get("config_json") or {},
            "resolved": resolved_config is not None,
        },
        "error_message": None,
    }


async def _resolve_tool_value(
    conn,
    value: Any,
    tool_input: dict[str, Any],
    *,
    redact_secrets: bool = False,
) -> Any:
    if isinstance(value, dict):
        return {
            key: await _resolve_tool_value(conn, item, tool_input, redact_secrets=redact_secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            await _resolve_tool_value(conn, item, tool_input, redact_secrets=redact_secrets)
            for item in value
        ]
    if not isinstance(value, str):
        return value

    full_match = _PLACEHOLDER_RE.fullmatch(value)
    if full_match:
        return await _resolve_tool_path(
            conn,
            full_match.group(1).strip(),
            tool_input,
            redact_secrets=redact_secrets,
        )

    async def replace_match(match: re.Match[str]) -> str:
        resolved = await _resolve_tool_path(
            conn,
            match.group(1).strip(),
            tool_input,
            redact_secrets=redact_secrets,
        )
        return "" if resolved is None else str(resolved)

    parts: list[str] = []
    cursor = 0
    for match in _PLACEHOLDER_RE.finditer(value):
        parts.append(value[cursor : match.start()])
        parts.append(await replace_match(match))
        cursor = match.end()
    parts.append(value[cursor:])
    return "".join(parts)


async def _resolve_tool_path(
    conn,
    path: str,
    tool_input: dict[str, Any],
    *,
    redact_secrets: bool,
) -> Any:
    if path.startswith("secrets."):
        secret_key = path.removeprefix("secrets.").strip()
        if redact_secrets:
            return "***"
        secret_value = await get_secret_value(conn, secret_key)
        if secret_value is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"secret not found or inactive: {secret_key}",
            )
        return secret_value
    if path.startswith("input."):
        return _get_path(path.removeprefix("input."), tool_input)
    return _get_path(path, tool_input)


def _get_path(path: str, value: dict[str, Any]) -> Any:
    current: Any = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


async def _get_tool_row(conn, tool_id: int) -> dict[str, Any]:
    result = await conn.execute(
        text(
            """
            SELECT *
            FROM tools
            WHERE id = :tool_id AND deleted_at IS NULL AND status != 'deleted'
            """
        ),
        {"tool_id": tool_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tool not found")
    return dict(row)


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


def _jsonb_stmt(sql: str, *jsonb_param_names: str):
    statement = text(sql)
    return statement.bindparams(
        *(bindparam(param_name, type_=JSONB) for param_name in jsonb_param_names)
    )


def _pagination(page: int, page_size: int) -> tuple[int, int, int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    return page, page_size, (page - 1) * page_size
