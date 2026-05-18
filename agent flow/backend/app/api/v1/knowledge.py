import hashlib
import json
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from app.api.v1.schemas import CreateKnowledgeBaseRequest, RetrieveKnowledgeRequest
from app.core.config import get_settings
from app.infra.db.session import engine
from app.services.audit import write_audit_log
from app.services.knowledge_processing import rank_chunks as _rank_chunks
from app.services.knowledge_processing import retrieve_chunks

router = APIRouter(tags=["knowledge"])
rank_chunks = _rank_chunks


@router.post("/knowledge-bases", status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(payload: CreateKnowledgeBaseRequest) -> dict[str, Any]:
    settings = get_settings()
    async with engine.begin() as conn:
        await _ensure_mock_user(conn, settings.mock_user_id)
        result = await conn.execute(
            _jsonb_stmt(
                """
                INSERT INTO knowledge_bases (
                  name,
                  description,
                  status,
                  embedding_model,
                  embedding_dim,
                  tokenizer,
                  slug,
                  config_json,
                  created_by
                )
                VALUES (
                  :name,
                  :description,
                  'active',
                  :embedding_model,
                  :embedding_dim,
                  :tokenizer,
                  :slug,
                  :config_json,
                  :created_by
                )
                RETURNING *
                """,
                "config_json",
            ),
            {
                "name": payload.name,
                "description": payload.description,
                "embedding_model": payload.embedding_model,
                "embedding_dim": payload.embedding_dim,
                "tokenizer": payload.tokenizer,
                "slug": payload.slug,
                "config_json": payload.config,
                "created_by": settings.mock_user_id,
            },
        )
        knowledge_base = dict(result.mappings().one())
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="knowledge.create",
            resource_type="knowledge_base",
            resource_id=knowledge_base["id"],
            detail={"name": knowledge_base["name"], "status": knowledge_base["status"]},
        )
        return knowledge_base


@router.get("/knowledge-bases")
async def list_knowledge_bases(
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    page, page_size, offset = _pagination(page, page_size)
    where = ["deleted_at IS NULL", "status != 'deleted'"]
    params: dict[str, Any] = {"limit": page_size, "offset": offset}
    if keyword:
        where.append("name ILIKE :keyword")
        params["keyword"] = f"%{keyword}%"
    where_sql = " AND ".join(where)

    async with engine.connect() as conn:
        total = await conn.scalar(
            text(f"SELECT count(*) FROM knowledge_bases WHERE {where_sql}"),
            params,
        )
        result = await conn.execute(
            text(
                f"""
                SELECT *
                FROM knowledge_bases
                WHERE {where_sql}
                ORDER BY updated_at DESC, id DESC
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


@router.get("/knowledge-bases/{kb_id}")
async def get_knowledge_base(kb_id: int) -> dict[str, Any]:
    async with engine.connect() as conn:
        return await _get_knowledge_base_row(conn, kb_id)


@router.post("/knowledge-bases/{kb_id}/documents")
async def upload_document(
    kb_id: int,
    file: Annotated[UploadFile, File()],
    metadata_json: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    settings = get_settings()
    metadata = _parse_metadata(metadata_json)
    data = await file.read()
    _validate_uploaded_file(
        file,
        len(data),
        settings.max_upload_bytes,
        settings.allowed_upload_types,
    )
    storage_url = _save_uploaded_file(settings.storage_dir, kb_id, file.filename, data)
    content_hash = hashlib.sha256(data).hexdigest()

    async with engine.begin() as conn:
        await _ensure_mock_user(conn, settings.mock_user_id)
        await _get_knowledge_base_row(conn, kb_id)
        result = await conn.execute(
            _jsonb_stmt(
                """
                INSERT INTO documents (
                  knowledge_base_id,
                  file_name,
                  file_type,
                  file_size,
                  storage_url,
                  content_hash,
                  status,
                  uploaded_by,
                  metadata_json
                )
                VALUES (
                  :knowledge_base_id,
                  :file_name,
                  :file_type,
                  :file_size,
                  :storage_url,
                  :content_hash,
                  'uploaded',
                  :uploaded_by,
                  :metadata_json
                )
                RETURNING *
                """,
                "metadata_json",
            ),
            {
                "knowledge_base_id": kb_id,
                "file_name": file.filename or "upload.bin",
                "file_type": file.content_type,
                "file_size": len(data),
                "storage_url": storage_url,
                "content_hash": content_hash,
                "uploaded_by": settings.mock_user_id,
                "metadata_json": metadata,
            },
        )
        document = dict(result.mappings().one())
        job = await _create_document_job(conn, document["id"], "parse")
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="knowledge.create",
            resource_type="document",
            resource_id=document["id"],
            detail={
                "knowledge_base_id": kb_id,
                "file_name": document["file_name"],
                "processing_job_id": job["id"],
            },
        )
        return _upload_response(document, job["id"])


@router.get("/knowledge-bases/{kb_id}/documents")
async def list_documents(
    kb_id: int,
    status: Literal[
        "uploaded",
        "parsing",
        "chunking",
        "embedding",
        "indexed",
        "failed",
        "deleted",
    ]
    | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    page, page_size, offset = _pagination(page, page_size)
    where = ["knowledge_base_id = :kb_id", "deleted_at IS NULL"]
    params: dict[str, Any] = {"kb_id": kb_id, "limit": page_size, "offset": offset}
    if status is not None:
        where.append("status = :status")
        params["status"] = status
    where_sql = " AND ".join(where)

    async with engine.connect() as conn:
        await _get_knowledge_base_row(conn, kb_id)
        total = await conn.scalar(text(f"SELECT count(*) FROM documents WHERE {where_sql}"), params)
        result = await conn.execute(
            text(
                f"""
                SELECT *
                FROM documents
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


@router.get("/documents/{document_id}")
async def get_document(document_id: int) -> dict[str, Any]:
    async with engine.connect() as conn:
        return await _get_document_row(conn, document_id)


@router.delete("/documents/{document_id}")
async def delete_document(document_id: int) -> dict[str, bool]:
    settings = get_settings()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                UPDATE documents
                SET status = 'deleted',
                    deleted_at = now(),
                    updated_at = now()
                WHERE id = :document_id AND deleted_at IS NULL
                RETURNING id
                """
            ),
            {"document_id": document_id},
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
        await conn.execute(
            text(
                """
                UPDATE knowledge_chunks
                SET status = 'deleted', updated_at = now()
                WHERE document_id = :document_id
                """
            ),
            {"document_id": document_id},
        )
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="knowledge.delete",
            resource_type="document",
            resource_id=document_id,
        )
        return {"success": True}


@router.post("/documents/{document_id}/retry")
async def retry_document(document_id: int) -> dict[str, Any]:
    settings = get_settings()
    async with engine.begin() as conn:
        document = await _get_document_row(conn, document_id)
        await conn.execute(
            text(
                """
                UPDATE documents
                SET status = 'uploaded',
                    error_stage = NULL,
                    error_message = NULL,
                    updated_at = now()
                WHERE id = :document_id
                """
            ),
            {"document_id": document_id},
        )
        job = await _create_document_job(conn, document_id, "reindex")
        document["status"] = "uploaded"
        await write_audit_log(
            conn,
            actor_user_id=settings.mock_user_id,
            action="knowledge.update",
            resource_type="document",
            resource_id=document_id,
            detail={"processing_job_id": job["id"], "job_type": job["job_type"]},
        )
        return _upload_response(document, job["id"])


@router.post("/knowledge-bases/{kb_id}/retrieve")
async def retrieve_knowledge(kb_id: int, payload: RetrieveKnowledgeRequest) -> dict[str, Any]:
    async with engine.connect() as conn:
        await _get_knowledge_base_row(conn, kb_id)
        chunks = await retrieve_chunks(
            conn,
            knowledge_base_id=kb_id,
            query=payload.query,
            top_k=payload.top_k,
            score_threshold=payload.score_threshold,
        )
    return {"chunks": chunks}


async def _get_knowledge_base_row(conn, kb_id: int) -> dict[str, Any]:
    result = await conn.execute(
        text(
            """
            SELECT *
            FROM knowledge_bases
            WHERE id = :kb_id AND deleted_at IS NULL AND status != 'deleted'
            """
        ),
        {"kb_id": kb_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="knowledge base not found",
        )
    return dict(row)


async def _get_document_row(conn, document_id: int) -> dict[str, Any]:
    result = await conn.execute(
        text("SELECT * FROM documents WHERE id = :document_id AND deleted_at IS NULL"),
        {"document_id": document_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return dict(row)


async def _create_document_job(conn, document_id: int, job_type: str) -> dict[str, Any]:
    result = await conn.execute(
        text(
            """
            INSERT INTO document_processing_jobs (document_id, job_type, status)
            VALUES (:document_id, :job_type, 'pending')
            RETURNING *
            """
        ),
        {"document_id": document_id, "job_type": job_type},
    )
    return dict(result.mappings().one())


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


def _upload_response(document: dict[str, Any], processing_job_id: int) -> dict[str, Any]:
    return {
        "document_id": document["id"],
        "knowledge_base_id": document["knowledge_base_id"],
        "file_name": document["file_name"],
        "status": document["status"],
        "processing_job_id": processing_job_id,
    }


def _parse_metadata(metadata_json: str | None) -> dict[str, Any]:
    if not metadata_json:
        return {}
    try:
        value = json.loads(metadata_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="metadata_json must be valid JSON",
        ) from exc
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="metadata_json must be an object",
        )
    return value


def _validate_uploaded_file(
    file: UploadFile,
    file_size: int,
    max_upload_bytes: int,
    allowed_content_types: set[str],
) -> None:
    if file_size <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="uploaded file is empty",
        )
    if file_size > max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"uploaded file exceeds {max_upload_bytes} bytes",
        )
    content_type = (file.content_type or "application/octet-stream").split(";")[0].strip().lower()
    if content_type not in allowed_content_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported file type: {content_type}",
        )


def _save_uploaded_file(
    storage_dir: Path,
    kb_id: int,
    filename: str | None,
    data: bytes,
) -> str:
    safe_name = Path(filename or "upload.bin").name
    target_dir = storage_dir / "knowledge_bases" / str(kb_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{uuid.uuid4().hex}_{safe_name}"
    target_path.write_bytes(data)
    return str(target_path)


def _jsonb_stmt(sql: str, *jsonb_param_names: str):
    statement = text(sql)
    return statement.bindparams(
        *(bindparam(param_name, type_=JSONB) for param_name in jsonb_param_names)
    )


def _pagination(page: int, page_size: int) -> tuple[int, int, int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    return page, page_size, (page - 1) * page_size
