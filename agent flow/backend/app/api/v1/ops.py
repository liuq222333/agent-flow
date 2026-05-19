import json
from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter, Query
from sqlalchemy import text

from app.core.config import get_settings
from app.infra.db.session import engine
from app.workers import workflow_run_worker

router = APIRouter(prefix="/ops", tags=["ops"])

WORKFLOW_RUN_QUEUE = workflow_run_worker.WORKFLOW_RUN_QUEUE
WORKFLOW_RUN_PROCESSING_QUEUE = workflow_run_worker.WORKFLOW_RUN_PROCESSING_QUEUE
WORKFLOW_RUN_DEAD_QUEUE = workflow_run_worker.WORKFLOW_RUN_DEAD_QUEUE


@router.get("/workers")
async def list_workers(active_seconds: int = Query(default=120, ge=1, le=86400)) -> dict[str, Any]:
    async with engine.connect() as conn:
        table_exists = await conn.scalar(
            text("SELECT to_regclass('public.worker_heartbeats') IS NOT NULL")
        )
        if not table_exists:
            return {
                "workers": [],
                "metadata": {"table_exists": False, "active_seconds": active_seconds},
            }

        result = await conn.execute(
            text(
                """
                SELECT worker_id,
                       worker_type,
                       queue_name,
                       status,
                       current_run_id,
                       current_job_id,
                       hostname,
                       pid,
                       metadata_json,
                       last_seen_at,
                       extract(epoch FROM last_seen_at)::bigint AS last_seen_epoch
                FROM worker_heartbeats
                WHERE last_seen_at > now() - (:active_seconds * interval '1 second')
                ORDER BY last_seen_at DESC, worker_id ASC
                """
            ),
            {"active_seconds": active_seconds},
        )
        workers = [dict(row) for row in result.mappings().all()]

    return {
        "workers": workers,
        "metadata": {"table_exists": True, "active_seconds": active_seconds},
    }


@router.get("/queues")
async def get_queue_depths() -> dict[str, Any]:
    client = redis.from_url(get_settings().redis_url)
    try:
        main_depth = await client.llen(WORKFLOW_RUN_QUEUE)
        processing_depth = await client.llen(WORKFLOW_RUN_PROCESSING_QUEUE)
        dead_letter_depth = await client.llen(WORKFLOW_RUN_DEAD_QUEUE)
    finally:
        await client.aclose()

    return {
        "queue_name": "workflow_runs",
        "main_depth": int(main_depth),
        "processing_depth": int(processing_depth),
        "dead_letter_depth": int(dead_letter_depth),
    }


@router.get("/queues/workflow_runs/dead")
async def get_dead_workflow_run_jobs(
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    client = redis.from_url(get_settings().redis_url)
    try:
        raw_jobs = await client.lrange(WORKFLOW_RUN_DEAD_QUEUE, 0, limit - 1)
    finally:
        await client.aclose()

    return {
        "queue_name": "workflow_runs",
        "limit": limit,
        "items": [_decode_dead_job(raw_job) for raw_job in raw_jobs],
    }


@router.post("/queues/workflow_runs/recover")
async def recover_workflow_run_queues() -> dict[str, Any]:
    settings = get_settings()
    processing_result = await workflow_run_worker.recover_processing_workflow_run_jobs(
        redis_url=settings.redis_url
    )
    stale_runs_result = await workflow_run_worker.recover_stale_workflow_runs(
        redis_url=settings.redis_url
    )
    return {
        "processing_jobs": processing_result,
        "stale_workflow_runs": stale_runs_result,
    }


def _decode_dead_job(raw_job: str | bytes) -> dict[str, Any]:
    raw_text = raw_job.decode("utf-8") if isinstance(raw_job, bytes) else raw_job
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return {"raw": raw_text}
    return payload if isinstance(payload, dict) else {"payload": payload}
