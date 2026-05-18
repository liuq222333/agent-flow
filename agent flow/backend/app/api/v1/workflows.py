from typing import Literal

from fastapi import APIRouter, Query, status

from app.api.v1.schemas import (
    CreateWorkflowRequest,
    PublishWorkflowRequest,
    RunWorkflowRequest,
    UpdateWorkflowRequest,
    ValidateGraphRequest,
)
from app.services import workflows as workflow_service

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workflow(payload: CreateWorkflowRequest):
    return await workflow_service.create_workflow(payload)


@router.get("")
async def list_workflows(
    status_filter: Literal["draft", "published", "archived"] | None = Query(
        default=None,
        alias="status",
    ),
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
):
    return await workflow_service.list_workflows(
        workflow_status=status_filter,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: int):
    return await workflow_service.get_workflow(workflow_id)


@router.put("/{workflow_id}")
async def update_workflow(workflow_id: int, payload: UpdateWorkflowRequest):
    return await workflow_service.update_workflow(workflow_id, payload)


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: int):
    return await workflow_service.delete_workflow(workflow_id)


@router.post("/{workflow_id}/validate")
async def validate_workflow(workflow_id: int, payload: ValidateGraphRequest):
    await workflow_service.get_workflow(workflow_id)
    graph = payload.graph_json.model_dump(mode="json", exclude_none=True)
    return workflow_service.validate_workflow_graph(graph, payload.mode)


@router.post("/{workflow_id}/publish")
async def publish_workflow(workflow_id: int, payload: PublishWorkflowRequest):
    return await workflow_service.publish_workflow(workflow_id, payload)


@router.get("/{workflow_id}/versions")
async def list_versions(workflow_id: int, page: int = 1, page_size: int = 20):
    return await workflow_service.list_versions(workflow_id, page=page, page_size=page_size)


@router.post("/{workflow_id}/run")
async def run_workflow(workflow_id: int, payload: RunWorkflowRequest):
    return await workflow_service.run_workflow(workflow_id, payload)
