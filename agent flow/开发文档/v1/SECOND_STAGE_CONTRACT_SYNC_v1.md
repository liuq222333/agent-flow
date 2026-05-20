# Agent Flow 第二阶段实现同步与接口契约 v1

本文档记录第二阶段已完成开发内容和当前实现契约，用于同步代码、接口、错误码、测试验收和后续开发任务。

同步时间：2026-05-19

## 1. 本轮已完成范围

本轮同步覆盖以下第二阶段任务：

- R2 Runtime 模块拆分第一轮。
- R3 Ops 失败运行列表和单条恢复。
- R4 Secret 脱敏与 generated workflow 路径边界测试。
- R5 DeepSeek / LLM 稳定错误码、metadata 和脱敏。
- R6 新增节点能力第一轮。
- API Node 生产化小步增强。
- Human Approval 最小暂停/恢复契约。
- Human Approval 当前运行面板 approve/reject 操作。
- Human Approval 最小审批中心。
- 前端 Trace 错误提示映射。

未覆盖：

- 完整登录、组织、多租户权限。

## 2. Runtime 契约同步

### 2.1 新增模块

新增后端模块：

```text
backend/app/services/generated_runtime.py
```

该模块负责 generated workflow 本地代码加载相关能力：

- `load_generated_workflow`
- `resolve_code_path`
- `is_generated_workflow_path`
- `sha256_file`
- `relative_project_path`

`backend/app/services/runtime.py` 保留原有对外运行函数，内部将 generated workflow 加载委托给 `generated_runtime.py`。

### 2.2 本地代码路径约束

运行时只允许加载 `backend/generated_workflows/` 下的 `workflow.py`。

以下路径必须被拒绝：

- `backend/generated_workflows/../outside.py`
- `backend/generated_workflows_evil/workflow.py`
- 任意 resolved path 不在 generated root 下的文件。

拒绝时使用错误码：

```text
workflow_code_missing
```

### 2.3 Generated Workflow 错误码

当前 generated workflow 运行错误码：

| 错误码 | 触发条件 | 是否阻止运行 |
| --- | --- | --- |
| `workflow_code_missing` | `code_path` 为空、文件不存在、路径越界 | 是 |
| `workflow_code_import_failed` | `workflow.py` 导入失败、语法错误、依赖错误 | 是 |
| `workflow_entrypoint_missing` | 没有 `async def run(input_data, context)` | 是 |

本地文件 hash 与发布 hash 不一致时：

- 不阻止运行。
- 记录 `code_modified=true`。
- 记录 `code_hash_at_run`。

## 3. Ops API 契约同步

### 3.1 已存在并继续保留的接口

```text
GET  /api/v1/ops/workers
GET  /api/v1/ops/queues
GET  /api/v1/ops/queues/workflow_runs/dead
POST /api/v1/ops/queues/workflow_runs/recover
```

### 3.2 新增失败运行列表接口

```text
GET /api/v1/ops/workflow_runs/failed?limit=20
```

响应：

```json
{
  "items": [
    {
      "run_id": 7,
      "workflow_id": 3,
      "workflow_version_id": 5,
      "status": "failed",
      "error_code": "node_error",
      "error_message": "boom",
      "created_at": "2026-05-19T01:00:00Z",
      "updated_at": "2026-05-19T01:02:00Z"
    }
  ],
  "count": 1
}
```

说明：

- 仅返回 `status='failed'` 的 workflow_runs。
- 默认按 `updated_at DESC, id DESC` 排序。
- `limit` 范围：1 到 100。

### 3.3 新增单条运行恢复接口

```text
POST /api/v1/ops/workflow_runs/{run_id}/recover
```

成功恢复响应：

```json
{
  "run_id": 42,
  "status": "pending",
  "recovered": true,
  "reason": "failed",
  "queued": true
}
```

无需恢复响应：

```json
{
  "run_id": 42,
  "status": "completed",
  "recovered": false,
  "reason": "already_completed",
  "queued": false
}
```

当前 `reason` 取值：

| reason | 含义 |
| --- | --- |
| `failed` | failed run 被恢复 |
| `dead_letter` | dead-letter 中存在该 run 的 job |
| `stale` | pending/running run 已过期 |
| `already_completed` | run 已完成，不恢复 |
| `already_running` | run 正常运行中，不恢复 |
| `already_pending` | run 正常 pending 中，不重复入队 |
| `cancelled` | run 已取消，不恢复 |

恢复行为：

- 将可恢复 run 更新为 `pending`。
- 清空 `output_json`。
- 清空 `error_code` 和 `error_message`。
- 将 `state_json` 重置为 `{}`。
- 将 running node_runs 标记为 failed，错误码为 `ops_recovery_reset`。
- 写入 metadata：
  - `ops_recovery_count`
  - `last_ops_recovery_reason`
  - `last_ops_recovered_at_epoch`
- 将 run 重新写入 Redis `workflow_runs` 队列。
- 如果该 run 有 dead-letter job，会从 dead-letter 队列移除对应 job。

幂等规则：

- `completed` 不恢复。
- 正常 `running` 不恢复。
- 正常 `pending` 不重复入队。
- `cancelled` 不恢复。

## 4. DeepSeek / LLM 错误码契约同步

### 4.1 默认模型

当前默认模型方向：

```text
provider = deepseek
model    = deepseek-v4-flash
```

API Key 来源：

```text
DEEPSEEK_API_KEY
```

或 provider/secret 配置解析后的 secret 值。

### 4.2 稳定错误码

| 错误码 | 触发条件 | retryable |
| --- | --- | --- |
| `model_api_key_missing` | 缺少 DeepSeek/OpenAI API Key | false |
| `model_request_failed` | 上游请求失败、HTTP 错误、连接错误、限流等 | 视状态码或异常而定 |
| `model_response_invalid` | 模型响应结构不符合预期 | false |
| `model_timeout` | LLM 节点超时 | true |

说明：

- LLM 缺 key 不再返回通用 `permission_denied`。
- LLM 超时不再返回通用 `timeout`，而是 `model_timeout`。
- LLM provider 上游错误统一归并为 `model_request_failed`。

### 4.3 node_runs metadata

LLM 节点成功时，`node_runs.metadata_json` 应包含：

- `provider`
- `model`
- `model_config_id`
- `duration_ms`
- `token_usage`

LLM 节点失败时，`node_runs.metadata_json` 应包含：

- `provider`
- `model`
- `model_config_id`
- `duration_ms`
- `retryable`
- `will_retry`
- `error_detail`

### 4.4 脱敏规则

以下内容不能出现在错误消息、trace、node_runs metadata、last_error 中：

- 明文 API Key。
- `sk-...` 形式 token。
- `Authorization: Bearer ...`。
- `api_key`、`x-api-key`、`token`、`secret`、`password` 等敏感字段值。

脱敏后使用：

```text
***
```

## 5. Secret 安全契约同步

Secret API 响应只返回 metadata，不返回明文值或密文值。

以下字段不能出现在 Secret API 响应中：

- `value`
- `encrypted_value`

覆盖范围：

- `POST /api/v1/secrets`
- `GET /api/v1/secrets`
- `PUT /api/v1/secrets/{secret_id}`

审计日志 detail 中也不能包含 Secret 明文。

当前审计 detail 示例：

```json
{
  "secret_key": "openai_api_key",
  "status": "active",
  "rotated": true
}
```

## 6. 前端契约同步

### 6.1 Ops 页面

Ops 页面新增：

- failed workflow_runs 数量。
- failed workflow_runs 列表。
- 单条 run 恢复按钮。

前端调用接口：

```text
GET  /api/v1/ops/workflow_runs/failed?limit=20
POST /api/v1/ops/workflow_runs/{run_id}/recover
```

### 6.2 Trace 错误提示

前端 Trace 保留原始错误码，同时显示中文诊断提示。

当前提示映射：

| 错误码 | 前端提示 |
| --- | --- |
| `model_api_key_missing` | 模型 API Key 未配置，请检查环境变量或 Secret 引用。 |
| `model_request_failed` | 模型请求失败，请检查模型服务、网络或 provider 配置。 |
| `model_response_invalid` | 模型响应格式异常，请查看节点 trace 中的 provider/model 信息。 |
| `model_timeout` | 模型请求超时，请调大节点超时时间或稍后重试。 |
| `workflow_code_missing` | 本地 workflow.py 缺失，请重新发布或恢复生成代码。 |
| `workflow_code_import_failed` | 本地 workflow.py 导入失败，请检查语法和依赖。 |
| `workflow_entrypoint_missing` | 本地 workflow.py 缺少 async run(input_data, context) 入口。 |

## 7. 新增节点契约同步

### 7.1 Set Variable Node

本轮新增首个第二阶段扩展节点：

```text
set_variable
```

用途：

- 将输入、节点输出、模板值整理写入 `variables.*`。
- 用于在 LLM、API、Knowledge、Branch 之间做轻量数据整理。
- 不引入数据库迁移，不引入等待态。

配置契约：

```json
{
  "assignments": {
    "normalized_query": "{{input.user_query}}",
    "customer.id": "{{input.customer_id}}",
    "variables.answer": "{{outputs.llm_1.answer}}"
  }
}
```

也支持数组形式：

```json
{
  "assignments": [
    { "name": "normalized_query", "value": "{{input.user_query}}" },
    { "target": "variables.customer.id", "value": "{{input.customer_id}}" }
  ]
}
```

运行输出：

```json
{
  "values": {
    "normalized_query": "用户输入",
    "customer.id": "c_001"
  },
  "count": 2
}
```

运行行为：

- `assignments` 对象 key 没有 `variables.` 前缀时，自动写入 `variables.<key>`。
- `assignments` 数组项必须包含 `name` 或 `target`。
- 值会按现有 placeholder 规则解析。
- 节点成功后会产生 `node_runs` 记录。

前端支持：

- 节点库新增“变量赋值”。
- 节点配置面板支持编辑 assignments。
- 画布节点和引用弹窗拥有独立颜色。

后端支持：

- `GET /api/v1/node-types` 返回 `set_variable`。
- `GET /api/v1/node-types/set_variable/schema` 返回配置 schema。
- Graph validation 支持 publish/run 校验。
- Runtime 支持执行并写入 `state.variables`。

错误码：

| 错误码 | 触发条件 |
| --- | --- |
| `invalid_config` | assignments 不是对象/数组，或数组项缺少 name/target |

### 7.2 API Node 配置增强

本轮补齐 API Node 的小步生产化配置，不改变现有节点类型：

```text
api
```

新增或明确的配置字段：

| 字段 | 说明 |
| --- | --- |
| `mode` | `mock` 或 `http`，默认 `mock` |
| `query_params` | HTTP query 参数，支持 placeholder 解析和敏感字段脱敏 |
| `response_path` | 从响应 JSON 中提取指定路径，例如 `data.result` |
| `max_response_bytes` | 响应大小上限，默认 `1048576`，最大 `5242880` |
| `fail_on_http_error` | HTTP 非成功状态码是否让节点失败，默认 true |
| `fail_on_request_error` | 网络或请求异常是否让节点失败，默认 true |
| `success_status_codes` | 自定义成功状态码列表 |

运行行为：

- `mode=http` 继续阻止 localhost、private network、link-local、reserved、unspecified 等地址。
- HTTP 响应体超过 `max_response_bytes` 时返回 `response_too_large`。
- `response_path` 不存在时返回 `api_response_error`。
- 前端 API 节点配置面板现在可编辑 headers、query params、body、mock response、response path、响应大小和失败策略。

新增或补充错误码：

| 错误码 | 触发条件 |
| --- | --- |
| `response_too_large` | HTTP 响应体超过 `max_response_bytes` |
| `api_response_error` | HTTP 状态码失败或 `response_path` 不存在 |
| `invalid_config` | API Node 配置值类型或范围不合法 |

### 7.3 Human Approval 最小暂停/恢复契约

本轮新增 Human Approval 的最小暂停/恢复模型：运行到审批节点时暂停，提交审批后重新入队并从 checkpoint 继续。

新增迁移：

```text
006_human_approval_tasks.sql
007_human_approval_node_status.sql
```

新增 run 状态：

```text
waiting_approval
```

新增表：

```text
human_approval_tasks
```

核心字段：

| 字段 | 说明 |
| --- | --- |
| `workflow_id` | 所属 workflow |
| `run_id` | 所属 workflow run |
| `node_id` / `node_name` | 触发审批的节点 |
| `title` / `description` | 给审批人的标题和描述 |
| `status` | `pending/approved/rejected/cancelled/expired` |
| `decision` | `approve/reject` |
| `input_json` | 审批上下文 |
| `response_json` | 审批提交内容 |
| `metadata_json` | 扩展信息 |

新增 API：

```text
GET  /api/v1/human-approval-tasks
GET  /api/v1/human-approval-tasks/{task_id}
POST /api/v1/human-approval-tasks/{task_id}/submit
POST /api/v1/human-approval-tasks/{task_id}/cancel
```

提交请求：

```json
{
  "decision": "approve",
  "response": {"approved": true},
  "comment": "ok"
}
```

取消请求：

```json
{
  "reason": "不再需要人工审批"
}
```

当前行为：

- 提交审批会把 task 标记为 `approved` 或 `rejected`。
- 审计日志记录 `human_approval.submit`。
- 取消 pending 审批会把 task 标记为 `cancelled`，审计日志记录 `human_approval.cancel`。
- 如果取消时对应 run 仍处于 `waiting_approval`，后端会同步把该 run 标记为 `cancelled`，清理等待审批 metadata，并在 state outputs 中写入取消结果。
- `create_human_approval_task` helper 会把 run 标记为 `waiting_approval`。
- Workflow 图已允许 `human_approval` 节点，Runtime 执行到该节点会创建审批任务、标记 node_run 为 `waiting_approval`，并停止继续执行后续节点。
- 提交审批会把审批输出写入 `workflow_runs.state_json.outputs[approval_node_id]`。
- 提交审批会把 run 改回 `pending`，重新推入 workflow worker 队列。
- Worker 恢复时会从 `state_json.metadata.waiting_approval.next_node_id` 继续执行，并清理等待 checkpoint。
- 前端节点库已提供“人工审批”节点和基础配置项。
- 前端运行面板在当前 trace 为 `waiting_approval` 时，会查询 pending `human_approval_tasks`，展示审批上下文，并允许填写 `response/comment` 后提交同意或拒绝。
- 审批提交后，前端会轮询该 run 直到进入完成、失败、取消或下一次等待审批状态，再刷新 trace 和最近运行列表。
- 前端 `Approvals` 页面会调用同一组 Human Approval API，支持 `pending/approved/rejected/cancelled/expired/all` 筛选；pending 任务可填写 `response/comment` 并单条或批量提交同意、拒绝或取消。
- 从 `Approvals` 页面提交审批后不强制等待 worker 完成，提交成功后刷新任务列表，避免审批中心被长轮询阻塞。
- Submit API 返回中记录 `resume_supported=true`、`resume_enqueued=true`。
- `scripts/migrate-db.ps1` 已加入 `006_human_approval_tasks.sql` 和 `007_human_approval_node_status.sql`，并兼容读取已归档到 `开发文档/v0` 的旧迁移文件。

## 8. 当前测试基线

本轮同步对应的验证结果：

```powershell
cd "D:\xm\agent flow\agent flow\backend"
.\.venv\Scripts\python.exe -m pytest
# 129 passed

.\.venv\Scripts\python.exe -m ruff check app tests
# All checks passed

cd "D:\xm\agent flow\agent flow\frontend"
npm run lint
# passed

npm run typecheck
# passed

npm run build
# passed
```

`git diff --check` 结果：

- 无空白错误。
- 仅有 Windows 工作区 CRLF/LF 提示。

## 9. 当前完成状态

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| R1 版本与代码产物体验 | 部分完成 | 已有版本/代码展示和 Trace code metadata，后续可继续打磨 UI |
| R2 Runtime 模块拆分 | 已完成第一轮 | generated workflow 加载已拆到 `generated_runtime.py` |
| R3 Ops 恢复闭环 | 已完成第一轮 | 失败列表、dead queue、单条恢复、队列恢复已具备 |
| R4 安全最小闭环 | 已完成第一轮 | Secret 脱敏、路径边界、模型错误脱敏已有测试 |
| R5 DeepSeek 产品化 | 已完成第一轮 | 默认模型、稳定错误码、metadata、脱敏已具备 |
| R6 新增节点能力 | 已完成第六轮 | 已新增 `set_variable` 节点、API Node 小步生产化配置、Human Approval 最小暂停/恢复契约、运行面板审批操作和最小审批中心 |
| R8 文档同步 | 进行中 | 本文档为第一轮实现同步 |

## 10. 后续文档待补

本轮已同步：

- `开发文档/v0/openapi_agent_workflow_platform_mvp_v1.yaml`
  - 新增 `GET /ops/workflow_runs/failed`
  - 新增 `POST /ops/workflow_runs/{run_id}/recover`
  - 新增 Ops failed/recovery response schemas
  - 补充稳定错误码说明

建议下一步继续补：

- Runtime 细节文档补 `generated_runtime.py` 模块职责。
- API 设计文档补 `workflow_runs/{run_id}/recover`。
- Testing 文档补 118 个后端测试和前端 build 验收基线。
- Node Protocol 文档准备 R6 新节点协议。

## 11. 结论

第二阶段当前已经从“可运行”推进到“可排障、可恢复、可脱敏、可定位模型错误”的状态。

下一步建议优先级：

1. 补 OpenAPI / API 设计文档。
2. 继续推进 R6 新增节点协议，下一轮可评估 Human Approval 权限/超时处理或 HTTP Node 增强。
3. 针对版本代码面板和审批面板继续做 UI 验收和轻量优化。
