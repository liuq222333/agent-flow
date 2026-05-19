from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1.schemas import SubmitHumanApprovalRequest
from app.main import app
from app.services import human_approvals


class _AsyncContext:
    def __init__(self, conn: Any) -> None:
        self.conn = conn

    async def __aenter__(self) -> Any:
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeEngine:
    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def connect(self) -> _AsyncContext:
        return _AsyncContext(self.conn)

    def begin(self) -> _AsyncContext:
        return _AsyncContext(self.conn)


class _FakeResult:
    def __init__(
        self,
        *,
        row: dict[str, Any] | None = None,
        rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.row = row
        self.rows = rows or []

    def mappings(self) -> "_FakeResult":
        return self

    def one(self) -> dict[str, Any]:
        assert self.row is not None
        return self.row

    def one_or_none(self) -> dict[str, Any] | None:
        return self.row

    def __iter__(self):
        return iter(self.rows)


def _approval_task(status: str = "pending") -> dict[str, Any]:
    return {
        "id": 9,
        "workflow_id": 11,
        "run_id": 22,
        "node_id": "approval_1",
        "node_name": "人工审批",
        "title": "退款审批",
        "description": "请审批退款请求",
        "status": status,
        "decision": None,
        "input_json": {"amount": 100},
        "response_json": None,
        "metadata_json": {},
        "requested_by": 1,
        "decided_by": None,
        "created_at": "2026-05-19T01:00:00Z",
        "updated_at": "2026-05-19T01:00:00Z",
        "decided_at": None,
        "expires_at": None,
    }


def test_human_approval_routes_are_registered() -> None:
    client = TestClient(app)

    openapi = client.get("/api/openapi.json").json()

    assert "/api/v1/human-approval-tasks" in openapi["paths"]
    assert "/api/v1/human-approval-tasks/{task_id}" in openapi["paths"]
    assert "/api/v1/human-approval-tasks/{task_id}/submit" in openapi["paths"]


class _ListTasksConnection:
    async def scalar(self, statement: Any, params: dict[str, Any] | None = None) -> int:
        assert params == {"limit": 2, "offset": 0, "status": "pending", "run_id": 22}
        return 1

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        assert params == {"limit": 2, "offset": 0, "status": "pending", "run_id": 22}
        return _FakeResult(rows=[_approval_task()])


@pytest.mark.asyncio
async def test_list_human_approval_tasks_filters_and_paginates(monkeypatch) -> None:
    monkeypatch.setattr(human_approvals, "engine", _FakeEngine(_ListTasksConnection()))

    result = await human_approvals.list_human_approval_tasks(
        task_status="pending",
        run_id=22,
        page=1,
        page_size=2,
    )

    assert result["total"] == 1
    assert result["items"][0]["node_id"] == "approval_1"


class _SubmitTaskConnection:
    def __init__(self, task: dict[str, Any]) -> None:
        self.task = task
        self.response_json: dict[str, Any] | None = None

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        sql = str(statement)
        params = params or {}
        if "SELECT" in sql and "FOR UPDATE" in sql:
            return _FakeResult(row=self.task)
        if "UPDATE human_approval_tasks" in sql:
            self.response_json = params["response_json"]
            updated = {
                **self.task,
                "status": params["status"],
                "decision": params["decision"],
                "response_json": params["response_json"],
                "decided_by": params["decided_by"],
            }
            return _FakeResult(row=updated)
        raise AssertionError(f"unexpected SQL: {sql}")


@pytest.mark.asyncio
async def test_submit_human_approval_task_marks_decision_and_audits(monkeypatch) -> None:
    conn = _SubmitTaskConnection(_approval_task())
    audits: list[dict[str, Any]] = []

    async def fake_audit_log(_conn: Any, **kwargs: Any) -> None:
        audits.append(kwargs)

    monkeypatch.setattr(human_approvals, "engine", _FakeEngine(conn))
    monkeypatch.setattr(human_approvals, "write_audit_log", fake_audit_log)

    result = await human_approvals.submit_human_approval_task(
        9,
        SubmitHumanApprovalRequest(
            decision="approve",
            response={"approved": True},
            comment="ok",
        ),
    )

    assert result["status"] == "approved"
    assert result["decision"] == "approve"
    assert result["resume_supported"] is False
    assert conn.response_json == {
        "decision": "approve",
        "response": {"approved": True},
        "comment": "ok",
    }
    assert audits[0]["action"] == "human_approval.submit"
    assert audits[0]["detail"]["resume_supported"] is False


@pytest.mark.asyncio
async def test_submit_non_pending_human_approval_task_conflicts(monkeypatch) -> None:
    conn = _SubmitTaskConnection(_approval_task(status="approved"))
    monkeypatch.setattr(human_approvals, "engine", _FakeEngine(conn))

    with pytest.raises(HTTPException) as exc_info:
        await human_approvals.submit_human_approval_task(
            9,
            SubmitHumanApprovalRequest(decision="reject"),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "human_approval_task_not_pending"


class _CreateTaskConnection:
    def __init__(self) -> None:
        self.run_metadata_json: dict[str, Any] | None = None

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        sql = str(statement)
        params = params or {}
        if "INSERT INTO human_approval_tasks" in sql:
            return _FakeResult(
                row={
                    **_approval_task(),
                    "id": 77,
                    "workflow_id": params["workflow_id"],
                    "run_id": params["run_id"],
                    "node_id": params["node_id"],
                    "title": params["title"],
                    "input_json": params["input_json"],
                    "metadata_json": params["metadata_json"],
                }
            )
        if "UPDATE workflow_runs" in sql:
            self.run_metadata_json = params["metadata_json"]
            return _FakeResult()
        raise AssertionError(f"unexpected SQL: {sql}")


@pytest.mark.asyncio
async def test_create_human_approval_task_marks_run_waiting() -> None:
    conn = _CreateTaskConnection()

    task = await human_approvals.create_human_approval_task(
        conn,  # type: ignore[arg-type]
        workflow_id=11,
        run_id=22,
        node_id="approval_1",
        node_name="人工审批",
        title="退款审批",
        description="请审批",
        input_json={"amount": 100},
        requested_by=1,
    )

    assert task["id"] == 77
    assert conn.run_metadata_json == {
        "waiting_approval_task_id": 77,
        "waiting_approval_node_id": "approval_1",
    }
