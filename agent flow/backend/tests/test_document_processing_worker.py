import asyncio
from typing import Any

import pytest

from app.workers import document_processing_worker


class _DocumentJobConnection:
    def __init__(self) -> None:
        self.retry_count = 0
        self.failed_params: dict[str, Any] | None = None

    async def execute(self, statement: Any, params: dict[str, Any]) -> None:
        sql = str(statement)
        if "UPDATE document_processing_jobs" in sql:
            assert "retry_count = retry_count + 1" in sql
            self.retry_count += 1
            self.failed_params = params


class _DocumentWorkerTransaction:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _DocumentWorkerEngine:
    def begin(self) -> _DocumentWorkerTransaction:
        return _DocumentWorkerTransaction()


@pytest.mark.asyncio
async def test_mark_job_failed_increments_retry_count(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _DocumentJobConnection()
    marked_document: dict[str, Any] = {}

    async def mark_document_failed(
        conn_arg: Any,
        document_id: int,
        *,
        error_stage: str,
        error_message: str,
    ) -> None:
        marked_document.update(
            {
                "conn": conn_arg,
                "document_id": document_id,
                "error_stage": error_stage,
                "error_message": error_message,
            }
        )

    monkeypatch.setattr(document_processing_worker, "mark_document_failed", mark_document_failed)

    await document_processing_worker.mark_job_failed(
        conn,
        9,
        document_id=33,
        error_stage="parse",
        error_message="no text",
    )

    assert conn.retry_count == 1
    assert conn.failed_params == {
        "job_id": 9,
        "error_stage": "parse",
        "error_message": "no text",
    }
    assert marked_document == {
        "conn": conn,
        "document_id": 33,
        "error_stage": "parse",
        "error_message": "no text",
    }


@pytest.mark.asyncio
async def test_run_once_with_worker_id_marks_document_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str | int | None, dict[str, Any] | None]] = []
    job = {"id": 12, "document_id": 44, "job_type": "parse"}

    async def claim_pending_job(conn: Any) -> dict[str, Any]:
        return job

    async def process_document_job(conn: Any, job_arg: dict[str, Any]) -> int:
        events.append(("process", job_arg["id"], None))
        return 3

    async def mark_job_success(conn: Any, job_id: int) -> None:
        events.append(("success", job_id, None))

    async def write_worker_heartbeat(
        worker_id: str,
        *,
        status_value: str,
        current_job_id: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> None:
        events.append((status_value, current_job_id, metadata_json))

    async def heartbeat_loop(
        worker_id: str,
        job_id: str,
        interval_seconds: int,
        metadata_json: dict[str, Any],
    ) -> None:
        events.append(("loop", job_id, metadata_json))
        await asyncio.sleep(3600)

    monkeypatch.setattr(document_processing_worker, "engine", _DocumentWorkerEngine())
    monkeypatch.setattr(document_processing_worker, "claim_pending_job", claim_pending_job)
    monkeypatch.setattr(document_processing_worker, "process_document_job", process_document_job)
    monkeypatch.setattr(document_processing_worker, "mark_job_success", mark_job_success)
    monkeypatch.setattr(
        document_processing_worker,
        "write_worker_heartbeat",
        write_worker_heartbeat,
    )
    monkeypatch.setattr(document_processing_worker, "_heartbeat_loop", heartbeat_loop)

    result = await document_processing_worker.run_once(
        worker_id="document-worker:test",
        heartbeat_interval_seconds=1,
    )

    metadata = {"document_id": 44, "job_type": "parse"}
    assert result is True
    assert ("busy", "12", metadata) in events
    assert ("process", 12, None) in events
    assert ("success", 12, None) in events
    assert events[-1] == ("idle", None, None)
