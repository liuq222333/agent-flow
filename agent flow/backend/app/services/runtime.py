import asyncio
import ipaddress
import json
import random
import re
import socket
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings
from app.services import generated_runtime, human_approvals, knowledge_processing
from app.services.generated_runtime import GeneratedWorkflow, WorkflowCodeError
from app.services.secrets import get_secret_value, resolve_deepseek_api_key, resolve_openai_api_key

Graph = dict[str, Any]
State = dict[str, Any]

_PLACEHOLDER_RE = re.compile(r"{{\s*([^}]+)\s*}}")
_BACKEND_ROOT = generated_runtime.BACKEND_ROOT
_PROJECT_ROOT = generated_runtime.PROJECT_ROOT
_GENERATED_ROOT = generated_runtime.GENERATED_ROOT
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
_MISSING = object()
_NODE_DEFAULT_TIMEOUT_SECONDS = {
    "llm": 60.0,
    "knowledge_base": 30.0,
    "api": 30.0,
    "intent": 30.0,
    "set_variable": 5.0,
    "human_approval": 5.0,
}
_API_DEFAULT_MAX_RESPONSE_BYTES = 1024 * 1024
_API_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
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


class HumanApprovalPause(Exception):
    def __init__(self, *, node_id: str, task_id: int, output: dict[str, Any]) -> None:
        super().__init__("workflow is waiting for human approval")
        self.node_id = node_id
        self.task_id = task_id
        self.output = output


class GeneratedWorkflowContext:
    def __init__(self, conn: AsyncConnection, *, run_id: int, state: State) -> None:
        self._conn = conn
        self.run_id = run_id
        self.state = state

    async def execute_graph(self, graph: Graph, input_data: dict[str, Any]) -> dict[str, Any]:
        self.state["input"] = input_data
        resume_from_node_id = _prepare_human_approval_resume(graph, self.state)
        await _execute_graph(
            self._conn,
            run_id=self.run_id,
            graph=graph,
            state=self.state,
            start_node_id=resume_from_node_id,
        )
        return self.state.get("final_output") or _fallback_output(self.state)

    async def execute_node(
        self,
        node_id: str,
        node_type: str,
        node_config: dict[str, Any] | None = None,
        input_mapping: dict[str, Any] | None = None,
        output_mapping: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        node = {
            "id": node_id,
            "type": node_type,
            "name": node_id,
            "config": node_config or {},
            "input_mapping": input_mapping,
            "output_mapping": output_mapping,
        }
        return await _execute_node_with_retry(self._conn, self.run_id, node, self.state)

    def get_state(self) -> State:
        return self.state

    def set_output(self, key: str, value: Any) -> None:
        self.state.setdefault("final_output", {})[key] = value

    def finish(self, outputs: dict[str, Any]) -> dict[str, Any]:
        self.state["final_output"] = outputs
        return outputs

    def fail(self, error_code: str, error_message: str) -> None:
        raise WorkflowCodeError(error_code, error_message)


async def execute_generated_workflow_sync(
    conn: AsyncConnection,
    *,
    workflow_id: int,
    version_id: int,
    code_path: str | None,
    code_hash: str | None,
    run_input: dict[str, Any],
    trigger_type: str,
    created_by: int,
) -> dict[str, Any]:
    run_row = await _create_run(
        conn,
        workflow_id,
        version_id,
        run_input,
        trigger_type,
        created_by,
        metadata_json={
            "execution_mode": "sync",
            "runtime": "generated_workflow",
            "code_path_at_run": code_path,
            "code_hash_published": code_hash,
            "code_hash_at_run": None,
            "code_modified": None,
        },
    )
    run_id = run_row["id"]

    state: State = {
        "input": run_input,
        "variables": {},
        "messages": [],
        "outputs": {},
        "metadata": {"run_id": run_id, "workflow_id": workflow_id, "version_id": version_id},
        "path": [],
        "final_output": {},
    }

    try:
        generated = _load_generated_workflow(code_path, code_hash)
        await _update_run_metadata(
            conn,
            run_id,
            {
                "execution_mode": "sync",
                "runtime": "generated_workflow",
                "code_path_at_run": _relative_project_path(generated.code_path),
                "code_hash_published": code_hash,
                "code_hash_at_run": generated.code_hash_at_run,
                "code_modified": generated.code_modified,
            },
        )

        await conn.execute(
            text(
                """
                UPDATE workflow_runs
                SET status = 'running', started_at = now(), updated_at = now()
                WHERE id = :run_id
                """
            ),
            {"run_id": run_id},
        )

        context = GeneratedWorkflowContext(conn, run_id=run_id, state=state)
        output = await generated.run(run_input, context)
        if output is None:
            output = state.get("final_output") or _fallback_output(state)
        elif isinstance(output, dict):
            state["final_output"] = output
        else:
            output = {"result": output}
            state["final_output"] = output

        await conn.execute(
            _jsonb_stmt(
                """
                UPDATE workflow_runs
                SET status = 'completed',
                    output_json = :output_json,
                    state_json = :state_json,
                    ended_at = now(),
                    updated_at = now()
                WHERE id = :run_id
                """,
                "output_json",
                "state_json",
            ),
            {"run_id": run_id, "output_json": output, "state_json": state},
        )
    except HumanApprovalPause:
        pass
    except WorkflowCodeError as exc:
        await _mark_run_failed(conn, run_id, exc.code, str(exc), state)
    except Exception as exc:  # pragma: no cover - defensive runtime boundary
        error_code, error_message = _workflow_error_info(exc)
        await _mark_run_failed(conn, run_id, error_code, error_message, state)

    result = await conn.execute(
        text("SELECT * FROM workflow_runs WHERE id = :run_id"),
        {"run_id": run_id},
    )
    return dict(result.mappings().one())


async def create_generated_workflow_run_pending(
    conn: AsyncConnection,
    *,
    workflow_id: int,
    version_id: int,
    code_path: str | None,
    code_hash: str | None,
    run_input: dict[str, Any],
    trigger_type: str,
    created_by: int,
) -> dict[str, Any]:
    return await _create_run(
        conn,
        workflow_id,
        version_id,
        run_input,
        trigger_type,
        created_by,
        metadata_json={
            "execution_mode": "async",
            "runtime": "generated_workflow",
            "queue": "redis_list",
            "code_path_at_run": code_path,
            "code_hash_published": code_hash,
            "code_hash_at_run": code_hash,
            "code_modified": None,
        },
    )


async def execute_pending_generated_workflow_run(
    conn: AsyncConnection,
    *,
    run_id: int,
) -> dict[str, Any]:
    result = await conn.execute(
        text(
            """
            SELECT
              wr.*,
              wv.code_path,
              wv.code_hash
            FROM workflow_runs wr
            JOIN workflow_versions wv ON wv.id = wr.version_id
            WHERE wr.id = :run_id
            FOR UPDATE OF wr
            """
        ),
        {"run_id": run_id},
    )
    run = dict(result.mappings().one())
    if run["status"] not in {"pending", "running"}:
        return run

    state = _pending_run_state(run)

    try:
        generated = _load_generated_workflow(run.get("code_path"), run.get("code_hash"))
        metadata = dict(run.get("metadata_json") or {})
        metadata.update(
            {
                "execution_mode": metadata.get("execution_mode", "async"),
                "runtime": "generated_workflow",
                "code_path_at_run": _relative_project_path(generated.code_path),
                "code_hash_published": run.get("code_hash"),
                "code_hash_at_run": generated.code_hash_at_run,
                "code_modified": generated.code_modified,
            }
        )
        await _update_run_metadata(conn, run_id, metadata)

        await conn.execute(
            text(
                """
                UPDATE workflow_runs
                SET status = 'running', started_at = COALESCE(started_at, now()), updated_at = now()
                WHERE id = :run_id
                """
            ),
            {"run_id": run_id},
        )

        context = GeneratedWorkflowContext(conn, run_id=run_id, state=state)
        output = await generated.run(state["input"], context)
        if output is None:
            output = state.get("final_output") or _fallback_output(state)
        elif isinstance(output, dict):
            state["final_output"] = output
        else:
            output = {"result": output}
            state["final_output"] = output

        await conn.execute(
            _jsonb_stmt(
                """
                UPDATE workflow_runs
                SET status = 'completed',
                    output_json = :output_json,
                    state_json = :state_json,
                    ended_at = now(),
                    updated_at = now()
                WHERE id = :run_id
                """,
                "output_json",
                "state_json",
            ),
            {"run_id": run_id, "output_json": output, "state_json": state},
        )
    except HumanApprovalPause:
        pass
    except WorkflowCodeError as exc:
        await _mark_run_failed(conn, run_id, exc.code, str(exc), state)
    except Exception as exc:  # pragma: no cover - defensive runtime boundary
        error_code, error_message = _workflow_error_info(exc)
        await _mark_run_failed(conn, run_id, error_code, error_message, state)

    result = await conn.execute(
        text("SELECT * FROM workflow_runs WHERE id = :run_id"),
        {"run_id": run_id},
    )
    return dict(result.mappings().one())


async def execute_workflow_sync(
    conn: AsyncConnection,
    *,
    workflow_id: int,
    version_id: int,
    graph: Graph,
    run_input: dict[str, Any],
    trigger_type: str,
    created_by: int,
) -> dict[str, Any]:
    run_row = await _create_run(conn, workflow_id, version_id, run_input, trigger_type, created_by)
    run_id = run_row["id"]

    state: State = {
        "input": run_input,
        "variables": {},
        "messages": [],
        "outputs": {},
        "metadata": {"run_id": run_id, "workflow_id": workflow_id, "version_id": version_id},
        "path": [],
        "final_output": {},
    }

    await conn.execute(
        text(
            """
            UPDATE workflow_runs
            SET status = 'running', started_at = now(), updated_at = now()
            WHERE id = :run_id
            """
        ),
        {"run_id": run_id},
    )

    try:
        await _execute_graph(conn, run_id=run_id, graph=graph, state=state)
        output = state.get("final_output") or _fallback_output(state)
        await conn.execute(
            _jsonb_stmt(
                """
                UPDATE workflow_runs
                SET status = 'completed',
                    output_json = :output_json,
                    state_json = :state_json,
                    ended_at = now(),
                    updated_at = now()
                WHERE id = :run_id
                """,
                "output_json",
                "state_json",
            ),
            {"run_id": run_id, "output_json": output, "state_json": state},
        )
    except HumanApprovalPause:
        pass
    except Exception as exc:  # pragma: no cover - defensive runtime boundary
        error_code, error_message = _workflow_error_info(exc)
        await conn.execute(
            _jsonb_stmt(
                """
                UPDATE workflow_runs
                SET status = 'failed',
                    error_code = :error_code,
                    error_message = :error_message,
                    state_json = :state_json,
                    ended_at = now(),
                    updated_at = now()
                WHERE id = :run_id
                """,
                "state_json",
            ),
            {
                "run_id": run_id,
                "error_code": error_code,
                "error_message": error_message,
                "state_json": state,
            },
        )

    result = await conn.execute(
        text("SELECT * FROM workflow_runs WHERE id = :run_id"),
        {"run_id": run_id},
    )
    return dict(result.mappings().one())


async def _execute_graph(
    conn: AsyncConnection,
    *,
    run_id: int,
    graph: Graph,
    state: State,
    start_node_id: str | None = None,
) -> None:
    nodes = {node["id"]: node for node in graph.get("nodes", [])}
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.get("edges", []):
        outgoing[edge["source"]].append(edge)
    for edges in outgoing.values():
        edges.sort(key=lambda item: item.get("id", ""))

    start_nodes = [node for node in nodes.values() if node.get("type") == "start"]
    if not start_nodes:
        raise ValueError("missing_start_node")

    if start_node_id == "":
        return
    if start_node_id is not None and start_node_id not in nodes:
        raise ValueError(f"resume_node_missing:{start_node_id}")

    node_id = start_node_id or start_nodes[0]["id"]
    visited_steps = 0
    max_steps = max(len(nodes) * 2, 1)

    while node_id:
        if visited_steps > max_steps:
            raise ValueError("possible_cycle_detected")
        visited_steps += 1

        node = nodes[node_id]
        state["path"].append(node_id)
        try:
            await _execute_node_with_retry(conn, run_id, node, state)
        except HumanApprovalPause as pause:
            state.setdefault("metadata", {})["waiting_approval"] = {
                "task_id": pause.task_id,
                "node_id": pause.node_id,
                "next_node_id": _next_node_id(node, outgoing.get(node_id, []), state),
            }
            await _persist_run_state(conn, run_id, state)
            raise
        except RuntimeNodeError as exc:
            node_id = await _next_node_after_error(
                conn,
                run_id,
                node,
                outgoing.get(node_id, []),
                nodes,
                state,
                exc,
            )
            if node_id is None:
                state["final_output"] = state.get("final_output") or _fallback_output(state)
                break
            continue

        if node.get("type") == "end":
            state["final_output"] = state.get("final_output") or _fallback_output(state)
            break

        node_id = _next_node_id(node, outgoing.get(node_id, []), state)


async def _execute_node_with_retry(
    conn: AsyncConnection,
    run_id: int,
    node: dict[str, Any],
    state: State,
) -> dict[str, Any]:
    retry_policy = _node_retry_policy(node)
    max_attempts = retry_policy["max_attempts"]
    last_error: RuntimeNodeError | None = None

    for attempt in range(1, max_attempts + 1):
        node_input = _build_node_input(node, state)
        started = time.perf_counter()
        node_run_id = await _create_node_run(conn, run_id, node, node_input, attempt=attempt)
        try:
            output = await _execute_node_with_timeout(conn, node, state, node_input)
            state["outputs"][node["id"]] = output
            _apply_output_mapping(node, output, state)
            duration_ms = int((time.perf_counter() - started) * 1000)
            await _mark_node_success(conn, node_run_id, output, duration_ms)
            await _persist_run_state(conn, run_id, state)
            return output
        except HumanApprovalPause as pause:
            state["outputs"][node["id"]] = pause.output
            duration_ms = int((time.perf_counter() - started) * 1000)
            await _mark_node_waiting_approval(
                conn,
                node_run_id,
                pause.output,
                duration_ms,
            )
            await _persist_run_state(conn, run_id, state)
            raise
        except Exception as exc:
            error = _normalize_node_error(exc, node)
            error.error_detail.setdefault("attempt", attempt)
            last_error = error
            duration_ms = int((time.perf_counter() - started) * 1000)
            will_retry = _should_retry_node(error, retry_policy, attempt)
            await _mark_node_failed(
                conn,
                node_run_id,
                error,
                duration_ms,
                will_retry=will_retry,
            )
            if not will_retry:
                raise error from exc
            await _sleep_before_retry(retry_policy, attempt)

    if last_error is not None:
        raise last_error
    raise RuntimeNodeError("unknown_error", "node execution failed without an attempt")


async def _execute_node_with_timeout(
    conn: AsyncConnection,
    node: dict[str, Any],
    state: State,
    node_input: dict[str, Any],
) -> dict[str, Any]:
    timeout_seconds = _node_timeout_seconds(node)
    try:
        return await asyncio.wait_for(
            _execute_node(conn, node, state, node_input),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        is_llm_node = str(node.get("type") or "") == "llm"
        error_code = "model_timeout" if is_llm_node else "timeout"
        error_message = (
            f"model request timed out after {timeout_seconds:g} seconds"
            if is_llm_node
            else f"node timed out after {timeout_seconds:g} seconds"
        )
        error_detail = {"timeout_seconds": timeout_seconds}
        if is_llm_node:
            error_detail.update(_node_llm_metadata(node))
        raise RuntimeNodeError(
            error_code,
            error_message,
            retryable=True,
            error_detail=error_detail,
        ) from exc


async def _next_node_after_error(
    conn: AsyncConnection,
    run_id: int,
    node: dict[str, Any],
    outgoing_edges: list[dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    state: State,
    error: RuntimeNodeError,
) -> str | None:
    on_error = _node_on_error(node)
    strategy = str(on_error.get("strategy") or "fail_workflow")
    if strategy == "fail_workflow":
        raise error

    _record_last_error(node, state, error)
    await _persist_run_state(conn, run_id, state)

    if strategy == "skip_node":
        return _first_outgoing_target(outgoing_edges)

    if strategy == "go_to_node":
        target = on_error.get("target")
        if not isinstance(target, str) or not target:
            raise RuntimeNodeError(
                "invalid_config",
                "on_error.target is required when strategy=go_to_node",
            ) from error
        if target not in nodes:
            raise RuntimeNodeError(
                "branch_target_not_found",
                f"on_error target not found: {target}",
            ) from error
        return target

    raise RuntimeNodeError(
        "invalid_config",
        f"unsupported on_error strategy: {strategy}",
    ) from error


def _node_on_error(node: dict[str, Any]) -> dict[str, Any]:
    config = node.get("config") or {}
    on_error = node.get("on_error") or config.get("on_error") or {}
    if not isinstance(on_error, dict):
        raise RuntimeNodeError("invalid_config", "on_error must be an object")
    return on_error


def _record_last_error(node: dict[str, Any], state: State, error: RuntimeNodeError) -> None:
    last_error = {
        "node_id": node.get("id"),
        "node_type": node.get("type"),
        "error_code": error.error_code,
        "error_message": _redact_sensitive_text(str(error)),
        "attempt": error.error_detail.get("attempt"),
    }
    for key in ("provider", "model", "model_config_id"):
        if key in error.error_detail:
            last_error[key] = error.error_detail[key]
    state.setdefault("metadata", {})["last_error"] = last_error


def _first_outgoing_target(outgoing_edges: list[dict[str, Any]]) -> str | None:
    if not outgoing_edges:
        return None
    return outgoing_edges[0].get("target")


def _node_retry_policy(node: dict[str, Any]) -> dict[str, Any]:
    retry = node.get("retry") or {}
    if not isinstance(retry, dict):
        raise RuntimeNodeError("invalid_config", "retry must be an object")
    raw_max_attempts = retry.get("max_attempts", 1)
    try:
        max_attempts = max(1, int(raw_max_attempts))
    except (TypeError, ValueError) as exc:
        raise RuntimeNodeError("invalid_config", "retry.max_attempts must be an integer") from exc

    retry_on = retry.get("retry_on")
    if retry_on is None:
        retry_on_set: set[str] | None = None
    elif isinstance(retry_on, list):
        retry_on_set = {str(item) for item in retry_on}
    else:
        raise RuntimeNodeError("invalid_config", "retry.retry_on must be a list")

    return {
        "max_attempts": max_attempts,
        "backoff": str(retry.get("backoff") or "none").lower(),
        "delay_seconds": float(
            retry.get("delay_seconds")
            or retry.get("interval_seconds")
            or retry.get("fixed_delay_seconds")
            or 0
        ),
        "max_delay_seconds": float(retry.get("max_delay_seconds") or 30),
        "jitter": _as_bool(retry.get("jitter"), default=False),
        "retry_on": retry_on_set,
    }


def _node_timeout_seconds(node: dict[str, Any]) -> float:
    config = node.get("config") or {}
    raw_timeout = node.get("timeout", config.get("timeout", config.get("timeout_seconds")))
    if raw_timeout in {None, ""}:
        return _NODE_DEFAULT_TIMEOUT_SECONDS.get(str(node.get("type")), 10.0)
    try:
        timeout_seconds = float(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise RuntimeNodeError("invalid_config", "timeout must be a number") from exc
    if timeout_seconds <= 0:
        raise RuntimeNodeError("invalid_config", "timeout must be greater than 0")
    return timeout_seconds


def _should_retry_node(
    error: RuntimeNodeError,
    retry_policy: dict[str, Any],
    attempt: int,
) -> bool:
    if attempt >= retry_policy["max_attempts"]:
        return False
    if not error.retryable:
        return False
    retry_on: set[str] | None = retry_policy["retry_on"]
    return retry_on is None or error.error_code in retry_on


async def _sleep_before_retry(retry_policy: dict[str, Any], attempt: int) -> None:
    backoff = retry_policy["backoff"]
    if backoff == "none":
        return
    delay = retry_policy["delay_seconds"] or 1.0
    if backoff == "fixed":
        if retry_policy["jitter"]:
            delay = random.uniform(0, delay)
        await asyncio.sleep(delay)
        return
    if backoff == "exponential":
        delay = min(delay * (2 ** (attempt - 1)), retry_policy["max_delay_seconds"])
        if retry_policy["jitter"]:
            delay = random.uniform(0, delay)
        await asyncio.sleep(delay)
        return
    raise RuntimeNodeError("invalid_config", f"unsupported retry backoff: {backoff}")


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


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _workflow_error_info(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, RuntimeNodeError):
        return exc.error_code, str(exc)
    if isinstance(exc, WorkflowCodeError):
        return exc.code, str(exc)
    return "unknown_error", str(exc) or exc.__class__.__name__


def _pending_run_state(run: dict[str, Any]) -> State:
    saved_state = run.get("state_json")
    if isinstance(saved_state, dict) and _human_approval_waiting_checkpoint(saved_state):
        state = dict(saved_state)
        state.setdefault("variables", {})
        state.setdefault("messages", [])
        state.setdefault("outputs", {})
        state.setdefault("path", [])
        state.setdefault("final_output", {})
        metadata = state.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["run_id"] = run["id"]
            metadata["workflow_id"] = run["workflow_id"]
            metadata["version_id"] = run["version_id"]
        else:
            state["metadata"] = {
                "run_id": run["id"],
                "workflow_id": run["workflow_id"],
                "version_id": run["version_id"],
            }
        state["input"] = run.get("input_json") or state.get("input") or {}
        return state

    return {
        "input": run["input_json"] or {},
        "variables": {},
        "messages": [],
        "outputs": {},
        "metadata": {
            "run_id": run["id"],
            "workflow_id": run["workflow_id"],
            "version_id": run["version_id"],
        },
        "path": [],
        "final_output": {},
    }


def _prepare_human_approval_resume(graph: Graph, state: State) -> str | None:
    checkpoint = _human_approval_waiting_checkpoint(state)
    if checkpoint is None:
        return None

    node_id = checkpoint.get("node_id")
    task_id = checkpoint.get("task_id")
    next_node_id = checkpoint.get("next_node_id")
    if not isinstance(node_id, str) or not node_id:
        return None
    if next_node_id is not None and not isinstance(next_node_id, str):
        return None

    output = state.get("outputs", {}).get(node_id)
    if not isinstance(output, dict) or output.get("decision") not in {"approve", "reject"}:
        return None

    node = next((item for item in graph.get("nodes", []) if item.get("id") == node_id), None)
    if isinstance(node, dict):
        _apply_output_mapping(node, output, state)

    variables = state.setdefault("variables", {})
    if isinstance(variables, dict):
        variables["last_human_approval"] = output

    metadata = state.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["last_human_approval"] = {
            "task_id": task_id,
            "node_id": node_id,
            "decision": output.get("decision"),
        }
        metadata.pop("waiting_approval", None)

    return next_node_id or ""


def _human_approval_waiting_checkpoint(state: State) -> dict[str, Any] | None:
    metadata = state.get("metadata")
    if not isinstance(metadata, dict):
        return None
    checkpoint = metadata.get("waiting_approval")
    return checkpoint if isinstance(checkpoint, dict) else None


def _build_node_input(node: dict[str, Any], state: State) -> dict[str, Any]:
    mapping = node.get("input_mapping") or {}
    if not mapping:
        return {"input": state["input"], "variables": state["variables"]}
    return {key: _resolve_value(value, state) for key, value in mapping.items()}


async def _execute_node(
    conn: AsyncConnection,
    node: dict[str, Any],
    state: State,
    node_input: dict[str, Any],
) -> dict[str, Any]:
    node_type = node.get("type")
    raw_config = node.get("config") or {}
    config = (
        raw_config
        if node_type == "api"
        else _resolve_value_with_node_input(raw_config, state, node_input)
    )

    if node_type == "start":
        return {"started": True}
    if node_type == "input":
        return {"input": state["input"]}
    if node_type == "knowledge_base":
        return await _execute_knowledge_base_node(conn, config, state, node_input)
    if node_type == "llm":
        return await _execute_llm_node(conn, config, state, node_input)
    if node_type == "message":
        return {"message": _resolve_value(config.get("template", ""), state)}
    if node_type == "api":
        return await _execute_api_node(conn, config, state, node_input)
    if node_type == "intent":
        return await _execute_intent_node(conn, config, state, node_input)
    if node_type == "branch":
        selected = _next_branch_target({**node, "config": config}, state)
        if not selected:
            raise RuntimeNodeError("branch_no_match", "Branch node did not match any target")
        return {"selected": selected}
    if node_type == "human_approval":
        return await _execute_human_approval_node(conn, node, config, state, node_input)
    if node_type == "set_variable":
        return _execute_set_variable_node(config, state)
    if node_type == "output":
        output = _resolve_value(config.get("outputs", state.get("variables", {})), state)
        state["final_output"] = output if isinstance(output, dict) else {"result": output}
        return state["final_output"]
    if node_type == "end":
        return {"completed": True}
    raise RuntimeNodeError("invalid_config", f"unsupported node type: {node_type}")


async def _execute_human_approval_node(
    conn: AsyncConnection,
    node: dict[str, Any],
    config: dict[str, Any],
    state: State,
    node_input: dict[str, Any],
) -> dict[str, Any]:
    metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
    workflow_id = metadata.get("workflow_id")
    run_id = metadata.get("run_id")
    if not isinstance(workflow_id, int) or not isinstance(run_id, int):
        raise RuntimeNodeError(
            "invalid_config",
            "human approval node requires workflow_id and run_id in runtime metadata",
        )

    title = str(config.get("title") or node.get("name") or "人工审批").strip()
    if not title:
        raise RuntimeNodeError("invalid_config", "human approval node requires title")
    description = config.get("description")
    description_text = None if description is None or description == "" else str(description)
    approval_input = config.get("input", node_input)
    if not isinstance(approval_input, dict):
        approval_input = {"value": approval_input}

    settings = get_settings()
    task = await human_approvals.create_human_approval_task(
        conn,
        workflow_id=workflow_id,
        run_id=run_id,
        node_id=str(node["id"]),
        node_name=node.get("name"),
        title=title,
        description=description_text,
        input_json=approval_input,
        requested_by=settings.mock_user_id,
        metadata_json={
            "approval_schema": config.get("approval_schema") or {},
            "timeout_seconds": config.get("timeout_seconds"),
        },
    )
    output = {
        "status": "waiting_approval",
        "task_id": task["id"],
        "decision": None,
        "resume_supported": False,
    }
    raise HumanApprovalPause(node_id=str(node["id"]), task_id=int(task["id"]), output=output)


async def _execute_knowledge_base_node(
    conn: AsyncConnection,
    config: dict[str, Any],
    state: State,
    node_input: dict[str, Any],
) -> dict[str, Any]:
    query = _resolve_value_with_node_input(
        config.get("query") or node_input.get("query") or node_input.get("question") or "",
        state,
        node_input,
    )
    top_k = int(config.get("top_k") or config.get("topK") or 5)
    score_threshold = float(config.get("score_threshold") or 0.0)
    context_budget_tokens = (
        int(config["context_budget_tokens"])
        if config.get("context_budget_tokens") not in {None, ""}
        else None
    )
    raw_ids = config.get("knowledge_base_ids")
    if raw_ids is None and config.get("knowledge_base_id") is not None:
        raw_ids = [config.get("knowledge_base_id")]
    if raw_ids is None:
        raw_ids = []
    knowledge_base_ids = [
        int(kb_id)
        for kb_id in _resolve_value(raw_ids, state)
        if kb_id is not None and str(kb_id).strip()
    ]

    chunks: list[dict[str, Any]] = []
    for knowledge_base_id in knowledge_base_ids:
        try:
            chunks.extend(
                await knowledge_processing.retrieve_chunks(
                    conn,
                    knowledge_base_id=knowledge_base_id,
                    query=str(query),
                    top_k=top_k,
                    score_threshold=score_threshold,
                )
            )
        except RuntimeNodeError:
            raise
        except Exception as exc:
            raise RuntimeNodeError(
                "knowledge_base_error",
                str(exc) or "knowledge base retrieval failed",
                retryable=True,
                error_detail={"knowledge_base_id": knowledge_base_id},
            ) from exc
    chunks = sorted(chunks, key=lambda item: item.get("score", 0), reverse=True)[:top_k]
    chunks = knowledge_processing.apply_context_budget(chunks, context_budget_tokens)
    state["variables"]["kb_context"] = chunks
    return {
        "chunks": chunks,
        "returned_chunks": len(chunks),
        "query": query,
        "knowledge_base_ids": knowledge_base_ids,
        "top_k": top_k,
        "score_threshold": score_threshold,
        "context_budget_tokens": context_budget_tokens,
        "retrieval_modes": sorted(
            {str(chunk.get("retrieval_mode")) for chunk in chunks if chunk.get("retrieval_mode")}
        ),
    }


def _execute_set_variable_node(config: dict[str, Any], state: State) -> dict[str, Any]:
    assignments = _normalize_variable_assignments(config)
    values: dict[str, Any] = {}
    for target, value in assignments:
        variable_path = _variable_assignment_path(target)
        _set_path(state["variables"], variable_path, value)
        values[variable_path] = value
    return {"values": values, "count": len(values)}


def _normalize_variable_assignments(config: dict[str, Any]) -> list[tuple[str, Any]]:
    raw_assignments = config.get("assignments", config.get("variables"))
    if isinstance(raw_assignments, dict):
        return [
            (_normalize_variable_target(str(target)), value)
            for target, value in raw_assignments.items()
            if str(target).strip()
        ]
    if isinstance(raw_assignments, list):
        assignments: list[tuple[str, Any]] = []
        for index, item in enumerate(raw_assignments):
            if not isinstance(item, dict):
                raise RuntimeNodeError(
                    "invalid_config",
                    f"set_variable assignment at index {index} must be an object",
                )
            target = item.get("target") or item.get("name")
            if not isinstance(target, str) or not target.strip():
                raise RuntimeNodeError(
                    "invalid_config",
                    f"set_variable assignment at index {index} requires target or name",
                )
            assignments.append((_normalize_variable_target(target), item.get("value")))
        return assignments
    raise RuntimeNodeError(
        "invalid_config",
        "set_variable config.assignments must be an object or an array",
    )


def _normalize_variable_target(target: str) -> str:
    normalized = target.strip()
    if normalized.startswith("variables."):
        return normalized
    return f"variables.{normalized}"


def _variable_assignment_path(target: str) -> str:
    if not target.startswith("variables."):
        raise RuntimeNodeError(
            "invalid_config",
            "set_variable target must start with variables.",
            error_detail={"target": target},
        )
    path = target.removeprefix("variables.").strip(".")
    if not path:
        raise RuntimeNodeError(
            "invalid_config",
            "set_variable target must include a variable path",
            error_detail={"target": target},
        )
    return path


async def _execute_llm_node(
    conn: AsyncConnection,
    config: dict[str, Any],
    state: State,
    node_input: dict[str, Any],
) -> dict[str, Any]:
    model_binding = await _resolve_llm_model_binding(conn, config)
    effective_config = {
        **model_binding.get("default_config", {}),
        **config,
    }
    provider = str(
        model_binding.get("provider_type") or effective_config.get("provider") or "mock"
    ).lower()
    model = str(
        model_binding.get("model_name")
        or effective_config.get("model")
        or ("local-mock" if provider in {"mock", "local", "local-mock"} else "gpt-4.1-mini")
    )
    prompt = _resolve_value(
        effective_config.get("user_prompt") or effective_config.get("prompt") or "",
        state,
    )
    system_prompt = _resolve_value(effective_config.get("system_prompt") or "", state)
    question = state.get("input", {}).get("user_query") or node_input.get("question") or prompt

    if provider in {"mock", "local", "local-mock"}:
        return {
            "answer": f"模拟回答：{question}",
            "provider": provider,
            "model": model,
            "model_config_id": model_binding.get("model_config_id"),
            "prompt": prompt,
        }

    if provider not in {"openai", "deepseek"}:
        raise RuntimeNodeError("invalid_config", f"unsupported LLM provider: {provider}")

    provider_config = model_binding.get("provider_config")
    llm_metadata = _llm_metadata(
        provider=provider,
        model=model,
        model_config_id=model_binding.get("model_config_id"),
    )
    api_key = (
        await resolve_deepseek_api_key(conn, provider_config)
        if provider == "deepseek"
        else await resolve_openai_api_key(conn, provider_config)
    )
    if not api_key:
        raise RuntimeNodeError(
            "model_api_key_missing",
            f"{provider} API key is not configured",
            error_detail=llm_metadata,
        )

    try:
        from openai import AsyncOpenAI
    except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject
        raise RuntimeNodeError("invalid_config", "openai package is not installed") from exc

    base_url = effective_config.get("base_url") or model_binding.get("provider_base_url")
    if provider == "deepseek" and not base_url:
        base_url = "https://api.deepseek.com"
    client_kwargs: dict[str, Any] = {
        "api_key": api_key,
        "timeout": float(effective_config.get("timeout_seconds") or 30),
    }
    if base_url:
        client_kwargs["base_url"] = str(base_url)
    client = AsyncOpenAI(**client_kwargs)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": str(system_prompt)})
    messages.append({"role": "user", "content": str(prompt or question)})
    request_kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(effective_config.get("temperature", 0.2)),
        "max_tokens": int(effective_config.get("max_tokens") or 1000),
    }
    if provider == "deepseek":
        thinking = effective_config.get("thinking")
        if isinstance(thinking, dict):
            request_kwargs["extra_body"] = {"thinking": thinking}
        else:
            thinking_mode = effective_config.get("thinking_mode", False)
            if isinstance(thinking_mode, str):
                thinking_mode = thinking_mode.strip().lower() in {"1", "true", "yes", "enabled"}
            request_kwargs["extra_body"] = {
                "thinking": {"type": "enabled" if thinking_mode else "disabled"},
            }

    try:
        response = await client.chat.completions.create(**request_kwargs)
    except Exception as exc:
        raise _with_llm_metadata(
            _normalize_node_error(exc, {"type": "llm"}),
            llm_metadata,
            secrets=(api_key,),
        ) from exc

    answer, reasoning_content, usage = _extract_llm_response(response, llm_metadata)
    return {
        "answer": answer,
        "reasoning_content": reasoning_content,
        "provider": provider,
        "model": model,
        "model_config_id": model_binding.get("model_config_id"),
        "prompt": prompt,
        "usage": usage,
    }


def _node_llm_metadata(node: dict[str, Any]) -> dict[str, Any]:
    config = node.get("config") or {}
    return _llm_metadata(
        provider=config.get("provider"),
        model=config.get("model"),
        model_config_id=config.get("model_config_id") or config.get("modelConfigId"),
    )


def _llm_metadata(
    *,
    provider: Any,
    model: Any,
    model_config_id: Any,
) -> dict[str, Any]:
    metadata = {
        "provider": str(provider) if provider not in {None, ""} else None,
        "model": str(model) if model not in {None, ""} else None,
        "model_config_id": model_config_id,
    }
    return {key: value for key, value in metadata.items() if value is not None}


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


def _extract_llm_response(
    response: Any,
    metadata: dict[str, Any],
) -> tuple[str, Any, dict[str, Any] | None]:
    try:
        choices = response.choices
        if not choices:
            raise ValueError("missing choices")
        message = getattr(choices[0], "message", None)
        if message is None:
            raise ValueError("missing message")
        content = getattr(message, "content", None)
        if content is None:
            answer = ""
        elif isinstance(content, str):
            answer = content
        else:
            raise ValueError("message content is not a string")
        return answer, getattr(message, "reasoning_content", None), _llm_usage_payload(response)
    except RuntimeNodeError:
        raise
    except Exception as exc:
        raise RuntimeNodeError(
            "model_response_invalid",
            "model response is invalid",
            error_detail={
                **metadata,
                "reason": _redact_sensitive_text(str(exc) or exc.__class__.__name__),
            },
        ) from exc


def _llm_usage_payload(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage
    model_dump = getattr(usage, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else None
    dict_dump = getattr(usage, "dict", None)
    if callable(dict_dump):
        dumped = dict_dump()
        return dumped if isinstance(dumped, dict) else None
    return None


async def _resolve_llm_model_binding(
    conn: AsyncConnection,
    config: dict[str, Any],
) -> dict[str, Any]:
    raw_model_config_id = config.get("model_config_id") or config.get("modelConfigId")
    if raw_model_config_id in {None, ""}:
        return {
            "model_config_id": None,
            "provider_type": None,
            "provider_config": {},
            "model_name": None,
            "default_config": {},
        }

    try:
        model_config_id = int(raw_model_config_id)
    except (TypeError, ValueError) as exc:
        raise RuntimeNodeError("invalid_config", "model_config_id must be an integer") from exc

    result = await conn.execute(
        text(
            """
            SELECT
              mc.id AS model_config_id,
              mc.model_name,
              mc.default_config_json,
              mp.provider_type,
              mp.base_url AS provider_base_url,
              mp.config_json AS provider_config
            FROM model_configs mc
            JOIN model_providers mp ON mp.id = mc.provider_id
            WHERE mc.id = :model_config_id
              AND mc.model_type = 'chat'
              AND mc.status = 'active'
              AND mp.status = 'active'
            """
        ),
        {"model_config_id": model_config_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise RuntimeNodeError(
            "invalid_config",
            f"model_config_id not found or inactive: {model_config_id}",
        )
    model_config = dict(row)
    return {
        "model_config_id": model_config["model_config_id"],
        "provider_type": model_config["provider_type"],
        "provider_base_url": model_config.get("provider_base_url"),
        "provider_config": model_config.get("provider_config") or {},
        "model_name": model_config["model_name"],
        "default_config": model_config.get("default_config_json") or {},
    }


async def _execute_intent_node(
    conn: AsyncConnection,
    config: dict[str, Any],
    state: State,
    node_input: dict[str, Any],
) -> dict[str, Any]:
    query = str(
        _resolve_value(
            config.get("query")
            or node_input.get("query")
            or state.get("input", {}).get("user_query")
            or "",
            state,
        )
    )
    intents = config.get("intents") or []
    fallback = config.get("fallback_intent") or config.get("default_intent") or "default"
    provider = str(config.get("provider") or "keyword").lower()

    if provider == "openai" and config.get("model") and await resolve_openai_api_key(conn):
        try:
            return await _classify_intent_with_openai(conn, config, query, intents, fallback)
        except Exception:
            pass

    intent, score = _classify_intent_by_keywords(query, intents, fallback)
    return {
        "intent": intent,
        "confidence": score,
        "provider": "keyword",
        "query": query,
    }


async def _classify_intent_with_openai(
    conn: AsyncConnection,
    config: dict[str, Any],
    query: str,
    intents: list[dict[str, Any]],
    fallback: str,
) -> dict[str, Any]:
    api_key = await resolve_openai_api_key(conn)
    if not api_key:
        raise RuntimeNodeError(
            "permission_denied",
            "OpenAI API key is required for intent provider=openai",
        )
    from openai import AsyncOpenAI

    model = str(config.get("model"))
    client = AsyncOpenAI(api_key=api_key, timeout=float(config.get("timeout_seconds") or 20))
    try:
        response = await client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify the user query into one intent. Return JSON with "
                        "intent and confidence. If unsure use the fallback intent."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"query": query, "intents": intents, "fallback_intent": fallback},
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0,
        )
    except Exception as exc:
        raise _normalize_node_error(exc, {"type": "llm"}) from exc
    raw = response.choices[0].message.content or "{}"
    parsed = json.loads(raw)
    allowed = {str(item.get("name")) for item in intents if isinstance(item, dict)}
    intent = str(parsed.get("intent") or fallback)
    if intent not in allowed:
        intent = fallback
    return {
        "intent": intent,
        "confidence": float(parsed.get("confidence") or 0.0),
        "provider": "openai",
        "query": query,
    }


def _classify_intent_by_keywords(
    query: str,
    intents: list[dict[str, Any]],
    fallback: str,
) -> tuple[str, float]:
    query_lower = query.lower()
    best_name = fallback
    best_score = 0.0
    for intent in intents:
        if not isinstance(intent, dict):
            continue
        name = str(intent.get("name") or "")
        description = str(intent.get("description") or "")
        keywords = [name, *description.replace(",", " ").replace(";", " ").split()]
        keywords = [keyword.lower().strip() for keyword in keywords if keyword.strip()]
        if not keywords:
            continue
        matched = sum(1 for keyword in set(keywords) if keyword and keyword in query_lower)
        score = matched / len(set(keywords))
        if score > best_score:
            best_name = name
            best_score = score
    return best_name, best_score


def _apply_output_mapping(node: dict[str, Any], output: dict[str, Any], state: State) -> None:
    mapping = node.get("output_mapping") or {}
    for source_key, destination in mapping.items():
        if source_key not in output:
            raise RuntimeNodeError(
                "output_mapping_error",
                f"Output field not found: {source_key}",
                error_detail={"source_key": source_key, "destination": destination},
            )
        value = output[source_key]
        if not isinstance(destination, str):
            raise RuntimeNodeError(
                "output_mapping_error",
                f"Invalid output mapping destination for {source_key}",
                error_detail={"source_key": source_key, "destination": destination},
            )
        if destination.startswith("variables."):
            _set_path(state["variables"], destination.removeprefix("variables."), value)
        elif destination.startswith("outputs."):
            _set_path(state["outputs"], destination.removeprefix("outputs."), value)
        elif destination == "messages":
            messages = value if isinstance(value, list) else [value]
            state.setdefault("messages", []).extend(_message_value(item) for item in messages)
        elif destination == "outputs":
            if not isinstance(value, dict):
                raise RuntimeNodeError(
                    "output_mapping_error",
                    "outputs mapping destination requires an object value",
                    error_detail={"source_key": source_key, "destination": destination},
                )
            state["outputs"].update(value)
        else:
            raise RuntimeNodeError(
                "output_mapping_error",
                f"Unsupported output mapping destination: {destination}",
                error_detail={"source_key": source_key, "destination": destination},
            )

    if node.get("type") == "llm" and "answer" in output:
        state["variables"].setdefault("answer", output["answer"])
    if node.get("type") == "knowledge_base" and "chunks" in output:
        state["variables"].setdefault("kb_context", output["chunks"])


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = [part for part in path.split(".") if part]
    if not parts:
        return
    current = target
    for part in parts[:-1]:
        existing = current.get(part)
        if not isinstance(existing, dict):
            existing = {}
            current[part] = existing
        current = existing
    current[parts[-1]] = value


def _message_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"type": "text", "content": "" if value is None else str(value)}


def _next_node_id(
    node: dict[str, Any],
    outgoing_edges: list[dict[str, Any]],
    state: State | None = None,
) -> str | None:
    if node.get("type") == "branch":
        target = _next_branch_target(node, state)
        if target:
            outgoing_targets = {edge.get("target") for edge in outgoing_edges}
            if target not in outgoing_targets:
                raise RuntimeNodeError(
                    "branch_target_not_found",
                    f"Branch target has no outgoing edge: {target}",
                )
            return target
    if not outgoing_edges:
        return None
    return outgoing_edges[0]["target"]


def _next_branch_target(node: dict[str, Any], state: State | None = None) -> str | None:
    config = node.get("config") or {}
    branches = config.get("branches") or []
    default_target = config.get("default_target") or config.get("default")
    if not isinstance(branches, list):
        return default_target

    for branch in branches:
        if not isinstance(branch, dict):
            continue
        target = branch.get("target")
        if not target:
            continue
        if state is None or _branch_matches(branch, state):
            return target
    if isinstance(default_target, dict):
        return default_target.get("target")
    if isinstance(default_target, str):
        return default_target
    return None


def _branch_matches(branch: dict[str, Any], state: State) -> bool:
    condition = branch.get("condition")
    if condition is None:
        return bool(branch.get("default") or branch.get("is_default"))
    if isinstance(condition, bool):
        return condition
    if isinstance(condition, str):
        resolved = _resolve_value(condition, state)
        if isinstance(resolved, bool):
            return resolved
        if resolved is None:
            return False
        return str(resolved).strip().lower() not in {"", "0", "false", "none", "null", "no"}
    if not isinstance(condition, dict):
        return False

    left = _resolve_value(condition.get("left") or condition.get("path"), state)
    if "value" in condition:
        right = _resolve_value(condition.get("value"), state)
    elif "right" in condition:
        right = _resolve_value(condition.get("right"), state)
    else:
        right = True
    operator = str(condition.get("operator") or condition.get("op") or "eq").lower()

    if operator in {"eq", "==", "equals"}:
        return left == right
    if operator in {"ne", "!=", "not_equals"}:
        return left != right
    if operator in {"contains", "in"}:
        try:
            return left in right if operator == "in" else right in left
        except TypeError:
            return False
    if operator in {"exists", "truthy"}:
        return bool(left)
    if operator in {"not_exists", "falsy"}:
        return not bool(left)
    if operator in {"gt", ">", "gte", ">=", "lt", "<", "lte", "<="}:
        try:
            left_number = float(left)
            right_number = float(right)
        except (TypeError, ValueError):
            return False
        if operator in {"gt", ">"}:
            return left_number > right_number
        if operator in {"gte", ">="}:
            return left_number >= right_number
        if operator in {"lt", "<"}:
            return left_number < right_number
        return left_number <= right_number
    return False


async def _execute_api_node(
    conn: AsyncConnection,
    config: dict[str, Any],
    state: State,
    node_input: dict[str, Any],
) -> dict[str, Any]:
    request = await _resolve_value_for_request(conn, config, state, node_input)
    safe_request = _redact_secrets_in_value(config)
    safe_request = _resolve_value_with_node_input(safe_request, state, node_input)
    mode = str(request.get("mode") or request.get("execution_mode") or "mock").lower()
    method = str(request.get("method") or "GET").upper()
    url = request.get("url") or request.get("endpoint")
    body = request.get("body", node_input)
    headers = request.get("headers") or {}
    query_params = request.get("query_params") or request.get("params") or {}
    timeout_seconds = _bounded_float(
        request.get("timeout_seconds", request.get("timeout")),
        default=10.0,
        minimum=0.1,
        maximum=30.0,
        field="timeout_seconds",
    )
    max_response_bytes = _bounded_int(
        request.get("max_response_bytes"),
        default=_API_DEFAULT_MAX_RESPONSE_BYTES,
        minimum=1,
        maximum=_API_MAX_RESPONSE_BYTES,
        field="max_response_bytes",
    )
    fail_on_http_error = _as_bool(request.get("fail_on_http_error"), default=True)
    fail_on_request_error = _as_bool(request.get("fail_on_request_error"), default=True)
    response_path = request.get("response_path")
    success_status_codes = {
        int(status)
        for status in request.get("success_status_codes", [])
        if str(status).strip()
    }

    if mode == "http":
        safe_url = safe_request.get("url") or safe_request.get("endpoint")
        safe_headers = safe_request.get("headers") or {}
        safe_body = safe_request.get("body", node_input)
        safe_query_params = safe_request.get("query_params") or safe_request.get("params") or {}
        error = _validate_public_http_url(str(url or ""))
        if error:
            return {
                "mode": "http",
                "status": "blocked",
                "status_code": None,
                "request": _request_payload(
                    method,
                    safe_url,
                    safe_headers,
                    safe_body,
                    safe_query_params,
                ),
                "response": None,
                "error": error,
            }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_seconds),
                follow_redirects=False,
            ) as client:
                response = await client.request(
                    method,
                    str(url),
                    headers=headers,
                    json=body,
                    params=query_params,
                )
            response_body = _decode_http_response(response, max_response_bytes)
            if fail_on_http_error and not _http_status_is_success(
                response.status_code,
                success_status_codes,
            ):
                raise _api_response_error(response.status_code, response_body)
            extracted_response = _extract_response_path(response_body, response_path)
            return {
                "mode": "http",
                "status": "success",
                "status_code": response.status_code,
                "request": _request_payload(
                    method,
                    safe_url,
                    safe_headers,
                    safe_body,
                    safe_query_params,
                ),
                "response": extracted_response,
                "response_path": response_path or None,
                "max_response_bytes": max_response_bytes,
                "error": None,
            }
        except RuntimeNodeError:
            raise
        except Exception as exc:
            if fail_on_request_error:
                raise _normalize_node_error(exc, {"type": "api"}) from exc
            return {
                "mode": "http",
                "status": "error",
                "status_code": None,
                "request": _request_payload(
                    method,
                    safe_url,
                    safe_headers,
                    safe_body,
                    safe_query_params,
                ),
                "response": None,
                "error": f"{exc.__class__.__name__}: {exc}",
            }

    safe_body = safe_request.get("body", node_input)
    safe_headers = safe_request.get("headers") or {}
    safe_url = safe_request.get("url") or safe_request.get("endpoint")
    safe_query_params = safe_request.get("query_params") or safe_request.get("params") or {}
    mock_response = _extract_response_path(
        request.get("mock_response", {"ok": True}),
        response_path,
    )
    return {
        "mode": "mock",
        "status": "mocked",
        "status_code": int(request.get("mock_status_code", 200)),
        "request": _request_payload(method, safe_url, safe_headers, safe_body, safe_query_params),
        "response": mock_response,
        "response_path": response_path or None,
        "max_response_bytes": max_response_bytes,
    }


def _request_payload(
    method: str,
    url: Any,
    headers: Any,
    body: Any,
    query_params: Any = None,
) -> dict[str, Any]:
    return {
        "method": method,
        "url": url,
        "query_params": _redact_sensitive_mapping(query_params or {}),
        "headers": _redact_sensitive_mapping(headers),
        "body": body,
    }


def _decode_http_response(response: httpx.Response, max_response_bytes: int) -> Any:
    if len(response.content) > max_response_bytes:
        raise RuntimeNodeError(
            "response_too_large",
            f"API response exceeded {max_response_bytes} bytes",
            error_detail={
                "status_code": response.status_code,
                "max_response_bytes": max_response_bytes,
            },
        )
    try:
        return response.json()
    except ValueError:
        return response.text[:8192]


def _bounded_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
    field: str,
) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeNodeError("invalid_config", f"{field} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise RuntimeNodeError(
            "invalid_config",
            f"{field} must be between {minimum} and {maximum}",
            error_detail={"field": field, "minimum": minimum, "maximum": maximum},
        )
    return parsed


def _bounded_float(
    value: Any,
    *,
    default: float,
    minimum: float,
    maximum: float,
    field: str,
) -> float:
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeNodeError("invalid_config", f"{field} must be a number") from exc
    if parsed < minimum or parsed > maximum:
        raise RuntimeNodeError(
            "invalid_config",
            f"{field} must be between {minimum:g} and {maximum:g}",
            error_detail={"field": field, "minimum": minimum, "maximum": maximum},
        )
    return parsed


def _http_status_is_success(status_code: int, success_status_codes: set[int]) -> bool:
    if success_status_codes:
        return status_code in success_status_codes
    return 200 <= status_code < 300


def _api_response_error(status_code: int, response_body: Any) -> RuntimeNodeError:
    error = _normalize_status_error(status_code, f"API returned HTTP {status_code}", "api")
    error.error_detail["response_preview"] = _safe_response_preview(response_body)
    return error


def _safe_response_preview(value: Any) -> Any:
    redacted = _redact_sensitive_mapping(value) if isinstance(value, dict) else value
    preview = str(redacted)
    return preview[:500]


def _extract_response_path(response_body: Any, response_path: Any) -> Any:
    if response_path in {None, ""}:
        return response_body
    if not isinstance(response_path, str):
        raise RuntimeNodeError("invalid_config", "response_path must be a string")
    try:
        return _get_path(response_path, response_body)
    except RuntimeNodeError as exc:
        raise RuntimeNodeError(
            "api_response_error",
            f"response_path not found: {response_path}",
            error_detail={"response_path": response_path},
        ) from exc


def _validate_public_http_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "api http mode only allows http and https URLs"
    if not parsed.hostname:
        return "api http mode requires a hostname"
    hostname = parsed.hostname.strip().lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        return "api http mode blocks localhost and private network URLs"
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(hostname, parsed.port or None)}
    except socket.gaierror as exc:
        return f"api http mode could not resolve hostname: {exc}"
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return "api http mode blocks unresolved or invalid IP addresses"
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return "api http mode blocks localhost and private network URLs"
    return None


async def _resolve_value_for_request(
    conn: AsyncConnection,
    value: Any,
    state: State,
    node_input: dict[str, Any],
) -> Any:
    if isinstance(value, dict):
        return {
            key: await _resolve_value_for_request(conn, item, state, node_input)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [await _resolve_value_for_request(conn, item, state, node_input) for item in value]
    if not isinstance(value, str):
        return value

    full_match = _PLACEHOLDER_RE.fullmatch(value)
    if full_match:
        return await _get_request_path(conn, full_match.group(1).strip(), state, node_input)

    async def resolve_match(match: re.Match[str]) -> str:
        resolved = await _get_request_path(conn, match.group(1).strip(), state, node_input)
        return "" if resolved is None else str(resolved)

    parts: list[str] = []
    cursor = 0
    for match in _PLACEHOLDER_RE.finditer(value):
        parts.append(value[cursor : match.start()])
        parts.append(await resolve_match(match))
        cursor = match.end()
    parts.append(value[cursor:])
    return "".join(parts)


async def _get_request_path(
    conn: AsyncConnection,
    path: str,
    state: State,
    node_input: dict[str, Any],
) -> Any:
    if path.startswith("secrets."):
        value = await get_secret_value(conn, path.removeprefix("secrets."))
        if value is None:
            raise RuntimeNodeError("permission_denied", f"Secret not found: {path}")
        return value
    return _get_path_with_node_input(path, state, node_input)


def _redact_secrets_in_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_secrets_in_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_secrets_in_value(item) for item in value]
    if not isinstance(value, str):
        return value
    if _PLACEHOLDER_RE.fullmatch(value):
        placeholder = _PLACEHOLDER_RE.fullmatch(value)
        if placeholder and placeholder.group(1).strip().startswith("secrets."):
            return "***"
    return _PLACEHOLDER_RE.sub(
        lambda match: "***" if match.group(1).strip().startswith("secrets.") else match.group(0),
        value,
    )


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


def _resolve_value(value: Any, state: State) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_value(item, state) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_value(item, state) for item in value]
    if not isinstance(value, str):
        return value

    full_match = _PLACEHOLDER_RE.fullmatch(value)
    if full_match:
        return _get_path(full_match.group(1).strip(), state)

    def replace(match: re.Match[str]) -> str:
        resolved = _get_path(match.group(1).strip(), state)
        return "" if resolved is None else str(resolved)

    return _PLACEHOLDER_RE.sub(replace, value)


def _resolve_value_with_node_input(value: Any, state: State, node_input: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {
            key: _resolve_value_with_node_input(item, state, node_input)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_resolve_value_with_node_input(item, state, node_input) for item in value]
    if not isinstance(value, str):
        return value

    full_match = _PLACEHOLDER_RE.fullmatch(value)
    if full_match:
        return _get_path_with_node_input(full_match.group(1).strip(), state, node_input)

    def replace(match: re.Match[str]) -> str:
        resolved = _get_path_with_node_input(match.group(1).strip(), state, node_input)
        return "" if resolved is None else str(resolved)

    return _PLACEHOLDER_RE.sub(replace, value)


def _get_path_with_node_input(path: str, state: State, node_input: dict[str, Any]) -> Any:
    resolved = _try_get_path(path, state)
    if resolved is not _MISSING:
        return resolved
    if path.startswith("node_input."):
        return _get_path(path.removeprefix("node_input."), node_input)
    return _get_path(path, node_input)


def _get_path(path: str, state: State) -> Any:
    resolved = _try_get_path(path, state)
    if resolved is _MISSING:
        raise RuntimeNodeError(
            "variable_not_found",
            f"Variable not found: {path}",
            error_detail={"path": path},
        )
    return resolved


def _try_get_path(path: str, state: State) -> Any:
    current: Any = state
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return _MISSING
            current = current[part]
        else:
            return _MISSING
    return current


def _fallback_output(state: State) -> dict[str, Any]:
    if state.get("variables"):
        return dict(state["variables"])
    return {"input": state.get("input", {})}


def _node_metadata(node: dict[str, Any]) -> dict[str, Any]:
    config = node.get("config") or {}
    metadata = {
        "runtime": "graph_runtime",
        "node_type": node.get("type"),
        "provider": config.get("provider"),
        "model": config.get("model"),
        "model_config_id": config.get("model_config_id") or config.get("modelConfigId"),
        "mode": config.get("mode") or config.get("execution_mode"),
    }
    return {key: value for key, value in metadata.items() if value is not None}


async def _create_run(
    conn: AsyncConnection,
    workflow_id: int,
    version_id: int,
    run_input: dict[str, Any],
    trigger_type: str,
    created_by: int,
    metadata_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = await conn.execute(
        _jsonb_stmt(
            """
            INSERT INTO workflow_runs (
              workflow_id,
              version_id,
              status,
              trigger_type,
              input_json,
              state_json,
              metadata_json,
              created_by
            )
            VALUES (
              :workflow_id,
              :version_id,
              'pending',
              :trigger_type,
              :input_json,
              '{}'::jsonb,
              :metadata_json,
              :created_by
            )
            RETURNING *
            """,
            "input_json",
            "metadata_json",
        ),
        {
            "workflow_id": workflow_id,
            "version_id": version_id,
            "trigger_type": trigger_type,
            "input_json": run_input,
            "metadata_json": metadata_json or {"execution_mode": "sync", "runtime": "graph_mock"},
            "created_by": created_by,
        },
    )
    return dict(result.mappings().one())


async def _update_run_metadata(
    conn: AsyncConnection,
    run_id: int,
    metadata_json: dict[str, Any],
) -> None:
    await conn.execute(
        _jsonb_stmt(
            """
            UPDATE workflow_runs
            SET metadata_json = :metadata_json,
                updated_at = now()
            WHERE id = :run_id
            """,
            "metadata_json",
        ),
        {"run_id": run_id, "metadata_json": metadata_json},
    )


async def _mark_run_failed(
    conn: AsyncConnection,
    run_id: int,
    error_code: str,
    error_message: str,
    state: State,
) -> None:
    await conn.execute(
        _jsonb_stmt(
            """
            UPDATE workflow_runs
            SET status = 'failed',
                error_code = :error_code,
                error_message = :error_message,
                state_json = :state_json,
                ended_at = now(),
                updated_at = now()
            WHERE id = :run_id
            """,
            "state_json",
        ),
        {
            "run_id": run_id,
            "error_code": error_code,
            "error_message": error_message,
            "state_json": state,
        },
    )


async def _persist_run_state(conn: AsyncConnection, run_id: int, state: State) -> None:
    await conn.execute(
        _jsonb_stmt(
            """
            UPDATE workflow_runs
            SET state_json = :state_json,
                updated_at = now()
            WHERE id = :run_id
            """,
            "state_json",
        ),
        {"run_id": run_id, "state_json": state},
    )


async def _create_node_run(
    conn: AsyncConnection,
    run_id: int,
    node: dict[str, Any],
    node_input: dict[str, Any],
    *,
    attempt: int = 1,
) -> int:
    result = await conn.execute(
        _jsonb_stmt(
            """
            INSERT INTO node_runs (
              run_id,
              node_id,
              node_type,
              node_name,
              status,
              attempt,
              input_json,
              metadata_json,
              started_at
            )
            VALUES (
              :run_id,
              :node_id,
              :node_type,
              :node_name,
              'running',
              :attempt,
              :input_json,
              :metadata_json,
              now()
            )
            RETURNING id
            """,
            "input_json",
            "metadata_json",
        ),
        {
            "run_id": run_id,
            "node_id": node["id"],
            "node_type": node["type"],
            "node_name": node.get("name"),
            "attempt": attempt,
            "input_json": node_input,
            "metadata_json": _node_metadata(node),
        },
    )
    return int(result.scalar_one())


async def _mark_node_success(
    conn: AsyncConnection,
    node_run_id: int,
    output: dict[str, Any],
    duration_ms: int,
) -> None:
    metadata_json = _node_success_metadata(output, duration_ms)
    await conn.execute(
        _jsonb_stmt(
            """
            UPDATE node_runs
            SET status = 'success',
                output_json = :output_json,
                metadata_json = COALESCE(metadata_json, '{}'::jsonb) || :metadata_json,
                duration_ms = :duration_ms,
                ended_at = now()
            WHERE id = :node_run_id
            """,
            "output_json",
            "metadata_json",
        ),
        {
            "node_run_id": node_run_id,
            "output_json": output,
            "metadata_json": {
                key: value for key, value in metadata_json.items() if value is not None
            },
            "duration_ms": duration_ms,
        },
    )


async def _mark_node_waiting_approval(
    conn: AsyncConnection,
    node_run_id: int,
    output: dict[str, Any],
    duration_ms: int,
) -> None:
    await conn.execute(
        _jsonb_stmt(
            """
            UPDATE node_runs
            SET status = :status,
                output_json = :output_json,
                metadata_json = COALESCE(metadata_json, '{}'::jsonb) || :metadata_json,
                duration_ms = :duration_ms
            WHERE id = :node_run_id
            """,
            "output_json",
            "metadata_json",
        ),
        {
            "node_run_id": node_run_id,
            "status": "waiting_approval",
            "output_json": output,
            "metadata_json": {
                "runtime": "graph_runtime",
                "duration_ms": duration_ms,
                "approval_task_id": output.get("task_id"),
                "resume_supported": output.get("resume_supported"),
            },
            "duration_ms": duration_ms,
        },
    )


def _node_success_metadata(output: dict[str, Any], duration_ms: int) -> dict[str, Any]:
    request = output.get("request") if isinstance(output.get("request"), dict) else {}
    usage = output.get("usage") if isinstance(output.get("usage"), dict) else None
    metadata = {
        "runtime": "graph_runtime",
        "status_code": output.get("status_code"),
        "provider": output.get("provider"),
        "model": output.get("model"),
        "model_config_id": output.get("model_config_id"),
        "mode": output.get("mode"),
        "method": request.get("method"),
        "url": request.get("url"),
        "duration_ms": duration_ms,
        "token_usage": usage,
        "knowledge_base_ids": output.get("knowledge_base_ids"),
        "top_k": output.get("top_k"),
        "returned_chunks": output.get("returned_chunks"),
        "retrieval_modes": output.get("retrieval_modes"),
    }
    return {key: value for key, value in metadata.items() if value is not None}


async def _mark_node_failed(
    conn: AsyncConnection,
    node_run_id: int,
    exc: Exception,
    duration_ms: int,
    *,
    will_retry: bool = False,
) -> None:
    error = _normalize_node_error(exc)
    error_detail = _redact_sensitive_data(error.error_detail)
    metadata_json = {
        "retryable": error.retryable,
        "will_retry": will_retry,
        "duration_ms": duration_ms,
        "error_detail": error_detail,
    }
    if isinstance(error_detail, dict):
        for key in ("provider", "model", "model_config_id", "token_usage"):
            if key in error_detail:
                metadata_json[key] = error_detail[key]
    await conn.execute(
        _jsonb_stmt(
            """
            UPDATE node_runs
            SET status = :status,
                error_code = :error_code,
                error_message = :error_message,
                metadata_json = COALESCE(metadata_json, '{}'::jsonb) || :metadata_json,
                duration_ms = :duration_ms,
                ended_at = now()
            WHERE id = :node_run_id
            """,
            "metadata_json",
        ),
        {
            "node_run_id": node_run_id,
            "status": "retrying" if will_retry else "failed",
            "error_code": error.error_code,
            "error_message": _redact_sensitive_text(str(error)),
            "metadata_json": metadata_json,
            "duration_ms": duration_ms,
        },
    )


def _load_generated_workflow(
    code_path: str | None,
    published_hash: str | None,
) -> GeneratedWorkflow:
    return generated_runtime.load_generated_workflow(
        code_path,
        published_hash,
        backend_root=_BACKEND_ROOT,
        project_root=_PROJECT_ROOT,
        generated_root=_GENERATED_ROOT,
    )


def _resolve_code_path(code_path: str) -> Path:
    return generated_runtime.resolve_code_path(
        code_path,
        backend_root=_BACKEND_ROOT,
        project_root=_PROJECT_ROOT,
        generated_root=_GENERATED_ROOT,
    )


def _is_generated_workflow_path(path: Path) -> bool:
    return generated_runtime.is_generated_workflow_path(path, generated_root=_GENERATED_ROOT)


def _sha256_file(path: Path) -> str:
    return generated_runtime.sha256_file(path)


def _relative_project_path(path: Path) -> str:
    return generated_runtime.relative_project_path(path, project_root=_PROJECT_ROOT)


def _jsonb_stmt(sql: str, *jsonb_param_names: str):
    statement = text(sql)
    return statement.bindparams(
        *(bindparam(param_name, type_=JSONB) for param_name in jsonb_param_names)
    )
