from typing import Literal

from fastapi import APIRouter

from app.services import workflows as workflow_service

router = APIRouter(tags=["runs"])


@router.get("/workflow-versions/{version_id}")
async def get_version(version_id: int):
    return await workflow_service.get_version(version_id)


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
