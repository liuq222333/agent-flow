from typing import Literal

from fastapi import APIRouter, Query

from app.api.v1.schemas import CancelHumanApprovalRequest, SubmitHumanApprovalRequest
from app.services import human_approvals as approval_service

router = APIRouter(tags=["human-approvals"])


@router.get("/human-approval-tasks")
async def list_human_approval_tasks(
    status: Literal["pending", "approved", "rejected", "cancelled", "expired"] | None = None,
    workflow_id: int | None = None,
    run_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return await approval_service.list_human_approval_tasks(
        task_status=status,
        workflow_id=workflow_id,
        run_id=run_id,
        page=page,
        page_size=page_size,
    )


@router.get("/human-approval-tasks/{task_id}")
async def get_human_approval_task(task_id: int):
    return await approval_service.get_human_approval_task(task_id)


@router.post("/human-approval-tasks/{task_id}/submit")
async def submit_human_approval_task(
    task_id: int,
    payload: SubmitHumanApprovalRequest,
):
    return await approval_service.submit_human_approval_task(task_id, payload)


@router.post("/human-approval-tasks/{task_id}/cancel")
async def cancel_human_approval_task(
    task_id: int,
    payload: CancelHumanApprovalRequest | None = None,
):
    return await approval_service.cancel_human_approval_task(
        task_id,
        payload or CancelHumanApprovalRequest(),
    )
