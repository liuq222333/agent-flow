import hashlib
import importlib.util
import inspect
import ipaddress
import json
import re
import socket
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection

from app.services import knowledge_processing
from app.services.secrets import get_secret_value, resolve_openai_api_key

Graph = dict[str, Any]
State = dict[str, Any]

_PLACEHOLDER_RE = re.compile(r"{{\s*([^}]+)\s*}}")
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _BACKEND_ROOT.parent
_GENERATED_ROOT = (_BACKEND_ROOT / "generated_workflows").resolve()
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


class WorkflowCodeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GeneratedWorkflow:
    run: Any
    code_path: Path
    code_hash_at_run: str
    code_modified: bool


class GeneratedWorkflowContext:
    def __init__(self, conn: AsyncConnection, *, run_id: int, state: State) -> None:
        self._conn = conn
        self.run_id = run_id
        self.state = state

    async def execute_graph(self, graph: Graph, input_data: dict[str, Any]) -> dict[str, Any]:
        self.state["input"] = input_data
        await _execute_graph(self._conn, run_id=self.run_id, graph=graph, state=self.state)
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
        node_input = _build_node_input(node, self.state)
        started = time.perf_counter()
        node_run_id = await _create_node_run(self._conn, self.run_id, node, node_input)
        try:
            output = await _execute_node(self._conn, node, self.state, node_input)
            self.state["outputs"][node_id] = output
            _apply_output_mapping(node, output, self.state)
            duration_ms = int((time.perf_counter() - started) * 1000)
            await _mark_node_success(self._conn, node_run_id, output, duration_ms)
            return output
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            await _mark_node_failed(self._conn, node_run_id, exc, duration_ms)
            raise

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
    except WorkflowCodeError as exc:
        await _mark_run_failed(conn, run_id, exc.code, str(exc), state)
    except Exception as exc:  # pragma: no cover - defensive runtime boundary
        await _mark_run_failed(conn, run_id, exc.__class__.__name__, str(exc), state)

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

    state: State = {
        "input": run["input_json"] or {},
        "variables": {},
        "messages": [],
        "outputs": {},
        "metadata": {
            "run_id": run_id,
            "workflow_id": run["workflow_id"],
            "version_id": run["version_id"],
        },
        "path": [],
        "final_output": {},
    }

    try:
        generated = _load_generated_workflow(run.get("code_path"), run.get("code_hash"))
        metadata = dict(run.get("metadata_json") or {})
        metadata.update(
            {
                "execution_mode": metadata.get("execution_mode", "async"),
                "runtime": "generated_workflow",
                "code_path_at_run": _relative_project_path(generated.code_path),
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
    except WorkflowCodeError as exc:
        await _mark_run_failed(conn, run_id, exc.code, str(exc), state)
    except Exception as exc:  # pragma: no cover - defensive runtime boundary
        await _mark_run_failed(conn, run_id, exc.__class__.__name__, str(exc), state)

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
    except Exception as exc:  # pragma: no cover - defensive runtime boundary
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
                "error_code": exc.__class__.__name__,
                "error_message": str(exc),
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

    node_id = start_nodes[0]["id"]
    visited_steps = 0
    max_steps = max(len(nodes) * 2, 1)

    while node_id:
        if visited_steps > max_steps:
            raise ValueError("possible_cycle_detected")
        visited_steps += 1

        node = nodes[node_id]
        state["path"].append(node_id)
        node_input = _build_node_input(node, state)
        started = time.perf_counter()
        node_run_id = await _create_node_run(conn, run_id, node, node_input)

        try:
            output = await _execute_node(conn, node, state, node_input)
            state["outputs"][node_id] = output
            _apply_output_mapping(node, output, state)
            duration_ms = int((time.perf_counter() - started) * 1000)
            await _mark_node_success(conn, node_run_id, output, duration_ms)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            await _mark_node_failed(conn, node_run_id, exc, duration_ms)
            raise

        if node.get("type") == "end":
            state["final_output"] = state.get("final_output") or _fallback_output(state)
            break

        node_id = _next_node_id(node, outgoing.get(node_id, []), state)


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
    config = node.get("config") or {}

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
        return {"selected": _next_branch_target(node, state)}
    if node_type == "output":
        output = _resolve_value(config.get("outputs", state.get("variables", {})), state)
        state["final_output"] = output if isinstance(output, dict) else {"result": output}
        return state["final_output"]
    if node_type == "end":
        return {"completed": True}
    return {"result": None}


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
        chunks.extend(
            await knowledge_processing.retrieve_chunks(
                conn,
                knowledge_base_id=knowledge_base_id,
                query=str(query),
                top_k=top_k,
                score_threshold=score_threshold,
            )
        )
    chunks = sorted(chunks, key=lambda item: item.get("score", 0), reverse=True)[:top_k]
    state["variables"]["kb_context"] = chunks
    return {
        "chunks": chunks,
        "query": query,
        "knowledge_base_ids": knowledge_base_ids,
        "top_k": top_k,
        "score_threshold": score_threshold,
    }


async def _execute_llm_node(
    conn: AsyncConnection,
    config: dict[str, Any],
    state: State,
    node_input: dict[str, Any],
) -> dict[str, Any]:
    provider = str(config.get("provider") or "mock").lower()
    model = str(config.get("model") or ("local-mock" if provider == "mock" else "gpt-4.1-mini"))
    prompt = _resolve_value(config.get("user_prompt") or config.get("prompt") or "", state)
    system_prompt = _resolve_value(config.get("system_prompt") or "", state)
    question = state.get("input", {}).get("user_query") or node_input.get("question") or prompt

    if provider == "mock":
        return {
            "answer": f"模拟回答：{question}",
            "provider": "mock",
            "model": model,
            "prompt": prompt,
        }

    if provider != "openai":
        raise ValueError(f"unsupported_llm_provider:{provider}")

    api_key = await resolve_openai_api_key(conn)
    if not api_key:
        raise RuntimeError("OpenAI API key is required for provider=openai")

    try:
        from openai import AsyncOpenAI
    except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject
        raise RuntimeError("openai package is not installed") from exc

    client = AsyncOpenAI(api_key=api_key, timeout=float(config.get("timeout_seconds") or 30))
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": str(system_prompt)})
    messages.append({"role": "user", "content": str(prompt or question)})
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=float(config.get("temperature", 0.2)),
    )
    answer = response.choices[0].message.content or ""
    return {
        "answer": answer,
        "provider": "openai",
        "model": model,
        "prompt": prompt,
        "usage": response.usage.model_dump() if response.usage else None,
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
        raise RuntimeError("OpenAI API key is required for intent provider=openai")
    from openai import AsyncOpenAI

    model = str(config.get("model"))
    client = AsyncOpenAI(api_key=api_key, timeout=float(config.get("timeout_seconds") or 20))
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
        value = output.get(source_key)
        if not isinstance(destination, str):
            continue
        if destination.startswith("variables."):
            _set_path(state["variables"], destination.removeprefix("variables."), value)
        elif destination == "messages":
            state.setdefault("messages", []).append(_message_value(value))

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
    request = await _resolve_value_for_request(conn, config, state)
    safe_request = _redact_secrets_in_value(config)
    safe_request = _resolve_value(safe_request, state)
    mode = str(request.get("mode") or request.get("execution_mode") or "mock").lower()
    method = str(request.get("method") or "GET").upper()
    url = request.get("url") or request.get("endpoint")
    body = request.get("body", node_input)
    headers = request.get("headers") or {}
    timeout_seconds = min(max(float(request.get("timeout_seconds") or 10), 0.1), 30.0)

    if mode == "http":
        safe_url = safe_request.get("url") or safe_request.get("endpoint")
        safe_headers = safe_request.get("headers") or {}
        safe_body = safe_request.get("body", node_input)
        error = _validate_public_http_url(str(url or ""))
        if error:
            return {
                "mode": "http",
                "status": "blocked",
                "status_code": None,
                "request": _request_payload(method, safe_url, safe_headers, safe_body),
                "response": None,
                "error": error,
            }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_seconds),
                follow_redirects=False,
            ) as client:
                response = await client.request(method, str(url), headers=headers, json=body)
            response_body: Any
            try:
                response_body = response.json()
            except ValueError:
                response_body = response.text[:8192]
            return {
                "mode": "http",
                "status": "success",
                "status_code": response.status_code,
                "request": _request_payload(method, safe_url, safe_headers, safe_body),
                "response": response_body,
                "error": None,
            }
        except Exception as exc:
            return {
                "mode": "http",
                "status": "error",
                "status_code": None,
                "request": _request_payload(method, safe_url, safe_headers, safe_body),
                "response": None,
                "error": f"{exc.__class__.__name__}: {exc}",
            }

    safe_body = safe_request.get("body", node_input)
    safe_headers = safe_request.get("headers") or {}
    safe_url = safe_request.get("url") or safe_request.get("endpoint")
    return {
        "mode": "mock",
        "status": "mocked",
        "status_code": int(request.get("mock_status_code", 200)),
        "request": _request_payload(method, safe_url, safe_headers, safe_body),
        "response": request.get("mock_response", {"ok": True}),
    }


def _request_payload(method: str, url: Any, headers: Any, body: Any) -> dict[str, Any]:
    return {
        "method": method,
        "url": url,
        "headers": _redact_sensitive_mapping(headers),
        "body": body,
    }


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


async def _resolve_value_for_request(conn: AsyncConnection, value: Any, state: State) -> Any:
    if isinstance(value, dict):
        return {
            key: await _resolve_value_for_request(conn, item, state)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [await _resolve_value_for_request(conn, item, state) for item in value]
    if not isinstance(value, str):
        return value

    full_match = _PLACEHOLDER_RE.fullmatch(value)
    if full_match:
        return await _get_request_path(conn, full_match.group(1).strip(), state)

    async def resolve_match(match: re.Match[str]) -> str:
        resolved = await _get_request_path(conn, match.group(1).strip(), state)
        return "" if resolved is None else str(resolved)

    parts: list[str] = []
    cursor = 0
    for match in _PLACEHOLDER_RE.finditer(value):
        parts.append(value[cursor : match.start()])
        parts.append(await resolve_match(match))
        cursor = match.end()
    parts.append(value[cursor:])
    return "".join(parts)


async def _get_request_path(conn: AsyncConnection, path: str, state: State) -> Any:
    if path.startswith("secrets."):
        return await get_secret_value(conn, path.removeprefix("secrets."))
    return _get_path(path, state)


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
    resolved = _get_path(path, state)
    if resolved is not None:
        return resolved
    if path.startswith("node_input."):
        return _get_path(path.removeprefix("node_input."), node_input)
    return _get_path(path, node_input)


def _get_path(path: str, state: State) -> Any:
    current: Any = state
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
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


async def _create_node_run(
    conn: AsyncConnection,
    run_id: int,
    node: dict[str, Any],
    node_input: dict[str, Any],
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
    metadata_json = {
        "runtime": "graph_runtime",
        "status_code": output.get("status_code"),
        "provider": output.get("provider"),
        "mode": output.get("mode"),
    }
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


async def _mark_node_failed(
    conn: AsyncConnection,
    node_run_id: int,
    exc: Exception,
    duration_ms: int,
) -> None:
    await conn.execute(
        text(
            """
            UPDATE node_runs
            SET status = 'failed',
                error_code = :error_code,
                error_message = :error_message,
                duration_ms = :duration_ms,
                ended_at = now()
            WHERE id = :node_run_id
            """
        ),
        {
            "node_run_id": node_run_id,
            "error_code": exc.__class__.__name__,
            "error_message": str(exc),
            "duration_ms": duration_ms,
        },
    )


def _load_generated_workflow(
    code_path: str | None,
    published_hash: str | None,
) -> GeneratedWorkflow:
    if not code_path:
        raise WorkflowCodeError("workflow_code_missing", "workflow version has no code_path")

    resolved_path = _resolve_code_path(code_path)
    if not resolved_path.exists() or not resolved_path.is_file():
        raise WorkflowCodeError(
            "workflow_code_missing",
            f"generated workflow code not found: {code_path}",
        )

    actual_hash = _sha256_file(resolved_path)
    module_key = hashlib.sha256(f"{resolved_path.as_posix()}:{actual_hash}".encode()).hexdigest()
    module_name = f"generated_workflow_{module_key}"
    spec = importlib.util.spec_from_file_location(module_name, resolved_path)
    if spec is None or spec.loader is None:
        raise WorkflowCodeError(
            "workflow_code_import_failed",
            f"cannot create import spec for generated workflow: {code_path}",
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise WorkflowCodeError("workflow_code_import_failed", str(exc)) from exc

    run = getattr(module, "run", None)
    if not inspect.iscoroutinefunction(run):
        raise WorkflowCodeError(
            "workflow_entrypoint_missing",
            "generated workflow must expose async def run(input_data, context)",
        )

    return GeneratedWorkflow(
        run=run,
        code_path=resolved_path,
        code_hash_at_run=actual_hash,
        code_modified=bool(published_hash and actual_hash != published_hash),
    )


def _resolve_code_path(code_path: str) -> Path:
    path = Path(code_path)
    if not path.is_absolute():
        candidates = [_PROJECT_ROOT / path, _BACKEND_ROOT / path]
        parts = path.parts
        if parts and parts[0] in {"backend", "app", _BACKEND_ROOT.name} and len(parts) > 1:
            candidates.append(_BACKEND_ROOT / Path(*parts[1:]))
    else:
        candidates = [path]

    resolved_candidates = [candidate.resolve() for candidate in candidates]
    resolved = next(
        (candidate for candidate in resolved_candidates if _is_generated_workflow_path(candidate)),
        resolved_candidates[0],
    )
    try:
        resolved.relative_to(_GENERATED_ROOT)
    except ValueError as exc:
        raise WorkflowCodeError(
            "workflow_code_missing",
            f"generated workflow code path is outside generated_workflows: {code_path}",
        ) from exc
    return resolved


def _is_generated_workflow_path(path: Path) -> bool:
    try:
        path.relative_to(_GENERATED_ROOT)
    except ValueError:
        return False
    return True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _relative_project_path(path: Path) -> str:
    try:
        relative = path.resolve().relative_to(_PROJECT_ROOT)
    except ValueError:
        relative = path.resolve()
    return relative.as_posix()


def _jsonb_stmt(sql: str, *jsonb_param_names: str):
    statement = text(sql)
    return statement.bindparams(
        *(bindparam(param_name, type_=JSONB) for param_name in jsonb_param_names)
    )
