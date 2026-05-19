import sys
from types import SimpleNamespace

import pytest

from app.services import runtime


class _ScalarResult:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value


class _MappingResult:
    def __init__(self, row=None) -> None:
        self.row = row

    def mappings(self):
        return self

    def one(self):
        return self.row

    def one_or_none(self):
        return self.row


class _FakeConnection:
    def __init__(self) -> None:
        self._node_run_id = 1
        self.node_runs = {}

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}

        if "INSERT INTO node_runs" in sql:
            node_run_id = self._node_run_id
            self._node_run_id += 1
            self.node_runs[node_run_id] = {
                "node_id": params["node_id"],
                "node_type": params["node_type"],
                "attempt": params["attempt"],
                "input_json": params["input_json"],
                "metadata_json": params["metadata_json"],
            }
            return _ScalarResult(node_run_id)

        if "UPDATE node_runs" in sql:
            self.node_runs[params["node_run_id"]].update(params)
            return _ScalarResult()

        return _ScalarResult()


class _HumanApprovalConnection(_FakeConnection):
    def __init__(self) -> None:
        super().__init__()
        self.approval_task_input = None
        self.approval_task_metadata = None
        self.run_waiting_metadata = None
        self.persisted_state = None

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}

        if "INSERT INTO human_approval_tasks" in sql:
            self.approval_task_input = params["input_json"]
            self.approval_task_metadata = params["metadata_json"]
            return _MappingResult(
                {
                    "id": 77,
                    "workflow_id": params["workflow_id"],
                    "run_id": params["run_id"],
                    "node_id": params["node_id"],
                    "node_name": params["node_name"],
                    "title": params["title"],
                    "description": params["description"],
                    "status": "pending",
                    "decision": None,
                    "input_json": params["input_json"],
                    "response_json": None,
                    "metadata_json": params["metadata_json"],
                    "requested_by": params["requested_by"],
                    "decided_by": None,
                    "created_at": None,
                    "updated_at": None,
                    "decided_at": None,
                    "expires_at": None,
                }
            )

        if "UPDATE workflow_runs" in sql and "status = 'waiting_approval'" in sql:
            self.run_waiting_metadata = params["metadata_json"]
            return _ScalarResult()

        if "UPDATE workflow_runs" in sql and "state_json" in sql:
            self.persisted_state = params["state_json"]
            return _ScalarResult()

        return await super().execute(statement, params)


class _ModelConfigConnection(_FakeConnection):
    async def execute(self, statement, params=None):
        sql = str(statement)
        if "FROM model_configs" in sql:
            return _MappingResult(
                {
                    "model_config_id": params["model_config_id"],
                    "model_name": "configured-chat-model",
                    "default_config_json": {"temperature": 0.7},
                    "provider_type": "mock",
                    "provider_base_url": None,
                    "provider_config": {},
                }
            )
        return await super().execute(statement, params)


class _DeepSeekModelConfigConnection(_FakeConnection):
    async def execute(self, statement, params=None):
        sql = str(statement)
        if "FROM model_configs" in sql:
            return _MappingResult(
                {
                    "model_config_id": params["model_config_id"],
                    "model_name": "deepseek-v4-flash",
                    "default_config_json": {"temperature": 0.3},
                    "provider_type": "deepseek",
                    "provider_base_url": "https://api.deepseek.com",
                    "provider_config": {"api_key_secret": "deepseek_api_key"},
                }
            )
        return await super().execute(statement, params)


class _FakeUsage:
    def __init__(self, payload) -> None:
        self.payload = payload

    def model_dump(self):
        return self.payload


def _install_fake_openai(monkeypatch, create):
    class _FakeCompletions:
        async def create(self, **kwargs):
            result = create(**kwargs)
            if hasattr(result, "__await__"):
                return await result
            return result

    class _FakeAsyncOpenAI:
        instances = []

        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.chat = SimpleNamespace(completions=_FakeCompletions())
            self.instances.append(self)

    monkeypatch.setitem(
        sys.modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=_FakeAsyncOpenAI),
    )
    return _FakeAsyncOpenAI


def test_branch_selects_matching_condition_target() -> None:
    state = {
        "input": {"plan": "pro"},
        "variables": {"score": 92},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "branch_1",
        "type": "branch",
        "config": {
            "branches": [
                {
                    "target": "basic_path",
                    "condition": {
                        "left": "{{ input.plan }}",
                        "operator": "eq",
                        "value": "basic",
                    },
                },
                {
                    "target": "pro_path",
                    "condition": {
                        "left": "{{ variables.score }}",
                        "operator": "gte",
                        "value": 90,
                    },
                },
            ],
            "default_target": "fallback_path",
        },
    }

    assert runtime._next_branch_target(node, state) == "pro_path"


@pytest.mark.asyncio
async def test_branch_node_selects_matching_condition_target() -> None:
    state = {
        "input": {"plan": "pro"},
        "variables": {"score": 92},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "branch_1",
        "type": "branch",
        "config": {
            "branches": [
                {
                    "target": "pro_path",
                    "condition": {
                        "left": "{{ variables.score }}",
                        "operator": "gte",
                        "value": 90,
                    },
                },
            ],
        },
    }

    output = await runtime._execute_node(_FakeConnection(), node, state, {})
    assert output == {"selected": "pro_path"}


@pytest.mark.asyncio
async def test_set_variable_node_writes_resolved_values() -> None:
    state = {
        "input": {"user_query": "refund request", "customer": {"id": "c_001"}},
        "variables": {"existing": "kept"},
        "outputs": {"llm_1": {"answer": "approved"}},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "set_1",
        "type": "set_variable",
        "config": {
            "assignments": {
                "normalized.query": "{{input.user_query}}",
                "variables.customer_id": "{{input.customer.id}}",
                "answer": "{{outputs.llm_1.answer}}",
            }
        },
    }
    conn = _FakeConnection()

    output = await runtime._execute_node_with_retry(conn, 100, node, state)

    assert output == {
        "values": {
            "normalized.query": "refund request",
            "customer_id": "c_001",
            "answer": "approved",
        },
        "count": 3,
    }
    assert state["variables"]["existing"] == "kept"
    assert state["variables"]["normalized"]["query"] == "refund request"
    assert state["variables"]["customer_id"] == "c_001"
    assert state["variables"]["answer"] == "approved"
    node_run = next(iter(conn.node_runs.values()))
    assert node_run["node_type"] == "set_variable"
    assert node_run["output_json"] == output


@pytest.mark.asyncio
async def test_set_variable_node_supports_assignment_list() -> None:
    state = {
        "input": {"score": 9},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "set_1",
        "type": "set_variable",
        "config": {
            "assignments": [
                {"name": "score", "value": "{{input.score}}"},
                {"target": "variables.status", "value": "ready"},
            ]
        },
    }

    output = await runtime._execute_node_with_retry(_FakeConnection(), 100, node, state)

    assert output["count"] == 2
    assert state["variables"] == {"score": 9, "status": "ready"}


@pytest.mark.asyncio
async def test_set_variable_node_rejects_invalid_assignment_target() -> None:
    state = {
        "input": {},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "set_1",
        "type": "set_variable",
        "config": {"assignments": [{"value": "missing target"}]},
    }

    with pytest.raises(runtime.RuntimeNodeError) as exc_info:
        await runtime._execute_node_with_retry(_FakeConnection(), 100, node, state)

    assert exc_info.value.error_code == "invalid_config"


@pytest.mark.asyncio
async def test_llm_node_can_bind_model_config_id() -> None:
    state = {
        "input": {"user_query": "hello"},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "llm_1",
        "type": "llm",
        "config": {
            "model_config_id": 7,
            "model": "fallback-model",
            "user_prompt": "问题：{{input.user_query}}",
        },
    }

    output = await runtime._execute_node(_ModelConfigConnection(), node, state, {})

    assert output["provider"] == "mock"
    assert output["model"] == "configured-chat-model"
    assert output["model_config_id"] == 7


@pytest.mark.asyncio
async def test_llm_node_supports_deepseek_model_config_without_key(monkeypatch) -> None:
    async def fake_deepseek_key(conn, provider_config):
        assert provider_config == {"api_key_secret": "deepseek_api_key"}
        return None

    monkeypatch.setattr(runtime, "resolve_deepseek_api_key", fake_deepseek_key)
    state = {
        "input": {"user_query": "hello"},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "llm_1",
        "type": "llm",
        "config": {
            "model_config_id": 11,
            "user_prompt": "问题：{{input.user_query}}",
        },
    }
    conn = _DeepSeekModelConfigConnection()

    with pytest.raises(runtime.RuntimeNodeError) as exc_info:
        await runtime._execute_node_with_retry(conn, 100, node, state)

    assert exc_info.value.error_code == "model_api_key_missing"
    assert exc_info.value.error_detail["provider"] == "deepseek"
    assert exc_info.value.error_detail["model"] == "deepseek-v4-flash"
    assert exc_info.value.error_detail["model_config_id"] == 11
    assert "deepseek_api_key" not in str(exc_info.value)
    node_run = next(iter(conn.node_runs.values()))
    assert node_run["error_code"] == "model_api_key_missing"
    assert node_run["metadata_json"]["provider"] == "deepseek"
    assert node_run["metadata_json"]["model"] == "deepseek-v4-flash"
    assert node_run["metadata_json"]["model_config_id"] == 11
    assert "deepseek_api_key" not in str(node_run)


@pytest.mark.asyncio
async def test_deepseek_llm_success_records_model_metadata_and_usage(monkeypatch) -> None:
    async def fake_deepseek_key(conn, provider_config):
        assert provider_config == {"api_key_secret": "deepseek_api_key"}
        return "sk-test-secret"

    def fake_create(**kwargs):
        assert kwargs["model"] == "deepseek-v4-flash"
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="hello from deepseek",
                        reasoning_content="brief reasoning",
                    )
                )
            ],
            usage=_FakeUsage(
                {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}
            ),
        )

    monkeypatch.setattr(runtime, "resolve_deepseek_api_key", fake_deepseek_key)
    fake_openai = _install_fake_openai(monkeypatch, fake_create)
    state = {
        "input": {"user_query": "hello"},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "llm_1",
        "type": "llm",
        "config": {
            "model_config_id": 11,
            "user_prompt": "问题：{{input.user_query}}",
        },
    }
    conn = _DeepSeekModelConfigConnection()

    output = await runtime._execute_node_with_retry(conn, 100, node, state)

    assert fake_openai.instances[0].kwargs["base_url"] == "https://api.deepseek.com"
    assert output["answer"] == "hello from deepseek"
    assert output["provider"] == "deepseek"
    assert output["model"] == "deepseek-v4-flash"
    assert output["usage"] == {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}
    node_run = next(iter(conn.node_runs.values()))
    assert node_run["metadata_json"]["provider"] == "deepseek"
    assert node_run["metadata_json"]["model"] == "deepseek-v4-flash"
    assert node_run["metadata_json"]["model_config_id"] == 11
    assert node_run["metadata_json"]["duration_ms"] >= 0
    assert node_run["metadata_json"]["token_usage"] == {
        "prompt_tokens": 7,
        "completion_tokens": 5,
        "total_tokens": 12,
    }
    assert "sk-test-secret" not in str(output)
    assert "sk-test-secret" not in str(node_run)


@pytest.mark.asyncio
async def test_deepseek_llm_request_error_uses_stable_code_and_redacts_key(monkeypatch) -> None:
    async def fake_deepseek_key(conn, provider_config):
        assert provider_config == {"api_key_secret": "deepseek_api_key"}
        return "deepseek-secret-token"

    def fake_create(**kwargs):
        raise RuntimeError(
            "upstream failed with deepseek-secret-token "
            "Authorization: Bearer deepseek-secret-token"
        )

    monkeypatch.setattr(runtime, "resolve_deepseek_api_key", fake_deepseek_key)
    _install_fake_openai(monkeypatch, fake_create)
    state = {
        "input": {"user_query": "hello"},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "llm_1",
        "type": "llm",
        "config": {
            "model_config_id": 11,
            "user_prompt": "问题：{{input.user_query}}",
        },
    }
    conn = _DeepSeekModelConfigConnection()

    with pytest.raises(runtime.RuntimeNodeError) as exc_info:
        await runtime._execute_node_with_retry(conn, 100, node, state)

    assert exc_info.value.error_code == "model_request_failed"
    assert "deepseek-secret-token" not in str(exc_info.value)
    node_run = next(iter(conn.node_runs.values()))
    assert node_run["error_code"] == "model_request_failed"
    assert node_run["metadata_json"]["provider"] == "deepseek"
    assert node_run["metadata_json"]["model"] == "deepseek-v4-flash"
    assert "deepseek-secret-token" not in str(node_run)


@pytest.mark.asyncio
async def test_deepseek_llm_invalid_response_uses_stable_code(monkeypatch) -> None:
    async def fake_deepseek_key(conn, provider_config):
        assert provider_config == {"api_key_secret": "deepseek_api_key"}
        return "sk-test-secret"

    def fake_create(**kwargs):
        return SimpleNamespace(choices=[], usage=None)

    monkeypatch.setattr(runtime, "resolve_deepseek_api_key", fake_deepseek_key)
    _install_fake_openai(monkeypatch, fake_create)
    state = {
        "input": {"user_query": "hello"},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "llm_1",
        "type": "llm",
        "config": {
            "model_config_id": 11,
            "user_prompt": "问题：{{input.user_query}}",
        },
    }
    conn = _DeepSeekModelConfigConnection()

    with pytest.raises(runtime.RuntimeNodeError) as exc_info:
        await runtime._execute_node_with_retry(conn, 100, node, state)

    assert exc_info.value.error_code == "model_response_invalid"
    assert exc_info.value.error_detail["provider"] == "deepseek"
    node_run = next(iter(conn.node_runs.values()))
    assert node_run["error_code"] == "model_response_invalid"
    assert node_run["metadata_json"]["provider"] == "deepseek"
    assert node_run["metadata_json"]["model"] == "deepseek-v4-flash"
    assert "sk-test-secret" not in str(node_run)


def test_branch_uses_default_when_no_condition_matches() -> None:
    state = {
        "input": {"plan": "free"},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "branch_1",
        "type": "branch",
        "config": {
            "branches": [
                {
                    "target": "paid_path",
                    "condition": {
                        "left": "{{ input.plan }}",
                        "operator": "eq",
                        "value": "paid",
                    },
                }
            ],
            "default_target": "free_path",
        },
    }

    assert runtime._next_branch_target(node, state) == "free_path"


@pytest.mark.asyncio
async def test_api_node_mock_mode_returns_safe_response_shape() -> None:
    state = {
        "input": {"ticket_id": 42},
        "variables": {"token": "redacted"},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "api_1",
        "type": "api",
        "config": {
            "mode": "mock",
            "method": "POST",
            "url": "https://api.example.test/tickets/{{ input.ticket_id }}",
            "headers": {"authorization": "Bearer {{ variables.token }}"},
            "body": {"ticket_id": "{{ input.ticket_id }}"},
            "mock_response": {"accepted": True},
        },
    }

    output = await runtime._execute_node(_FakeConnection(), node, state, {"fallback": False})

    assert output["mode"] == "mock"
    assert output["status"] == "mocked"
    assert output["status_code"] == 200
    assert output["request"]["url"] == "https://api.example.test/tickets/42"
    assert output["request"]["body"] == {"ticket_id": 42}
    assert output["response"] == {"accepted": True}


@pytest.mark.asyncio
async def test_api_node_redacts_sensitive_header_names_without_secret_placeholders() -> None:
    state = {
        "input": {},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "api_1",
        "type": "api",
        "config": {
            "mode": "mock",
            "method": "GET",
            "url": "https://api.example.test",
            "headers": {
                "Authorization": "Bearer literal-token",
                "X-API-Key": "literal-key",
                "X-Request-ID": "req-123",
            },
        },
    }

    output = await runtime._execute_node(_FakeConnection(), node, state, {})

    assert output["request"]["headers"]["Authorization"] == "***"
    assert output["request"]["headers"]["X-API-Key"] == "***"
    assert output["request"]["headers"]["X-Request-ID"] == "req-123"
    assert "literal-token" not in str(output)
    assert "literal-key" not in str(output)


@pytest.mark.asyncio
async def test_api_node_http_private_url_is_rejected() -> None:
    state = {
        "input": {},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "api_1",
        "type": "api",
        "config": {"mode": "http", "method": "GET", "url": "http://127.0.0.1/admin"},
    }

    output = await runtime._execute_node(_FakeConnection(), node, state, {})

    assert output["mode"] == "http"
    assert output["status"] == "blocked"
    assert output["response"] is None
    assert "private network" in output["error"]


@pytest.mark.asyncio
async def test_api_secret_placeholder_is_resolved_but_not_leaked(monkeypatch) -> None:
    state = {
        "input": {},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }

    async def fake_secret(conn, key):
        assert key == "api_token"
        return "super-secret-token"

    monkeypatch.setattr(runtime, "get_secret_value", fake_secret)

    node = {
        "id": "api_1",
        "type": "api",
        "config": {
            "mode": "mock",
            "method": "POST",
            "url": "https://api.example.test",
            "headers": {"authorization": "Bearer {{ secrets.api_token }}"},
            "body": {"token": "{{ secrets.api_token }}"},
        },
    }

    output = await runtime._execute_node(_FakeConnection(), node, state, {})

    assert output["request"]["headers"]["authorization"] == "Bearer ***"
    assert output["request"]["body"]["token"] == "***"
    assert "super-secret-token" not in str(output)


@pytest.mark.asyncio
async def test_knowledge_base_node_calls_retrieve_helper(monkeypatch) -> None:
    state = {
        "input": {"question": "refund policy"},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    calls = []

    async def fake_retrieve(conn, *, knowledge_base_id, query, top_k, score_threshold):
        calls.append((knowledge_base_id, query, top_k, score_threshold))
        return [{"chunk_id": str(knowledge_base_id), "content": query, "score": 0.9}]

    monkeypatch.setattr(runtime.knowledge_processing, "retrieve_chunks", fake_retrieve)
    node = {
        "id": "kb_1",
        "type": "knowledge_base",
        "config": {
            "knowledge_base_ids": [7, 8],
            "query": "{{ input.question }}",
            "top_k": 3,
            "score_threshold": 0.2,
        },
    }

    output = await runtime._execute_node(_FakeConnection(), node, state, {})

    assert calls == [(7, "refund policy", 3, 0.2), (8, "refund policy", 3, 0.2)]
    assert output["chunks"][0]["chunk_id"] == "7"
    assert state["variables"]["kb_context"] == output["chunks"]


@pytest.mark.asyncio
async def test_knowledge_base_node_resolves_query_from_node_input(monkeypatch) -> None:
    state = {
        "input": {"user_query": "refund policy"},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    calls = []

    async def fake_retrieve(conn, *, knowledge_base_id, query, top_k, score_threshold):
        calls.append((knowledge_base_id, query, top_k, score_threshold))
        return []

    monkeypatch.setattr(runtime.knowledge_processing, "retrieve_chunks", fake_retrieve)
    node = {
        "id": "kb_1",
        "type": "knowledge_base",
        "config": {
            "knowledge_base_ids": [7],
            "query": "{{question}}",
            "top_k": 3,
        },
        "input_mapping": {"question": "{{input.user_query}}"},
    }

    node_input = runtime._build_node_input(node, state)
    await runtime._execute_node(_FakeConnection(), node, state, node_input)

    assert calls == [(7, "refund policy", 3, 0.0)]


@pytest.mark.asyncio
async def test_knowledge_base_node_applies_context_budget(monkeypatch) -> None:
    state = {
        "input": {"question": "refund policy"},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }

    async def fake_retrieve(conn, *, knowledge_base_id, query, top_k, score_threshold):
        return [
            {"chunk_id": "1", "content": "alpha", "score": 0.9, "token_count": 3},
            {"chunk_id": "2", "content": "beta", "score": 0.8, "token_count": 4},
        ]

    monkeypatch.setattr(runtime.knowledge_processing, "retrieve_chunks", fake_retrieve)
    node = {
        "id": "kb_1",
        "type": "knowledge_base",
        "config": {
            "knowledge_base_ids": [7],
            "query": "{{ input.question }}",
            "top_k": 5,
            "context_budget_tokens": 5,
        },
    }

    output = await runtime._execute_node(_FakeConnection(), node, state, {})

    assert [chunk["chunk_id"] for chunk in output["chunks"]] == ["1"]
    assert output["returned_chunks"] == 1


@pytest.mark.asyncio
async def test_intent_node_keyword_classifies_and_falls_back() -> None:
    state = {
        "input": {"user_query": "I need a refund for this order"},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "intent_1",
        "type": "intent",
        "config": {
            "intents": [
                {"name": "refund", "description": "refund return money"},
                {"name": "shipping", "description": "delivery tracking"},
            ],
            "fallback_intent": "unknown",
        },
    }

    output = await runtime._execute_node(_FakeConnection(), node, state, {})
    assert output["intent"] == "refund"

    state["input"]["user_query"] = "something unrelated"
    output = await runtime._execute_node(_FakeConnection(), node, state, {})
    assert output["intent"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_query", "expected_intent", "expected_message_node", "skipped_message_node"),
    [
        ("我要退款，这个订单买错了", "refund_request", "refund_message", "general_message"),
        ("我想咨询一下会员权益", "general_question", "general_message", "refund_message"),
    ],
)
async def test_intent_branch_graph_executes_only_selected_path(
    user_query,
    expected_intent,
    expected_message_node,
    skipped_message_node,
) -> None:
    state = {
        "input": {"user_query": user_query},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    graph = {
        "nodes": [
            {"id": "start_1", "type": "start", "name": "Start", "config": {}},
            {
                "id": "intent_1",
                "type": "intent",
                "name": "Intent",
                "config": {
                    "intents": [
                        {
                            "name": "refund_request",
                            "description": "退款 退货 refund money",
                        },
                        {
                            "name": "general_question",
                            "description": "咨询 帮助 问题 question help",
                        },
                    ],
                    "fallback_intent": "general_question",
                },
                "output_mapping": {
                    "intent": "variables.intent",
                    "confidence": "variables.intent_confidence",
                },
            },
            {
                "id": "branch_1",
                "type": "branch",
                "name": "Branch",
                "config": {
                    "branches": [
                        {
                            "target": "refund_message",
                            "condition": {
                                "left": "{{ variables.intent }}",
                                "operator": "eq",
                                "value": "refund_request",
                            },
                        }
                    ],
                    "default_target": "general_message",
                },
            },
            {
                "id": "refund_message",
                "type": "message",
                "name": "Refund Message",
                "config": {"template": "已进入退款流程"},
                "output_mapping": {"message": "variables.reply"},
            },
            {
                "id": "general_message",
                "type": "message",
                "name": "General Message",
                "config": {"template": "已进入普通咨询流程"},
                "output_mapping": {"message": "variables.reply"},
            },
            {"id": "end_1", "type": "end", "name": "End", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start_1", "target": "intent_1"},
            {"id": "e2", "source": "intent_1", "target": "branch_1"},
            {"id": "e3", "source": "branch_1", "target": "refund_message"},
            {"id": "e4", "source": "branch_1", "target": "general_message"},
            {"id": "e5", "source": "refund_message", "target": "end_1"},
            {"id": "e6", "source": "general_message", "target": "end_1"},
        ],
    }
    conn = _FakeConnection()

    await runtime._execute_graph(conn, run_id=100, graph=graph, state=state)

    node_runs = {run["node_id"]: run for run in conn.node_runs.values()}
    assert state["variables"]["intent"] == expected_intent
    assert isinstance(state["variables"]["intent_confidence"], float)
    assert state["outputs"]["intent_1"]["intent"] == expected_intent
    assert state["outputs"]["branch_1"]["selected"] == expected_message_node
    assert expected_message_node in node_runs
    assert skipped_message_node not in node_runs
    assert state["path"] == ["start_1", "intent_1", "branch_1", expected_message_node, "end_1"]


@pytest.mark.asyncio
async def test_api_graph_resolves_variables_and_secrets_without_leaking_trace(
    monkeypatch,
) -> None:
    state = {
        "input": {"ticket_id": 42},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }

    async def fake_secret(conn, key):
        assert key == "refund_api_token"
        return "super-secret-token"

    monkeypatch.setattr(runtime, "get_secret_value", fake_secret)

    graph = {
        "nodes": [
            {"id": "start_1", "type": "start", "name": "Start", "config": {}},
            {
                "id": "api_1",
                "type": "api",
                "name": "Refund API",
                "config": {
                    "mode": "mock",
                    "method": "POST",
                    "url": "https://api.example.test/refunds/{{ input.ticket_id }}",
                    "headers": {"Authorization": "Bearer {{ secrets.refund_api_token }}"},
                    "body": {
                        "ticket_id": "{{ input.ticket_id }}",
                        "token_echo": "{{ secrets.refund_api_token }}",
                    },
                    "mock_response": {"accepted": True, "ticket_id": "{{ input.ticket_id }}"},
                },
                "output_mapping": {"response": "variables.api_response"},
            },
            {
                "id": "output_1",
                "type": "output",
                "name": "Output",
                "config": {
                    "outputs": {
                        "accepted": "{{ variables.api_response.accepted }}",
                        "ticket_id": "{{ variables.api_response.ticket_id }}",
                    }
                },
            },
            {"id": "end_1", "type": "end", "name": "End", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start_1", "target": "api_1"},
            {"id": "e2", "source": "api_1", "target": "output_1"},
            {"id": "e3", "source": "output_1", "target": "end_1"},
        ],
    }
    conn = _FakeConnection()

    await runtime._execute_graph(conn, run_id=101, graph=graph, state=state)

    api_trace = next(run for run in conn.node_runs.values() if run["node_id"] == "api_1")
    api_output = api_trace["output_json"]
    assert state["final_output"] == {"accepted": True, "ticket_id": 42}
    assert api_output["request"]["url"] == "https://api.example.test/refunds/42"
    assert api_output["request"]["headers"]["Authorization"] == "Bearer ***"
    assert api_output["request"]["body"] == {"ticket_id": 42, "token_echo": "***"}
    assert "super-secret-token" not in str(api_output)
    assert "super-secret-token" not in str(api_trace)


@pytest.mark.asyncio
async def test_message_graph_renders_template_and_maps_to_final_output() -> None:
    state = {
        "input": {"name": "Ada", "order_id": "R-100"},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    graph = {
        "nodes": [
            {"id": "start_1", "type": "start", "name": "Start", "config": {}},
            {
                "id": "message_1",
                "type": "message",
                "name": "Message",
                "config": {
                    "template": "Hi {{ input.name }}, refund {{ input.order_id }} is queued."
                },
                "output_mapping": {"message": "variables.customer_message"},
            },
            {
                "id": "output_1",
                "type": "output",
                "name": "Output",
                "config": {"outputs": {"message": "{{ variables.customer_message }}"}},
            },
            {"id": "end_1", "type": "end", "name": "End", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start_1", "target": "message_1"},
            {"id": "e2", "source": "message_1", "target": "output_1"},
            {"id": "e3", "source": "output_1", "target": "end_1"},
        ],
    }

    await runtime._execute_graph(_FakeConnection(), run_id=102, graph=graph, state=state)

    assert state["outputs"]["message_1"] == {
        "message": "Hi Ada, refund R-100 is queued."
    }
    assert state["variables"]["customer_message"] == "Hi Ada, refund R-100 is queued."
    assert state["final_output"] == {"message": "Hi Ada, refund R-100 is queued."}


@pytest.mark.asyncio
async def test_human_approval_node_creates_task_and_pauses_graph() -> None:
    state = {
        "input": {"amount": 100},
        "variables": {},
        "outputs": {},
        "metadata": {"run_id": 22, "workflow_id": 11, "version_id": 3},
        "path": [],
        "final_output": {},
    }
    graph = {
        "nodes": [
            {"id": "start_1", "type": "start", "name": "Start", "config": {}},
            {
                "id": "approval_1",
                "type": "human_approval",
                "name": "人工审批",
                "config": {
                    "title": "退款审批",
                    "description": "金额 {{input.amount}}",
                    "timeout_seconds": 3600,
                    "approval_schema": {"required": ["approved"]},
                },
            },
            {
                "id": "output_1",
                "type": "output",
                "name": "Output",
                "config": {"outputs": {"approved": True}},
            },
        ],
        "edges": [
            {"id": "e1", "source": "start_1", "target": "approval_1"},
            {"id": "e2", "source": "approval_1", "target": "output_1"},
        ],
    }
    conn = _HumanApprovalConnection()

    with pytest.raises(runtime.HumanApprovalPause) as exc_info:
        await runtime._execute_graph(conn, run_id=22, graph=graph, state=state)

    assert exc_info.value.task_id == 77
    assert state["path"] == ["start_1", "approval_1"]
    assert "output_1" not in state["outputs"]
    assert state["outputs"]["approval_1"] == {
        "status": "waiting_approval",
        "task_id": 77,
        "decision": None,
        "resume_supported": False,
    }
    assert state["metadata"]["waiting_approval"] == {
        "task_id": 77,
        "node_id": "approval_1",
        "next_node_id": "output_1",
    }
    approval_run = next(
        run for run in conn.node_runs.values() if run["node_id"] == "approval_1"
    )
    assert approval_run["status"] == "waiting_approval"
    assert approval_run["output_json"]["task_id"] == 77
    assert approval_run["metadata_json"]["approval_task_id"] == 77
    assert conn.run_waiting_metadata == {
        "waiting_approval_task_id": 77,
        "waiting_approval_node_id": "approval_1",
    }
    assert conn.approval_task_input == {
        "input": {"amount": 100},
        "variables": {},
    }
    assert conn.approval_task_metadata == {
        "approval_schema": {"required": ["approved"]},
        "timeout_seconds": 3600,
    }
    assert conn.persisted_state == state


@pytest.mark.asyncio
async def test_retry_recreates_node_run_and_re_resolves_input_mapping(monkeypatch) -> None:
    state = {
        "input": {"name": "Ada"},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "api_1",
        "type": "api",
        "name": "API",
        "input_mapping": {"name": "{{input.name}}"},
        "output_mapping": {"result": "variables.result"},
        "retry": {
            "max_attempts": 2,
            "backoff": "none",
            "retry_on": ["api_request_error"],
        },
    }
    calls = 0

    async def fake_execute_node(conn, current_node, current_state, node_input):
        nonlocal calls
        calls += 1
        if calls == 1:
            current_state["input"]["name"] = "Grace"
            raise runtime.RuntimeNodeError(
                "api_request_error",
                "temporary outage",
                retryable=True,
            )
        return {"result": node_input["name"]}

    monkeypatch.setattr(runtime, "_execute_node", fake_execute_node)
    conn = _FakeConnection()

    output = await runtime._execute_node_with_retry(conn, 100, node, state)

    assert output == {"result": "Grace"}
    assert state["variables"]["result"] == "Grace"
    assert [run["attempt"] for run in conn.node_runs.values()] == [1, 2]
    first_run, second_run = conn.node_runs.values()
    assert first_run["status"] == "retrying"
    assert first_run["error_code"] == "api_request_error"
    assert first_run["metadata_json"]["will_retry"] is True
    assert second_run["input_json"] == {"name": "Grace"}


@pytest.mark.asyncio
async def test_node_timeout_records_stable_error_code(monkeypatch) -> None:
    state = {
        "input": {},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {"id": "slow_1", "type": "message", "timeout": 0.001, "config": {}}

    async def slow_execute_node(conn, current_node, current_state, node_input):
        await runtime.asyncio.sleep(0.05)
        return {"message": "too late"}

    monkeypatch.setattr(runtime, "_execute_node", slow_execute_node)
    conn = _FakeConnection()

    with pytest.raises(runtime.RuntimeNodeError) as exc_info:
        await runtime._execute_node_with_retry(conn, 100, node, state)

    assert exc_info.value.error_code == "timeout"
    node_run = next(iter(conn.node_runs.values()))
    assert node_run["error_code"] == "timeout"
    assert node_run["metadata_json"]["retryable"] is True


@pytest.mark.asyncio
async def test_llm_node_timeout_records_model_timeout(monkeypatch) -> None:
    state = {
        "input": {},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "llm_1",
        "type": "llm",
        "timeout": 0.001,
        "config": {"provider": "deepseek", "model": "deepseek-chat"},
    }

    async def slow_execute_node(conn, current_node, current_state, node_input):
        await runtime.asyncio.sleep(0.05)
        return {"answer": "too late"}

    monkeypatch.setattr(runtime, "_execute_node", slow_execute_node)
    conn = _FakeConnection()

    with pytest.raises(runtime.RuntimeNodeError) as exc_info:
        await runtime._execute_node_with_retry(conn, 100, node, state)

    assert exc_info.value.error_code == "model_timeout"
    assert exc_info.value.error_detail["provider"] == "deepseek"
    assert exc_info.value.error_detail["model"] == "deepseek-chat"
    node_run = next(iter(conn.node_runs.values()))
    assert node_run["error_code"] == "model_timeout"
    assert node_run["metadata_json"]["provider"] == "deepseek"
    assert node_run["metadata_json"]["model"] == "deepseek-chat"
    assert node_run["metadata_json"]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_missing_variable_fails_with_stable_error_code() -> None:
    state = {
        "input": {},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    graph = {
        "nodes": [
            {"id": "start_1", "type": "start", "name": "Start", "config": {}},
            {
                "id": "message_1",
                "type": "message",
                "name": "Message",
                "config": {"template": "Hi {{input.name}}"},
            },
        ],
        "edges": [{"id": "e1", "source": "start_1", "target": "message_1"}],
    }
    conn = _FakeConnection()

    with pytest.raises(runtime.RuntimeNodeError) as exc_info:
        await runtime._execute_graph(conn, run_id=100, graph=graph, state=state)

    assert exc_info.value.error_code == "variable_not_found"
    message_run = [run for run in conn.node_runs.values() if run["node_id"] == "message_1"][0]
    assert message_run["error_code"] == "variable_not_found"


def test_output_mapping_supports_outputs_and_messages_destinations() -> None:
    state = {
        "input": {},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "messages": [],
        "final_output": {},
    }
    node = {
        "id": "message_1",
        "type": "message",
        "output_mapping": {
            "payload": "outputs",
            "detail": "outputs.detail",
            "messages": "messages",
        },
    }
    output = {
        "payload": {"ok": True},
        "detail": {"id": 7},
        "messages": ["one", {"type": "text", "content": "two"}],
    }

    runtime._apply_output_mapping(node, output, state)

    assert state["outputs"] == {"ok": True, "detail": {"id": 7}}
    assert state["messages"] == [
        {"type": "text", "content": "one"},
        {"type": "text", "content": "two"},
    ]


@pytest.mark.asyncio
async def test_on_error_skip_node_continues_to_next_node(monkeypatch) -> None:
    state = {
        "input": {},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    graph = {
        "nodes": [
            {"id": "start_1", "type": "start", "name": "Start", "config": {}},
            {
                "id": "api_1",
                "type": "api",
                "name": "API",
                "config": {},
                "on_error": {"strategy": "skip_node"},
            },
            {
                "id": "message_1",
                "type": "message",
                "name": "Message",
                "config": {"template": "fallback"},
                "output_mapping": {"message": "variables.reply"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "start_1", "target": "api_1"},
            {"id": "e2", "source": "api_1", "target": "message_1"},
        ],
    }

    async def fake_execute_node(conn, node, current_state, node_input):
        if node["id"] == "api_1":
            raise runtime.RuntimeNodeError("api_response_error", "HTTP 500", retryable=True)
        return await original_execute_node(conn, node, current_state, node_input)

    original_execute_node = runtime._execute_node
    monkeypatch.setattr(runtime, "_execute_node", fake_execute_node)
    conn = _FakeConnection()

    await runtime._execute_graph(conn, run_id=100, graph=graph, state=state)

    assert state["variables"]["reply"] == "fallback"
    assert state["metadata"]["last_error"]["node_id"] == "api_1"
    assert state["metadata"]["last_error"]["error_code"] == "api_response_error"
    assert state["path"] == ["start_1", "api_1", "message_1"]


@pytest.mark.asyncio
async def test_on_error_go_to_node_jumps_to_error_handler(monkeypatch) -> None:
    state = {
        "input": {},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    graph = {
        "nodes": [
            {"id": "start_1", "type": "start", "name": "Start", "config": {}},
            {
                "id": "api_1",
                "type": "api",
                "name": "API",
                "config": {},
                "on_error": {"strategy": "go_to_node", "target": "error_message"},
            },
            {
                "id": "success_message",
                "type": "message",
                "name": "Success",
                "config": {"template": "success"},
                "output_mapping": {"message": "variables.reply"},
            },
            {
                "id": "error_message",
                "type": "message",
                "name": "Error",
                "config": {"template": "handled {{metadata.last_error.error_code}}"},
                "output_mapping": {"message": "variables.reply"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "start_1", "target": "api_1"},
            {"id": "e2", "source": "api_1", "target": "success_message"},
        ],
    }

    async def fake_execute_node(conn, node, current_state, node_input):
        if node["id"] == "api_1":
            raise runtime.RuntimeNodeError("api_response_error", "HTTP 500", retryable=True)
        return await original_execute_node(conn, node, current_state, node_input)

    original_execute_node = runtime._execute_node
    monkeypatch.setattr(runtime, "_execute_node", fake_execute_node)
    conn = _FakeConnection()

    await runtime._execute_graph(conn, run_id=100, graph=graph, state=state)

    assert state["variables"]["reply"] == "handled api_response_error"
    assert state["path"] == ["start_1", "api_1", "error_message"]


def test_http_status_error_normalizes_to_retryable_rate_limit() -> None:
    request = runtime.httpx.Request("GET", "https://api.example.test")
    response = runtime.httpx.Response(429, request=request)
    exc = runtime.httpx.HTTPStatusError("too many requests", request=request, response=response)

    error = runtime._normalize_node_error(exc, {"type": "api"})

    assert error.error_code == "rate_limit"
    assert error.retryable is True
    assert error.error_detail["status_code"] == 429


@pytest.mark.asyncio
async def test_api_mock_response_path_and_query_params_are_resolved() -> None:
    state = {
        "input": {"tenant": "acme"},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "api_1",
        "type": "api",
        "config": {
            "mode": "mock",
            "method": "GET",
            "url": "https://api.example.test/orders",
            "query_params": {"tenant": "{{input.tenant}}"},
            "mock_response": {"data": {"result": {"ok": True}}},
            "response_path": "data.result",
        },
    }

    output = await runtime._execute_node(_FakeConnection(), node, state, {})

    assert output["response"] == {"ok": True}
    assert output["request"]["query_params"] == {"tenant": "acme"}
    assert output["response_path"] == "data.result"
    assert output["max_response_bytes"] == 1024 * 1024


@pytest.mark.asyncio
async def test_api_mock_missing_response_path_raises_stable_error() -> None:
    state = {
        "input": {},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "api_1",
        "type": "api",
        "config": {
            "mode": "mock",
            "method": "GET",
            "url": "https://api.example.test/orders",
            "mock_response": {"data": {}},
            "response_path": "data.missing",
        },
    }

    with pytest.raises(runtime.RuntimeNodeError) as exc_info:
        await runtime._execute_node(_FakeConnection(), node, state, {})

    assert exc_info.value.error_code == "api_response_error"
    assert exc_info.value.error_detail == {"response_path": "data.missing"}


def test_api_decode_http_response_enforces_max_response_bytes() -> None:
    response = runtime.httpx.Response(200, content=b"abcdef")

    with pytest.raises(runtime.RuntimeNodeError) as exc_info:
        runtime._decode_http_response(response, max_response_bytes=3)

    assert exc_info.value.error_code == "response_too_large"
    assert exc_info.value.error_detail["max_response_bytes"] == 3


@pytest.mark.asyncio
async def test_api_invalid_response_limit_raises_invalid_config() -> None:
    state = {
        "input": {},
        "variables": {},
        "outputs": {},
        "metadata": {},
        "path": [],
        "final_output": {},
    }
    node = {
        "id": "api_1",
        "type": "api",
        "config": {
            "mode": "mock",
            "method": "GET",
            "url": "https://api.example.test/orders",
            "max_response_bytes": "not-a-number",
        },
    }

    with pytest.raises(runtime.RuntimeNodeError) as exc_info:
        await runtime._execute_node(_FakeConnection(), node, state, {})

    assert exc_info.value.error_code == "invalid_config"
