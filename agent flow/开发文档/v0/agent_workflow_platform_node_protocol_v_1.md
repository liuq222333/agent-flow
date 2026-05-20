# Agent 工作流平台节点协议设计文档 v0.1

## 1. 文档目标

本文档定义 Agent 工作流平台的节点协议 Node Protocol。

节点协议是前端编辑器、后端校验、Runtime 执行器、节点执行器和 Trace 日志之间的统一契约。

本文档用于明确：

```text
节点统一结构是什么
节点如何声明输入和输出
节点如何读取 State
节点如何写入 State
节点如何引用变量
节点如何配置重试、超时和错误处理
不同类型节点的 config schema 是什么
Runtime 如何根据节点协议执行节点
前端如何根据节点协议渲染配置面板
```

---

## 2. 核心设计原则

节点协议遵循以下原则：

```text
统一结构：所有节点都遵守相同基础结构
类型扩展：不同节点通过 type 和 config 扩展能力
输入显式：节点输入通过 input_mapping 声明
输出显式：节点输出通过 output_mapping 声明
状态隔离：节点之间不直接互相调用，只通过 State 通信
可追踪：每个节点执行都必须记录输入、输出、状态、错误和耗时
可校验：节点配置必须可被 JSON Schema 校验
可扩展：后续新增节点不应破坏已有协议
```

---

## 3. 核心概念

## 3.1 Node

Node 是工作流中的最小执行单元。

一个节点负责完成一个明确任务，例如：

```text
调用 LLM
检索知识库
识别意图
判断分支
调用 API
生成消息
输出结果
```

## 3.2 State

State 是工作流运行时的全局状态容器。节点通过 State 读取输入、写入输出。

MVP State 结构：

```json
{
  "input": {},
  "variables": {},
  "messages": [],
  "outputs": {},
  "metadata": {
    "workflow_id": "",
    "version_id": "",
    "run_id": "",
    "user_id": ""
  }
}
```

## 3.3 input_mapping

input_mapping 定义节点执行前从 State 中读取哪些数据，并映射成节点本地输入。

示例：

```json
{
  "question": "{{input.user_query}}",
  "context": "{{variables.kb_context}}"
}
```

Runtime 会将其解析为：

```json
{
  "question": "用户真实输入的问题",
  "context": ["知识库检索结果"]
}
```

## 3.4 output_mapping

output_mapping 定义节点执行结果写入 State 的位置。

示例：

```json
{
  "answer": "variables.final_answer"
}
```

表示节点执行结果中的 `answer` 字段会写入：

```text
state.variables.final_answer
```

## 3.5 config

config 是节点的类型专属配置。

例如 LLM Node 的 config 包含：

```text
model
system_prompt
user_prompt
temperature
max_tokens
```

API Node 的 config 包含：

```text
method
url
headers
body
timeout
```

---

## 4. 节点统一结构

所有节点必须遵守以下基础结构：

```json
{
  "id": "node_001",
  "type": "llm",
  "name": "生成回答",
  "description": "根据输入生成回答",
  "position": {
    "x": 100,
    "y": 200
  },
  "input_mapping": {},
  "output_mapping": {},
  "config": {},
  "retry": {
    "max_attempts": 1,
    "backoff": "none"
  },
  "timeout": 60,
  "on_error": {
    "strategy": "fail_workflow"
  },
  "enabled": true
}
```

---

## 5. 基础字段说明

## 5.1 id

节点唯一 ID。

要求：

```text
同一个 workflow_version 内唯一
前端创建节点时生成
发布后不可变
推荐格式：node_xxx 或 type_xxx
```

示例：

```json
{
  "id": "llm_001"
}
```

## 5.2 type

节点类型。

MVP 支持类型：

```text
start
input
llm
knowledge_base
intent
branch
api
message
output
end
```

## 5.3 name

节点展示名称。

示例：

```json
{
  "name": "生成客服回复"
}
```

## 5.4 description

节点说明，可选。

## 5.5 position

前端画布位置。

```json
{
  "position": {
    "x": 300,
    "y": 160
  }
}
```

## 5.6 input_mapping

节点输入映射。

不是所有节点都必须有 input_mapping，例如 Start Node 和 End Node 可以为空。

## 5.7 output_mapping

节点输出映射。

不是所有节点都必须有 output_mapping，例如 Branch Node 可以不写入 State，只决定路径。

## 5.8 config

节点配置。

由节点类型决定具体结构。

## 5.9 retry

重试策略。

```json
{
  "max_attempts": 3,
  "backoff": "exponential",
  "retry_on": ["timeout", "rate_limit", "network_error"]
}
```

MVP 支持：

```text
max_attempts
backoff: none / fixed / exponential
retry_on
```

## 5.10 timeout

节点超时时间，单位秒。

默认：

```text
60 秒
```

## 5.11 on_error

错误处理策略。

```json
{
  "strategy": "fail_workflow"
}
```

MVP 支持：

```text
fail_workflow    节点失败后终止整个工作流
skip_node        跳过当前节点，继续后续节点
go_to_node       跳转到指定错误处理节点
```

MVP 第一阶段可以只实现 fail_workflow。

## 5.12 enabled

节点是否启用。

```json
{
  "enabled": true
}
```

MVP 草稿阶段允许前端保存 `enabled: false`，用于临时停用节点。

发布阶段必须强校验：

```text
GraphValidator 发现 enabled: false 时，发布失败
错误码：disabled_node_in_publish
已发布版本中的节点一律视为 enabled = true
Runtime 不实现禁用节点的透明跳转语义
```

---

## 6. 变量引用协议

## 6.1 变量引用语法

MVP 使用 Mustache 风格变量引用。

示例：

```text
{{input.user_query}}
{{variables.kb_context}}
{{variables.intent_result.intent}}
{{outputs.answer}}
{{metadata.user_id}}
```

---

## 6.2 可引用路径

MVP 支持以下根路径：

```text
input
variables
messages
outputs
metadata
```

示例：

```text
{{input.user_query}}
{{variables.order_id}}
{{variables.api_result.data.status}}
{{metadata.run_id}}
```

---

## 6.3 变量解析规则

Runtime 在节点执行前解析变量。

规则：

```text
如果整个字段都是变量引用，则保留原始类型
如果变量引用嵌入字符串中，则转换为字符串
如果变量不存在，节点执行失败
如果路径非法，节点执行失败
```

示例 1：完整变量引用，保留数组类型。

```json
{
  "context": "{{variables.kb_context}}"
}
```

如果 `variables.kb_context` 是数组，则解析后仍为数组。

示例 2：嵌入字符串，转为字符串。

```text
问题是：{{input.user_query}}
```

解析后：

```text
问题是：用户输入内容
```

---

## 6.4 变量不存在处理

MVP 默认严格模式。

```text
变量不存在时节点失败
记录错误类型：variable_not_found
记录错误路径
```

错误示例：

```json
{
  "error_code": "variable_not_found",
  "message": "Variable not found: variables.order_id"
}
```

---

## 6.5 config 解析上下文

节点执行时变量解析分为两个阶段。

```text
Phase 1：解析 input_mapping
  可引用：input / variables / messages / outputs / metadata
  不可引用：secrets
  结果：node_input

Phase 2：解析 node.config
  可引用：node_input 的顶层字段
  可引用：input / variables / messages / outputs / metadata
  可引用：secrets（仅服务端执行时解析）
```

示例：

```json
{
  "input_mapping": {
    "question": "{{input.user_query}}"
  },
  "config": {
    "query": "{{question}}"
  }
}
```

其中 `{{question}}` 引用的是 Phase 1 解析后的 `node_input.question`，不是 `state.question`。

`output_mapping` 的 value 是 State 写入路径，不解析 `{{...}}`。

---

## 7. 输入输出映射协议

## 7.1 节点执行输入构造

Runtime 执行节点前：

```text
1. 读取 node.input_mapping
2. 解析其中变量
3. 得到 node_input
4. 使用 node_input + State 解析 node.config，得到 resolved_config
5. 将 node_input 和 resolved_config 传给对应 NodeExecutor
6. 将 node_input 写入 node_run.input_json
```

示例：

```json
{
  "input_mapping": {
    "question": "{{input.user_query}}",
    "context": "{{variables.kb_context}}"
  }
}
```

解析后：

```json
{
  "question": "退款规则是什么？",
  "context": [
    {
      "content": "用户可在签收后 7 天内申请退款..."
    }
  ]
}
```

---

## 7.2 节点执行输出写回

NodeExecutor 返回 node_output。

示例：

```json
{
  "answer": "你可以在 7 天内申请退款。",
  "confidence": 0.91
}
```

output_mapping：

```json
{
  "answer": "variables.final_answer",
  "confidence": "variables.answer_confidence"
}
```

Runtime 写入 State：

```json
{
  "variables": {
    "final_answer": "你可以在 7 天内申请退款。",
    "answer_confidence": 0.91
  }
}
```

---

## 7.3 output_mapping 规则

规则：

```text
output_mapping key 对应 node_output 中的字段
output_mapping value 对应 State 写入路径
只允许写入 variables、messages、outputs
不允许写入 input
metadata 默认只读
```

允许：

```text
variables.answer
outputs.final_result
messages
```

不允许：

```text
input.user_query
metadata.run_id
```

---

## 8. NodeExecutor 接口协议

后端 Runtime 应为每种节点实现对应 NodeExecutor。

统一接口：

```python
class NodeExecutor:
    def execute(self, node, node_input, resolved_config, state, context):
        pass
```

参数说明：

```text
node         当前节点完整定义
node_input   根据 input_mapping 解析后的节点输入
resolved_config 根据 node_input + State 解析后的节点配置
state        当前工作流 State
context      执行上下文，例如 run_id、user_id、logger、secrets
```

返回：

```text
node_output  节点执行结果，必须是 JSON-serializable 对象
```

示例：

```json
{
  "answer": "模型回答内容"
}
```

---

## 9. 节点执行生命周期

每个节点执行应遵循以下生命周期：

```text
1. validate_node_config
2. resolve_input_mapping
3. resolve_node_config
4. create_node_run
5. execute_node
6. validate_node_output
7. apply_output_mapping_or_output_merge
8. update_node_run_success
9. resolve_next_node
```

失败时：

```text
1. catch_error
2. update_node_run_failed
3. apply_retry_policy
4. apply_on_error_policy
5. update_workflow_run_status
```

---

## 10. 节点状态协议

节点运行状态：

```text
pending
running
success
failed
skipped
retrying
```

MVP 第一版必须支持：

```text
running
success
failed
```

---

## 11. 错误协议

节点错误统一格式：

```json
{
  "error_code": "llm_provider_error",
  "error_message": "LLM provider returned 500",
  "error_detail": {},
  "retryable": true
}
```

常见错误类型：

```text
variable_not_found
invalid_config
timeout
llm_provider_error
api_request_error
api_response_error
knowledge_base_error
branch_no_match
output_mapping_error
permission_denied
unknown_error
```

---

## 12. Trace 协议

每个节点运行必须记录 node_run。

基础字段：

```json
{
  "run_id": "run_001",
  "node_id": "llm_001",
  "node_type": "llm",
  "status": "success",
  "input_json": {},
  "output_json": {},
  "error_message": null,
  "started_at": "2026-01-01T10:00:00Z",
  "ended_at": "2026-01-01T10:00:02Z",
  "duration_ms": 2000,
  "metadata_json": {}
}
```

LLM Node Trace 扩展：

```json
{
  "metadata_json": {
    "model": "gpt-4.1-mini",
    "prompt_tokens": 1000,
    "completion_tokens": 300,
    "total_tokens": 1300,
    "estimated_cost": 0.01
  }
}
```

API Node Trace 扩展：

```json
{
  "metadata_json": {
    "method": "POST",
    "url": "https://api.example.com/search",
    "status_code": 200,
    "duration_ms": 420
  }
}
```

Knowledge Base Node Trace 扩展：

```json
{
  "metadata_json": {
    "knowledge_base_ids": [101],
    "top_k": 5,
    "returned_chunks": 4
  }
}
```

---

# 13. MVP 节点 Schema

## 13.1 Start Node

用途：工作流开始节点。

规则：

```text
一个 workflow 必须且只能有一个 Start Node
Start Node 不执行业务逻辑
Start Node 只能有出边，不能有入边
```

结构：

```json
{
  "id": "start_1",
  "type": "start",
  "name": "开始",
  "position": { "x": 100, "y": 100 },
  "config": {}
}
```

---

## 13.2 End Node

用途：工作流结束节点。

规则：

```text
End Node 不执行业务逻辑
执行到 End Node 后 workflow_run 标记为 completed
End Node 只能有入边，不能有出边
```

结构：

```json
{
  "id": "end_1",
  "type": "end",
  "name": "结束",
  "position": { "x": 800, "y": 100 },
  "config": {}
}
```

---

## 13.3 Input Node

用途：定义工作流输入字段。

配置：

```json
{
  "fields": [
    {
      "name": "user_query",
      "type": "string",
      "label": "用户问题",
      "required": true,
      "default": ""
    }
  ]
}
```

完整节点示例：

```json
{
  "id": "input_1",
  "type": "input",
  "name": "用户输入",
  "position": { "x": 200, "y": 100 },
  "config": {
    "fields": [
      {
        "name": "user_query",
        "type": "string",
        "label": "用户问题",
        "required": true
      }
    ]
  },
  "output_mapping": {
    "user_query": "variables.user_query"
  }
}
```

说明：

MVP 中，工作流初始 input 已经由运行接口传入。Input Node 可以用于校验和声明输入字段，也可以把 input 字段复制到 variables 中，方便后续节点使用。

---

## 13.4 LLM Node

用途：调用大模型。

config schema：

```json
{
  "provider": "openai",
  "model": "gpt-4.1-mini",
  "system_prompt": "你是一个专业助手",
  "user_prompt": "请回答：{{question}}",
  "temperature": 0.3,
  "max_tokens": 2000,
  "response_format": "text"
}
```

完整节点示例：

```json
{
  "id": "llm_1",
  "type": "llm",
  "name": "生成回答",
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
    "system_prompt": "你是一个客服助手，请根据资料回答用户问题。",
    "user_prompt": "问题：{{question}}\n资料：{{context}}",
    "temperature": 0.3,
    "max_tokens": 1000,
    "response_format": "text"
  },
  "retry": {
    "max_attempts": 2,
    "backoff": "exponential",
    "retry_on": ["timeout", "rate_limit", "llm_provider_error"]
  },
  "timeout": 60
}
```

NodeExecutor 输出：

```json
{
  "answer": "这里是模型生成的回答。",
  "usage": {
    "prompt_tokens": 1000,
    "completion_tokens": 300,
    "total_tokens": 1300
  }
}
```

MVP 要求：

```text
支持 system_prompt 和 user_prompt
支持变量插值
支持文本输出
记录 token usage
```

---

## 13.5 Knowledge Base Node

用途：检索知识库。

config schema：

```json
{
  "knowledge_base_ids": [101],
  "query": "{{question}}",
  "retrieval_mode": "vector",
  "top_k": 5,
  "score_threshold": 0.65,
  "context_budget_tokens": 3000
}
```

完整节点示例：

```json
{
  "id": "kb_1",
  "type": "knowledge_base",
  "name": "检索知识库",
  "input_mapping": {
    "question": "{{input.user_query}}"
  },
  "output_mapping": {
    "chunks": "variables.kb_context"
  },
  "config": {
    "knowledge_base_ids": [101],
    "query": "{{question}}",
    "retrieval_mode": "vector",
    "top_k": 5,
    "score_threshold": 0.65,
    "context_budget_tokens": 3000
  },
  "timeout": 30
}
```

`knowledge_base_ids` 必须使用 `knowledge_bases.id` 的数字主键数组，不允许使用字符串 slug。

NodeExecutor 输出：

```json
{
  "chunks": [
    {
      "chunk_id": "chunk_001",
      "content": "相关文档内容...",
      "score": 0.86,
      "source": {
        "document_id": "doc_001",
        "file_name": "产品手册.pdf",
        "page_start": 3,
        "page_end": 3,
        "section_title": "退款规则"
      }
    }
  ]
}
```

MVP 要求：

```text
支持选择一个或多个知识库
支持 top_k
支持 score_threshold
返回 chunk 内容和来源信息
```

---

## 13.6 Intent Recognition Node

用途：识别用户意图。

config schema：

```json
{
  "model": "gpt-4.1-mini",
  "intents": [
    {
      "name": "refund_request",
      "description": "用户申请退款"
    },
    {
      "name": "general_question",
      "description": "普通咨询问题"
    }
  ],
  "fallback_intent": "general_question"
}
```

Branch Node 与 edges 的关系是发布前强约束：

```text
branches[].target 必须存在于 graph.nodes
default 分支的 target 也必须存在
每个 branches[].target 必须有对应 edge：edge.source = Branch 节点 id，edge.target = target
Branch 节点的所有出边都必须能映射回某个 branches[].target
同一 target 可以被多个 branch 复用，对应一条 edge 即可
```

完整节点示例：

```json
{
  "id": "intent_1",
  "type": "intent",
  "name": "识别意图",
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
        "description": "用户申请退款"
      },
      {
        "name": "query_order",
        "description": "查询订单状态"
      },
      {
        "name": "general_question",
        "description": "普通咨询问题"
      }
    ],
    "fallback_intent": "general_question"
  },
  "timeout": 30
}
```

NodeExecutor 输出：

```json
{
  "intent": "refund_request",
  "confidence": 0.92
}
```

---

## 13.7 Branch Node

用途：根据条件选择下一条路径。

Branch Node 可以不写入 State，只决定下一节点。

config schema：

```json
{
  "branches": [
    {
      "id": "branch_refund",
      "condition": {
        "left": "{{variables.intent_result.intent}}",
        "operator": "eq",
        "right": "refund_request"
      },
      "target": "refund_node_1"
    },
    {
      "id": "branch_default",
      "condition": "default",
      "target": "general_node_1"
    }
  ]
}
```

支持操作符：

```text
eq          等于
neq         不等于
contains    包含
gt          大于
gte         大于等于
lt          小于
lte         小于等于
exists      存在
not_exists  不存在
```

完整节点示例：

```json
{
  "id": "branch_1",
  "type": "branch",
  "name": "意图分支",
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
        "id": "branch_general",
        "condition": "default",
        "target": "llm_general_1"
      }
    ]
  }
}
```

NodeExecutor 输出：

```json
{
  "selected_branch_id": "branch_refund",
  "target": "llm_refund_1"
}
```

Runtime 规则：

```text
Branch Node 的下一节点由 selected target 决定
如果没有匹配分支且没有 default，节点失败
```

---

## 13.8 API Node

用途：调用 HTTP API。

config schema：

```json
{
  "method": "POST",
  "url": "https://api.example.com/search",
  "headers": {
    "Content-Type": "application/json"
  },
  "query_params": {},
  "body": {},
  "response_path": "data",
  "timeout": 30
}
```

完整节点示例：

```json
{
  "id": "api_1",
  "type": "api",
  "name": "查询订单",
  "input_mapping": {
    "order_id": "{{variables.order_id}}"
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
    "body": {
      "order_id": "{{order_id}}"
    },
    "response_path": "data",
    "timeout": 30
  },
  "retry": {
    "max_attempts": 2,
    "backoff": "fixed",
    "retry_on": ["timeout", "network_error"]
  },
  "timeout": 30
}
```

NodeExecutor 输出：

```json
{
  "response": {
    "status": "paid",
    "amount": 199
  },
  "status_code": 200
}
```

安全要求：

```text
不允许前端直接暴露 secret value
headers 和 body 支持变量引用
请求必须有超时
响应体大小需要限制
```

---

## 13.9 Message Node

用途：生成消息。

config schema：

```json
{
  "message_type": "text",
  "template": "{{variables.answer}}"
}
```

完整节点示例：

```json
{
  "id": "message_1",
  "type": "message",
  "name": "回复用户",
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
}
```

NodeExecutor 输出：

```json
{
  "message": {
    "type": "text",
    "content": "这里是回复内容。"
  }
}
```

---

## 13.10 Output Node

用途：生成最终输出。

config schema：

```json
{
  "outputs": {
    "answer": "{{variables.answer}}",
    "sources": "{{variables.kb_context}}"
  }
}
```

完整节点示例：

```json
{
  "id": "output_1",
  "type": "output",
  "name": "最终输出",
  "config": {
    "outputs": {
      "answer": "{{variables.answer}}",
      "sources": "{{variables.kb_context}}"
    }
  }
}
```

NodeExecutor 输出：

```json
{
  "outputs": {
    "answer": "最终回答",
    "sources": []
  }
}
```

Output Node 的 NodeExecutor 返回 `node_output.outputs`，通常直接来自 `resolved_config.outputs`。Runtime 将 `node_output.outputs` merge 到 `state.outputs`。Output Node 不使用 `output_mapping`。

---

# 14. Graph 校验规则

发布工作流前必须校验 Graph。

MVP 校验规则：

```text
必须有且只有一个 Start Node
必须至少有一个 End Node
所有 node id 唯一
所有 edge id 唯一
edge.source 必须存在
edge.target 必须存在
除 Start Node 外，业务节点必须可从 Start Node 到达
End Node 不能有出边
Start Node 不能有入边
Branch Node 的 target 必须存在
不能存在明显孤立节点，除非 disabled
```

MVP 可以暂不校验复杂循环，因为第一版不支持循环。

---

# 15. 前端表单渲染协议

前端可以根据 node type 渲染不同配置表单。

建议每类节点维护一个表单 schema：

```json
{
  "type": "llm",
  "fields": [
    {
      "name": "config.model",
      "label": "模型",
      "component": "select",
      "required": true
    },
    {
      "name": "config.system_prompt",
      "label": "System Prompt",
      "component": "textarea",
      "required": false
    },
    {
      "name": "config.user_prompt",
      "label": "User Prompt",
      "component": "textarea",
      "required": true
    }
  ]
}
```

前端配置面板至少包含：

```text
基础信息：name、description
输入映射：input_mapping
输出映射：output_mapping
节点配置：config
重试设置：retry
超时设置：timeout
错误处理：on_error
```

MVP 可以先隐藏高级项，只展示常用配置。

---

# 16. 后端校验协议

后端在以下时机校验节点：

```text
保存草稿时：弱校验，允许部分配置缺失
发布版本时：强校验，必须完整可运行
运行工作流时：再次校验已发布版本
```

弱校验：

```text
node id 唯一
node type 合法
graph JSON 格式合法
```

强校验：

```text
所有必填 config 存在
input_mapping 引用路径合法，尽可能静态检查
output_mapping 写入路径合法
Graph 连通性合法
Branch target 合法
Start / End 合法
```

---

# 17. 版本兼容策略

Graph JSON 应包含协议版本。

示例：

```json
{
  "schema_version": "1.0",
  "nodes": [],
  "edges": []
}
```

后续升级节点协议时：

```text
新增字段必须向后兼容
废弃字段保留一段兼容期
Runtime 根据 schema_version 选择解析逻辑
发布后的 workflow_version 不直接修改
```

---

# 18. 示例完整工作流

## 18.1 知识库问答工作流

```json
{
  "schema_version": "1.0",
  "nodes": [
    {
      "id": "start_1",
      "type": "start",
      "name": "开始",
      "position": { "x": 100, "y": 100 },
      "config": {}
    },
    {
      "id": "input_1",
      "type": "input",
      "name": "用户输入",
      "position": { "x": 250, "y": 100 },
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
      "name": "检索知识库",
      "position": { "x": 400, "y": 100 },
      "input_mapping": {
        "question": "{{input.user_query}}"
      },
      "output_mapping": {
        "chunks": "variables.kb_context"
      },
      "config": {
        "knowledge_base_ids": [101],
        "query": "{{question}}",
        "retrieval_mode": "vector",
        "top_k": 5,
        "score_threshold": 0.65,
        "context_budget_tokens": 3000
      }
    },
    {
      "id": "llm_1",
      "type": "llm",
      "name": "生成回答",
      "position": { "x": 550, "y": 100 },
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
        "system_prompt": "你是一个知识库问答助手。请只基于给定资料回答。",
        "user_prompt": "问题：{{question}}\n资料：{{context}}",
        "temperature": 0.2,
        "max_tokens": 1000,
        "response_format": "text"
      }
    },
    {
      "id": "output_1",
      "type": "output",
      "name": "最终输出",
      "position": { "x": 700, "y": 100 },
      "config": {
        "outputs": {
          "answer": "{{variables.answer}}",
          "sources": "{{variables.kb_context}}"
        }
      }
    },
    {
      "id": "end_1",
      "type": "end",
      "name": "结束",
      "position": { "x": 850, "y": 100 },
      "config": {}
    }
  ],
  "edges": [
    { "id": "e1", "source": "start_1", "target": "input_1" },
    { "id": "e2", "source": "input_1", "target": "kb_1" },
    { "id": "e3", "source": "kb_1", "target": "llm_1" },
    { "id": "e4", "source": "llm_1", "target": "output_1" },
    { "id": "e5", "source": "output_1", "target": "end_1" }
  ]
}
```

---

# 19. MVP 实现优先级

节点协议相关实现顺序：

```text
1. 定义 Node 基础 TypeScript / Python 类型
2. 定义 Workflow Graph 类型
3. 实现变量解析器
4. 实现 input_mapping 解析
5. 实现 output_mapping 写回
6. 实现 Start / End / Input / Output Node
7. 实现 LLM Node
8. 实现 Knowledge Base Node
9. 实现 Intent Node
10. 实现 Branch Node
11. 实现 API Node
12. 实现 Message Node
13. 补充 Graph 发布校验
14. 补充 Trace 元数据
```

---

# 20. 结论

节点协议是 Agent 工作流平台的核心工程契约。

MVP 阶段应优先稳定以下内容：

```text
Node 基础结构
State 结构
input_mapping
output_mapping
变量引用语法
Trace 协议
Graph 校验规则
MVP 节点 config schema
```

只要节点协议稳定，后续新增 Memory Node、Database Node、Info Collection Node、Code Node、Loop Node、Human Approval Node 都可以作为增量扩展，不需要重写 Runtime。
