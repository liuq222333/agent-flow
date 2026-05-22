from collections import defaultdict, deque
from typing import Any, Literal

Graph = dict[str, Any]
ValidationMode = Literal["draft", "publish", "run"]

ALLOWED_NODE_TYPES = {
    "start",
    "input",
    "llm",
    "knowledge_base",
    "intent",
    "branch",
    "human_approval",
    "set_variable",
    "api",
    "message",
    "output",
    "end",
}


def default_graph() -> Graph:
    return {
        "schema_version": "1.0",
        "nodes": [
            {
                "id": "start_1",
                "type": "start",
                "name": "开始",
                "position": {"x": 80, "y": 160},
                "config": {
                    "fields": [
                        {
                            "name": "rawQuery",
                            "type": "string",
                            "label": "用户输入",
                            "required": True,
                        },
                        {"name": "chatHistory", "type": "array", "label": "历史消息"},
                        {"name": "fileUrls", "type": "array", "label": "文件 URL"},
                        {"name": "fileNames", "type": "array", "label": "文件名"},
                        {"name": "end_user_id", "type": "string", "label": "终端用户 ID"},
                        {"name": "conversation_id", "type": "string", "label": "会话 ID"},
                        {"name": "request_id", "type": "string", "label": "请求 ID"},
                        {"name": "fields", "type": "array", "label": "扩展字段"},
                    ]
                },
            },
            {
                "id": "llm_1",
                "type": "llm",
                "name": "生成回答",
                "position": {"x": 360, "y": 160},
                "input_mapping": {"query": "{{input.rawQuery}}"},
                "output_mapping": {
                    "output": "variables.output",
                    "answer": "variables.answer",
                },
                "config": {
                    "provider": "mock",
                    "model": "local-mock",
                    "system_prompt": "你是一个本地调试助手。",
                    "user_prompt": "问题：{{query}}",
                    "temperature": 0.2,
                },
            },
            {
                "id": "end_1",
                "type": "end",
                "name": "结束",
                "position": {"x": 640, "y": 160},
                "config": {
                    "response_mode": "parameters",
                    "outputs": {
                        "output": "{{outputs.llm_1.output}}",
                        "rawQuery": "{{input.rawQuery}}",
                    },
                    "output_value_kinds": {
                        "output": "reference",
                        "rawQuery": "reference",
                    },
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "start_1", "target": "llm_1"},
            {"id": "e2", "source": "llm_1", "target": "end_1"},
        ],
    }


def validate_graph(graph: Graph, mode: ValidationMode) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list):
        errors.append(_issue("invalid_nodes", "nodes 必须是数组", "nodes"))
        nodes = []
    if not isinstance(edges, list):
        errors.append(_issue("invalid_edges", "edges 必须是数组", "edges"))
        edges = []

    node_ids: set[str] = set()
    node_by_id: dict[str, dict[str, Any]] = {}
    node_path_by_id: dict[str, str] = {}
    start_nodes: list[dict[str, Any]] = []
    end_nodes: list[dict[str, Any]] = []
    output_nodes: list[dict[str, Any]] = []

    for index, node in enumerate(nodes):
        path = f"nodes[{index}]"
        if not isinstance(node, dict):
            errors.append(_issue("invalid_node", "节点必须是对象", path))
            continue

        node_id = node.get("id")
        node_type = node.get("type")
        if not node_id or not isinstance(node_id, str):
            errors.append(_issue("missing_node_id", "节点缺少 id", path))
            continue
        if node_id in node_ids:
            errors.append(_issue("duplicate_node_id", "节点 id 重复", path, node_id))
        node_ids.add(node_id)
        node_by_id[node_id] = node
        node_path_by_id[node_id] = path

        if node_type not in ALLOWED_NODE_TYPES:
            errors.append(_issue("invalid_node_type", "节点类型不支持", f"{path}.type", node_id))
        if not node.get("name"):
            errors.append(_issue("missing_node_name", "节点缺少 name", f"{path}.name", node_id))
        if not isinstance(node.get("position"), dict):
            errors.append(
                _issue("missing_node_position", "节点缺少 position", f"{path}.position", node_id)
            )
        if "config" not in node or not isinstance(node.get("config"), dict):
            errors.append(
                _issue("missing_node_config", "节点缺少 config", f"{path}.config", node_id)
            )

        if node_type == "start":
            start_nodes.append(node)
        if node_type == "end":
            end_nodes.append(node)
        if node_type == "output":
            output_nodes.append(node)
        if mode in {"publish", "run"} and node.get("enabled") is False:
            errors.append(
                _issue(
                    "disabled_node_in_publish",
                    "发布或运行时不允许存在 disabled 节点",
                    path,
                    node_id,
                )
            )
        if mode in {"publish", "run"} and node_type == "llm":
            _validate_llm_node_config(node, path, errors)
        if mode in {"publish", "run"} and node_type == "api":
            _validate_api_node_config(node, path, errors)
        if mode in {"publish", "run"} and node_type == "set_variable":
            _validate_set_variable_node_config(node, path, errors)
        if mode in {"publish", "run"} and node_type == "output":
            _validate_final_output_config(
                node,
                path,
                errors,
                node_label="Output Node",
                missing_code="missing_output_outputs",
                missing_message="Output Node 必须配置 outputs 对象",
                missing_template_code="missing_output_template",
            )
        if mode in {"publish", "run"} and node_type == "human_approval":
            _validate_human_approval_node_config(node, path, errors)

    edge_ids: set[str] = set()
    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)
    edge_pairs: set[tuple[str, str]] = set()

    for index, edge in enumerate(edges):
        path = f"edges[{index}]"
        if not isinstance(edge, dict):
            errors.append(_issue("invalid_edge", "边必须是对象", path))
            continue

        edge_id = edge.get("id")
        source = edge.get("source")
        target = edge.get("target")
        if not edge_id or not isinstance(edge_id, str):
            errors.append(_issue("missing_edge_id", "边缺少 id", path))
        elif edge_id in edge_ids:
            errors.append(_issue("duplicate_edge_id", "边 id 重复", path))
        edge_ids.add(str(edge_id))

        if source not in node_by_id:
            errors.append(_issue("edge_source_missing", "边的 source 节点不存在", f"{path}.source"))
        if target not in node_by_id:
            errors.append(_issue("edge_target_missing", "边的 target 节点不存在", f"{path}.target"))
        if source in node_by_id and target in node_by_id:
            outgoing[source].append(target)
            incoming[target].append(source)
            edge_pairs.add((source, target))

    if mode in {"publish", "run"}:
        if len(start_nodes) != 1:
            errors.append(
                _issue("invalid_start_node_count", "工作流必须且只能有一个 Start Node", "nodes")
            )
        if len(end_nodes) != 1:
            errors.append(
                _issue("invalid_end_node_count", "工作流必须且只能有一个 End Node", "nodes")
            )
        if len(end_nodes) == 1:
            end_node = end_nodes[0]
            end_config = end_node.get("config") if isinstance(end_node.get("config"), dict) else {}
            end_has_final_output = _has_final_output_config(end_config)
            if not output_nodes or end_has_final_output:
                _validate_final_output_config(
                    end_node,
                    node_path_by_id[end_node["id"]],
                    errors,
                    node_label="End Node",
                    missing_code="missing_end_outputs",
                    missing_message="End Node 必须配置 outputs 对象；旧 Output Node 工作流除外",
                    missing_template_code="missing_end_template",
                )

        for node_id, node in node_by_id.items():
            node_type = node.get("type")
            if node_type == "start" and incoming.get(node_id):
                errors.append(
                    _issue(
                        "start_node_has_incoming",
                        "Start Node 不能有入边",
                        node_path_by_id[node_id],
                        node_id,
                    )
                )
            if node_type == "end" and outgoing.get(node_id):
                errors.append(
                    _issue(
                        "end_node_has_outgoing",
                        "End Node 不能有出边",
                        node_path_by_id[node_id],
                        node_id,
                    )
                )
            if node_type != "branch" and len(outgoing.get(node_id, [])) > 1:
                errors.append(
                    _issue(
                        "non_branch_multiple_outgoing",
                        "非 Branch 节点最多只能有一条出边",
                        node_path_by_id[node_id],
                        node_id,
                    )
                )

    for node_id, node in node_by_id.items():
        if node.get("type") == "branch":
            branches = node.get("config", {}).get("branches", [])
            if branches and not isinstance(branches, list):
                errors.append(
                    _issue(
                        "invalid_branch_config",
                        "branches 必须是数组",
                        "config.branches",
                        node_id,
                    )
                )
                continue
            branch_targets: set[str] = set()
            for branch_index, branch in enumerate(branches):
                target = branch.get("target") if isinstance(branch, dict) else None
                path = f"{node_path_by_id[node_id]}.config.branches[{branch_index}].target"
                if target not in node_by_id:
                    errors.append(
                        _issue("branch_target_missing", "Branch target 节点不存在", path, node_id)
                    )
                elif (node_id, target) not in edge_pairs:
                    errors.append(
                        _issue(
                            "branch_edge_missing",
                            "Branch target 必须存在对应 edge",
                            path,
                            node_id,
                        )
                    )
                if isinstance(target, str):
                    branch_targets.add(target)

            if mode in {"publish", "run"}:
                for target in outgoing.get(node_id, []):
                    if target not in branch_targets:
                        errors.append(
                            _issue(
                                "branch_edge_unmapped",
                                "Branch 出边必须能映射到 branches[].target",
                                node_path_by_id[node_id],
                                node_id,
                            )
                        )

        on_error = node.get("on_error") or {}
        target = on_error.get("target") if isinstance(on_error, dict) else None
        if target and target not in node_by_id:
            errors.append(
                _issue(
                    "on_error_target_missing",
                    "on_error.target 节点不存在",
                    "on_error.target",
                    node_id,
                )
            )

    if start_nodes:
        reachable = _reachable(start_nodes[0]["id"], outgoing)
        for index, node in enumerate(nodes):
            node_id = node.get("id") if isinstance(node, dict) else None
            if not node_id or node_id in reachable:
                continue
            issue = _issue(
                "node_unreachable_from_start",
                "节点必须能从 Start Node 到达",
                f"nodes[{index}]",
                node_id,
            )
            if mode in {"publish", "run"} and node.get("type") != "start":
                errors.append(issue)
            else:
                warnings.append(issue)
        if end_nodes and end_nodes[0]["id"] not in reachable and mode in {"publish", "run"}:
            errors.append(
                _issue(
                    "end_node_unreachable",
                    "End Node 必须能从 Start Node 到达",
                    "edges",
                    end_nodes[0]["id"],
                )
            )

    cycle = _find_cycle(node_by_id.keys(), outgoing)
    if cycle and mode in {"publish", "run"}:
        errors.append(
            _issue(
                "graph_cycle_detected",
                "工作流 Graph 不允许存在环",
                "edges",
                cycle[0],
            )
            | {"cycle": cycle}
        )

    return {"valid": not errors, "errors": errors, "warnings": warnings}


def _reachable(start_node_id: str, outgoing: dict[str, list[str]]) -> set[str]:
    visited = {start_node_id}
    queue: deque[str] = deque([start_node_id])
    while queue:
        node_id = queue.popleft()
        for target in outgoing.get(node_id, []):
            if target not in visited:
                visited.add(target)
                queue.append(target)
    return visited


def _find_cycle(node_ids: Any, outgoing: dict[str, list[str]]) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node_id: str) -> list[str] | None:
        visiting.add(node_id)
        stack.append(node_id)
        for target in outgoing.get(node_id, []):
            if target in visiting:
                cycle_start = stack.index(target)
                return [*stack[cycle_start:], target]
            if target not in visited:
                cycle = visit(target)
                if cycle:
                    return cycle
        stack.pop()
        visiting.remove(node_id)
        visited.add(node_id)
        return None

    for node_id in node_ids:
        if node_id not in visited:
            cycle = visit(node_id)
            if cycle:
                return cycle
    return None


def _issue(code: str, message: str, path: str, node_id: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "path": path, "node_id": node_id}


def _validate_llm_node_config(
    node: dict[str, Any],
    path: str,
    errors: list[dict[str, Any]],
) -> None:
    node_id = node.get("id")
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    if not (config.get("model_config_id") or config.get("model")):
        errors.append(
            _issue(
                "missing_llm_model",
                "LLM Node 必须配置 model_config_id 或 model",
                f"{path}.config.model_config_id",
                node_id,
            )
        )
    if not (config.get("user_prompt") or config.get("prompt")):
        errors.append(
            _issue(
                "missing_llm_prompt",
                "LLM Node 必须配置 user_prompt",
                f"{path}.config.user_prompt",
                node_id,
            )
        )


def _validate_set_variable_node_config(
    node: dict[str, Any],
    path: str,
    errors: list[dict[str, Any]],
) -> None:
    node_id = node.get("id")
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    assignments = config.get("assignments", config.get("variables"))
    if assignments is None or assignments == "":
        errors.append(
            _issue(
                "missing_set_variable_assignments",
                "Set Variable Node 必须配置 assignments",
                f"{path}.config.assignments",
                node_id,
            )
        )
        return
    if isinstance(assignments, dict):
        if not assignments:
            errors.append(
                _issue(
                    "empty_set_variable_assignments",
                    "Set Variable Node 至少需要一个赋值项",
                    f"{path}.config.assignments",
                    node_id,
                )
            )
        return
    if isinstance(assignments, list):
        if not assignments:
            errors.append(
                _issue(
                    "empty_set_variable_assignments",
                    "Set Variable Node 至少需要一个赋值项",
                    f"{path}.config.assignments",
                    node_id,
                )
            )
            return
        for index, assignment in enumerate(assignments):
            has_target = (
                isinstance(assignment, dict)
                and bool(assignment.get("target") or assignment.get("name"))
            )
            if not has_target:
                errors.append(
                    _issue(
                        "invalid_set_variable_assignment",
                        "Set Variable Node 赋值项必须包含 target 或 name",
                        f"{path}.config.assignments[{index}]",
                        node_id,
                    )
                )
        return
    errors.append(
        _issue(
            "invalid_set_variable_assignments",
            "Set Variable Node assignments 必须是对象或数组",
            f"{path}.config.assignments",
            node_id,
        )
    )


def _has_final_output_config(config: dict[str, Any]) -> bool:
    return bool(config.get("response_mode") or config.get("outputs") or config.get("template"))


def _validate_final_output_config(
    node: dict[str, Any],
    path: str,
    errors: list[dict[str, Any]],
    *,
    node_label: str,
    missing_code: str,
    missing_message: str,
    missing_template_code: str,
) -> None:
    node_id = node.get("id")
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    mode = str(config.get("response_mode") or "parameters").strip().lower()
    if mode not in {"parameters", "template"}:
        errors.append(
            _issue(
                "invalid_final_output_response_mode",
                f"{node_label} response_mode 必须是 parameters 或 template",
                f"{path}.config.response_mode",
                node_id,
            )
        )
    if not isinstance(config.get("outputs"), dict):
        errors.append(
            _issue(
                missing_code,
                missing_message,
                f"{path}.config.outputs",
                node_id,
            )
        )
    if mode == "template" and not str(config.get("template") or "").strip():
        errors.append(
            _issue(
                missing_template_code,
                f"{node_label} 模板模式必须配置 template",
                f"{path}.config.template",
                node_id,
            )
        )


def _validate_human_approval_node_config(
    node: dict[str, Any],
    path: str,
    errors: list[dict[str, Any]],
) -> None:
    node_id = node.get("id")
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    title = str(config.get("title") or "").strip()
    if not title:
        errors.append(
            _issue(
                "missing_human_approval_title",
                "Human Approval Node 必须配置 title",
                f"{path}.config.title",
                node_id,
            )
        )

    timeout_seconds = config.get("timeout_seconds")
    if timeout_seconds is None or timeout_seconds == "":
        return
    try:
        parsed = int(timeout_seconds)
    except (TypeError, ValueError):
        parsed = 0
    if parsed < 1 or parsed > 604800:
        errors.append(
            _issue(
                "invalid_human_approval_timeout",
                "Human Approval Node timeout_seconds 必须在 1 到 604800 之间",
                f"{path}.config.timeout_seconds",
                node_id,
            )
        )


def _validate_api_node_config(
    node: dict[str, Any],
    path: str,
    errors: list[dict[str, Any]],
) -> None:
    node_id = node.get("id")
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    mode = str(config.get("mode") or config.get("execution_mode") or "mock").lower()
    if mode not in {"mock", "http"}:
        errors.append(
            _issue(
                "invalid_api_mode",
                "API Node mode 必须是 mock 或 http",
                f"{path}.config.mode",
                node_id,
            )
        )
    if not str(config.get("url") or config.get("endpoint") or "").strip():
        errors.append(
            _issue(
                "missing_api_url",
                "API Node 必须配置 url",
                f"{path}.config.url",
                node_id,
            )
        )
    method = str(config.get("method") or "GET").upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        errors.append(
            _issue(
                "invalid_api_method",
                "API Node method 必须是 GET、POST、PUT、PATCH 或 DELETE",
                f"{path}.config.method",
                node_id,
            )
        )
    max_response_bytes = config.get("max_response_bytes")
    if max_response_bytes is not None and max_response_bytes != "":
        try:
            parsed = int(max_response_bytes)
        except (TypeError, ValueError):
            parsed = 0
        if parsed < 1 or parsed > 5 * 1024 * 1024:
            errors.append(
                _issue(
                    "invalid_api_max_response_bytes",
                    "API Node max_response_bytes 必须在 1 到 5242880 之间",
                    f"{path}.config.max_response_bytes",
                    node_id,
                )
            )
