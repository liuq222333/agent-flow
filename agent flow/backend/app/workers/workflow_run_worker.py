import asyncio
import contextlib
import json
import logging
import os
import socket
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import redis.asyncio as redis
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from app.core.config import get_settings
from app.infra.db.session import engine
from app.services.runtime import execute_pending_generated_workflow_run

WORKFLOW_RUN_QUEUE = "agent_flow:workflow_runs"
WORKFLOW_RUN_PROCESSING_QUEUE = f"{WORKFLOW_RUN_QUEUE}:processing"
WORKFLOW_RUN_DEAD_QUEUE = f"{WORKFLOW_RUN_QUEUE}:dead"
DEFAULT_RECOVERY_INTERVAL_SECONDS = 60
DEFAULT_STALE_RUN_SECONDS = 15 * 60
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 10
DEFAULT_LEASE_SECONDS = 60
MAX_QUEUE_ATTEMPTS = 3
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkflowRunJob:
    run_id: int
    raw: str
    job_id: str | None = None
    queue_attempt: int = 1
    enqueued_at_epoch: int | None = None


def encode_workflow_run_job(
    run_id: int,
    *,
    job_id: str | None = None,
    queue_attempt: int = 1,
    enqueued_at_epoch: int | None = None,
) -> str:
    payload = {
        "job_id": job_id or f"wrj_{uuid4().hex}",
        "run_id": int(run_id),
        "queue_name": "workflow_runs",
        "enqueued_at_epoch": enqueued_at_epoch or int(time.time()),
        "queue_attempt": max(int(queue_attempt), 1),
    }
    return json.dumps(payload, separators=(",", ":"))


def decode_workflow_run_job(raw: str | bytes) -> int:
    return decode_workflow_run_job_payload(raw)["run_id"]


def decode_workflow_run_job_payload(raw: str | bytes) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    payload = json.loads(raw)
    run_id = payload.get("run_id")
    if not isinstance(run_id, int) or run_id <= 0:
        raise ValueError("workflow run job must contain a positive integer run_id")
    queue_attempt = payload.get("queue_attempt", 1)
    if not isinstance(queue_attempt, int) or queue_attempt <= 0:
        payload["queue_attempt"] = 1
    return payload


def decode_workflow_run_job_record(raw: str | bytes) -> WorkflowRunJob:
    raw_text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    payload = decode_workflow_run_job_payload(raw_text)
    return WorkflowRunJob(
        run_id=int(payload["run_id"]),
        raw=raw_text,
        job_id=payload.get("job_id") if isinstance(payload.get("job_id"), str) else None,
        queue_attempt=int(payload.get("queue_attempt") or 1),
        enqueued_at_epoch=(
            int(payload["enqueued_at_epoch"])
            if isinstance(payload.get("enqueued_at_epoch"), int)
            else None
        ),
    )


async def enqueue_workflow_run(run_id: int, *, redis_url: str | None = None) -> None:
    client = redis.from_url(redis_url or get_settings().redis_url)
    try:
        await client.lpush(WORKFLOW_RUN_QUEUE, encode_workflow_run_job(run_id))
    finally:
        await client.aclose()


async def dequeue_workflow_run(
    *,
    redis_url: str | None = None,
    timeout_seconds: int = 5,
) -> WorkflowRunJob | None:
    client = redis.from_url(redis_url or get_settings().redis_url)
    try:
        raw_job = await client.brpoplpush(
            WORKFLOW_RUN_QUEUE,
            WORKFLOW_RUN_PROCESSING_QUEUE,
            timeout=timeout_seconds,
        )
        if raw_job is None:
            return None
        try:
            return decode_workflow_run_job_record(raw_job)
        except Exception as exc:
            await _move_raw_processing_job_to_dead(
                client,
                raw_job,
                reason="invalid_payload",
                error_message=str(exc),
            )
            raise
    finally:
        await client.aclose()


async def ack_workflow_run_job(
    job: WorkflowRunJob,
    *,
    redis_url: str | None = None,
) -> None:
    client = redis.from_url(redis_url or get_settings().redis_url)
    try:
        await client.lrem(WORKFLOW_RUN_PROCESSING_QUEUE, 1, job.raw)
    finally:
        await client.aclose()


async def retry_or_dead_letter_workflow_run_job(
    job: WorkflowRunJob,
    *,
    redis_url: str | None = None,
    reason: str,
    error_message: str | None = None,
    max_attempts: int = MAX_QUEUE_ATTEMPTS,
) -> str:
    client = redis.from_url(redis_url or get_settings().redis_url)
    try:
        await client.lrem(WORKFLOW_RUN_PROCESSING_QUEUE, 1, job.raw)
        if job.queue_attempt >= max_attempts:
            await _push_dead_workflow_run_job(
                client,
                job,
                reason=reason,
                error_message=error_message,
            )
            return "dead"
        await client.lpush(
            WORKFLOW_RUN_QUEUE,
            encode_workflow_run_job(
                job.run_id,
                job_id=job.job_id,
                queue_attempt=job.queue_attempt + 1,
            ),
        )
        return "requeued"
    finally:
        await client.aclose()


async def execute_workflow_run(run_id: int) -> dict[str, Any]:
    async with engine.begin() as conn:
        status = await conn.scalar(
            text("SELECT status FROM workflow_runs WHERE id = :run_id"),
            {"run_id": run_id},
        )
        if status == "cancelled":
            logger.info("skipping cancelled workflow run %s", run_id)
            return {"id": run_id, "status": "cancelled", "skipped": True}
        return await execute_pending_generated_workflow_run(conn, run_id=run_id)


def build_worker_id() -> str:
    hostname = socket.gethostname() or "unknown-host"
    return f"workflow-worker:{hostname}:{os.getpid()}:{uuid4().hex[:12]}"


async def claim_workflow_run(
    run_id: int,
    *,
    worker_id: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> dict[str, Any] | None:
    lease_seconds = max(int(lease_seconds), 1)
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT id, status, metadata_json
                FROM workflow_runs
                WHERE id = :run_id
                FOR UPDATE
                """
            ),
            {"run_id": run_id},
        )
        row = result.mappings().one_or_none()
        if row is None or row["status"] not in {"pending", "running"}:
            return None
        metadata = _claim_metadata(row.get("metadata_json"), worker_id, lease_seconds)
        updated = await conn.execute(
            _jsonb_stmt(
                """
                UPDATE workflow_runs
                SET metadata_json = :metadata_json,
                    updated_at = now()
                WHERE id = :run_id
                RETURNING id, status, metadata_json
                """,
                "metadata_json",
            ),
            {"run_id": run_id, "metadata_json": metadata},
        )
        return dict(updated.mappings().one())


async def write_worker_heartbeat(
    worker_id: str,
    *,
    status_value: str,
    current_run_id: int | None = None,
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
                  current_run_id,
                  current_job_id,
                  hostname,
                  pid,
                  metadata_json
                )
                VALUES (
                  :worker_id,
                  'workflow',
                  'workflow_runs',
                  :status,
                  :current_run_id,
                  :current_job_id,
                  :hostname,
                  :pid,
                  :metadata_json
                )
                ON CONFLICT (worker_id) DO UPDATE
                SET status = EXCLUDED.status,
                    current_run_id = EXCLUDED.current_run_id,
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
                "status": status_value,
                "current_run_id": current_run_id,
                "current_job_id": current_job_id,
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "metadata_json": metadata_json or {},
            },
        )


async def recover_stale_workflow_runs(
    *,
    redis_url: str | None = None,
    stale_after_seconds: int = DEFAULT_STALE_RUN_SECONDS,
    limit: int = 50,
) -> dict[str, list[int]]:
    stale_after_seconds = max(int(stale_after_seconds), 1)
    limit = min(max(int(limit), 1), 500)
    requeue_run_ids: list[int] = []
    failed_run_ids: list[int] = []
    requeue_error_run_ids: list[int] = []

    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT wr.id, wr.status, wr.metadata_json
                FROM workflow_runs wr
                LEFT JOIN worker_heartbeats wh
                  ON wh.worker_id = wr.metadata_json #>> '{worker,worker_id}'
                WHERE wr.status IN ('pending', 'running')
                  AND COALESCE(wr.metadata_json->>'execution_mode', '') = 'async'
                  AND (
                    (
                      wr.status = 'pending'
                      AND wr.updated_at < now() - (:stale_after_seconds * interval '1 second')
                    )
                    OR (
                      wr.status = 'running'
                      AND COALESCE(wh.last_seen_at, wr.updated_at)
                        < now() - (:stale_after_seconds * interval '1 second')
                    )
                  )
                ORDER BY wr.updated_at ASC, wr.id ASC
                LIMIT :limit
                FOR UPDATE OF wr SKIP LOCKED
                """
            ),
            {"stale_after_seconds": stale_after_seconds, "limit": limit},
        )
        rows = [dict(row) for row in result.mappings().all()]

        for row in rows:
            run_id = int(row["id"])
            metadata = _recovery_metadata(row.get("metadata_json"), row["status"])

            if row["status"] == "pending":
                await conn.execute(
                    _jsonb_stmt(
                        """
                        UPDATE workflow_runs
                        SET metadata_json = :metadata_json,
                            updated_at = now()
                        WHERE id = :run_id
                        """,
                        "metadata_json",
                    ),
                    {"run_id": run_id, "metadata_json": metadata},
                )
                requeue_run_ids.append(run_id)
                continue

            await conn.execute(
                text(
                    """
                    UPDATE node_runs
                    SET status = 'failed',
                        error_code = 'worker_lost',
                        error_message = 'worker stopped before finishing this node',
                        ended_at = COALESCE(ended_at, now())
                    WHERE run_id = :run_id AND status = 'running'
                    """
                ),
                {"run_id": run_id},
            )
            await conn.execute(
                _jsonb_stmt(
                    """
                    UPDATE workflow_runs
                    SET status = 'failed',
                        error_code = 'worker_lost',
                        error_message = :error_message,
                        metadata_json = :metadata_json,
                        ended_at = COALESCE(ended_at, now()),
                        updated_at = now()
                    WHERE id = :run_id
                    """,
                    "metadata_json",
                ),
                {
                    "run_id": run_id,
                    "error_message": (
                        "async workflow run was stale; worker likely exited before completion"
                    ),
                    "metadata_json": metadata,
                },
            )
            failed_run_ids.append(run_id)

    for run_id in requeue_run_ids:
        try:
            await enqueue_workflow_run(run_id, redis_url=redis_url)
        except Exception:
            logger.exception("failed to requeue stale pending workflow run %s", run_id)
            requeue_error_run_ids.append(run_id)

    if requeue_run_ids or failed_run_ids or requeue_error_run_ids:
        logger.info(
            "recovered stale workflow runs: requeued=%s failed=%s requeue_errors=%s",
            requeue_run_ids,
            failed_run_ids,
            requeue_error_run_ids,
        )
    return {
        "requeued": requeue_run_ids,
        "failed": failed_run_ids,
        "requeue_errors": requeue_error_run_ids,
    }


async def recover_processing_workflow_run_jobs(
    *,
    redis_url: str | None = None,
    stale_after_seconds: int = DEFAULT_STALE_RUN_SECONDS,
    limit: int = 100,
) -> dict[str, list[int] | int]:
    stale_after_seconds = max(int(stale_after_seconds), 1)
    limit = min(max(int(limit), 1), 500)
    requeued: list[int] = []
    acked_terminal: list[int] = []
    invalid_payloads = 0
    skipped_running: list[int] = []
    now_epoch = int(time.time())

    client = redis.from_url(redis_url or get_settings().redis_url)
    try:
        raw_jobs = await client.lrange(WORKFLOW_RUN_PROCESSING_QUEUE, 0, limit - 1)
        for raw_job in raw_jobs:
            raw_text = raw_job.decode("utf-8") if isinstance(raw_job, bytes) else raw_job
            try:
                job = decode_workflow_run_job_record(raw_text)
            except Exception as exc:
                await _move_raw_processing_job_to_dead(
                    client,
                    raw_text,
                    reason="invalid_payload",
                    error_message=str(exc),
                )
                invalid_payloads += 1
                continue

            if not _processing_job_is_stale(job, now_epoch, stale_after_seconds):
                continue

            async with engine.connect() as conn:
                status_value = await conn.scalar(
                    text("SELECT status FROM workflow_runs WHERE id = :run_id"),
                    {"run_id": job.run_id},
                )

            if (
                status_value in {"completed", "failed", "cancelled", "waiting_approval"}
                or status_value is None
            ):
                await client.lrem(WORKFLOW_RUN_PROCESSING_QUEUE, 1, job.raw)
                acked_terminal.append(job.run_id)
                continue

            if status_value == "pending":
                await client.lrem(WORKFLOW_RUN_PROCESSING_QUEUE, 1, job.raw)
                if job.queue_attempt >= MAX_QUEUE_ATTEMPTS:
                    await _push_dead_workflow_run_job(
                        client,
                        job,
                        reason="processing_recovery_attempt_exhausted",
                    )
                else:
                    await client.lpush(
                        WORKFLOW_RUN_QUEUE,
                        encode_workflow_run_job(
                            job.run_id,
                            job_id=job.job_id,
                            queue_attempt=job.queue_attempt + 1,
                        ),
                    )
                    requeued.append(job.run_id)
                continue

            if status_value == "running":
                skipped_running.append(job.run_id)

    finally:
        await client.aclose()

    return {
        "requeued": requeued,
        "acked_terminal": acked_terminal,
        "skipped_running": skipped_running,
        "invalid_payloads": invalid_payloads,
    }


async def run_once(
    *,
    redis_url: str | None = None,
    timeout_seconds: int = 5,
    worker_id: str | None = None,
    heartbeat_interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> bool:
    try:
        job_or_run_id = await dequeue_workflow_run(
            redis_url=redis_url,
            timeout_seconds=timeout_seconds,
        )
    except Exception:
        logger.warning("discarding invalid workflow run job", exc_info=True)
        return True
    if job_or_run_id is None:
        return False
    job = _coerce_workflow_run_job(job_or_run_id)
    run_id = job.run_id
    heartbeat_task: asyncio.Task[None] | None = None
    executed_without_crash = False
    try:
        if worker_id:
            await claim_workflow_run(run_id, worker_id=worker_id, lease_seconds=lease_seconds)
            await write_worker_heartbeat(
                worker_id,
                status_value="busy",
                current_run_id=run_id,
                current_job_id=job.job_id,
            )
            heartbeat_task = asyncio.create_task(
                _heartbeat_loop(worker_id, run_id, heartbeat_interval_seconds, job.job_id)
            )
        await execute_workflow_run(run_id)
        executed_without_crash = True
    except Exception:
        logger.exception("workflow run job %s failed unexpectedly", run_id)
        if job.raw:
            try:
                await retry_or_dead_letter_workflow_run_job(
                    job,
                    redis_url=redis_url,
                    reason="worker_execution_exception",
                )
            except Exception:
                logger.exception("failed to requeue or dead-letter workflow run job %s", run_id)
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
        if worker_id:
            await write_worker_heartbeat(worker_id, status_value="idle")
    if executed_without_crash and job.raw:
        await ack_workflow_run_job(job, redis_url=redis_url)
    return True


async def run_forever(
    *,
    redis_url: str | None = None,
    timeout_seconds: int = 5,
    recovery_interval_seconds: int = DEFAULT_RECOVERY_INTERVAL_SECONDS,
    stale_after_seconds: int = DEFAULT_STALE_RUN_SECONDS,
    heartbeat_interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> None:
    worker_id = build_worker_id()
    await write_worker_heartbeat(worker_id, status_value="idle")
    last_recovery_at = 0.0
    last_idle_heartbeat_at = 0.0
    while True:
        now = time.monotonic()
        if recovery_interval_seconds > 0 and now - last_recovery_at >= recovery_interval_seconds:
            last_recovery_at = now
            try:
                await recover_processing_workflow_run_jobs(
                    redis_url=redis_url,
                    stale_after_seconds=stale_after_seconds,
                )
                await recover_stale_workflow_runs(
                    redis_url=redis_url,
                    stale_after_seconds=stale_after_seconds,
                )
            except Exception:
                logger.exception("stale workflow run recovery failed")
        idle_heartbeat_due = (
            heartbeat_interval_seconds > 0
            and now - last_idle_heartbeat_at >= heartbeat_interval_seconds
        )
        if idle_heartbeat_due:
            last_idle_heartbeat_at = now
            await write_worker_heartbeat(worker_id, status_value="idle")
        await run_once(
            redis_url=redis_url,
            timeout_seconds=timeout_seconds,
            worker_id=worker_id,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            lease_seconds=lease_seconds,
        )


async def _heartbeat_loop(
    worker_id: str,
    run_id: int,
    interval_seconds: int,
    job_id: str | None,
) -> None:
    interval_seconds = max(int(interval_seconds), 1)
    while True:
        await asyncio.sleep(interval_seconds)
        await write_worker_heartbeat(
            worker_id,
            status_value="busy",
            current_run_id=run_id,
            current_job_id=job_id,
        )


def _coerce_workflow_run_job(job_or_run_id: WorkflowRunJob | int) -> WorkflowRunJob:
    if isinstance(job_or_run_id, WorkflowRunJob):
        return job_or_run_id
    return WorkflowRunJob(run_id=int(job_or_run_id), raw="")


def _processing_job_is_stale(
    job: WorkflowRunJob,
    now_epoch: int,
    stale_after_seconds: int,
) -> bool:
    if job.enqueued_at_epoch is None:
        return True
    return now_epoch - job.enqueued_at_epoch >= stale_after_seconds


async def _push_dead_workflow_run_job(
    client: Any,
    job: WorkflowRunJob,
    *,
    reason: str,
    error_message: str | None = None,
) -> None:
    payload = {
        "job": decode_workflow_run_job_payload(job.raw) if job.raw else {"run_id": job.run_id},
        "dead_reason": reason,
        "dead_at_epoch": int(time.time()),
        "last_error": error_message,
    }
    await client.lpush(WORKFLOW_RUN_DEAD_QUEUE, json.dumps(payload, separators=(",", ":")))


async def _move_raw_processing_job_to_dead(
    client: Any,
    raw_job: str | bytes,
    *,
    reason: str,
    error_message: str | None = None,
) -> None:
    raw_text = raw_job.decode("utf-8") if isinstance(raw_job, bytes) else raw_job
    await client.lrem(WORKFLOW_RUN_PROCESSING_QUEUE, 1, raw_text)
    payload = {
        "job": raw_text,
        "dead_reason": reason,
        "dead_at_epoch": int(time.time()),
        "last_error": error_message,
    }
    await client.lpush(WORKFLOW_RUN_DEAD_QUEUE, json.dumps(payload, separators=(",", ":")))


def _claim_metadata(
    metadata_json: Any,
    worker_id: str,
    lease_seconds: int,
) -> dict[str, Any]:
    metadata = dict(metadata_json or {})
    worker_metadata = dict(metadata.get("worker") or {})
    claim_count = worker_metadata.get("claim_count") or 0
    try:
        claim_count = int(claim_count)
    except (TypeError, ValueError):
        claim_count = 0
    now_seconds = int(time.time())
    worker_metadata.update(
        {
            "worker_id": worker_id,
            "queue_name": "workflow_runs",
            "claimed_at_epoch": now_seconds,
            "lease_expires_at_epoch": now_seconds + lease_seconds,
            "claim_count": claim_count + 1,
        }
    )
    metadata["worker"] = worker_metadata
    return metadata


def _recovery_metadata(metadata_json: Any, status_value: str) -> dict[str, Any]:
    metadata = dict(metadata_json or {})
    recovery_count = metadata.get("worker_recovery_count") or 0
    try:
        recovery_count = int(recovery_count)
    except (TypeError, ValueError):
        recovery_count = 0
    metadata.update(
        {
            "worker_recovery_count": recovery_count + 1,
            "last_worker_recovery_status": status_value,
            "last_worker_recovery_reason": "stale_async_run",
        }
    )
    return metadata


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
