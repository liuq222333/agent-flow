import asyncio
import json
import logging
from typing import Any

import redis.asyncio as redis
from sqlalchemy import text

from app.core.config import get_settings
from app.infra.db.session import engine
from app.services.runtime import execute_pending_generated_workflow_run

WORKFLOW_RUN_QUEUE = "agent_flow:workflow_runs"
logger = logging.getLogger(__name__)


def encode_workflow_run_job(run_id: int) -> str:
    return json.dumps({"run_id": int(run_id)}, separators=(",", ":"))


def decode_workflow_run_job(raw: str | bytes) -> int:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    payload = json.loads(raw)
    run_id = payload.get("run_id")
    if not isinstance(run_id, int) or run_id <= 0:
        raise ValueError("workflow run job must contain a positive integer run_id")
    return run_id


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
) -> int | None:
    client = redis.from_url(redis_url or get_settings().redis_url)
    try:
        item = await client.brpop(WORKFLOW_RUN_QUEUE, timeout=timeout_seconds)
    finally:
        await client.aclose()
    if item is None:
        return None
    _queue_name, raw_job = item
    return decode_workflow_run_job(raw_job)


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


async def run_once(*, redis_url: str | None = None, timeout_seconds: int = 5) -> bool:
    try:
        run_id = await dequeue_workflow_run(redis_url=redis_url, timeout_seconds=timeout_seconds)
    except Exception:
        logger.warning("discarding invalid workflow run job", exc_info=True)
        return True
    if run_id is None:
        return False
    try:
        await execute_workflow_run(run_id)
    except Exception:
        logger.exception("workflow run job %s failed unexpectedly", run_id)
    return True


async def run_forever(*, redis_url: str | None = None, timeout_seconds: int = 5) -> None:
    while True:
        await run_once(redis_url=redis_url, timeout_seconds=timeout_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
