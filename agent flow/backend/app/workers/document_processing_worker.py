import asyncio
import contextlib
import logging
import os
import socket
from typing import Any
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from app.infra.db.session import engine
from app.services.knowledge_processing import (
    DocumentProcessingError,
    mark_document_failed,
    process_document_job,
)

DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 10
DOCUMENT_JOB_QUEUE = "document_processing_jobs"
logger = logging.getLogger(__name__)


async def claim_pending_job(conn) -> dict[str, Any] | None:
    result = await conn.execute(
        text(
            """
            SELECT *
            FROM document_processing_jobs
            WHERE status = 'pending'
              AND job_type IN ('parse', 'reindex')
            ORDER BY created_at ASC, id ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        )
    )
    job = result.mappings().one_or_none()
    if job is None:
        return None

    job_dict = dict(job)
    await conn.execute(
        text(
            """
            UPDATE document_processing_jobs
            SET status = 'running',
                started_at = now(),
                updated_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": job_dict["id"]},
    )
    return job_dict


def build_worker_id() -> str:
    hostname = socket.gethostname() or "unknown-host"
    return f"document-worker:{hostname}:{os.getpid()}:{uuid4().hex[:12]}"


async def write_worker_heartbeat(
    worker_id: str,
    *,
    status_value: str,
    current_job_id: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            _jsonb_stmt(
                """
                INSERT INTO worker_heartbeats (
                  worker_id,
                  worker_type,
                  queue_name,
                  status,
                  current_job_id,
                  hostname,
                  pid,
                  metadata_json
                )
                VALUES (
                  :worker_id,
                  'document',
                  :queue_name,
                  :status,
                  :current_job_id,
                  :hostname,
                  :pid,
                  :metadata_json
                )
                ON CONFLICT (worker_id) DO UPDATE
                SET status = EXCLUDED.status,
                    current_run_id = NULL,
                    current_job_id = EXCLUDED.current_job_id,
                    hostname = EXCLUDED.hostname,
                    pid = EXCLUDED.pid,
                    last_seen_at = now(),
                    metadata_json = EXCLUDED.metadata_json
                """,
                "metadata_json",
            ),
            {
                "worker_id": worker_id,
                "queue_name": DOCUMENT_JOB_QUEUE,
                "status": status_value,
                "current_job_id": current_job_id,
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "metadata_json": metadata_json or {},
            },
        )


async def run_once(
    *,
    worker_id: str | None = None,
    heartbeat_interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
) -> bool:
    async with engine.begin() as conn:
        job = await claim_pending_job(conn)
    if job is None:
        return False

    job_id = str(job["id"])
    heartbeat_task: asyncio.Task[None] | None = None
    try:
        if worker_id:
            metadata = {
                "document_id": job.get("document_id"),
                "job_type": job.get("job_type"),
            }
            await write_worker_heartbeat(
                worker_id,
                status_value="busy",
                current_job_id=job_id,
                metadata_json=metadata,
            )
            heartbeat_task = asyncio.create_task(
                _heartbeat_loop(
                    worker_id,
                    job_id,
                    heartbeat_interval_seconds,
                    metadata,
                )
            )
        async with engine.begin() as conn:
            chunk_count = await process_document_job(conn, job)
            await mark_job_success(conn, job["id"])
        logger.info("document processing job %s indexed %s chunks", job["id"], chunk_count)
    except DocumentProcessingError as exc:
        async with engine.begin() as conn:
            await mark_job_failed(
                conn,
                job["id"],
                document_id=job["document_id"],
                error_stage=exc.stage,
                error_message=exc.message,
            )
        logger.warning("document processing job %s failed: %s", job["id"], exc.message)
    except Exception as exc:
        async with engine.begin() as conn:
            await mark_job_failed(
                conn,
                job["id"],
                document_id=job["document_id"],
                error_stage="processing",
                error_message=str(exc),
            )
        logger.exception("document processing job %s failed unexpectedly", job["id"])
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
        if worker_id:
            await write_worker_heartbeat(worker_id, status_value="idle")
    return True


async def mark_job_success(conn, job_id: int) -> None:
    await conn.execute(
        text(
            """
            UPDATE document_processing_jobs
            SET status = 'success',
                error_stage = NULL,
                error_message = NULL,
                ended_at = now(),
                updated_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": job_id},
    )


async def mark_job_failed(
    conn,
    job_id: int,
    *,
    document_id: int,
    error_stage: str,
    error_message: str,
) -> None:
    await conn.execute(
        text(
            """
            UPDATE document_processing_jobs
            SET status = 'failed',
                retry_count = retry_count + 1,
                error_stage = :error_stage,
                error_message = :error_message,
                ended_at = now(),
                updated_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": job_id, "error_stage": error_stage, "error_message": error_message},
    )
    await mark_document_failed(
        conn,
        document_id,
        error_stage=error_stage,
        error_message=error_message,
    )


async def run_forever(
    poll_interval_seconds: float = 5.0,
    heartbeat_interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    worker_id = build_worker_id()
    await write_worker_heartbeat(worker_id, status_value="idle")
    last_idle_heartbeat_at = 0.0
    while True:
        now = asyncio.get_running_loop().time()
        idle_heartbeat_due = (
            heartbeat_interval_seconds > 0
            and now - last_idle_heartbeat_at >= heartbeat_interval_seconds
        )
        if idle_heartbeat_due:
            last_idle_heartbeat_at = now
            await write_worker_heartbeat(worker_id, status_value="idle")
        processed = await run_once(
            worker_id=worker_id,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        )
        if not processed:
            await asyncio.sleep(poll_interval_seconds)


async def _heartbeat_loop(
    worker_id: str,
    job_id: str,
    interval_seconds: int,
    metadata_json: dict[str, Any],
) -> None:
    interval_seconds = max(int(interval_seconds), 1)
    while True:
        await asyncio.sleep(interval_seconds)
        await write_worker_heartbeat(
            worker_id,
            status_value="busy",
            current_job_id=job_id,
            metadata_json=metadata_json,
        )


def _jsonb_stmt(sql: str, *jsonb_param_names: str):
    statement = text(sql)
    return statement.bindparams(
        *(bindparam(param_name, type_=JSONB) for param_name in jsonb_param_names)
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
