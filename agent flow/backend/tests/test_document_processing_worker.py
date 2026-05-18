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
