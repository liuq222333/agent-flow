# Agent 工作流平台 MVP 示例工作流与验收样例 v0.1

## 1. 文档目标

本文档提供 MVP 阶段可用于前端编辑器、后端 Runtime、接口联调和端到端验收的标准示例工作流。

示例遵循：

```text
schema_version = 1.0
Node Protocol v0.1
MVP 节点范围
Runtime 只支持顺序执行和 Branch
```

---

## 2. 示例一：简单 LLM 工作流

### 2.1 场景

用户输入一个问题，LLM 直接生成回答。

流程：

```text
Start → Input → LLM → Output → End
```

### 2.2 测试输入

```json
{
  "user_query": "请用一句话介绍这个平台"
}
```

### 2.3 期望输出

```json
{
  "answer": "这是一个用于可视化编排、运行和追踪 Agent 工作流的平台。"
}
```

### 2.4 Graph JSON

```json
{
  "schema_version": "1.0",
  "nodes": [
    {
      "id": "start_1",
      "type": "start",
      "name": "开始",
      "position": { "x": 80, "y": 160 },
      "config": {}
    },
    {
      "id": "input_1",
      "type": "input",
      "name": "用户输入",
      "position": { "x": 260, "y": 160 },
      "config": {
        "fields": [
          {
            "name": "user_query",
            "type": "string",
            "label": "用户问题",
            "required": true
          }
        ]
      }
    },
    {
      "id": "llm_1",
      "type": "llm",
      "name": "生成回答",
      "position": { "x": 440, "y": 160 },
      "input_mapping": {
        "question": "{{input.user_query}}"
      },
      "output_mapping": {
        "answer": "variables.answer"
      },
      "config": {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "system_prompt": "你是一个简洁、专业的产品助手。",
        "user_prompt": "请回答用户问题：{{question}}",
        "temperature": 0.3,
        "max_tokens": 500,
        "response_format": "text"
      },
      "retry": {
        "max_attempts": 2,
        "backoff": "fixed",
        "retry_on": ["timeout", "rate_limit", "llm_provider_error"]
      },
      "timeout": 60
    },
    {
      "id": "output_1",
      "type": "output",
      "name": "最终输出",
      "position": { "x": 620, "y": 160 },
      "config": {
        "outputs": {
          "answer": "{{variables.answer}}"
        }
      },
      "output_mapping": {
        "outputs": "outputs"
      }
    },
    {
      "id": "end_1",
      "type": "end",
      "name": "结束",
      "position": { "x": 800, "y": 160 },
      "config": {}
    }
  ],
  "edges": [
    { "id": "e_start_input", "source": "start_1", "target": "input_1" },
    { "id": "e_input_llm", "source": "input_1", "target": "llm_1" },
    { "id": "e_llm_output", "source": "llm_1", "target": "output_1" },
    { "id": "e_output_end", "source": "output_1", "target": "end_1" }
  ]
}
```

### 2.5 验收点

```text
workflow_run.status = completed
node_runs 包含 start/input/llm/output/end
llm_1 metadata_json 包含 model 和 token usage
workflow_runs.output_json.answer 有值
```

---

## 3. 示例二：知识库问答工作流

### 3.1 场景

用户询问售后政策，知识库节点检索文档片段，LLM 基于片段生成带来源的回答。

流程：

```text
Start → Input → Knowledge Base → LLM → Output → End
```

### 3.2 前置数据

需要先创建知识库并上传文档：

```text
knowledge_base_id = kb_001
文档：售后政策.pdf 或 售后政策.md
文档状态：indexed
```

如果数据库 ID 使用数字，实际运行时把 `kb_001` 替换为对应 ID 字符串或数字，前后端保持一致即可。

### 3.3 测试输入

```json
{
  "user_query": "7 天无理由退款规则是什么？"
}
```

### 3.4 期望输出

```json
{
  "answer": "用户通常可以在签收后 7 天内申请无理由退款，具体条件以售后政策为准。",
  "sources": [
    {
      "file_name": "售后政策.pdf",
      "page_start": 3
    }
  ]
}
```

### 3.5 Graph JSON

```json
{
  "schema_version": "1.0",
  "nodes": [
    {
      "id": "start_1",
      "type": "start",
      "name": "开始",
      "position": { "x": 80, "y": 160 },
      "config": {}
    },
    {
      "id": "input_1",
      "type": "input",
      "name": "用户输入",
      "position": { "x": 260, "y": 160 },
      "config": {
        "fields": [
          {
            "name": "user_query",
            "type": "string",
            "label": "用户问题",
            "required": true
          }
        ]
      }
    },
    {
      "id": "kb_1",
      "type": "knowledge_base",
      "name": "检索售后知识库",
      "position": { "x": 440, "y": 160 },
      "input_mapping": {
        "question": "{{input.user_query}}"
      },
      "output_mapping": {
        "chunks": "variables.kb_context"
      },
      "config": {
        "knowledge_base_ids": ["kb_001"],
        "query": "{{question}}",
        "retrieval_mode": "vector",
        "top_k": 5,
        "score_threshold": 0.65,
        "context_budget_tokens": 3000
      },
      "timeout": 30
    },
    {
      "id": "llm_1",
      "type": "llm",
      "name": "基于资料回答",
      "position": { "x": 620, "y": 160 },
      "input_mapping": {
        "question": "{{input.user_query}}",
        "context": "{{variables.kb_context}}"
      },
      "output_mapping": {
        "answer": "variables.answer"
      },
      "config": {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "system_prompt": "你是一个知识库问答助手。请只基于给定资料回答，无法确定时说明资料不足。",
        "user_prompt": "问题：{{question}}\n资料：{{context}}\n请给出简洁回答，并尽量保留来源信息。",
        "temperature": 0.2,
        "max_tokens": 1000,
        "response_format": "text"
      },
      "timeout": 60
    },
    {
      "id": "output_1",
      "type": "output",
      "name": "最终输出",
      "position": { "x": 800, "y": 160 },
      "config": {
        "outputs": {
          "answer": "{{variables.answer}}",
          "sources": "{{variables.kb_context}}"
        }
      },
      "output_mapping": {
        "outputs": "outputs"
      }
    },
    {
      "id": "end_1",
      "type": "end",
      "name": "结束",
      "position": { "x": 980, "y": 160 },
      "config": {}
    }
  ],
  "edges": [
    { "id": "e_start_input", "source": "start_1", "target": "input_1" },
    { "id": "e_input_kb", "source": "input_1", "target": "kb_1" },
    { "id": "e_kb_llm", "source": "kb_1", "target": "llm_1" },
    { "id": "e_llm_output", "source": "llm_1", "target": "output_1" },
    { "id": "e_output_end", "source": "output_1", "target": "end_1" }
  ]
}
```

### 3.6 验收点

```text
kb_1 output_json.chunks 至少有 1 条
kb_1 metadata_json.returned_chunks > 0
llm_1 input_json.context 保留数组或可读 JSON
output_json.answer 有值
output_json.sources 有来源信息
```

---

## 4. 示例三：意图识别 + 分支工作流

### 4.1 场景

系统先识别用户意图，再根据意图进入退款回答或通用回答。

流程：

```text
Start → Input → Intent → Branch
                         ├─ refund_request → LLM → Output → End
                         └─ general_question → LLM → Output → End
```

### 4.2 测试输入 A

```json
{
  "user_query": "我要申请退款"
}
```

期望：

```text
Intent = refund_request
Branch target = llm_refund_1
```

### 4.3 测试输入 B

```json
{
  "user_query": "你们平台能做什么？"
}
```

期望：

```text
Intent = general_question
Branch target = llm_general_1
```

### 4.4 Graph JSON

```json
{
  "schema_version": "1.0",
  "nodes": [
    {
      "id": "start_1",
      "type": "start",
      "name": "开始",
      "position": { "x": 80, "y": 220 },
      "config": {}
    },
    {
      "id": "input_1",
      "type": "input",
      "name": "用户输入",
      "position": { "x": 240, "y": 220 },
      "config": {
        "fields": [
          {
            "name": "user_query",
            "type": "string",
            "label": "用户问题",
            "required": true
          }
        ]
      }
    },
    {
      "id": "intent_1",
      "type": "intent",
      "name": "识别意图",
      "position": { "x": 400, "y": 220 },
      "input_mapping": {
        "text": "{{input.user_query}}"
      },
      "output_mapping": {
        "intent": "variables.intent_result.intent",
        "confidence": "variables.intent_result.confidence"
      },
      "config": {
        "model": "gpt-4.1-mini",
        "intents": [
          {
            "name": "refund_request",
            "description": "用户申请退款、退货、售后退款"
          },
          {
            "name": "general_question",
            "description": "普通咨询问题"
          }
        ],
        "fallback_intent": "general_question"
      },
      "timeout": 30
    },
    {
      "id": "branch_1",
      "type": "branch",
      "name": "按意图分支",
      "position": { "x": 560, "y": 220 },
      "config": {
        "branches": [
          {
            "id": "branch_refund",
            "condition": {
              "left": "{{variables.intent_result.intent}}",
              "operator": "eq",
              "right": "refund_request"
            },
            "target": "llm_refund_1"
          },
          {
            "id": "branch_default",
            "condition": "default",
            "target": "llm_general_1"
          }
        ]
      }
    },
    {
      "id": "llm_refund_1",
      "type": "llm",
      "name": "退款说明",
      "position": { "x": 760, "y": 120 },
      "input_mapping": {
        "question": "{{input.user_query}}"
      },
      "output_mapping": {
        "answer": "variables.answer"
      },
      "config": {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "system_prompt": "你是客服助手。",
        "user_prompt": "用户想退款。请说明下一步需要提供订单号，并保持简洁。用户原话：{{question}}",
        "temperature": 0.3,
        "max_tokens": 600,
        "response_format": "text"
      }
    },
    {
      "id": "llm_general_1",
      "type": "llm",
      "name": "通用回答",
      "position": { "x": 760, "y": 320 },
      "input_mapping": {
        "question": "{{input.user_query}}"
      },
      "output_mapping": {
        "answer": "variables.answer"
      },
      "config": {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "system_prompt": "你是平台介绍助手。",
        "user_prompt": "请回答用户问题：{{question}}",
        "temperature": 0.3,
        "max_tokens": 600,
        "response_format": "text"
      }
    },
    {
      "id": "output_1",
      "type": "output",
      "name": "最终输出",
      "position": { "x": 960, "y": 220 },
      "config": {
        "outputs": {
          "intent": "{{variables.intent_result.intent}}",
          "answer": "{{variables.answer}}"
        }
      },
      "output_mapping": {
        "outputs": "outputs"
      }
    },
    {
      "id": "end_1",
      "type": "end",
      "name": "结束",
      "position": { "x": 1140, "y": 220 },
      "config": {}
    }
  ],
  "edges": [
    { "id": "e_start_input", "source": "start_1", "target": "input_1" },
    { "id": "e_input_intent", "source": "input_1", "target": "intent_1" },
    { "id": "e_intent_branch", "source": "intent_1", "target": "branch_1" },
    { "id": "e_branch_refund", "source": "branch_1", "target": "llm_refund_1", "label": "refund_request" },
    { "id": "e_branch_general", "source": "branch_1", "target": "llm_general_1", "label": "default" },
    { "id": "e_refund_output", "source": "llm_refund_1", "target": "output_1" },
    { "id": "e_general_output", "source": "llm_general_1", "target": "output_1" },
    { "id": "e_output_end", "source": "output_1", "target": "end_1" }
  ]
}
```

### 4.5 验收点

```text
branch_1 output_json.selected_branch_id 有值
只有命中的 LLM 分支产生 node_run
未命中的 LLM 分支没有 node_run
output_json.intent 等于识别出的 intent
```

---

## 5. 示例四：API 调用 + Message 工作流

### 5.1 场景

用户输入订单号，API Node 查询订单状态，LLM 转成自然语言，再通过 Message Node 生成用户可见消息。

流程：

```text
Start → Input → API → LLM → Message → Output → End
```

### 5.2 测试输入

```json
{
  "order_id": "ORDER_10001"
}
```

### 5.3 前置工具

API Node 可直接配置 URL，也可以引用工具。MVP 示例先直接配置 URL：

```text
POST https://api.example.com/orders/query
```

真实联调时建议替换为本地 mock API：

```text
POST http://localhost:3001/mock/orders/query
```

### 5.4 Graph JSON

```json
{
  "schema_version": "1.0",
  "nodes": [
    {
      "id": "start_1",
      "type": "start",
      "name": "开始",
      "position": { "x": 80, "y": 160 },
      "config": {}
    },
    {
      "id": "input_1",
      "type": "input",
      "name": "订单号输入",
      "position": { "x": 240, "y": 160 },
      "config": {
        "fields": [
          {
            "name": "order_id",
            "type": "string",
            "label": "订单号",
            "required": true
          }
        ]
      }
    },
    {
      "id": "api_1",
      "type": "api",
      "name": "查询订单",
      "position": { "x": 400, "y": 160 },
      "input_mapping": {
        "order_id": "{{input.order_id}}"
      },
      "output_mapping": {
        "response": "variables.order_api_response"
      },
      "config": {
        "method": "POST",
        "url": "https://api.example.com/orders/query",
        "headers": {
          "Content-Type": "application/json",
          "Authorization": "Bearer {{secrets.order_api_key}}"
        },
        "query_params": {},
        "body": {
          "order_id": "{{order_id}}"
        },
        "response_path": "data",
        "timeout": 30
      },
      "retry": {
        "max_attempts": 2,
        "backoff": "fixed",
        "retry_on": ["timeout", "network_error", "api_request_error"]
      },
      "timeout": 30
    },
    {
      "id": "llm_1",
      "type": "llm",
      "name": "生成订单说明",
      "position": { "x": 560, "y": 160 },
      "input_mapping": {
        "order": "{{variables.order_api_response}}"
      },
      "output_mapping": {
        "answer": "variables.answer"
      },
      "config": {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "system_prompt": "你是订单客服助手。",
        "user_prompt": "请把订单查询结果转成一句用户可读的话：{{order}}",
        "temperature": 0.2,
        "max_tokens": 500,
        "response_format": "text"
      }
    },
    {
      "id": "message_1",
      "type": "message",
      "name": "回复用户",
      "position": { "x": 720, "y": 160 },
      "input_mapping": {
        "answer": "{{variables.answer}}"
      },
      "output_mapping": {
        "message": "messages"
      },
      "config": {
        "message_type": "text",
        "template": "{{answer}}"
      }
    },
    {
      "id": "output_1",
      "type": "output",
      "name": "最终输出",
      "position": { "x": 880, "y": 160 },
      "config": {
        "outputs": {
          "answer": "{{variables.answer}}",
          "order": "{{variables.order_api_response}}"
        }
      },
      "output_mapping": {
        "outputs": "outputs"
      }
    },
    {
      "id": "end_1",
      "type": "end",
      "name": "结束",
      "position": { "x": 1040, "y": 160 },
      "config": {}
    }
  ],
  "edges": [
    { "id": "e_start_input", "source": "start_1", "target": "input_1" },
    { "id": "e_input_api", "source": "input_1", "target": "api_1" },
    { "id": "e_api_llm", "source": "api_1", "target": "llm_1" },
    { "id": "e_llm_message", "source": "llm_1", "target": "message_1" },
    { "id": "e_message_output", "source": "message_1", "target": "output_1" },
    { "id": "e_output_end", "source": "output_1", "target": "end_1" }
  ]
}
```

### 5.5 Mock API 响应建议

```json
{
  "data": {
    "order_id": "ORDER_10001",
    "status": "shipped",
    "amount": 199,
    "delivery_company": "顺丰",
    "tracking_no": "SF123456789"
  }
}
```

### 5.6 验收点

```text
api_1 metadata_json.status_code = 200
api_1 output_json.response 有订单数据
Authorization 不出现在 node_run.input_json 明文中
message_1 将消息追加到 state.messages
output_json.order 有值
```

---

## 6. 通用失败验收样例

### 6.1 变量不存在

构造：

```json
{
  "input_mapping": {
    "order_id": "{{variables.missing_order_id}}"
  }
}
```

期望：

```text
node_run.status = failed
error_code = variable_not_found
workflow_run.status = failed
```

---

### 6.2 Branch 无匹配且无 default

构造：

```json
{
  "branches": [
    {
      "id": "only_refund",
      "condition": {
        "left": "{{variables.intent_result.intent}}",
        "operator": "eq",
        "right": "refund_request"
      },
      "target": "llm_refund_1"
    }
  ]
}
```

输入使 intent 为：

```text
general_question
```

期望：

```text
branch_1 failed
error_code = branch_no_match
workflow_run.status = failed
```

---

### 6.3 API 超时

构造：

```json
{
  "type": "api",
  "timeout": 1,
  "config": {
    "url": "https://api.example.com/slow"
  }
}
```

期望：

```text
error_code = timeout
如果 retry_on 包含 timeout，则产生多条 attempt
超过 max_attempts 后 workflow_run.status = failed
```

---

## 7. 结论

这四个示例覆盖 MVP 的核心能力：

```text
LLM 生成
知识库检索
意图识别
条件分支
API 调用
消息输出
Trace 记录
错误定位
```

建议在开发早期就把这些示例作为固定测试样例，前端、后端、Runtime 和测试环境都围绕它们持续验收。

