from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.models import router as models_router
from app.api.v1.node_types import router as node_types_router
from app.api.v1.ops import router as ops_router
from app.api.v1.runs import router as runs_router
from app.api.v1.secrets import router as secrets_router
from app.api.v1.tools import router as tools_router
from app.api.v1.workflows import router as workflows_router
from app.core.config import get_settings
from app.infra.db.session import engine

router = APIRouter()
WORKFLOW_RUN_QUEUE = "agent_flow:workflow_runs"
WORKFLOW_RUN_PROCESSING_QUEUE = f"{WORKFLOW_RUN_QUEUE}:processing"
WORKFLOW_RUN_DEAD_QUEUE = f"{WORKFLOW_RUN_QUEUE}:dead"


@router.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "agent-workflow-api",
        "version": "0.1.0",
    }


@router.get("/ready")
async def ready() -> JSONResponse:
    settings = get_settings()
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - diagnostic endpoint
        checks["database"] = f"error:{exc.__class__.__name__}"

    try:
        client = redis.from_url(settings.redis_url)
        await client.ping()
        await client.aclose()
        checks["redis"] = "ok"
    except Exception as exc:  # pragma: no cover - diagnostic endpoint
        checks["redis"] = f"error:{exc.__class__.__name__}"

    checks["encryption_key"] = (
        "ok" if len(settings.secret_encryption_key) >= 32 else "error:too_short"
    )
    checks["default_model_provider"] = "ok" if settings.default_model_provider else "error:empty"

    is_ready = all(value == "ok" for value in checks.values())
    payload = {"status": "ready" if is_ready else "not_ready", "checks": checks}
    return JSONResponse(
        payload,
        status_code=status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> PlainTextResponse:
    settings = get_settings()
    lines = [
        "# HELP agent_flow_workflow_runs_total Workflow runs by status.",
        "# TYPE agent_flow_workflow_runs_total gauge",
        "# HELP agent_flow_node_runs_total Node runs by node type and status.",
        "# TYPE agent_flow_node_runs_total gauge",
        "# HELP agent_flow_queue_depth Redis queue depth by queue name.",
        "# TYPE agent_flow_queue_depth gauge",
        "# HELP agent_flow_queue_processing_depth Redis processing queue depth by queue name.",
        "# TYPE agent_flow_queue_processing_depth gauge",
        "# HELP agent_flow_queue_dead_letter_depth Redis dead-letter queue depth by queue name.",
        "# TYPE agent_flow_queue_dead_letter_depth gauge",
        "# HELP agent_flow_worker_active Active workers by worker type and queue.",
        "# TYPE agent_flow_worker_active gauge",
        "# HELP agent_flow_worker_last_heartbeat_timestamp Last worker heartbeat epoch seconds.",
        "# TYPE agent_flow_worker_last_heartbeat_timestamp gauge",
        "# HELP agent_flow_metrics_scrape_error Metrics scrape errors by component.",
        "# TYPE agent_flow_metrics_scrape_error gauge",
    ]

    try:
        async with engine.connect() as conn:
            workflow_rows = await conn.execute(
                text(
                    """
                    SELECT status, count(*) AS count
                    FROM workflow_runs
                    GROUP BY status
                    ORDER BY status
                    """
                )
            )
            for row in workflow_rows.mappings():
                lines.append(
                    _metric_line(
                        "agent_flow_workflow_runs_total",
                        int(row["count"]),
                        {"status": str(row["status"])},
                    )
                )

            node_rows = await conn.execute(
                text(
                    """
                    SELECT node_type, status, count(*) AS count
                    FROM node_runs
                    GROUP BY node_type, status
                    ORDER BY node_type, status
                    """
                )
            )
            for row in node_rows.mappings():
                lines.append(
                    _metric_line(
                        "agent_flow_node_runs_total",
                        int(row["count"]),
                        {"node_type": str(row["node_type"]), "status": str(row["status"])},
                    )
                )
            has_worker_heartbeats = await conn.scalar(
                text("SELECT to_regclass('public.worker_heartbeats') IS NOT NULL")
            )
            if has_worker_heartbeats:
                worker_rows = await conn.execute(
                    text(
                        """
                        SELECT worker_type, queue_name, status, count(*) AS count
                        FROM worker_heartbeats
                        WHERE last_seen_at > now() - interval '2 minutes'
                        GROUP BY worker_type, queue_name, status
                        ORDER BY worker_type, queue_name, status
                        """
                    )
                )
                for row in worker_rows.mappings():
                    lines.append(
                        _metric_line(
                            "agent_flow_worker_active",
                            int(row["count"]),
                            {
                                "worker_type": str(row["worker_type"]),
                                "queue_name": str(row["queue_name"]),
                                "status": str(row["status"]),
                            },
                        )
                    )

                heartbeat_rows = await conn.execute(
                    text(
                        """
                        SELECT worker_id, worker_type, queue_name,
                               extract(epoch FROM last_seen_at)::bigint AS last_seen_epoch
                        FROM worker_heartbeats
                        WHERE last_seen_at > now() - interval '10 minutes'
                        ORDER BY worker_id
                        """
                    )
                )
                for row in heartbeat_rows.mappings():
                    lines.append(
                        _metric_line(
                            "agent_flow_worker_last_heartbeat_timestamp",
                            int(row["last_seen_epoch"]),
                            {
                                "worker_id": str(row["worker_id"]),
                                "worker_type": str(row["worker_type"]),
                                "queue_name": str(row["queue_name"]),
                            },
                        )
                    )
                lines.append(
                    _metric_line(
                        "agent_flow_metrics_scrape_error",
                        0,
                        {"component": "worker_heartbeats"},
                    )
                )
            else:
                lines.append(
                    _metric_line(
                        "agent_flow_metrics_scrape_error",
                        1,
                        {"component": "worker_heartbeats"},
                    )
                )
        lines.append(_metric_line("agent_flow_metrics_scrape_error", 0, {"component": "database"}))
    except Exception:  # pragma: no cover - diagnostic endpoint
        lines.append(_metric_line("agent_flow_metrics_scrape_error", 1, {"component": "database"}))

    client = None
    try:
        client = redis.from_url(settings.redis_url)
        queue_depth = await client.llen(WORKFLOW_RUN_QUEUE)
        processing_depth = await client.llen(WORKFLOW_RUN_PROCESSING_QUEUE)
        dead_letter_depth = await client.llen(WORKFLOW_RUN_DEAD_QUEUE)
        lines.append(
            _metric_line(
                "agent_flow_queue_depth",
                int(queue_depth),
                {"queue_name": "workflow_runs"},
            )
        )
        lines.append(
            _metric_line(
                "agent_flow_queue_processing_depth",
                int(processing_depth),
                {"queue_name": "workflow_runs"},
            )
        )
        lines.append(
            _metric_line(
                "agent_flow_queue_dead_letter_depth",
                int(dead_letter_depth),
                {"queue_name": "workflow_runs"},
            )
        )
        lines.append(_metric_line("agent_flow_metrics_scrape_error", 0, {"component": "redis"}))
    except Exception:  # pragma: no cover - diagnostic endpoint
        lines.append(_metric_line("agent_flow_metrics_scrape_error", 1, {"component": "redis"}))
    finally:
        if client is not None:
            await client.aclose()

    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


def _metric_line(name: str, value: int | float, labels: dict[str, str]) -> str:
    label_text = ",".join(
        f'{key}="{_escape_metric_label(label_value)}"'
        for key, label_value in sorted(labels.items())
    )
    return f"{name}{{{label_text}}} {value}"


def _escape_metric_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


router.include_router(workflows_router)
router.include_router(runs_router)
router.include_router(knowledge_router)
router.include_router(tools_router)
router.include_router(models_router)
router.include_router(secrets_router)
router.include_router(node_types_router)
router.include_router(ops_router)
