# Agent Flow 第二阶段普通节点协议 v1

本文档沉淀普通 Agent 工作流节点协议，用于约束前端编辑器、`GET /api/v1/node-types` schema、Graph validation、Runtime executor、Trace、测试和 smoke。

同步时间：2026-05-20

## 1. 范围与边界

本协议覆盖普通 Agent 工作流主线节点：

```text
start
input
llm
intent
branch
api
message
set_variable
output
end
```

`human_approval` 已完成 MVP：可创建待审批任务、暂停 run、提交后恢复、取消 pending 审批。第二阶段后续暂停扩展审批权限、多人审批、超时通知和复杂审批流；新增工作优先回到普通 Agent 节点协议、发布、运行、Trace 和排障。

`knowledge_base` 已存在于实现中，但本文件先聚焦用户指定的普通 Agent 节点集合；知识库节点继续遵守同一基础协议，细节以现有实现和后续知识库专项文档为准。

## 2. 节点统一结构

所有节点保存到 `workflow_versions.graph_json.nodes[]` 时必须遵守统一结构：

```json
{
  "id": "llm_1",
  "type": "llm",
  "name": "生成回答",
  "description": "可选说明",
  "position": { "x": 320, "y": 120 },
  "config": {},
  "input_mapping": {},
  "output_mapping": {},
  "retry": {
    "max_attempts": 1,
    "backoff": "none",
    "retry_on": []
  },
  "timeout": 60,
  "on_error": {
    "strategy": "fail_workflow"
  },
  "enabled": true
}
```

字段约定：

| 字段 | 要求 |
| --- | --- |
| `id` | 同一 workflow version 内唯一，发布后不可变 |
| `type` | 必须是已注册节点类型 |
| `name` | 前端展示名，Trace 中保留 |
| `position` | 前端画布坐标，不参与 Runtime 语义 |
| `config` | 节点类型专属配置，必须有 JSON Schema |
| `input_mapping` | 从 State 解析为 `node_input` |
| `output_mapping` | 将 `node_output` 写回 State |
| `retry` | 节点级重试策略 |
| `timeout` | 节点级超时，单位秒 |
| `on_error` | `fail_workflow`、`skip_node`、`go_to_node` |
| `enabled` | 草稿可用；发布版本不应包含 disabled 节点 |

## 3. State 与变量解析

Runtime State 基础结构：

```json
{
  "input": {},
  "variables": {},
  "messages": [],
  "outputs": {},
  "metadata": {
    "workflow_id": 1,
    "version_id": 2,
    "run_id": 3
  },
  "path": [],
  "final_output": {}
}
```

变量引用使用 `{{path.to.value}}`：

| 根路径 | 用途 |
| --- | --- |
| `input` | 运行入参 |
| `variables` | 节点间共享变量 |
| `messages` | 消息数组 |
| `outputs` | 按节点输出或显式 output_mapping 写入的输出 |
| `metadata` | run/workflow/version 等运行元信息 |
| `node_input` | config 解析时可显式引用当前节点输入 |
| `secrets` | 仅 API 请求配置服务端解析，Trace 必须脱敏 |

解析规则：

- `input_mapping` 先解析，结果写入 `node_run.input_json`。
- 非 API 节点的 `config` 在执行前使用 State + `node_input` 解析。
- API 节点的请求配置由 API executor 解析，以便支持 `secrets.*` 并生成脱敏 request trace。
- 整个字段为单个变量引用时保留原始类型；嵌入字符串时转为字符串。
- 缺失变量返回 `variable_not_found`。

## 4. output_mapping 规则

`output_mapping` 的 key 对应 `node_output` 字段，value 是写入 State 的目标路径。

允许写入：

```text
variables.*
outputs
outputs.*
messages
```

禁止写入：

```text
input.*
metadata.*
```

默认行为：

- 每个节点成功后，Runtime 应至少把节点输出保存在 `state.outputs[node_id]`。
- 显式 `output_mapping` 再把指定字段写入 `variables`、`outputs` 或 `messages`。
- `output` 节点的 `config.outputs` 生成最终输出，写入 `state.final_output`。

## 5. Runtime 生命周期

每个普通节点执行必须遵守：

```text
1. 读取节点定义和 schema 约束
2. 解析 input_mapping 得到 node_input
3. 创建 node_runs 记录，status=running
4. 执行对应 Runtime executor
5. 校验 executor 返回 JSON-serializable node_output
6. 写入 state.outputs[node_id]
7. 应用 output_mapping
8. 更新 node_runs 为 success 或 retrying/failed/skipped
9. 根据 edge、branch 结果或 on_error 选择下一节点
```

失败时：

- `node_runs.error_code` 必须使用稳定错误码。
- `node_runs.metadata_json.retryable` 标记是否可重试。
- 将最后错误写入 `state.metadata.last_error`，供错误处理节点引用。
- `fail_workflow` 终止运行；`skip_node` 继续默认下一节点；`go_to_node` 跳转到指定节点。

## 6. Trace 契约

每次节点尝试都必须有 `node_runs`：

```json
{
  "run_id": 100,
  "node_id": "api_1",
  "node_type": "api",
  "node_name": "查询订单",
  "status": "success",
  "attempt": 1,
  "input_json": {},
  "output_json": {},
  "error_code": null,
  "error_message": null,
  "started_at": "2026-05-20T08:00:00Z",
  "ended_at": "2026-05-20T08:00:01Z",
  "duration_ms": 1000,
  "metadata_json": {
    "runtime": "graph_runtime",
    "node_type": "api"
  }
}
```

Trace 必须满足：

- 保留原始 `error_code`，前端只做提示映射，不替换 code。
- `metadata_json.duration_ms` 成功和失败都应写入。
- API/LLM/Secret 相关内容必须脱敏，明文 token 不得出现在 `input_json`、`output_json`、`metadata_json`、`error_message`。
- 重试时每次 attempt 独立记录 node_run，失败 attempt 标为 `retrying` 并记录 `will_retry=true`。

## 7. 稳定错误码

通用错误码：

| 错误码 | 触发条件 | retryable |
| --- | --- | --- |
| `invalid_config` | config 类型、必填字段、范围不合法 | false |
| `variable_not_found` | 变量路径不存在 | false |
| `output_mapping_error` | 输出写回目标非法或源字段不存在 | false |
| `timeout` | 普通节点超时 | true |
| `rate_limit` | 上游返回限流 | true |
| `network_error` | 网络层错误 | true |
| `permission_denied` | secret 或权限资源不可用 | false |
| `unknown_error` | 未归类异常 | false |

LLM 错误码：

| 错误码 | 触发条件 | retryable |
| --- | --- | --- |
| `model_api_key_missing` | 模型 API Key 缺失 | false |
| `model_request_failed` | 模型上游请求失败 | 视异常 |
| `model_response_invalid` | 模型响应结构不符合预期 | false |
| `model_timeout` | LLM 节点超时 | true |

Branch/API 错误码：

| 错误码 | 触发条件 | retryable |
| --- | --- | --- |
| `branch_no_match` | 无条件命中且无 default | false |
| `api_request_error` | API 请求异常 | true |
| `api_response_error` | HTTP 状态失败或 response_path 不存在 | 视状态 |
| `response_too_large` | 响应超过 `max_response_bytes` | false |

## 8. 节点类型契约

### 8.1 Start

用途：声明工作流输入，并作为流程入口。

结构：

```json
{
  "id": "start_1",
  "type": "start",
  "name": "开始",
  "position": { "x": 80, "y": 120 },
  "config": {
    "fields": [
      { "name": "rawQuery", "type": "string", "label": "用户输入", "required": true },
      { "name": "chatHistory", "type": "array", "label": "历史消息" },
      { "name": "fileUrls", "type": "array", "label": "文件 URL" },
      { "name": "fileNames", "type": "array", "label": "文件名" }
    ]
  }
}
```

约定：

| 项 | 约定 |
| --- | --- |
| config schema | `fields[]` 声明输入字段；默认主输入为 `rawQuery` |
| input_mapping | 忽略 |
| output_mapping | 通常为空 |
| runtime output | `{ "started": true, "rawQuery": "...", ... }`；`rawQuery` 兼容读取旧 `user_query` |
| trace metadata | `runtime`、`node_type`、`duration_ms` |
| error code | 理论上不应失败；结构错误归为 `invalid_config` |

Graph 规则：必须且只能有一个；不能有入边；必须有出边。

### 8.2 Input（历史兼容）

用途：历史工作流中声明和校验运行输入字段。新三段式主线改由 Start 节点声明输入。

config schema：

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

约定：

| 项 | 约定 |
| --- | --- |
| input_mapping | 默认读取 `state.input` |
| output_mapping | 可将字段写入 `variables.*` |
| runtime output | `{ "input": state.input }` |
| trace | 记录声明字段和实际输入快照 |
| error code | 字段类型/必填校验失败使用 `invalid_config` 或后续专用 `input_validation_failed` |

### 8.3 LLM

用途：调用模型生成文本或 JSON。

config schema：

```json
{
  "model_config_id": 11,
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "system_prompt": "你是一个严谨、清晰的 AI 助手。",
  "user_prompt": "问题：{{question}}",
  "temperature": 0.3,
  "max_tokens": 1000,
  "response_format": "text"
}
```

示例：

```json
{
  "id": "llm_1",
  "type": "llm",
  "name": "生成回答",
  "input_mapping": {
    "query": "{{input.rawQuery}}",
    "context": "{{variables.kb_context}}"
  },
  "output_mapping": {
    "output": "variables.output",
    "answer": "variables.answer"
  },
  "config": {
    "provider": "deepseek",
    "model": "deepseek-v4-flash",
    "user_prompt": "问题：{{query}}\n资料：{{context}}",
    "temperature": 0.3,
    "max_tokens": 1000
  },
  "timeout": 60
}
```

runtime output：

```json
{
  "output": "模型生成内容",
  "answer": "模型生成内容",
  "reasoning_content": null,
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "model_config_id": 11,
  "prompt": "问题：...",
  "usage": {
    "prompt_tokens": 7,
    "completion_tokens": 5,
    "total_tokens": 12
  }
}
```

`output` 是新主线标准字段；`answer` 为旧工作流兼容字段，短期保留。

Trace 要求：

- `metadata_json.provider`
- `metadata_json.model`
- `metadata_json.model_config_id`
- `metadata_json.token_usage`
- 失败时补 `retryable`、`will_retry`、脱敏 `error_detail`

错误码：`model_api_key_missing`、`model_request_failed`、`model_response_invalid`、`model_timeout`、`invalid_config`。

### 8.4 Intent

用途：识别输入文本意图。

config schema：

```json
{
  "model": "local-mock",
  "provider": "keyword",
  "intents": [
    { "name": "refund_request", "description": "用户申请退款" },
    { "name": "general_question", "description": "普通咨询问题" }
  ],
  "fallback_intent": "general_question"
}
```

约定：

| 项 | 约定 |
| --- | --- |
| input_mapping | 通常包含 `text` 或 `query` |
| output_mapping | `intent` 写入 `variables.intent_result.intent`，`confidence` 写入 `variables.intent_result.confidence` |
| runtime output | `{ "intent": "...", "confidence": 0.9, "provider": "keyword", "query": "..." }` |
| trace | 记录 provider、intent 数量、fallback |
| error code | `invalid_config`、模型调用时沿用 LLM 稳定错误码 |

### 8.5 Branch

用途：根据条件选择下一节点。

config schema：

```json
{
  "branches": [
    {
      "id": "refund",
      "condition": {
        "left": "{{variables.intent_result.intent}}",
        "operator": "eq",
        "right": "refund_request"
      },
      "target": "refund_llm"
    },
    {
      "id": "default",
      "condition": "default",
      "target": "general_llm"
    }
  ]
}
```

支持操作符：

```text
eq
neq
contains
gt
gte
lt
lte
exists
not_exists
```

约定：

| 项 | 约定 |
| --- | --- |
| input_mapping | 可为空，条件直接引用 State |
| output_mapping | 通常为空 |
| runtime output | `{ "selected": "target_node_id" }` |
| trace | 记录 selected target；建议后续补 selected branch id |
| error code | `branch_no_match`、`invalid_config`、`variable_not_found` |

Graph validation：

- 每个 `branches[].target` 必须存在。
- default target 必须存在。
- Branch 节点出边必须和 target 集合一致。

### 8.6 API

用途：调用外部 HTTP API 或 mock API。

config schema：

```json
{
  "mode": "mock",
  "method": "GET",
  "url": "https://api.example.test/orders",
  "headers": {},
  "query_params": {},
  "body": {},
  "mock_response": {},
  "mock_status_code": 200,
  "response_path": "data.result",
  "timeout_seconds": 10,
  "max_response_bytes": 1048576,
  "fail_on_http_error": true,
  "fail_on_request_error": true,
  "success_status_codes": [200]
}
```

约定：

| 项 | 约定 |
| --- | --- |
| input_mapping | 可把上游字段整理为请求参数 |
| output_mapping | 通常 `{ "response": "variables.api_response" }` |
| runtime output | 包含 `mode`、`status`、`status_code`、脱敏 `request`、`response`、`response_path`、`max_response_bytes` |
| trace | request 必须脱敏，保留 status_code/mode/duration |
| error code | `api_request_error`、`api_response_error`、`response_too_large`、`invalid_config`、`permission_denied` |

安全约定：

- `mode=http` 只允许 `http`/`https`。
- 阻止 localhost、private network、link-local、reserved、unspecified、multicast。
- `secrets.*` 只在服务端解析。
- `Authorization`、`api_key`、`x-api-key`、`token`、`secret`、`password` 等字段值一律在 Trace 中显示为 `***`。
- 默认 `mode=mock`，生产 HTTP 调用必须显式配置 `mode=http`。

### 8.7 Message

用途：生成消息对象或文本消息。

config schema：

```json
{
  "message_type": "text",
  "template": "{{variables.answer}}"
}
```

约定：

| 项 | 约定 |
| --- | --- |
| input_mapping | 可将 answer/context 读入 `node_input` |
| output_mapping | 常用 `{ "message": "messages" }` 或 `{ "message": "variables.reply" }` |
| runtime output | 当前实现返回 `{ "message": "文本内容" }` |
| trace | 记录模板解析后的输出，不记录未脱敏 secret |
| error code | `variable_not_found`、`invalid_config` |

### 8.8 Set Variable

用途：整理输入、模板值和节点输出，写入 `variables.*`。

config schema：

```json
{
  "assignments": {
    "normalized_query": "{{input.rawQuery}}",
    "customer.id": "{{input.customer_id}}",
    "variables.answer": "{{outputs.llm_1.output}}"
  }
}
```

也支持数组形式：

```json
{
  "assignments": [
    { "name": "normalized_query", "value": "{{input.rawQuery}}" },
    { "target": "variables.customer.id", "value": "{{input.customer_id}}" }
  ]
}
```

约定：

| 项 | 约定 |
| --- | --- |
| input_mapping | 可为空，assignment value 直接引用 State |
| output_mapping | 可选，常用 `{ "values": "variables.last_set_variables" }` |
| runtime output | `{ "values": { "path": "value" }, "count": 1 }` |
| trace | 记录写入后的 values 和 count |
| error code | `invalid_config`、`variable_not_found` |

写入规则：

- assignment target 无 `variables.` 前缀时自动补齐。
- 实际写入 `state.variables` 时，返回的 `values` key 使用去掉 `variables.` 后的变量路径。
- target 不能为空，且最终必须落在 `variables.*`。

### 8.9 Output（历史兼容）

用途：历史工作流中生成 workflow 最终输出。新三段式主线改由 End 节点生成最终输出。

config schema：

```json
{
  "response_mode": "parameters",
  "outputs": {
    "answer": "{{variables.answer}}",
    "sources": "{{variables.kb_context}}"
  },
  "template": "",
  "output_value_kinds": {
    "answer": "reference",
    "sources": "reference"
  }
}
```

约定：

| 项 | 约定 |
| --- | --- |
| input_mapping | 通常为空 |
| output_mapping | 不需要；由 `config.outputs` 直接生成 final output |
| response_mode | `parameters` 直接返回参数对象；`template` 先解析 `outputs`，再用 `template` 渲染文本 |
| output_value_kinds | 前端辅助字段，标记 `reference/text/number/boolean/json`，Runtime 不依赖它 |
| runtime output | `parameters` 模式为解析后的对象；`template` 模式固定为 `{ "output": "渲染后的文本" }` |
| trace | output_json 等于最终输出 |
| error code | `variable_not_found`、`invalid_config` |

模板模式示例：

```json
{
  "response_mode": "template",
  "outputs": {
    "answer": "{{outputs.llm_1.output}}",
    "intent": "{{variables.intent}}"
  },
  "template": "意图 {{intent}}，回复：{{answer}}"
}
```

Runtime 将该节点输出写入：

```text
state.final_output
state.outputs[output_node_id]
```

### 8.10 End

用途：工作流结束，并在三段式主线中生成最终输出。

结构：

```json
{
  "id": "end_1",
  "type": "end",
  "name": "结束",
  "position": { "x": 980, "y": 120 },
  "config": {
    "response_mode": "parameters",
    "outputs": {
      "output": "{{outputs.llm_1.output}}",
      "rawQuery": "{{outputs.start_1.rawQuery}}"
    },
    "template": "",
    "output_value_kinds": {
      "output": "reference",
      "rawQuery": "reference"
    }
  }
}
```

约定：

| 项 | 约定 |
| --- | --- |
| config schema | 新图支持 `response_mode`、`outputs`、`template`、`output_value_kinds`；旧图存在 Output 节点时允许 `{}` |
| input_mapping | 忽略 |
| output_mapping | 通常为空 |
| response_mode | `parameters` 直接返回参数对象；`template` 渲染 `{ "output": "文本" }` |
| runtime output | 配置最终输出时等于 final output；兼容空配置时为 `{ "completed": true }` |
| trace | 配置输出时 `output_json` 等于最终输出 |
| error code | `variable_not_found`、`invalid_config` |

Graph 规则：必须且只能有一个；不能有出边。没有历史 Output 节点的新图，End 必须配置 `outputs`。

## 9. 前端配置契约

前端新增或维护节点时必须同步：

| 项 | 要求 |
| --- | --- |
| NodeType | `frontend/src/app/workflow-editor/types.ts` 中包含节点 type |
| nodeCatalog | `constants.ts` 中有 label、group、Icon、默认 config、默认 mappings |
| 配置面板 | 可编辑必填 config；复杂字段至少支持 JSON 编辑或专用表单 |
| 引用提示 | 输入/输出 mapping 能用现有引用弹窗或 JSON 编辑 |
| 运行面板 | Trace 能显示 node_run status、input、output、metadata、error_code |
| 错误提示 | 稳定错误码保留，同时可映射中文诊断 |

前端不是 schema 的唯一来源；后端 `GET /api/v1/node-types/{type}/schema` 是发布/运行前强校验的权威参考。

## 10. Runtime executor 契约

每个新增普通节点必须有明确 executor：

```text
backend/app/services/runtime.py
  _execute_node(...) 分派 node_type
  _execute_<type>_node(...) 实现业务逻辑
```

executor 要求：

- 输入：`conn`、`config`、`state`、`node_input`，必要时传入完整 `node`。
- 输出：JSON-serializable dict。
- 不直接修改 `input` 和 `metadata`，除非该节点协议明确允许。
- 如需写 State，优先返回 `node_output` 交给 Runtime 统一 `output_mapping`；`set_variable` 这类数据节点可按协议直接写 `state.variables`。
- 外部请求必须有 timeout、错误码归一、Trace 脱敏。
- 失败抛 `RuntimeNodeError`，不要让底层异常直接穿透到 API 响应。

## 11. 新增节点准入清单

后续新增普通节点必须一次性带齐以下内容，否则不进入主线：

| 检查项 | 最小要求 |
| --- | --- |
| schema | `GET /api/v1/node-types/{type}/schema` 返回 `node_schema`、`config_schema`、`form_schema` |
| 前端配置 | `NodeType`、节点库默认配置、配置面板可编辑必填字段 |
| Runtime executor | `_execute_node` 分派和 executor 实现 |
| Graph validation | 发布时校验必填 config、边关系和节点特有约束 |
| Trace | node_run input/output/metadata/status/error_code 完整 |
| error code | 复用稳定错误码或新增文档化错误码 |
| 测试 | 至少单元测试覆盖 success 和 invalid_config/核心失败路径 |
| smoke | 用户主线 smoke 或脚本能覆盖节点最小可运行路径 |
| 文档 | 更新本协议或新增节点专项文档 |

## 12. 当前实现映射

当前已有实现和测试参考：

| 类型 | 后端 schema | Runtime | 测试 |
| --- | --- | --- | --- |
| node type schema | `backend/app/api/v1/node_types.py` | 不适用 | `backend/tests/test_node_types.py` |
| graph validation | `backend/app/services/graph_validation.py` | 发布/运行前 | `backend/tests/test_graph_validation.py` |
| runtime executor | `backend/app/services/runtime.py` | `_execute_node` | `backend/tests/test_runtime_nodes.py` |
| workflow core smoke | `scripts/smoke_workflow_core.py` | 发布/运行/Trace | `scripts/smoke-workflow-core.ps1` |
| human approval smoke | `scripts/smoke_human_approval.py` | 审批 MVP | `scripts/smoke-human-approval.ps1` |

## 13. 主控注意的契约点

- 普通节点协议以本文件为 v1 基准，审批节点只保留 MVP 状态，不继续扩展旁支。
- `node-types` API 的 schema、前端默认配置和 Runtime executor 必须三方一致。
- `output_mapping` 只允许写 `variables`、`outputs`、`messages`，避免节点污染运行输入和 metadata。
- API/LLM 节点的 Trace 脱敏是硬约束，不能为调试便利输出明文 secret。
- 新增节点必须带 schema、前端配置、Runtime executor、Trace、测试或 smoke，不能只加前端节点。
