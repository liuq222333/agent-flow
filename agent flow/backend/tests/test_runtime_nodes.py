import pytest

from app.services import runtime


class _ScalarResult:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value


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
                "input_json": params["input_json"],
                "metadata_json": params["metadata_json"],
            }
            return _ScalarResult(node_run_id)

        if "UPDATE node_runs" in sql:
            self.node_runs[params["node_run_id"]].update(params)
            return _ScalarResult()

        return _ScalarResult()


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
