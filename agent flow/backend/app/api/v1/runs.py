from typing import Literal

from fastapi import APIRouter, Query

from app.api.v1.schemas import RegenerateWorkflowCodeRequest, RetryRunRequest
from app.services import workflows as workflow_service

router = APIRouter(tags=["runs"])


@router.get("/workflow-versions/{version_id}")
async def get_version(version_id: int):
    return await workflow_service.get_version(version_id)


@router.get("/workflow-versions/{version_id}/code")
async def get_version_code(version_id: int):
    return await workflow_service.get_version_code(version_id)


@router.post("/workflow-versions/{version_id}/regenerate-code")
async def regenerate_version_code(
    version_id: int,
    payload: RegenerateWorkflowCodeRequest | None = None,
):
    return await workflow_service.regenerate_version_code(
        version_id,
        payload or RegenerateWorkflowCodeRequest(),
    )


@router.post("/generated-workflows/cleanup")
async def cleanup_generated_workflows(dry_run: bool = Query(default=False)):
    return await workflow_service.cleanup_generated_workflows(dry_run=dry_run)


@router.get("/runs")
async def list_runs(
    workflow_id: int | None = None,
    status: Literal["pending", "running", "completed", "failed", "cancelled"] | None = None,
    page: int = 1,
    page_size: int = 20,
):
    return await workflow_service.list_runs(
        workflow_id=workflow_id,
        run_status=status,
        page=page,
        page_size=page_size,
    )


@router.get("/runs/{run_id}")
async def get_run(run_id: int):
    return await workflow_service.get_run(run_id)


@router.get("/runs/{run_id}/node-runs")
async def list_node_runs(run_id: int):
    return await workflow_service.list_node_runs(run_id)


@router.get("/runs/{run_id}/trace")
async def get_trace(run_id: int, after_node_run_id: int | None = None):
    return await workflow_service.get_trace(run_id, after_node_run_id=after_node_run_id)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: int):
    return await workflow_service.cancel_run(run_id)


@router.post("/runs/{run_id}/retry")
async def retry_run(run_id: int, payload: RetryRunRequest | None = None):
    return await workflow_service.retry_run(run_id, payload or RetryRunRequest())
