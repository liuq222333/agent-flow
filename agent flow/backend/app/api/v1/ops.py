import json
import time
from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

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


@router.get("/workflow_runs/failed")
async def list_failed_workflow_runs(
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT
                  id AS run_id,
                  workflow_id,
                  version_id AS workflow_version_id,
                  status,
                  error_code,
                  error_message,
                  created_at,
                  updated_at
                FROM workflow_runs
                WHERE status = 'failed'
                ORDER BY updated_at DESC, id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        items = [dict(row) for row in result.mappings().all()]

    return {"items": items, "count": len(items)}


@router.post("/workflow_runs/{run_id}/recover")
async def recover_workflow_run(run_id: int) -> dict[str, Any]:
    settings = get_settings()
    client = redis.from_url(settings.redis_url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT
                      wr.id AS run_id,
                      wr.workflow_id,
                      wr.version_id AS workflow_version_id,
                      wr.status,
                      wr.error_code,
                      wr.error_message,
                      wr.metadata_json,
                      wr.created_at,
                      wr.updated_at,
                      CASE
                        WHEN wr.status = 'pending'
                         AND wr.updated_at < now() - (:stale_after_seconds * interval '1 second')
                          THEN TRUE
                        WHEN wr.status = 'running'
                         AND COALESCE(wh.last_seen_at, wr.updated_at)
                           < now() - (:stale_after_seconds * interval '1 second')
                          THEN TRUE
                        ELSE FALSE
                      END AS is_stale
                    FROM workflow_runs wr
                    LEFT JOIN worker_heartbeats wh
                      ON wh.worker_id = wr.metadata_json #>> '{worker,worker_id}'
                    WHERE wr.id = :run_id
                    FOR UPDATE OF wr
                    """
                ),
                {
                    "run_id": run_id,
                    "stale_after_seconds": workflow_run_worker.DEFAULT_STALE_RUN_SECONDS,
                },
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

            run = dict(row)
            status_value = str(run["status"])
            dead_jobs = await _find_dead_jobs_for_run(client, run_id)
            if status_value == "completed":
                return {
                    "run_id": run_id,
                    "status": status_value,
                    "recovered": False,
                    "reason": "already_completed",
                    "queued": False,
                }
            if status_value == "running" and not run["is_stale"]:
                return {
                    "run_id": run_id,
                    "status": status_value,
                    "recovered": False,
                    "reason": "already_running",
                    "queued": False,
                }
            if status_value == "pending" and not run["is_stale"] and not dead_jobs:
                return {
                    "run_id": run_id,
                    "status": status_value,
                    "recovered": False,
                    "reason": "already_pending",
                    "queued": False,
                }
            if status_value == "cancelled":
                return {
                    "run_id": run_id,
                    "status": status_value,
                    "recovered": False,
                    "reason": "cancelled",
                    "queued": False,
                }

            reason = _recover_reason(
                status_value,
                is_stale=bool(run["is_stale"]),
                dead_jobs_count=len(dead_jobs),
            )
            metadata = _ops_recovery_metadata(run.get("metadata_json"), reason)
            await conn.execute(
                text(
                    """
                    UPDATE node_runs
                    SET status = 'failed',
                        error_code = 'ops_recovery_reset',
                        error_message = 'workflow run was recovered and requeued',
                        ended_at = COALESCE(ended_at, now())
                    WHERE run_id = :run_id AND status = 'running'
                    """
                ),
                {"run_id": run_id},
            )
            updated = await conn.execute(
                _jsonb_stmt(
                    """
                    UPDATE workflow_runs
                    SET status = 'pending',
                        output_json = NULL,
                        state_json = '{}'::jsonb,
                        error_code = NULL,
                        error_message = NULL,
                        metadata_json = :metadata_json,
                        started_at = NULL,
                        ended_at = NULL,
                        updated_at = now()
                    WHERE id = :run_id
                    RETURNING id AS run_id, status
                    """,
                    "metadata_json",
                ),
                {"run_id": run_id, "metadata_json": metadata},
            )
            updated_run = dict(updated.mappings().one())

        await _remove_dead_jobs(client, dead_jobs)
        await client.lpush(WORKFLOW_RUN_QUEUE, workflow_run_worker.encode_workflow_run_job(run_id))
        return {
            "run_id": updated_run["run_id"],
            "status": updated_run["status"],
            "recovered": True,
            "reason": reason,
            "queued": True,
        }
    finally:
        await client.aclose()


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


async def _find_dead_jobs_for_run(
    client: Any,
    run_id: int,
    *,
    scan_limit: int = 1000,
) -> list[str | bytes]:
    raw_jobs = await client.lrange(WORKFLOW_RUN_DEAD_QUEUE, 0, scan_limit - 1)
    return [raw_job for raw_job in raw_jobs if _dead_job_run_id(raw_job) == run_id]


async def _remove_dead_jobs(client: Any, raw_jobs: list[str | bytes]) -> int:
    removed = 0
    for raw_job in raw_jobs:
        removed += await client.lrem(WORKFLOW_RUN_DEAD_QUEUE, 0, raw_job)
    return int(removed)


def _dead_job_run_id(raw_job: str | bytes) -> int | None:
    payload = _decode_dead_job(raw_job)
    job = payload.get("job")
    if isinstance(job, dict):
        return _coerce_run_id(job.get("run_id"))
    if isinstance(job, str):
        try:
            decoded_job = workflow_run_worker.decode_workflow_run_job_payload(job)
        except Exception:
            return None
        return _coerce_run_id(decoded_job.get("run_id"))
    return None


def _coerce_run_id(value: Any) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _recover_reason(status_value: str, *, is_stale: bool, dead_jobs_count: int) -> str:
    if dead_jobs_count > 0:
        return "dead_letter"
    if is_stale:
        return "stale"
    return status_value


def _ops_recovery_metadata(metadata_json: Any, reason: str) -> dict[str, Any]:
    metadata = dict(metadata_json or {})
    recovery_count = metadata.get("ops_recovery_count") or 0
    try:
        recovery_count = int(recovery_count)
    except (TypeError, ValueError):
        recovery_count = 0
    metadata.update(
        {
            "ops_recovery_count": recovery_count + 1,
            "last_ops_recovery_reason": reason,
            "last_ops_recovered_at_epoch": int(time.time()),
        }
    )
    return metadata


def _jsonb_stmt(sql: str, *jsonb_param_names: str):
    statement = text(sql)
    return statement.bindparams(
        *(bindparam(param_name, type_=JSONB) for param_name in jsonb_param_names)
    )
