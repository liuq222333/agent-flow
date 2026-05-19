from dataclasses import dataclass, field
from hmac import compare_digest
from typing import Any

from starlette import status

PUBLIC_PATHS = {
    "/api/docs",
    "/api/openapi.json",
    "/api/redoc",
    "/api/v1/health",
    "/api/v1/metrics",
    "/api/v1/ready",
}


@dataclass(frozen=True)
class AuthDecision:
    allowed: bool
    status_code: int = status.HTTP_200_OK
    detail: str = "ok"
    headers: dict[str, str] = field(default_factory=dict)


def authenticate_api_request(
    path: str,
    authorization: str | None,
    settings: Any,
) -> AuthDecision:
    if _is_public_path(path):
        return AuthDecision(allowed=True)

    mode = str(settings.auth_mode).strip().lower()
    if mode in {"mock", "local", "disabled", "none"}:
        return AuthDecision(allowed=True)

    if mode != "bearer":
        return AuthDecision(
            allowed=False,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="auth_mode_invalid",
        )

    expected_token = (settings.api_bearer_token or "").strip()
    if not expected_token:
        return AuthDecision(
            allowed=False,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="api_bearer_token_not_configured",
        )

    token = _extract_bearer_token(authorization)
    if token is None:
        return AuthDecision(
            allowed=False,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authorization_required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not compare_digest(token, expected_token):
        return AuthDecision(
            allowed=False,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="authorization_forbidden",
        )

    return AuthDecision(allowed=True)


def _is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith("/api/docs/")


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None

    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer":
        return None

    stripped_token = token.strip()
    return stripped_token or None
