from copy import deepcopy
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/node-types", tags=["node-types"])

NODE_TYPE_ORDER = [
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
]

NODE_TYPE_SUMMARIES: dict[str, dict[str, str]] = {
    "start": {
        "type": "start",
        "name": "开始",
        "category": "io",
        "description": "声明工作流输入字段，并作为流程起点。",
    },
    "input": {
        "type": "input",
        "name": "用户输入",
        "category": "io",
        "description": "声明工作流输入字段。",
    },
    "llm": {
        "type": "llm",
        "name": "大模型",
        "category": "ai",
        "description": "调用大模型生成文本结果。",
    },
    "knowledge_base": {
        "type": "knowledge_base",
        "name": "知识库检索",
        "category": "ai",
        "description": "从一个或多个知识库检索上下文。",
    },
    "intent": {
        "type": "intent",
        "name": "意图识别",
        "category": "ai",
        "description": "识别输入文本的业务意图。",
    },
    "branch": {
        "type": "branch",
        "name": "条件分支",
        "category": "control",
        "description": "根据条件选择下一条执行路径。",
    },
    "human_approval": {
        "type": "human_approval",
        "name": "人工审批",
        "category": "control",
        "description": "执行到该节点时创建待审批任务，并暂停工作流。",
    },
    "set_variable": {
        "type": "set_variable",
        "name": "变量赋值",
        "category": "data",
        "description": "将输入、模板或节点输出整理写入 variables。",
    },
    "api": {
        "type": "api",
        "name": "API 调用",
        "category": "integration",
        "description": "调用外部 HTTP API。",
    },
    "message": {
        "type": "message",
        "name": "消息",
        "category": "io",
        "description": "根据模板生成回复消息。",
    },
    "output": {
        "type": "output",
        "name": "最终输出",
        "category": "io",
        "description": "历史兼容节点。新工作流请在结束节点配置最终输出。",
    },
    "end": {
        "type": "end",
        "name": "结束",
        "category": "io",
        "description": "工作流结束节点，并生成最终输出。",
    },
}

BASE_NODE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["id", "type", "name", "position", "config"],
    "properties": {
        "id": {"type": "string"},
        "type": {"type": "string", "enum": NODE_TYPE_ORDER},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "position": {
            "type": "object",
            "required": ["x", "y"],
            "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
        },
        "input_mapping": {"type": "object", "additionalProperties": True},
        "output_mapping": {"type": "object", "additionalProperties": True},
        "config": {"type": "object", "additionalProperties": True},
        "retry": {
            "type": "object",
            "properties": {
                "max_attempts": {"type": "integer", "minimum": 1, "default": 1},
                "backoff": {
                    "type": "string",
                    "enum": ["none", "fixed", "exponential"],
                    "default": "none",
                },
                "retry_on": {"type": "array", "items": {"type": "string"}},
            },
        },
        "timeout": {"type": "integer", "minimum": 1, "default": 60},
        "on_error": {
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "enum": ["fail_workflow", "skip_node", "go_to_node"],
                    "default": "fail_workflow",
                },
                "target": {"type": "string"},
            },
        },
        "enabled": {"type": "boolean", "default": True},
    },
}

CONFIG_SCHEMAS: dict[str, dict[str, Any]] = {
    "start": {
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "type"],
                    "properties": {
                        "name": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["string", "number", "boolean", "array", "object", "json"],
                        },
                        "label": {"type": "string"},
                        "required": {"type": "boolean", "default": False},
                        "default": {},
                    },
                },
                "default": [],
            }
        },
    },
    "input": {
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "type", "label"],
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string", "enum": ["string", "number", "boolean"]},
                        "label": {"type": "string"},
                        "required": {"type": "boolean", "default": False},
                        "default": {},
                    },
                },
                "default": [],
            }
        },
    },
    "llm": {
        "type": "object",
        "required": ["model", "user_prompt"],
        "properties": {
            "model_config_id": {"type": "integer"},
            "provider": {
                "type": "string",
                "enum": ["mock", "deepseek", "openai"],
                "default": "deepseek",
            },
            "model": {"type": "string", "default": "deepseek-v4-flash"},
            "system_prompt": {"type": "string", "default": ""},
            "user_prompt": {"type": "string"},
            "temperature": {"type": "number", "minimum": 0, "maximum": 2, "default": 0.3},
            "max_tokens": {"type": "integer", "minimum": 1, "default": 1000},
            "response_format": {"type": "string", "enum": ["text", "json"], "default": "text"},
        },
    },
    "knowledge_base": {
        "type": "object",
        "required": ["knowledge_base_ids", "query"],
        "properties": {
            "knowledge_base_ids": {"type": "array", "items": {"type": "integer"}},
            "query": {"type": "string"},
            "retrieval_mode": {"type": "string", "enum": ["vector"], "default": "vector"},
            "top_k": {"type": "integer", "minimum": 1, "default": 5},
            "score_threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.65},
            "context_budget_tokens": {"type": "integer", "minimum": 1, "default": 3000},
        },
    },
    "intent": {
        "type": "object",
        "required": ["model", "intents"],
        "properties": {
            "model": {"type": "string"},
            "intents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "description"],
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                    },
                },
            },
            "fallback_intent": {"type": "string"},
        },
    },
    "branch": {
        "type": "object",
        "required": ["branches"],
        "properties": {
            "branches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "condition", "target"],
                    "properties": {
                        "id": {"type": "string"},
                        "condition": {
                            "oneOf": [
                                {"type": "string", "enum": ["default"]},
                                {
                                    "type": "object",
                                    "required": ["left", "operator"],
                                    "properties": {
                                        "left": {"type": "string"},
                                        "operator": {
                                            "type": "string",
                                            "enum": [
                                                "eq",
                                                "neq",
                                                "contains",
                                                "gt",
                                                "gte",
                                                "lt",
                                                "lte",
                                                "exists",
                                                "not_exists",
                                            ],
                                        },
                                        "right": {},
                                    },
                                },
                            ]
                        },
                        "target": {"type": "string"},
                    },
                },
            }
        },
    },
    "human_approval": {
        "type": "object",
        "required": ["title"],
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "timeout_seconds": {
                "type": "integer",
                "minimum": 1,
                "maximum": 604800,
            },
            "approval_schema": {"type": "object", "additionalProperties": True},
        },
    },
    "api": {
        "type": "object",
        "required": ["method", "url"],
        "properties": {
            "mode": {"type": "string", "enum": ["mock", "http"], "default": "mock"},
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
            "url": {"type": "string"},
            "headers": {"type": "object", "additionalProperties": {"type": "string"}},
            "query_params": {"type": "object", "additionalProperties": True},
            "body": {},
            "mock_response": {},
            "mock_status_code": {"type": "integer", "minimum": 100, "maximum": 599},
            "response_path": {"type": "string"},
            "timeout_seconds": {"type": "number", "minimum": 0.1, "maximum": 30, "default": 10},
            "max_response_bytes": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5242880,
                "default": 1048576,
            },
            "fail_on_http_error": {"type": "boolean", "default": True},
            "fail_on_request_error": {"type": "boolean", "default": True},
            "success_status_codes": {
                "type": "array",
                "items": {"type": "integer", "minimum": 100, "maximum": 599},
            },
        },
    },
    "set_variable": {
        "type": "object",
        "properties": {
            "assignments": {
                "oneOf": [
                    {"type": "object", "additionalProperties": True},
                    {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["value"],
                            "properties": {
                                "name": {"type": "string"},
                                "target": {"type": "string"},
                                "value": {},
                            },
                        },
                    },
                ],
                "default": {},
            },
            "variables": {"type": "object", "additionalProperties": True},
        },
    },
    "message": {
        "type": "object",
        "required": ["message_type", "template"],
        "properties": {
            "message_type": {"type": "string", "enum": ["text"], "default": "text"},
            "template": {"type": "string"},
        },
    },
    "output": {
        "type": "object",
        "required": ["outputs"],
        "properties": {
            "response_mode": {
                "type": "string",
                "enum": ["parameters", "template"],
                "default": "parameters",
            },
            "outputs": {"type": "object", "additionalProperties": True},
            "template": {"type": "string", "default": ""},
            "output_value_kinds": {
                "type": "object",
                "additionalProperties": {
                    "type": "string",
                    "enum": ["reference", "text", "number", "boolean", "json"],
                },
            },
        },
    },
    "end": {
        "type": "object",
        "properties": {
            "response_mode": {
                "type": "string",
                "enum": ["parameters", "template"],
                "default": "parameters",
            },
            "outputs": {"type": "object", "additionalProperties": True},
            "template": {"type": "string", "default": ""},
            "output_value_kinds": {
                "type": "object",
                "additionalProperties": {
                    "type": "string",
                    "enum": ["reference", "text", "number", "boolean", "json"],
                },
            },
        },
    },
}

FORM_SCHEMAS: dict[str, dict[str, Any]] = {
    node_type: {
        "type": node_type,
        "fields": [
            {"name": name, "label": label, "component": component, "required": required}
            for name, label, component, required in fields
        ],
    }
    for node_type, fields in {
        "start": [("config.fields", "输入字段", "field_array", False)],
        "input": [("config.fields", "输入字段", "field_array", False)],
        "llm": [
            ("config.model_config_id", "模型配置", "select", False),
            ("config.provider", "Provider", "input", False),
            ("config.model", "模型", "input", True),
            ("config.system_prompt", "System Prompt", "textarea", False),
            ("config.user_prompt", "User Prompt", "textarea", True),
            ("config.temperature", "Temperature", "number", False),
        ],
        "knowledge_base": [
            ("config.knowledge_base_ids", "知识库", "number_array", True),
            ("config.query", "检索 query", "textarea", True),
            ("config.top_k", "Top K", "number", False),
            ("config.score_threshold", "Score Threshold", "number", False),
        ],
        "intent": [
            ("config.model", "模型", "input", True),
            ("config.intents", "意图列表", "object_array", True),
            ("config.fallback_intent", "兜底意图", "input", False),
        ],
        "branch": [("config.branches", "分支", "branch_array", True)],
        "human_approval": [
            ("config.title", "审批标题", "input", True),
            ("config.description", "审批说明", "textarea", False),
            ("config.timeout_seconds", "超时秒数", "number", False),
        ],
        "set_variable": [
            ("config.assignments", "变量赋值", "key_value", True),
        ],
        "api": [
            ("config.mode", "Mode", "select", True),
            ("config.method", "Method", "select", True),
            ("config.url", "URL", "input", True),
            ("config.headers", "Headers", "key_value", False),
            ("config.query_params", "Query Params", "key_value", False),
            ("config.body", "Body", "json", False),
            ("config.response_path", "Response Path", "input", False),
            ("config.timeout_seconds", "Timeout", "number", False),
            ("config.max_response_bytes", "Max Response Bytes", "number", False),
        ],
        "message": [
            ("config.message_type", "消息类型", "select", True),
            ("config.template", "模板", "textarea", True),
        ],
        "output": [
            ("config.response_mode", "回复模式", "select", False),
            ("config.outputs", "输出", "key_value", True),
            ("config.template", "回复模板", "textarea", False),
        ],
        "end": [
            ("config.response_mode", "回复模式", "select", False),
            ("config.outputs", "输出", "key_value", True),
            ("config.template", "回复模板", "textarea", False),
        ],
    }.items()
}


@router.get("")
async def list_node_types() -> dict[str, list[dict[str, str]]]:
    return {"items": [NODE_TYPE_SUMMARIES[node_type] for node_type in NODE_TYPE_ORDER]}


@router.get("/{node_type}/schema")
async def get_node_type_schema(node_type: str) -> dict[str, Any]:
    if node_type not in NODE_TYPE_SUMMARIES:
        raise HTTPException(status_code=404, detail={"code": "node_type_not_found"})

    node_schema = deepcopy(BASE_NODE_SCHEMA)
    node_schema["properties"]["type"] = {"type": "string", "const": node_type}
    node_schema["properties"]["config"] = deepcopy(CONFIG_SCHEMAS[node_type])
    return {
        "type": node_type,
        "node_schema": node_schema,
        "config_schema": deepcopy(CONFIG_SCHEMAS[node_type]),
        "form_schema": deepcopy(FORM_SCHEMAS[node_type]),
    }
