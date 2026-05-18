import logging
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

logger = logging.getLogger(__name__)


async def write_audit_log(
    conn,
    *,
    actor_user_id: int | None,
    action: str,
    resource_type: str,
    resource_id: str | int | None = None,
    detail: dict[str, Any] | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Best-effort audit logging that never blocks the primary business action."""
    try:
        async with conn.begin_nested():
            await conn.execute(
                text(
                    """
                    INSERT INTO audit_logs (
                      actor_user_id,
                      action,
                      resource_type,
                      resource_id,
                      request_id,
                      ip_address,
                      user_agent,
                      detail_json
                    )
                    VALUES (
                      :actor_user_id,
                      :action,
                      :resource_type,
                      :resource_id,
                      :request_id,
                      :ip_address,
                      :user_agent,
                      :detail_json
                    )
                    """
                ).bindparams(bindparam("detail_json", type_=JSONB)),
                {
                    "actor_user_id": actor_user_id,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": str(resource_id) if resource_id is not None else None,
                    "request_id": request_id,
                    "ip_address": ip_address,
                    "user_agent": user_agent,
                    "detail_json": detail or {},
                },
            )
    except Exception:
        logger.warning(
            "failed to write audit log for action=%s resource_type=%s resource_id=%s",
            action,
            resource_type,
            resource_id,
            exc_info=True,
        )
