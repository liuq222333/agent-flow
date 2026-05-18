import asyncio
import logging
from typing import Any

from sqlalchemy import text

from app.infra.db.session import engine
from app.services.knowledge_processing import (
    DocumentProcessingError,
    mark_document_failed,
    process_document_job,
)

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


async def run_once() -> bool:
    async with engine.begin() as conn:
        job = await claim_pending_job(conn)
    if job is None:
        return False

    try:
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


async def run_forever(poll_interval_seconds: float = 5.0) -> None:
    while True:
        processed = await run_once()
        if not processed:
            await asyncio.sleep(poll_interval_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
