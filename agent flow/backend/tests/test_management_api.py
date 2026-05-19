from io import BytesIO

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import Headers, UploadFile

from app.api.v1 import tools as tool_api
from app.api.v1.knowledge import _normalize_knowledge_config, _validate_uploaded_file, rank_chunks
from app.api.v1.secrets import decrypt_secret_value, encrypt_secret_value, sanitize_secret_row
from app.api.v1.tools import mock_tool_test_result
from app.main import app


def test_management_routes_are_registered() -> None:
    client = TestClient(app)

    openapi = client.get("/api/openapi.json").json()

    assert "/api/v1/knowledge-bases" in openapi["paths"]
    assert "/api/v1/tools" in openapi["paths"]
    assert "/api/v1/model-providers" in openapi["paths"]
    assert "post" in openapi["paths"]["/api/v1/model-providers"]
    assert "put" in openapi["paths"]["/api/v1/model-providers/{provider_id}"]
    assert "/api/v1/secrets" in openapi["paths"]
    assert "post" in openapi["paths"]["/api/v1/model-configs"]
    assert "put" in openapi["paths"]["/api/v1/model-configs/{model_config_id}"]
    assert "/api/v1/workflow-versions/{version_id}/code" in openapi["paths"]
    assert "/api/v1/workflow-versions/{version_id}/regenerate-code" in openapi["paths"]
    assert "/api/v1/generated-workflows/cleanup" in openapi["paths"]
    assert "/api/v1/runs/{run_id}/retry" in openapi["paths"]
    assert "/api/v1/metrics" in openapi["paths"]


def test_secret_helpers_encrypt_and_hide_value() -> None:
    encrypted = encrypt_secret_value("super-secret", "dev-only-change-me-32-bytes-minimum")

    assert encrypted != "super-secret"
    assert decrypt_secret_value(encrypted, "dev-only-change-me-32-bytes-minimum") == "super-secret"
    assert sanitize_secret_row(
        {"id": 1, "secret_key": "openai", "encrypted_value": encrypted, "value": "super-secret"}
    ) == {"id": 1, "secret_key": "openai"}


def test_tool_test_result_is_mock_only() -> None:
    result = mock_tool_test_result(
        {"id": 1, "name": "Order API", "config_json": {"url": "https://example.com"}},
        {"order_id": 42},
    )

    assert result["success"] is True
    assert result["response"]["mode"] == "mock"
    assert result["response"]["input"] == {"order_id": 42}


@pytest.mark.asyncio
async def test_tool_config_resolution_supports_secret_redaction(monkeypatch) -> None:
    async def fake_secret(conn, key):
        assert key == "order_api_key"
        return "real-secret"

    monkeypatch.setattr(tool_api, "get_secret_value", fake_secret)
    config = {
        "headers": {"Authorization": "Bearer {{secrets.order_api_key}}"},
        "body": {"order_id": "{{input.order_id}}"},
    }

    resolved = await tool_api._resolve_tool_value(None, config, {"order_id": "A-1001"})
    safe = await tool_api._resolve_tool_value(
        None,
        config,
        {"order_id": "A-1001"},
        redact_secrets=True,
    )

    assert resolved["headers"]["Authorization"] == "Bearer real-secret"
    assert safe["headers"]["Authorization"] == "Bearer ***"
    assert safe["body"]["order_id"] == "A-1001"


def test_rank_chunks_scores_text_matches() -> None:
    chunks = [
        {"id": 1, "content": "billing support and refund", "document_id": 10},
        {"id": 2, "content": "shipping status", "document_id": 11},
    ]

    ranked = rank_chunks(chunks, "billing refund")

    assert ranked[0]["id"] == 1
    assert ranked[0]["score"] == 1.0


def test_knowledge_config_is_normalized_and_validated() -> None:
    normalized = _normalize_knowledge_config(
        {
            "embedding_provider": "local-hash",
            "chunk_size_tokens": "256",
            "chunk_overlap_tokens": "32",
        }
    )

    assert normalized["embedding_provider"] == "local"
    assert normalized["chunk_size_tokens"] == 256
    assert normalized["chunk_overlap_tokens"] == 32

    try:
        _normalize_knowledge_config(
            {
                "embedding_provider": "unknown",
                "chunk_size_tokens": 256,
                "chunk_overlap_tokens": 32,
            }
        )
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("unsupported embedding provider should fail")

    try:
        _normalize_knowledge_config({"chunk_size_tokens": 80, "chunk_overlap_tokens": 80})
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("chunk overlap equal to chunk size should fail")


def test_upload_file_validation_rejects_unsafe_inputs() -> None:
    allowed_types = {"text/plain"}
    valid = UploadFile(
        file=BytesIO(b"policy"),
        filename="policy.txt",
        headers=Headers({"content-type": "text/plain"}),
    )

    _validate_uploaded_file(valid, 10, 100, allowed_types)

    empty = UploadFile(
        file=BytesIO(),
        filename="empty.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    try:
        _validate_uploaded_file(empty, 0, 100, allowed_types)
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("empty upload should fail")

    too_large = UploadFile(
        file=BytesIO(b"x" * 101),
        filename="big.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    try:
        _validate_uploaded_file(too_large, 101, 100, allowed_types)
    except HTTPException as exc:
        assert exc.status_code == 413
    else:
        raise AssertionError("oversized upload should fail")

    unsupported = UploadFile(
        file=BytesIO(b"binary"),
        filename="script.exe",
        headers=Headers({"content-type": "application/octet-stream"}),
    )
    try:
        _validate_uploaded_file(unsupported, 10, 100, allowed_types)
    except HTTPException as exc:
        assert exc.status_code == 415
    else:
        raise AssertionError("unsupported upload type should fail")
