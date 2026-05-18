from fastapi.testclient import TestClient

from app.core.auth import authenticate_api_request
from app.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


class _Settings:
    def __init__(self, auth_mode: str = "mock", api_bearer_token: str | None = None) -> None:
        self.auth_mode = auth_mode
        self.api_bearer_token = api_bearer_token


def test_auth_allows_public_paths() -> None:
    decision = authenticate_api_request("/api/v1/ready", None, _Settings("bearer"))
    assert decision.allowed is True


def test_auth_mock_mode_allows_api_requests() -> None:
    decision = authenticate_api_request("/api/v1/workflows", None, _Settings("mock"))
    assert decision.allowed is True


def test_auth_bearer_mode_requires_valid_token() -> None:
    settings = _Settings("bearer", "secret-token")

    missing = authenticate_api_request("/api/v1/workflows", None, settings)
    assert missing.allowed is False
    assert missing.status_code == 401

    wrong = authenticate_api_request("/api/v1/workflows", "Bearer wrong", settings)
    assert wrong.allowed is False
    assert wrong.status_code == 403

    correct = authenticate_api_request("/api/v1/workflows", "Bearer secret-token", settings)
    assert correct.allowed is True


def test_auth_bearer_mode_fails_closed_without_token() -> None:
    decision = authenticate_api_request("/api/v1/workflows", "Bearer any", _Settings("bearer"))
    assert decision.allowed is False
    assert decision.status_code == 503
