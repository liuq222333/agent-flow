from typing import Any

import pytest

from app.services.audit import write_audit_log


class _NestedTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _AuditConnection:
    def __init__(self, *, fail_execute: bool = False) -> None:
        self.fail_execute = fail_execute
        self.params: dict[str, Any] | None = None

    def begin_nested(self) -> _NestedTransaction:
        return _NestedTransaction()

    async def execute(self, statement: Any, params: dict[str, Any]) -> None:
        if self.fail_execute:
            raise RuntimeError("audit table unavailable")
        self.params = params


@pytest.mark.asyncio
async def test_write_audit_log_inserts_resource_details() -> None:
    conn = _AuditConnection()

    await write_audit_log(
        conn,
        actor_user_id=7,
        action="workflow.create",
        resource_type="workflow",
        resource_id=42,
        detail={"name": "Support triage"},
    )

    assert conn.params == {
        "actor_user_id": 7,
        "action": "workflow.create",
        "resource_type": "workflow",
        "resource_id": "42",
        "request_id": None,
        "ip_address": None,
        "user_agent": None,
        "detail_json": {"name": "Support triage"},
    }


@pytest.mark.asyncio
async def test_write_audit_log_failure_is_best_effort() -> None:
    conn = _AuditConnection(fail_execute=True)

    await write_audit_log(
        conn,
        actor_user_id=7,
        action="tool.test",
        resource_type="tool",
        resource_id=1,
    )
