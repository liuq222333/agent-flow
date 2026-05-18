from __future__ import annotations

import json
from typing import Any


GRAPH: dict[str, Any] = json.loads('{"edges": [{"id": "e1", "source": "start_1", "target": "input_1"}, {"id": "e2", "source": "input_1", "target": "kb_1"}, {"id": "e3", "source": "kb_1", "target": "output_1"}, {"id": "e4", "source": "output_1", "target": "end_1"}], "nodes": [{"config": {}, "enabled": true, "id": "start_1", "name": "start", "position": {"x": 80.0, "y": 160.0}, "type": "start"}, {"config": {"fields": [{"name": "user_query", "required": true, "type": "string"}]}, "enabled": true, "id": "input_1", "name": "input", "position": {"x": 280.0, "y": 160.0}, "type": "input"}, {"config": {"knowledge_base_ids": [5], "query": "{{question}}", "score_threshold": 0.0, "top_k": 3}, "enabled": true, "id": "kb_1", "input_mapping": {"question": "{{input.user_query}}"}, "name": "knowledge_base", "output_mapping": {"chunks": "variables.kb_context"}, "position": {"x": 500.0, "y": 160.0}, "type": "knowledge_base"}, {"config": {"outputs": {"chunks": "{{variables.kb_context}}"}}, "enabled": true, "id": "output_1", "name": "output", "position": {"x": 720.0, "y": 160.0}, "type": "output"}, {"config": {}, "enabled": true, "id": "end_1", "name": "end", "position": {"x": 920.0, "y": 160.0}, "type": "end"}], "schema_version": "1.0"}')


async def run(input_data: dict[str, Any], context) -> dict[str, Any]:
    return await context.execute_graph(GRAPH, input_data)
