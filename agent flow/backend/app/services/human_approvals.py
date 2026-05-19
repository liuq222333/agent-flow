from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.v1.schemas import SubmitHumanApprovalRequest
from app.core.config import get_settings
from app.infra.db.session import engine
from app.services.audit import write_audit_log

PENDING_STATUS = "pending"


async def list_human_approval_tasks(
    *,
    task_status: str | None = None,
    workflow_id: int | None = None,
    run_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    where = ["1 = 1"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if task_status:
        where.append("status = :status")
        params["status"] = task_status
    if workflow_id is not None:
        where.append("workflow_id = :workflow_id")
        params["workflow_id"] = workflow_id
    if run_id is not None:
        where.append("run_id = :run_id")
        params["run_id"] = run_id
    where_sql = " AND ".join(where)

    async with engine.connect() as conn:
        total = await conn.scalar(
            text(f"SELECT count(*) FROM human_approval_tasks WHERE {where_sql}"),
            params,
        )
        result = await conn.execute(
            text(
                f"""
                SELECT *
                FROM human_approval_tasks
                WHERE {where_sql}
                ORDER BY created_at DESC, id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        return {
            "items": [dict(row) for row in result.mappings()],
            "page": page,
            "page_size": page_size,
            "total": total or 0,
        }


async def get_human_approval_task(task_id: int) -> dict[str, Any]:
    async with engine.connect() as conn:
        return await _get_task_row(conn, task_id)


async def submit_human_approval_task(
    task_id: int,
    payload: SubmitHumanApprovalRequest,
) -> dict[str, Any]:
    settings = get_settings()
    decision_status = "approved" if payload.decision == "approve" else "rejected"
    response_json = {
        "decision": payload.decision,
        "response": payload.response,
        "comment": payload.comment,
    }
    async with engine.begin() as conn:
        task = await _get_task_row_for_update(conn, task_id)
        if task["status"] != PENDING_STATUS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "human_approval_task_not_pending",
                    "message": "human approval task is not pending",
                    "status": task["status"],
                },
            )

        result = await conn.execute(
            _jsonb_stmt(
                """
                UPDATE human_approval_tasks
                SET status = :status,
                    decision = :decision,
                    response_json = :response_json,
                    decided_by = :decided_by,
                    decided_at = now(),
                    updated_at = now()
                WHERE id = :task_id
                RETURNING *
                """,
                "response_json",
            ),
            {
                "task_id": task_id,
                "status": decision_status,
                "decision": payload.decision,
                "response_json": response_json,
                "decided_by": settings.mock_user_id,
            },
        )
        updated = dict(result.mappings().one())
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="human_approval.submit",
            resource_type="human_approval_task",
            resource_id=updated["id"],
            detail={
                "workflow_id": updated["workflow_id"],
                "run_id": updated["run_id"],
                "node_id": updated["node_id"],
                "decision": payload.decision,
                "resume_supported": False,
            },
        )
        return {**updated, "resume_supported": False}


async def create_human_approval_task(
    conn: AsyncConnection,
    *,
    workflow_id: int,
    run_id: int,
    node_id: str,
    node_name: str | None,
    title: str,
    description: str | None,
    input_json: dict[str, Any],
    requested_by: int | None,
    metadata_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = await conn.execute(
        _jsonb_stmt(
            """
            INSERT INTO human_approval_tasks (
              workflow_id,
              run_id,
              node_id,
              node_name,
              title,
              description,
              status,
              input_json,
              requested_by,
              metadata_json
            )
            VALUES (
              :workflow_id,
              :run_id,
              :node_id,
              :node_name,
              :title,
              :description,
              'pending',
              :input_json,
              :requested_by,
              :metadata_json
            )
            RETURNING *
            """,
            "input_json",
            "metadata_json",
        ),
        {
            "workflow_id": workflow_id,
            "run_id": run_id,
            "node_id": node_id,
            "node_name": node_name,
            "title": title,
            "description": description,
            "input_json": input_json,
            "requested_by": requested_by,
            "metadata_json": metadata_json or {},
        },
    )
    task = dict(result.mappings().one())
    await conn.execute(
        text(
            """
            UPDATE workflow_runs
            SET status = 'waiting_approval',
                metadata_json = COALESCE(metadata_json, '{}'::jsonb) || :metadata_json,
                updated_at = now()
            WHERE id = :run_id
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "run_id": run_id,
            "metadata_json": {
                "waiting_approval_task_id": task["id"],
                "waiting_approval_node_id": node_id,
            },
        },
    )
    return task


async def _get_task_row(conn: AsyncConnection, task_id: int) -> dict[str, Any]:
    result = await conn.execute(
        text("SELECT * FROM human_approval_tasks WHERE id = :task_id"),
        {"task_id": task_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="human approval task not found",
        )
    return dict(row)


async def _get_task_row_for_update(conn: AsyncConnection, task_id: int) -> dict[str, Any]:
    result = await conn.execute(
        text(
            """
            SELECT *
            FROM human_approval_tasks
            WHERE id = :task_id
            FOR UPDATE
            """
        ),
        {"task_id": task_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="human approval task not found",
        )
    return dict(row)


def _jsonb_stmt(sql: str, *jsonb_param_names: str):
    statement = text(sql)
    for name in jsonb_param_names:
        statement = statement.bindparams(bindparam(name, type_=JSONB))
    return statement
