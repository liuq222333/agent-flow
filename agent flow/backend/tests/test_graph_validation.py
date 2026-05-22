from copy import deepcopy

from app.services.graph_validation import default_graph, validate_graph


def test_default_graph_is_publishable() -> None:
    result = validate_graph(default_graph(), "publish")
    assert result["valid"] is True
    assert result["errors"] == []


def test_publish_rejects_disabled_nodes() -> None:
    graph = deepcopy(default_graph())
    graph["nodes"][1]["enabled"] = False

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "disabled_node_in_publish"


def test_publish_rejects_llm_node_without_prompt() -> None:
    graph = deepcopy(default_graph())
    llm_node = next(node for node in graph["nodes"] if node["type"] == "llm")
    llm_node["config"].pop("user_prompt", None)
    llm_node["config"].pop("prompt", None)

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "missing_llm_prompt" for error in result["errors"])


def test_publish_rejects_missing_edge_target() -> None:
    graph = deepcopy(default_graph())
    graph["edges"][0]["target"] = "missing_node"

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "edge_target_missing" for error in result["errors"])


def test_publish_rejects_start_incoming_edge() -> None:
    graph = deepcopy(default_graph())
    graph["edges"].append({"id": "e5", "source": "llm_1", "target": "start_1"})

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "start_node_has_incoming" for error in result["errors"])


def test_publish_rejects_end_outgoing_edge() -> None:
    graph = deepcopy(default_graph())
    graph["edges"].append({"id": "e5", "source": "end_1", "target": "llm_1"})

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "end_node_has_outgoing" for error in result["errors"])


def test_publish_rejects_multiple_outgoing_edges_from_non_branch() -> None:
    graph = deepcopy(default_graph())
    graph["edges"].append({"id": "e5", "source": "llm_1", "target": "start_1"})

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "non_branch_multiple_outgoing" for error in result["errors"])


def test_publish_rejects_unreachable_business_node() -> None:
    graph = deepcopy(default_graph())
    graph["nodes"].append(
        {
            "id": "llm_unreachable",
            "type": "llm",
            "name": "未连接模型",
            "position": {"x": 500, "y": 320},
            "config": {"model": "local-mock", "user_prompt": "hello"},
        }
    )

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "node_unreachable_from_start" for error in result["errors"])


def test_publish_rejects_graph_cycle() -> None:
    graph = _branch_graph()
    graph["edges"] = [
        {"id": "e1", "source": "start_1", "target": "branch_1"},
        {"id": "e2", "source": "branch_1", "target": "input_1"},
        {"id": "e3", "source": "branch_1", "target": "end_1"},
        {"id": "e4", "source": "input_1", "target": "branch_1"},
    ]

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "graph_cycle_detected" for error in result["errors"])


def test_publish_accepts_set_variable_node_with_assignments() -> None:
    graph = deepcopy(default_graph())
    graph["nodes"].insert(
        3,
        {
            "id": "set_1",
            "type": "set_variable",
            "name": "变量赋值",
            "position": {"x": 620, "y": 160},
            "config": {"assignments": {"normalized_query": "{{input.rawQuery}}"}},
        },
    )
    graph["edges"] = [
        {"id": "e1", "source": "start_1", "target": "llm_1"},
        {"id": "e2", "source": "llm_1", "target": "set_1"},
        {"id": "e3", "source": "set_1", "target": "end_1"},
    ]

    result = validate_graph(graph, "publish")

    assert result["valid"] is True


def test_publish_accepts_human_approval_node_with_title() -> None:
    graph = deepcopy(default_graph())
    graph["nodes"].insert(
        3,
        {
            "id": "approval_1",
            "type": "human_approval",
            "name": "人工审批",
            "position": {"x": 620, "y": 160},
            "config": {"title": "退款审批", "timeout_seconds": 3600},
        },
    )
    graph["edges"] = [
        {"id": "e1", "source": "start_1", "target": "llm_1"},
        {"id": "e2", "source": "llm_1", "target": "approval_1"},
        {"id": "e3", "source": "approval_1", "target": "end_1"},
    ]

    result = validate_graph(graph, "publish")

    assert result["valid"] is True


def test_publish_rejects_human_approval_node_without_title() -> None:
    graph = deepcopy(default_graph())
    graph["nodes"].append(
        {
            "id": "approval_1",
            "type": "human_approval",
            "name": "人工审批",
            "position": {"x": 500, "y": 320},
            "config": {"timeout_seconds": 3600},
        }
    )
    graph["edges"] = [
        {"id": "e1", "source": "start_1", "target": "llm_1"},
        {"id": "e2", "source": "llm_1", "target": "approval_1"},
        {"id": "e3", "source": "approval_1", "target": "end_1"},
    ]

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "missing_human_approval_title" for error in result["errors"])


def test_publish_rejects_human_approval_node_with_invalid_timeout() -> None:
    graph = deepcopy(default_graph())
    graph["nodes"].append(
        {
            "id": "approval_1",
            "type": "human_approval",
            "name": "人工审批",
            "position": {"x": 500, "y": 320},
            "config": {"title": "退款审批", "timeout_seconds": 0},
        }
    )
    graph["edges"] = [
        {"id": "e1", "source": "start_1", "target": "llm_1"},
        {"id": "e2", "source": "llm_1", "target": "approval_1"},
        {"id": "e3", "source": "approval_1", "target": "end_1"},
    ]

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "invalid_human_approval_timeout" for error in result["errors"])


def test_publish_rejects_set_variable_node_without_assignments() -> None:
    graph = deepcopy(default_graph())
    graph["nodes"].append(
        {
            "id": "set_1",
            "type": "set_variable",
            "name": "变量赋值",
            "position": {"x": 500, "y": 320},
            "config": {},
        }
    )
    graph["edges"] = [
        {"id": "e1", "source": "start_1", "target": "llm_1"},
        {"id": "e2", "source": "llm_1", "target": "set_1"},
        {"id": "e3", "source": "set_1", "target": "end_1"},
    ]

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "missing_set_variable_assignments" for error in result["errors"])


def test_publish_rejects_output_node_without_outputs() -> None:
    graph = _legacy_output_graph()
    output_node = next(node for node in graph["nodes"] if node["type"] == "output")
    output_node["config"] = {"response_mode": "parameters"}

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "missing_output_outputs" for error in result["errors"])


def test_publish_rejects_output_template_mode_without_template() -> None:
    graph = _legacy_output_graph()
    output_node = next(node for node in graph["nodes"] if node["type"] == "output")
    output_node["config"] = {
        "response_mode": "template",
        "outputs": {"answer": "{{variables.answer}}"},
    }

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "missing_output_template" for error in result["errors"])


def test_publish_accepts_output_template_mode_with_template() -> None:
    graph = _legacy_output_graph()
    output_node = next(node for node in graph["nodes"] if node["type"] == "output")
    output_node["config"] = {
        "response_mode": "template",
        "outputs": {"answer": "{{variables.answer}}"},
        "template": "回复：{{answer}}",
    }

    result = validate_graph(graph, "publish")

    assert result["valid"] is True


def test_publish_rejects_end_without_outputs_when_no_output_node() -> None:
    graph = deepcopy(default_graph())
    end_node = next(node for node in graph["nodes"] if node["type"] == "end")
    end_node["config"] = {}

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "missing_end_outputs" for error in result["errors"])


def test_publish_accepts_end_template_mode_with_template() -> None:
    graph = deepcopy(default_graph())
    end_node = next(node for node in graph["nodes"] if node["type"] == "end")
    end_node["config"] = {
        "response_mode": "template",
        "outputs": {"output": "{{outputs.llm_1.output}}"},
        "template": "回复：{{output}}",
    }

    result = validate_graph(graph, "publish")

    assert result["valid"] is True


def test_publish_rejects_api_node_with_invalid_response_limit() -> None:
    graph = deepcopy(default_graph())
    api_node = {
        "id": "api_1",
        "type": "api",
        "name": "API",
        "position": {"x": 620, "y": 160},
        "config": {
            "mode": "mock",
            "method": "GET",
            "url": "https://api.example.test/orders",
            "max_response_bytes": 10 * 1024 * 1024,
        },
    }
    graph["nodes"].insert(3, api_node)
    graph["edges"] = [
        {"id": "e1", "source": "start_1", "target": "llm_1"},
        {"id": "e2", "source": "llm_1", "target": "api_1"},
        {"id": "e3", "source": "api_1", "target": "end_1"},
    ]

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "invalid_api_max_response_bytes" for error in result["errors"])


def test_publish_rejects_branch_target_without_edge() -> None:
    graph = _branch_graph()
    graph["edges"] = [
        {"id": "e1", "source": "start_1", "target": "branch_1"},
        {"id": "e2", "source": "branch_1", "target": "end_1"},
    ]

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "branch_edge_missing" for error in result["errors"])


def test_publish_rejects_branch_outgoing_edge_without_branch_target() -> None:
    graph = _branch_graph()
    graph["edges"].append({"id": "e4", "source": "branch_1", "target": "input_1"})

    result = validate_graph(graph, "publish")

    assert result["valid"] is False
    assert any(error["code"] == "branch_edge_unmapped" for error in result["errors"])


def _branch_graph() -> dict:
    return {
        "schema_version": "1.0",
        "nodes": [
            {
                "id": "start_1",
                "type": "start",
                "name": "开始",
                "position": {"x": 80, "y": 160},
                "config": {},
            },
            {
                "id": "branch_1",
                "type": "branch",
                "name": "分支",
                "position": {"x": 280, "y": 160},
                "config": {
                    "branches": [
                        {"id": "b1", "condition": "default", "target": "output_1"},
                        {"id": "b2", "condition": "default", "target": "end_1"},
                    ]
                },
            },
            {
                "id": "input_1",
                "type": "input",
                "name": "用户输入",
                "position": {"x": 280, "y": 320},
                "config": {"fields": []},
            },
            {
                "id": "output_1",
                "type": "output",
                "name": "最终输出",
                "position": {"x": 500, "y": 160},
                "config": {"outputs": {}},
            },
            {
                "id": "end_1",
                "type": "end",
                "name": "结束",
                "position": {"x": 720, "y": 160},
                "config": {},
            },
        ],
        "edges": [
            {"id": "e1", "source": "start_1", "target": "branch_1"},
            {"id": "e2", "source": "branch_1", "target": "output_1"},
            {"id": "e3", "source": "branch_1", "target": "end_1"},
            {"id": "e4", "source": "output_1", "target": "end_1"},
        ],
    }


def _legacy_output_graph() -> dict:
    graph = deepcopy(default_graph())
    end_node = next(node for node in graph["nodes"] if node["type"] == "end")
    end_node["position"] = {"x": 920, "y": 160}
    end_node["config"] = {}
    graph["nodes"].insert(
        2,
        {
            "id": "output_1",
            "type": "output",
            "name": "最终输出",
            "position": {"x": 640, "y": 160},
            "config": {"outputs": {"output": "{{outputs.llm_1.output}}"}},
        },
    )
    graph["edges"] = [
        {"id": "e1", "source": "start_1", "target": "llm_1"},
        {"id": "e2", "source": "llm_1", "target": "output_1"},
        {"id": "e3", "source": "output_1", "target": "end_1"},
    ]
    return graph
