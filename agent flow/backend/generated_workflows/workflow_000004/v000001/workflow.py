from __future__ import annotations

import json
from typing import Any


GRAPH: dict[str, Any] = json.loads('{"edges": [{"id": "e1", "source": "start_1", "target": "input_1"}, {"id": "e2", "source": "input_1", "target": "llm_1"}, {"id": "e3", "source": "llm_1", "target": "output_1"}, {"id": "e4", "source": "output_1", "target": "end_1"}], "nodes": [{"config": {}, "id": "start_1", "name": "开始", "position": {"x": 80, "y": 160}, "type": "start"}, {"config": {"fields": [{"label": "用户问题", "name": "user_query", "required": true, "type": "string"}]}, "id": "input_1", "name": "用户输入", "position": {"x": 280, "y": 160}, "type": "input"}, {"config": {"model": "local-mock", "provider": "mock", "system_prompt": "你是一个本地调试助手。", "temperature": 0.2, "user_prompt": "问题：{{input.user_query}}"}, "id": "llm_1", "name": "生成回答", "output_mapping": {"answer": "variables.answer"}, "position": {"x": 500, "y": 160}, "type": "llm"}, {"config": {"outputs": {"answer": "{{variables.answer}}", "user_query": "{{input.user_query}}"}}, "id": "output_1", "name": "最终输出", "position": {"x": 720, "y": 160}, "type": "output"}, {"config": {}, "id": "end_1", "name": "结束", "position": {"x": 920, "y": 160}, "type": "end"}], "schema_version": "1.0"}')


async def run(input_data: dict[str, Any], context) -> dict[str, Any]:
    return await context.execute_graph(GRAPH, input_data)
