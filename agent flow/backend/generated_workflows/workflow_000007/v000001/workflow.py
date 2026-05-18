from __future__ import annotations

import json
from typing import Any


GRAPH: dict[str, Any] = json.loads('{"edges": [{"id": "e1", "source": "start_1", "target": "input_1"}, {"id": "e2", "source": "input_1", "target": "llm_1"}, {"id": "e3", "source": "llm_1", "target": "output_1"}, {"id": "e4", "source": "output_1", "target": "end_1"}], "nodes": [{"config": {}, "enabled": true, "id": "start_1", "name": "开始", "position": {"x": 80.0, "y": 160.0}, "type": "start"}, {"config": {"fields": [{"name": "user_query", "required": true, "type": "string"}]}, "enabled": true, "id": "input_1", "name": "用户输入", "position": {"x": 280.0, "y": 160.0}, "type": "input"}, {"config": {"model": "local-mock", "provider": "mock", "user_prompt": "问题：{{input.user_query}}"}, "enabled": true, "id": "llm_1", "name": "生成回答", "output_mapping": {"answer": "variables.answer"}, "position": {"x": 500.0, "y": 160.0}, "type": "llm"}, {"config": {"outputs": {"answer": "{{variables.answer}}", "user_query": "{{input.user_query}}"}}, "enabled": true, "id": "output_1", "name": "最终输出", "position": {"x": 720.0, "y": 160.0}, "type": "output"}, {"config": {}, "enabled": true, "id": "end_1", "name": "结束", "position": {"x": 920.0, "y": 160.0}, "type": "end"}], "schema_version": "1.0"}')


async def run(input_data: dict[str, Any], context) -> dict[str, Any]:
    return await context.execute_graph(GRAPH, input_data)
