import re
from typing import Any

import httpx

from app.services.generated_runtime import WorkflowCodeError

_SENSITIVE_KEYWORDS = {
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "api-key",
    "apikey",
    "token",
    "access-token",
    "refresh-token",
    "secret",
    "password",
}
_MODEL_ERROR_CODES = {
    "model_api_key_missing",
    "model_request_failed",
    "model_response_invalid",
    "model_timeout",
}


class RuntimeNodeError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str | None = None,
        *,
        retryable: bool = False,
        error_detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or error_code)
        self.error_code = error_code
        self.retryable = retryable
        self.error_detail = error_detail or {}


def _normalize_node_error(exc: Exception, node: dict[str, Any] | None = None) -> RuntimeNodeError:
    if isinstance(exc, RuntimeNodeError):
        return exc
    node_type = str((node or {}).get("type") or "")
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        return _normalize_status_error(int(status_code), _safe_exception_message(exc), node_type)
    class_name = exc.__class__.__name__.lower()
    if "ratelimit" in class_name or "rate_limit" in class_name:
        if node_type == "llm":
            return RuntimeNodeError(
                "model_request_failed",
                _safe_exception_message(exc),
                retryable=True,
            )
        return RuntimeNodeError("rate_limit", str(exc), retryable=True)
    if "connection" in class_name and node_type == "llm":
        return RuntimeNodeError(
            "model_request_failed",
            _safe_exception_message(exc),
            retryable=True,
        )
    if isinstance(exc, TimeoutError) or "timeout" in class_name:
        error_code = "model_timeout" if node_type == "llm" else "timeout"
        return RuntimeNodeError(error_code, _safe_exception_message(exc), retryable=True)
    if isinstance(exc, httpx.TimeoutException):
        error_code = "model_timeout" if node_type == "llm" else "timeout"
        return RuntimeNodeError(error_code, _safe_exception_message(exc), retryable=True)
    if isinstance(exc, httpx.HTTPStatusError):
        return _normalize_http_status_error(exc, node_type=node_type or "api")
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        if node_type == "llm":
            return RuntimeNodeError(
                "model_request_failed",
                _safe_exception_message(exc),
                retryable=True,
            )
        return RuntimeNodeError("network_error", str(exc), retryable=True)
    if isinstance(exc, httpx.RequestError):
        if node_type == "llm":
            return RuntimeNodeError(
                "model_request_failed",
                _safe_exception_message(exc),
                retryable=True,
            )
        return RuntimeNodeError("api_request_error", str(exc), retryable=True)
    if isinstance(exc, ValueError):
        return RuntimeNodeError("invalid_config", str(exc))

    if node_type == "llm":
        return RuntimeNodeError(
            "model_request_failed",
            _safe_exception_message(exc),
            retryable=True,
        )
    if node_type == "knowledge_base":
        return RuntimeNodeError("knowledge_base_error", str(exc), retryable=True)
    if node_type == "api":
        return RuntimeNodeError("api_request_error", str(exc), retryable=True)
    return RuntimeNodeError("unknown_error", str(exc) or exc.__class__.__name__)


def _normalize_http_status_error(
    exc: httpx.HTTPStatusError,
    *,
    node_type: str = "api",
) -> RuntimeNodeError:
    status_code = exc.response.status_code
    return _normalize_status_error(status_code, _safe_exception_message(exc), node_type)


def _normalize_status_error(status_code: int, message: str, node_type: str) -> RuntimeNodeError:
    if node_type == "llm":
        return RuntimeNodeError(
            "model_request_failed",
            _redact_sensitive_text(message),
            retryable=status_code == 429 or status_code >= 500,
            error_detail={"status_code": status_code},
        )
    if status_code == 429:
        return RuntimeNodeError(
            "rate_limit",
            _redact_sensitive_text(message),
            retryable=True,
            error_detail={"status_code": status_code},
        )
    if 500 <= status_code:
        error_code = "llm_provider_error" if node_type == "llm" else "api_response_error"
        return RuntimeNodeError(
            error_code,
            _redact_sensitive_text(message),
            retryable=True,
            error_detail={"status_code": status_code},
        )
    if 400 <= status_code:
        error_code = "llm_provider_error" if node_type == "llm" else "api_response_error"
        return RuntimeNodeError(
            error_code,
            _redact_sensitive_text(message),
            retryable=False,
            error_detail={"status_code": status_code},
        )
    return RuntimeNodeError(
        "unknown_error",
        _redact_sensitive_text(message),
        retryable=False,
        error_detail={"status_code": status_code},
    )


def _safe_exception_message(exc: Exception, secrets: tuple[str, ...] = ()) -> str:
    return _redact_sensitive_text(str(exc) or exc.__class__.__name__, secrets=secrets)


def _redact_sensitive_text(value: str, *, secrets: tuple[str, ...] = ()) -> str:
    if not value:
        return value
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "***")
    redacted = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "***", redacted)
    redacted = re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+)[^,\s;)}]+",
        r"\1***",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}",
        r"\1***",
        redacted,
    )
    redacted = re.sub(
        r"(?i)((?:api[_-]?key|x-api-key|token|secret|password)\s*[:=]\s*)[\"']?[^,\s\"'}]+",
        r"\1***",
        redacted,
    )
    return redacted


def _redact_sensitive_data(value: Any, *, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_sensitive_value(_redact_sensitive_data(item, secrets=secrets))
            if _is_sensitive_key(str(key))
            else _redact_sensitive_data(item, secrets=secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_data(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        return _redact_sensitive_text(value, secrets=secrets)
    return value


def _redact_sensitive_mapping(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        if _is_sensitive_key(str(key)):
            redacted[key] = _redact_sensitive_value(item)
        elif isinstance(item, dict):
            redacted[key] = _redact_sensitive_mapping(item)
        else:
            redacted[key] = item
    return redacted


def _redact_sensitive_value(value: Any) -> Any:
    if isinstance(value, str) and "***" in value:
        return value
    return "***" if value else value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("_", "-")
    return any(keyword in normalized for keyword in _SENSITIVE_KEYWORDS)


def _workflow_error_info(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, RuntimeNodeError):
        return exc.error_code, str(exc)
    if isinstance(exc, WorkflowCodeError):
        return exc.code, str(exc)
    return "unknown_error", str(exc) or exc.__class__.__name__


def _with_llm_metadata(
    error: RuntimeNodeError,
    metadata: dict[str, Any],
    *,
    secrets: tuple[str, ...] = (),
) -> RuntimeNodeError:
    error_code = (
        error.error_code if error.error_code in _MODEL_ERROR_CODES else "model_request_failed"
    )
    error_detail = {**metadata, **_redact_sensitive_data(error.error_detail, secrets=secrets)}
    return RuntimeNodeError(
        error_code,
        _redact_sensitive_text(str(error), secrets=secrets),
        retryable=error.retryable,
        error_detail=error_detail,
    )


def _http_status_is_success(status_code: int, success_status_codes: set[int]) -> bool:
    if success_status_codes:
        return status_code in success_status_codes
    return 200 <= status_code < 300


def _api_response_error(
    status_code: int,
    response_body: Any,
    *,
    secrets: tuple[str, ...] = (),
) -> RuntimeNodeError:
    error = _normalize_status_error(status_code, f"API returned HTTP {status_code}", "api")
    error.error_detail["response_preview"] = _safe_response_preview(
        response_body,
        secrets=secrets,
    )
    return error


def _safe_response_preview(value: Any, *, secrets: tuple[str, ...] = ()) -> Any:
    redacted = _redact_sensitive_data(value, secrets=secrets)
    preview = str(redacted)
    return preview[:500]


def _redact_api_runtime_error(
    error: RuntimeNodeError,
    *,
    secrets: tuple[str, ...] = (),
) -> RuntimeNodeError:
    return RuntimeNodeError(
        error.error_code,
        _redact_sensitive_text(str(error), secrets=secrets),
        retryable=error.retryable,
        error_detail=_redact_sensitive_data(error.error_detail, secrets=secrets),
    )
