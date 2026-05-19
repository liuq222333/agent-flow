import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from app.api.v1.schemas import (
    CreateWorkflowRequest,
    PublishWorkflowRequest,
    RegenerateWorkflowCodeRequest,
    RetryRunRequest,
    RunWorkflowRequest,
    UpdateWorkflowRequest,
)
from app.core.config import get_settings
from app.infra.db.session import engine
from app.services.audit import write_audit_log
from app.services.graph_validation import default_graph, validate_graph
from app.services.runtime import (
    create_generated_workflow_run_pending,
    execute_generated_workflow_sync,
)
from app.services.workflow_codegen import (
    WorkflowCodeArtifact,
    cleanup_generated_workflow_dirs,
    generate_workflow_code,
    generated_workflow_version_dir,
    inspect_workflow_code,
    read_workflow_code_source,
    remove_generated_workflow_version,
    resolve_generated_code_path,
)


async def create_workflow(payload: CreateWorkflowRequest) -> dict[str, Any]:
    settings = get_settings()
    graph = _graph_or_default(payload.draft_graph_json)
    async with engine.begin() as conn:
        await _ensure_mock_user(conn, settings.mock_user_id)
        result = await conn.execute(
            _jsonb_stmt(
                """
                INSERT INTO workflows (
                  name,
                  description,
                  status,
                  draft_graph_json,
                  created_by,
                  updated_by
                )
                VALUES (:name, :description, 'draft', :draft_graph_json, :user_id, :user_id)
                RETURNING *
                """,
                "draft_graph_json",
            ),
            {
                "name": payload.name,
                "description": payload.description,
                "draft_graph_json": graph,
                "user_id": settings.mock_user_id,
            },
        )
        workflow = dict(result.mappings().one())
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="workflow.create",
            resource_type="workflow",
            resource_id=workflow["id"],
            detail={"name": workflow["name"], "status": workflow["status"]},
        )
        return workflow


async def list_workflows(
    *,
    workflow_status: str | None,
    keyword: str | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    where = ["w.deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if workflow_status:
        where.append("w.status = :status")
        params["status"] = workflow_status
    if keyword:
        where.append("w.name ILIKE :keyword")
        params["keyword"] = f"%{keyword}%"
    where_sql = " AND ".join(where)

    async with engine.connect() as conn:
        total = await conn.scalar(
            text(f"SELECT count(*) FROM workflows w WHERE {where_sql}"),
            params,
        )
        result = await conn.execute(
            text(
                f"""
                SELECT
                  w.*,
                  v.version AS current_version,
                  lr.id AS latest_run_id,
                  lr.status AS latest_run_status,
                  lr.created_at AS latest_run_created_at
                FROM workflows w
                LEFT JOIN workflow_versions v ON v.id = w.current_version_id
                LEFT JOIN LATERAL (
                  SELECT id, status, created_at
                  FROM workflow_runs
                  WHERE workflow_id = w.id
                  ORDER BY created_at DESC
                  LIMIT 1
                ) lr ON TRUE
                WHERE {where_sql}
                ORDER BY w.updated_at DESC, w.id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = []
        for row in result.mappings():
            item = dict(row)
            item["latest_run"] = (
                {
                    "run_id": item.pop("latest_run_id"),
                    "status": item.pop("latest_run_status"),
                    "created_at": item.pop("latest_run_created_at"),
                }
                if item.get("latest_run_id")
                else None
            )
            item.pop("latest_run_id", None)
            item.pop("latest_run_status", None)
            item.pop("latest_run_created_at", None)
            items.append(item)
        return {"items": items, "page": page, "page_size": page_size, "total": total or 0}


async def get_workflow(workflow_id: int) -> dict[str, Any]:
    async with engine.connect() as conn:
        row = await _get_workflow_row(conn, workflow_id)
        return row


async def update_workflow(workflow_id: int, payload: UpdateWorkflowRequest) -> dict[str, Any]:
    settings = get_settings()
    async with engine.begin() as conn:
        current = await _get_workflow_row(conn, workflow_id)
        graph = (
            payload.draft_graph_json.model_dump(mode="json", exclude_none=True)
            if payload.draft_graph_json is not None
            else current["draft_graph_json"]
        )
        result = await conn.execute(
            _jsonb_stmt(
                """
                UPDATE workflows
                SET name = :name,
                    description = :description,
                    draft_graph_json = :draft_graph_json,
                    updated_by = :updated_by,
                    updated_at = now()
                WHERE id = :workflow_id AND deleted_at IS NULL
                RETURNING *
                """,
                "draft_graph_json",
            ),
            {
                "workflow_id": workflow_id,
                "name": payload.name if payload.name is not None else current["name"],
                "description": (
                    payload.description
                    if "description" in payload.model_fields_set
                    else current["description"]
                ),
                "draft_graph_json": graph,
                "updated_by": settings.mock_user_id,
            },
        )
        workflow = dict(result.mappings().one())
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="workflow.update",
            resource_type="workflow",
            resource_id=workflow["id"],
            detail={"name": workflow["name"], "status": workflow["status"]},
        )
        return workflow


async def delete_workflow(workflow_id: int) -> dict[str, bool]:
    settings = get_settings()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                UPDATE workflows
                SET status = 'archived',
                    deleted_at = now(),
                    updated_at = now()
                WHERE id = :workflow_id AND deleted_at IS NULL
                RETURNING id
                """
            ),
            {"workflow_id": workflow_id},
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workflow not found")
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="workflow.delete",
            resource_type="workflow",
            resource_id=workflow_id,
        )
    return {"success": True}


async def publish_workflow(
    workflow_id: int,
    payload: PublishWorkflowRequest,
) -> dict[str, Any]:
    settings = get_settings()
    artifact: WorkflowCodeArtifact | None = None
    try:
        async with engine.begin() as conn:
            workflow = await _get_workflow_row_for_update(conn, workflow_id)
            graph = workflow["draft_graph_json"] or default_graph()
            validation = validate_graph(graph, "publish")
            if not validation["valid"]:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=validation,
                )

            next_version = await conn.scalar(
                text(
                    """
                    SELECT COALESCE(max(version), 0) + 1
                    FROM workflow_versions
                    WHERE workflow_id = :workflow_id
                    """
                ),
                {"workflow_id": workflow_id},
            )
            graph_hash = hashlib.sha256(
                json.dumps(graph, sort_keys=True).encode("utf-8")
            ).hexdigest()
            artifact = await _generate_workflow_code_with_cleanup(
                conn,
                workflow_id=workflow_id,
                version=int(next_version),
                graph=graph,
                graph_hash=graph_hash,
            )
            result = await conn.execute(
                _jsonb_stmt(
                    """
                    INSERT INTO workflow_versions (
                      workflow_id,
                      version,
                      schema_version,
                      graph_json,
                      graph_hash,
                      code_path,
                      code_hash,
                      code_generated_at,
                      release_note,
                      published_by
                    )
                    VALUES (
                      :workflow_id,
                      :version,
                      :schema_version,
                      :graph_json,
                      :graph_hash,
                      :code_path,
                      :code_hash,
                      :code_generated_at,
                      :release_note,
                      :published_by
                    )
                    RETURNING *
                    """,
                    "graph_json",
                ),
                {
                    "workflow_id": workflow_id,
                    "version": next_version,
                    "schema_version": graph.get("schema_version", "1.0"),
                    "graph_json": graph,
                    "graph_hash": graph_hash,
                    "code_path": artifact.code_path,
                    "code_hash": artifact.code_hash,
                    "code_generated_at": artifact.code_generated_at,
                    "release_note": payload.release_note,
                    "published_by": settings.mock_user_id,
                },
            )
            version = dict(result.mappings().one())
            await conn.execute(
                text(
                    """
                    UPDATE workflows
                    SET status = 'published',
                        current_version_id = :version_id,
                        updated_by = :user_id,
                        updated_at = now()
                    WHERE id = :workflow_id
                    """
                ),
                {
                    "workflow_id": workflow_id,
                    "version_id": version["id"],
                    "user_id": settings.mock_user_id,
                },
            )
            await write_audit_log(
                conn,
                actor_user_id=settings.mock_user_id,
                action="workflow.publish",
                resource_type="workflow",
                resource_id=workflow_id,
                detail={"version_id": version["id"], "version": version["version"]},
            )
            return {
                "workflow_id": workflow_id,
                "version_id": version["id"],
                "version": version["version"],
                "schema_version": version["schema_version"],
                "code_path": version["code_path"],
                "code_hash": version["code_hash"],
                "code_generated_at": version["code_generated_at"],
                "created_at": version["created_at"],
            }
    except Exception:
        if artifact is not None:
            remove_generated_workflow_version(artifact.version_dir)
        raise


async def list_versions(workflow_id: int, *, page: int, page_size: int) -> dict[str, Any]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    async with engine.connect() as conn:
        await _get_workflow_row(conn, workflow_id)
        total = await conn.scalar(
            text("SELECT count(*) FROM workflow_versions WHERE workflow_id = :workflow_id"),
            {"workflow_id": workflow_id},
        )
        result = await conn.execute(
            text(
                """
                SELECT
                  id,
                  workflow_id,
                  version,
                  schema_version,
                  release_note,
                  published_by,
                  code_path,
                  code_hash,
                  code_generated_at,
                  created_at
                FROM workflow_versions
                WHERE workflow_id = :workflow_id
                ORDER BY version DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"workflow_id": workflow_id, "limit": page_size, "offset": (page - 1) * page_size},
        )
        return {
            "items": [_with_code_inspection(dict(row)) for row in result.mappings()],
            "page": page,
            "page_size": page_size,
            "total": total or 0,
        }


async def get_version(version_id: int) -> dict[str, Any]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT * FROM workflow_versions WHERE id = :version_id"),
            {"version_id": version_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="workflow version not found",
            )
        return _with_code_inspection(dict(row))


async def get_version_code(version_id: int) -> dict[str, Any]:
    async with engine.begin() as conn:
        version = await _get_version_row(conn, version_id)
        inspection = inspect_workflow_code(version.get("code_path"), version.get("code_hash"))
        if inspection.code_status in {"missing_metadata", "missing_file"}:
            version = await _ensure_version_code(conn, version)
        try:
            code = read_workflow_code_source(version["code_path"], version.get("code_hash"))
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "workflow_code_missing", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "workflow_code_invalid_path", "message": str(exc)},
            ) from exc
        return {
            "id": version["id"],
            "workflow_id": version["workflow_id"],
            "version": version["version"],
            "schema_version": version["schema_version"],
            "code_path": code.code_path,
            "code_hash": version.get("code_hash"),
            "code_hash_actual": code.code_hash_actual,
            "code_modified": code.code_modified,
            "code_status": code.code_status,
            "code_generated_at": version.get("code_generated_at"),
            "source": code.source,
        }


async def regenerate_version_code(
    version_id: int,
    payload: RegenerateWorkflowCodeRequest,
) -> dict[str, Any]:
    settings = get_settings()
    async with engine.begin() as conn:
        result = await _regenerate_version_code_locked(
            conn,
            version_id,
            force=payload.force,
            allowed_statuses={"missing_metadata", "missing_file", "invalid_path"},
            skip_when_unneeded=False,
            actor_user_id=settings.mock_user_id,
            audit_action="workflow_version.regenerate_code",
        )
        version = result["version"]
        return {
            **version,
            "regenerated": result["regenerated"],
            "previous_code_status": result["previous_code_status"],
        }


async def cleanup_generated_workflows(*, dry_run: bool) -> dict[str, Any]:
    settings = get_settings()
    async with engine.begin() as conn:
        referenced_code_paths = await _list_referenced_code_paths(conn)
        report = cleanup_generated_workflow_dirs(
            referenced_code_paths=referenced_code_paths,
            dry_run=dry_run,
        )
        payload = asdict(report)
        payload["removed_total"] = (
            len(report.removed_temp_dirs)
            + len(report.removed_orphan_version_dirs)
            + len(report.removed_empty_workflow_dirs)
        )
        payload["kept_total"] = len(report.kept_version_dirs)
        if not dry_run and payload["removed_total"] > 0:
            await write_audit_log(
                conn,
                actor_user_id=settings.mock_user_id,
                action="generated_workflows.cleanup",
                resource_type="generated_workflows",
                detail=payload,
            )
        return payload


async def run_workflow(workflow_id: int, payload: RunWorkflowRequest) -> dict[str, Any]:
    settings = get_settings()
    async_run_id: int | None = None
    response_payload: dict[str, Any] | None = None
    async with engine.begin() as conn:
        workflow = await _get_workflow_row(conn, workflow_id)
        version_id = payload.version_id or workflow["current_version_id"]
        if version_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="workflow is not published",
            )

        version = await _get_version_row(conn, int(version_id))
        if version["workflow_id"] != workflow_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="version does not belong to workflow",
            )
        version = await _ensure_version_code(conn, version)

        if payload.execution_mode == "async":
            run = await create_generated_workflow_run_pending(
                conn,
                workflow_id=workflow_id,
                version_id=int(version_id),
                code_path=version.get("code_path"),
                code_hash=version.get("code_hash"),
                run_input=payload.input,
                trigger_type=payload.trigger_type,
                created_by=settings.mock_user_id,
            )
            await write_audit_log(
                conn,
                actor_user_id=settings.mock_user_id,
                action="workflow.run",
                resource_type="workflow_run",
                resource_id=run["id"],
                detail={
                    "workflow_id": workflow_id,
                    "version_id": int(version_id),
                    "execution_mode": payload.execution_mode,
                },
            )
            async_run_id = int(run["id"])
            response_payload = {
                "run_id": run["id"],
                "status": run["status"],
                "output": run["output_json"] or {},
                "started_at": run["started_at"],
                "ended_at": run["ended_at"],
            }
        else:
            run = await execute_generated_workflow_sync(
                conn,
                workflow_id=workflow_id,
                version_id=int(version_id),
                code_path=version.get("code_path"),
                code_hash=version.get("code_hash"),
                run_input=payload.input,
                trigger_type=payload.trigger_type,
                created_by=settings.mock_user_id,
            )
            await write_audit_log(
                conn,
                actor_user_id=settings.mock_user_id,
                action="workflow.run",
                resource_type="workflow_run",
                resource_id=run["id"],
                detail={
                    "workflow_id": workflow_id,
                    "version_id": int(version_id),
                    "execution_mode": payload.execution_mode,
                },
            )
            return {
                "run_id": run["id"],
                "status": run["status"],
                "output": run["output_json"] or {},
                "started_at": run["started_at"],
                "ended_at": run["ended_at"],
            }

    if async_run_id is not None and response_payload is not None:
        await _enqueue_async_workflow_run(async_run_id)
        return response_payload

    raise RuntimeError("workflow run did not produce a response")


async def list_runs(
    *,
    workflow_id: int | None,
    run_status: str | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    where = ["1 = 1"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if workflow_id is not None:
        where.append("workflow_id = :workflow_id")
        params["workflow_id"] = workflow_id
    if run_status:
        where.append("status = :status")
        params["status"] = run_status
    where_sql = " AND ".join(where)

    async with engine.connect() as conn:
        total = await conn.scalar(
            text(f"SELECT count(*) FROM workflow_runs WHERE {where_sql}"),
            params,
        )
        result = await conn.execute(
            text(
                f"""
                SELECT *
                FROM workflow_runs
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


async def get_run(run_id: int) -> dict[str, Any]:
    async with engine.connect() as conn:
        return await _get_run_row(conn, run_id)


async def list_node_runs(run_id: int, *, after_node_run_id: int | None = None) -> dict[str, Any]:
    async with engine.connect() as conn:
        await _get_run_row(conn, run_id)
        where = "run_id = :run_id"
        params: dict[str, Any] = {"run_id": run_id}
        if after_node_run_id is not None:
            where += " AND id > :after_node_run_id"
            params["after_node_run_id"] = after_node_run_id
        result = await conn.execute(
            text(
                f"""
                SELECT *
                FROM node_runs
                WHERE {where}
                ORDER BY id ASC
                """
            ),
            params,
        )
        return {"items": [dict(row) for row in result.mappings()]}


async def get_trace(run_id: int, *, after_node_run_id: int | None = None) -> dict[str, Any]:
    async with engine.connect() as conn:
        run = await _get_run_row(conn, run_id)
        version = await _get_version_row(conn, run["version_id"])
        nodes = await list_node_runs(run_id, after_node_run_id=after_node_run_id)
        return {"run": run, "nodes": nodes["items"], "graph_json": version["graph_json"]}


async def cancel_run(run_id: int) -> dict[str, Any]:
    settings = get_settings()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                UPDATE workflow_runs
                SET status = 'cancelled',
                    ended_at = now(),
                    updated_at = now()
                WHERE id = :run_id AND status IN ('pending', 'running', 'waiting_approval')
                RETURNING id, status
                """
            ),
            {"run_id": run_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            existing = await conn.execute(
                text("SELECT id, status FROM workflow_runs WHERE id = :run_id"),
                {"run_id": run_id},
            )
            existing_row = existing.mappings().one_or_none()
            if existing_row is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
            await write_audit_log(
                conn,
                actor_user_id=settings.mock_user_id,
                action="workflow.cancel",
                resource_type="workflow_run",
                resource_id=existing_row["id"],
                detail={"status": existing_row["status"], "cancelled": False},
            )
            return {
                "run_id": existing_row["id"],
                "status": existing_row["status"],
                "cancelled": False,
            }
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="workflow.cancel",
            resource_type="workflow_run",
            resource_id=row["id"],
            detail={"status": row["status"], "cancelled": True},
        )
        return {"run_id": row["id"], "status": row["status"], "cancelled": True}


async def retry_run(run_id: int, payload: RetryRunRequest) -> dict[str, Any]:
    settings = get_settings()
    retry_run_id: int | None = None
    response_payload: dict[str, Any] | None = None
    async with engine.begin() as conn:
        original_run = await _get_run_row(conn, run_id)
        if original_run["status"] not in {"failed", "cancelled"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="only failed or cancelled runs can be retried",
            )

        version = await _get_version_row(conn, original_run["version_id"])
        version = await _ensure_version_code(conn, version)
        run_input = (
            payload.input if payload.input is not None else (original_run["input_json"] or {})
        )
        next_run = await create_generated_workflow_run_pending(
            conn,
            workflow_id=original_run["workflow_id"],
            version_id=original_run["version_id"],
            code_path=version.get("code_path"),
            code_hash=version.get("code_hash"),
            run_input=run_input,
            trigger_type=original_run["trigger_type"],
            created_by=original_run.get("created_by") or settings.mock_user_id,
        )
        metadata = dict(next_run.get("metadata_json") or {})
        metadata.update(
            {
                "retry_of_run_id": original_run["id"],
                "retry_of_status": original_run["status"],
                "retry_reason": payload.reason,
            }
        )
        result = await conn.execute(
            _jsonb_stmt(
                """
                UPDATE workflow_runs
                SET metadata_json = :metadata_json,
                    updated_at = now()
                WHERE id = :run_id
                RETURNING *
                """,
                "metadata_json",
            ),
            {"run_id": next_run["id"], "metadata_json": metadata},
        )
        next_run = dict(result.mappings().one())
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="workflow.retry",
            resource_type="workflow_run",
            resource_id=next_run["id"],
            detail={
                "retry_of_run_id": original_run["id"],
                "retry_of_status": original_run["status"],
                "workflow_id": original_run["workflow_id"],
                "version_id": original_run["version_id"],
            },
        )
        retry_run_id = int(next_run["id"])
        response_payload = {
            "run_id": next_run["id"],
            "status": next_run["status"],
            "retry_of_run_id": original_run["id"],
            "output": next_run["output_json"] or {},
            "started_at": next_run["started_at"],
            "ended_at": next_run["ended_at"],
        }

    if retry_run_id is not None and response_payload is not None:
        await _enqueue_async_workflow_run(retry_run_id)
        return response_payload

    raise RuntimeError("workflow retry did not produce a response")


def validate_workflow_graph(graph: dict[str, Any], mode: str) -> dict[str, Any]:
    return validate_graph(graph, mode)  # type: ignore[arg-type]


async def _get_workflow_row(conn, workflow_id: int) -> dict[str, Any]:
    result = await conn.execute(
        text("SELECT * FROM workflows WHERE id = :workflow_id AND deleted_at IS NULL"),
        {"workflow_id": workflow_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workflow not found")
    return dict(row)


async def _get_workflow_row_for_update(conn, workflow_id: int) -> dict[str, Any]:
    result = await conn.execute(
        text(
            """
            SELECT *
            FROM workflows
            WHERE id = :workflow_id AND deleted_at IS NULL
            FOR UPDATE
            """
        ),
        {"workflow_id": workflow_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workflow not found")
    return dict(row)


async def _get_version_row(conn, version_id: int) -> dict[str, Any]:
    result = await conn.execute(
        text("SELECT * FROM workflow_versions WHERE id = :version_id"),
        {"version_id": version_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="workflow version not found",
        )
    return dict(row)


async def _ensure_version_code(conn, version: dict[str, Any]) -> dict[str, Any]:
    inspection = inspect_workflow_code(version.get("code_path"), version.get("code_hash"))
    if inspection.code_status not in {"missing_metadata", "missing_file"}:
        return version

    result = await _regenerate_version_code_locked(
        conn,
        int(version["id"]),
        force=False,
        allowed_statuses={"missing_metadata", "missing_file"},
        skip_when_unneeded=True,
        actor_user_id=None,
        audit_action=None,
    )
    return result["version"]


async def _regenerate_version_code_locked(
    conn,
    version_id: int,
    *,
    force: bool,
    allowed_statuses: set[str],
    skip_when_unneeded: bool,
    actor_user_id: int | None,
    audit_action: str | None,
) -> dict[str, Any]:
    locked = await conn.execute(
        text("SELECT * FROM workflow_versions WHERE id = :version_id FOR UPDATE"),
        {"version_id": version_id},
    )
    row = locked.mappings().one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="workflow version not found",
        )
    version = dict(row)
    inspection = inspect_workflow_code(version.get("code_path"), version.get("code_hash"))
    if not force and inspection.code_status not in allowed_statuses:
        if skip_when_unneeded:
            return {
                "version": _with_code_inspection(version),
                "regenerated": False,
                "previous_code_status": inspection.code_status,
            }
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "workflow_code_regenerate_blocked",
                "message": (
                    "workflow code exists; pass force=true to replace it"
                    if inspection.code_status == "ok"
                    else "workflow code has local hash changes; pass force=true to replace it"
                ),
                "code_status": inspection.code_status,
            },
        )

    target_dir = generated_workflow_version_dir(
        workflow_id=int(version["workflow_id"]),
        version=int(version["version"]),
    ).resolve()
    if await _generated_version_dir_is_referenced_elsewhere(
        conn,
        target_dir,
        exclude_version_id=version_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "workflow_code_version_dir_referenced",
                "message": "generated workflow version directory is referenced by another version",
            },
        )

    graph = version["graph_json"]
    graph_hash = version.get("graph_hash") or hashlib.sha256(
        json.dumps(graph, sort_keys=True).encode("utf-8")
    ).hexdigest()
    artifact: WorkflowCodeArtifact | None = None
    backup_dir = _backup_generated_version_dir(target_dir)
    try:
        artifact = await _generate_workflow_code_with_cleanup(
            conn,
            workflow_id=int(version["workflow_id"]),
            version=int(version["version"]),
            graph=graph,
            graph_hash=graph_hash,
        )
        updated_result = await conn.execute(
            text(
                """
                UPDATE workflow_versions
                SET code_path = :code_path,
                    code_hash = :code_hash,
                    code_generated_at = :code_generated_at
                WHERE id = :version_id
                RETURNING *
                """
            ),
            {
                "version_id": version_id,
                "code_path": artifact.code_path,
                "code_hash": artifact.code_hash,
                "code_generated_at": artifact.code_generated_at,
            },
        )
        updated = dict(updated_result.mappings().one())
        if actor_user_id is not None and audit_action is not None:
            await write_audit_log(
                conn,
                actor_user_id=actor_user_id,
                action=audit_action,
                resource_type="workflow_version",
                resource_id=version_id,
                detail={
                    "workflow_id": updated["workflow_id"],
                    "version": updated["version"],
                    "force": force,
                    "previous_code_status": inspection.code_status,
                    "code_hash": updated["code_hash"],
                },
            )
    except Exception:
        if artifact is not None:
            remove_generated_workflow_version(artifact.version_dir)
        _restore_generated_version_backup(target_dir, backup_dir)
        raise

    _discard_generated_version_backup(backup_dir)
    return {
        "version": _with_code_inspection(updated),
        "regenerated": True,
        "previous_code_status": inspection.code_status,
    }


async def _generated_version_dir_is_referenced_elsewhere(
    conn,
    version_dir: Path,
    *,
    exclude_version_id: int,
) -> bool:
    result = await conn.execute(
        text(
            """
            SELECT id, code_path
            FROM workflow_versions
            WHERE code_path IS NOT NULL AND id <> :version_id
            """
        ),
        {"version_id": exclude_version_id},
    )
    target = version_dir.resolve()
    for row in result.mappings():
        try:
            referenced_dir = resolve_generated_code_path(str(row["code_path"])).parent.resolve()
        except ValueError:
            continue
        if referenced_dir == target:
            return True
    return False


def _backup_generated_version_dir(version_dir: Path) -> Path | None:
    if not version_dir.exists():
        return None
    backup_dir = version_dir.with_name(f".{version_dir.name}.backup-{uuid4().hex}")
    version_dir.rename(backup_dir)
    return backup_dir


def _restore_generated_version_backup(version_dir: Path, backup_dir: Path | None) -> None:
    if backup_dir is None or not backup_dir.exists():
        return
    shutil.rmtree(version_dir, ignore_errors=True)
    backup_dir.rename(version_dir)


def _discard_generated_version_backup(backup_dir: Path | None) -> None:
    if backup_dir is not None:
        shutil.rmtree(backup_dir, ignore_errors=True)


async def _generate_workflow_code_with_cleanup(
    conn,
    *,
    workflow_id: int,
    version: int,
    graph: dict[str, Any],
    graph_hash: str,
) -> WorkflowCodeArtifact:
    try:
        return generate_workflow_code(
            workflow_id=workflow_id,
            version=version,
            graph=graph,
            graph_hash=graph_hash,
        )
    except FileExistsError:
        cleanup_generated_workflow_dirs(
            referenced_code_paths=await _list_referenced_code_paths(conn),
            dry_run=False,
        )
        return generate_workflow_code(
            workflow_id=workflow_id,
            version=version,
            graph=graph,
            graph_hash=graph_hash,
        )


async def _list_referenced_code_paths(conn) -> list[str]:
    result = await conn.execute(
        text("SELECT code_path FROM workflow_versions WHERE code_path IS NOT NULL")
    )
    return [str(path) for path in result.scalars().all() if path]


def _with_code_inspection(version: dict[str, Any]) -> dict[str, Any]:
    inspection = inspect_workflow_code(version.get("code_path"), version.get("code_hash"))
    version["code_path"] = inspection.code_path or version.get("code_path")
    version["code_hash_actual"] = inspection.code_hash_actual
    version["code_modified"] = inspection.code_modified
    version["code_status"] = inspection.code_status
    return version


async def _get_run_row(conn, run_id: int) -> dict[str, Any]:
    result = await conn.execute(
        text("SELECT * FROM workflow_runs WHERE id = :run_id"),
        {"run_id": run_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return dict(row)


async def _ensure_mock_user(conn, user_id: int) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO users (id, email, username, display_name, role, status)
            VALUES (:id, :email, :username, :display_name, 'admin', 'active')
            ON CONFLICT (id) DO UPDATE
            SET status = 'active', updated_at = now()
            """
        ),
        {
            "id": user_id,
            "email": f"mock-user-{user_id}@local.agent-flow",
            "username": f"mock_user_{user_id}",
            "display_name": "Mock User",
        },
    )
    await conn.execute(
        text(
            """
            SELECT setval(
              pg_get_serial_sequence('users', 'id'),
              greatest((SELECT max(id) FROM users), 1),
              true
            )
            """
        )
    )


def _graph_or_default(graph) -> dict[str, Any]:
    if graph is None:
        return default_graph()
    return graph.model_dump(mode="json", exclude_none=True)


async def _enqueue_async_workflow_run(run_id: int) -> None:
    from app.workers.workflow_run_worker import enqueue_workflow_run

    await enqueue_workflow_run(run_id)


def _jsonb_stmt(sql: str, *jsonb_param_names: str):
    statement = text(sql)
    return statement.bindparams(
        *(bindparam(param_name, type_=JSONB) for param_name in jsonb_param_names)
    )
