from typing import Any

import pytest

from app.api.v1.schemas import RetryRunRequest
from app.services import workflows


class _RetryTransaction:
    def __init__(self, conn: "_RetryConnection") -> None:
        self.conn = conn

    async def __aenter__(self) -> "_RetryConnection":
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _RetryEngine:
    def __init__(self, conn: "_RetryConnection") -> None:
        self.conn = conn

    def begin(self) -> _RetryTransaction:
        return _RetryTransaction(self.conn)


class _RetryMappingResult:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    def mappings(self) -> "_RetryMappingResult":
        return self

    def one(self) -> dict[str, Any]:
        return self._row


class _RetryConnection:
    def __init__(self) -> None:
        self.metadata_json: dict[str, Any] | None = None

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        params = params or {}
        self.metadata_json = params["metadata_json"]
        return _RetryMappingResult(
            {
                "id": params["run_id"],
                "status": "pending",
                "output_json": None,
                "started_at": None,
                "ended_at": None,
                "metadata_json": self.metadata_json,
            }
        )


@pytest.mark.asyncio
async def test_retry_run_creates_new_async_run_and_enqueues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _RetryConnection()
    enqueued: list[int] = []
    audits: list[dict[str, Any]] = []

    async def get_run_row(_conn: Any, run_id: int) -> dict[str, Any]:
        return {
            "id": run_id,
            "workflow_id": 11,
            "version_id": 22,
            "status": "failed",
            "trigger_type": "manual",
            "input_json": {"name": "Ada"},
            "created_by": 5,
        }

    async def get_version_row(_conn: Any, version_id: int) -> dict[str, Any]:
        return {"id": version_id, "workflow_id": 11, "code_path": "workflow.py", "code_hash": "h"}

    async def ensure_version_code(_conn: Any, version: dict[str, Any]) -> dict[str, Any]:
        return version

    async def create_pending(_conn: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["workflow_id"] == 11
        assert kwargs["version_id"] == 22
        assert kwargs["run_input"] == {"name": "Ada"}
        assert kwargs["created_by"] == 5
        return {
            "id": 33,
            "status": "pending",
            "output_json": None,
            "started_at": None,
            "ended_at": None,
            "metadata_json": {"execution_mode": "async"},
        }

    async def enqueue(run_id: int) -> None:
        enqueued.append(run_id)

    async def write_audit_log(_conn: Any, **kwargs: Any) -> None:
        audits.append(kwargs)

    monkeypatch.setattr(workflows, "engine", _RetryEngine(conn))
    monkeypatch.setattr(workflows, "_get_run_row", get_run_row)
    monkeypatch.setattr(workflows, "_get_version_row", get_version_row)
    monkeypatch.setattr(workflows, "_ensure_version_code", ensure_version_code)
    monkeypatch.setattr(workflows, "create_generated_workflow_run_pending", create_pending)
    monkeypatch.setattr(workflows, "_enqueue_async_workflow_run", enqueue)
    monkeypatch.setattr(workflows, "write_audit_log", write_audit_log)

    result = await workflows.retry_run(7, RetryRunRequest(reason="provider recovered"))

    assert result["run_id"] == 33
    assert result["status"] == "pending"
    assert result["retry_of_run_id"] == 7
    assert enqueued == [33]
    assert conn.metadata_json == {
        "execution_mode": "async",
        "retry_of_run_id": 7,
        "retry_of_status": "failed",
        "retry_reason": "provider recovered",
    }
    assert audits[0]["action"] == "workflow.retry"
