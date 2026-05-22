# Agent Flow 第二阶段开发文档 v1

本文档结合最初开发目标、当前项目功能状态和 `开发文档/v0/NEXT_STAGE_DEVELOPMENT_SUMMARY_v0.md`，定义 Agent Flow 第二阶段的开发范围、优先级、技术方案、任务拆分和验收标准。

第二阶段的核心目标不是重新设计系统，而是在当前 MVP 已跑通的基础上，把“前端创建工作流 → 后端发布生成本地代码 → 运行以本地代码为准 → 多工作流多版本稳定隔离”的模式做扎实，并补齐版本体验、运行排障、权限安全和 Runtime 可维护性。

更新时间：2026-05-20

实现同步文档：

- `开发文档/v1/SECOND_STAGE_CONTRACT_SYNC_v1.md`

---

## 1. 背景与最初需求回收

最初的核心需求可以概括为：

```text
前端创建一个工作流后，
后端可以基于 workflow graph 自动生成对应的本地 Python 代码，
实际运行时以本地代码为准。
```

同时明确过几个设计约束：

- 不只会有一个 agent 工作流，会有多个工作流。
- 不引入业务区域、项目空间、folder 或 area 模型。
- 代码生成目录只按 `workflow_id + version` 隔离。
- 生成代码是本地可编辑源码，不是临时缓存。
- 每次发布生成新版本目录，不覆盖旧版本代码。
- 运行时默认 import 本地 `workflow.py`。
- 本地代码 hash 和发布 hash 不一致时只记录 `code_modified=true`，不阻止运行。

当前 MVP 已经实现上述主链路。第二阶段要做的是把它从“功能可跑”推进到“可维护、可排障、可安全试用、可继续扩展节点”的状态。

---

## 2. 当前功能基线

### 2.1 已实现主链路

当前项目已经支持：

- Workflow 创建、保存草稿、校验、发布。
- 发布时生成本地代码：

```text
backend/generated_workflows/
  workflow_000001/
    v000001/
      __init__.py
      workflow.py
      manifest.json
```

- `workflow_versions` 记录：
  - `code_path`
  - `code_hash`
  - `code_generated_at`
- 运行时根据 `workflow_versions.code_path` import 本地 `workflow.py`。
- 同步运行由 API 执行。
- 异步运行通过 Redis 交给 `worker-workflow`。
- 运行写入 `workflow_runs`、`node_runs`、trace 和 code metadata。
- 手动修改 generated `workflow.py` 后，运行记录 `code_modified=true`。
- workflow/document worker heartbeat 已接入 Ops。

### 2.2 已实现节点能力

当前可用节点包括：

- `start`
- `input`
- `llm`
- `knowledge_base`
- `intent`
- `branch`
- `set_variable`
- `api`
- `message`
- `output`
- `end`

其中：

- LLM 默认接入 DeepSeek V4 Flash。
- Knowledge 支持 pgvector 检索和关键词回退。
- API Node 支持 mock、受限 HTTP、query params、response path 和响应大小限制。
- Message Node 支持追加消息并进入输出映射。
- Set Variable Node 支持将输入、模板值或节点输出写入 `variables.*`。
- Trace 支持节点 input/output/error/metadata 展开。

### 2.3 已实现运维能力

当前 Ops 能力：

- `/api/v1/health`
- `/api/v1/ready`
- `/api/v1/metrics`
- `/api/v1/ops/workers`
- `/api/v1/ops/queues`
- `/api/v1/ops/queues/workflow_runs/dead`
- `/api/v1/ops/queues/workflow_runs/recover`
- `/api/v1/ops/workflow_runs/failed`
- `/api/v1/ops/workflow_runs/{run_id}/recover`

已可看到：

- `worker_type=workflow`
- `worker_type=document`
- workflow run 队列深度
- processing queue 深度
- dead-letter 深度
- worker heartbeat
- failed workflow_runs 列表
- 单条 run 恢复结果

### 2.4 已通过的基础验收

当前推荐继续保持以下命令作为每轮开发验收：

```powershell
cd "D:\xm\agent flow\agent flow"
.\scripts\check-acceptance.ps1
.\scripts\smoke-workflow-core.ps1
```

当前已验证：

- 后端测试通过，当前基线为 `141 passed`。
- ruff 通过。
- 前端 typecheck/lint 通过。
- 前端生产构建通过。
- smoke 覆盖 generated workflow、sync/async、Knowledge、Intent/Branch、API/Message、trace 脱敏。
- DeepSeek 真实调用成功，返回 `provider=deepseek`、`model=deepseek-v4-flash` 和 token usage。

当前 R2/R3/R4/R5 第一轮实现状态详见：

```text
开发文档/v1/SECOND_STAGE_CONTRACT_SYNC_v1.md
```

---

## 3. 第二阶段目标

第二阶段目标分为 6 个方向。

### 3.1 目标 A：版本与代码产物体验完整化

让用户清楚知道：

- 当前工作流是否发布。
- 当前运行使用哪个版本。
- 当前版本生成了哪份本地代码。
- 本地代码是否被手动修改。
- 如何查看、重生成和清理 generated workflow code。

### 3.2 目标 B：Runtime 可维护性提升

当前 Runtime 主体功能已可用，但单文件复杂度较高。第二阶段应在不改变行为的前提下逐步拆分：

- mapping
- generated import
- persistence
- errors
- retry
- execution context

目标是为后续新增节点降低风险。

### 3.3 目标 C：运行失败与 Ops 排障体验

用户需要能在 UI 中处理：

- pending 卡住
- worker 不活跃
- dead-letter job
- failed/cancelled run retry
- code missing/import failed/entrypoint missing

### 3.4 目标 D：权限与安全最小闭环

MVP 目前是 mock user。第二阶段至少要让权限路径可测试：

- 多 mock user 或 JWT 接入入口。
- Workflow/Run/Secret/Tool/Knowledge 的基础权限。
- Secret 访问限制。
- 版本代码查看权限。
- API Node 外呼安全策略继续收紧。

### 3.5 目标 E：DeepSeek 与模型配置产品化

DeepSeek 已真实接入，第二阶段需要把模型配置体验做顺：

- provider 测试连接。
- 默认模型可见。
- thinking mode 配置。
- max_tokens/temperature/timeout 配置。
- 缺 key 或 provider 异常时给出清晰错误。

### 3.6 目标 F：为新增节点打基础

第二阶段末尾可以开始新增节点，但前提是：

- Runtime 已拆分到可维护状态。
- Node Protocol 不破坏现有节点。
- 每个新增节点都有 schema、前端配置、Runtime executor、trace 和 smoke。

---

## 4. 第二阶段非目标

第二阶段暂不做：

- 不引入 area/project/folder 模型。
- 不做完整多租户组织系统。
- 不上 Kubernetes。
- 不接企业 KMS。
- 不做完整商业监控告警平台。
- 不做复杂代码沙箱。
- 不把 `backend/generated_workflows/` 重新纳入 Git。
- 不改变“运行以本地 generated workflow code 为准”的基本模式。

---

## 5. 核心架构原则

### 5.1 DB 是发布事实来源

数据库记录工作流版本、graph、代码路径、发布 hash 和发布时间。

`workflow_versions.graph_json` 是发布时不可变 graph。

### 5.2 本地代码是运行事实来源

运行时使用 `workflow_versions.code_path` 指向的本地 `workflow.py`。

如果本地代码被手动修改：

- 继续运行。
- 记录 hash 差异。
- trace 中暴露 `code_modified=true`。

### 5.3 多工作流按 workflow_id + version 隔离

目录约定继续保持：

```text
backend/generated_workflows/
  workflow_000001/
    v000001/
  workflow_000001/
    v000002/
  workflow_000002/
    v000001/
```

不增加 area/project/folder 层级。

### 5.4 每次改动都要保持契约同步

涉及接口、数据库、运行时、前端展示的变更，必须同步：

- OpenAPI
- README
- OPERATIONS
- `开发文档/v1`
- smoke 或测试用例

---

## 6. 第二阶段里程碑

建议分 6 个里程碑推进。

```text
M7 交付基线整理与版本体验
M8 Runtime 模块拆分
M9 Ops 与运行恢复 UI
M10 权限与安全最小闭环
M11 模型与 DeepSeek 产品化
M12 新节点能力预研与首个新增节点
```

---

## 7. M7：交付基线整理与版本体验

### 7.1 目标

把当前项目状态整理成稳定的第二阶段起点，并补齐版本和 generated code 的用户体验。

### 7.2 后端任务

- 确认 `backend/generated_workflows/` 不再被 Git 跟踪。
- 确认 `frontend/tsconfig.tsbuildinfo` 不再被 Git 跟踪。
- 保留 `workflow_versions.code_path/code_hash/code_generated_at`。
- 完善版本代码相关 API 的错误响应：
  - `workflow_code_missing`
  - `workflow_code_invalid_path`
  - `workflow_code_regenerate_blocked`
  - `workflow_code_version_dir_referenced`
- `cleanup generated workflows` API 默认建议走 dry-run。

### 7.3 前端任务

Workflow 编辑器增加或优化：

- 当前工作流发布状态。
- 当前版本号。
- code path 简洁展示。
- code hash 采用可折叠/可复制形式。
- generated at 格式化。
- code status badge：
  - ok
  - modified
  - missing_metadata
  - missing_file
  - invalid_path
- 查看 `workflow.py` 面板。
- regenerate-code 按钮与确认弹窗。
- cleanup generated workflows 管理入口。

### 7.4 文档任务

- 更新 OpenAPI。
- 更新 README。
- 更新 OPERATIONS。
- 将本文件作为第二阶段开发入口。

### 7.5 验收

- 发布 v1 后生成 `workflow_XXXXXX/v000001/workflow.py`。
- 发布 v2 后生成 `workflow_XXXXXX/v000002/workflow.py`，不覆盖 v1。
- UI 可看到 v1/v2 的 code metadata。
- 手动修改 v1 `workflow.py` 后运行 v1，trace 显示 `code_modified=true`。
- regenerate-code 不会在未确认时覆盖手改代码。
- `.\scripts\check-acceptance.ps1` 通过。
- `.\scripts\smoke-workflow-core.ps1` 通过。

---

## 8. M8：Runtime 模块拆分

### 8.1 目标

在不改变行为的前提下降低 `runtime.py` 复杂度，为新增节点和复杂执行策略做准备。

### 8.2 拆分顺序

第一批拆分：

```text
backend/app/services/runtime_mapping.py
backend/app/services/runtime_generated.py
backend/app/services/runtime_persistence.py
backend/app/services/runtime_errors.py
```

建议迁移内容：

| 新模块 | 职责 |
| --- | --- |
| `runtime_mapping.py` | input_mapping、output_mapping、变量解析、path get/set |
| `runtime_generated.py` | generated workflow path resolve、hash、import、entrypoint |
| `runtime_persistence.py` | workflow_runs/node_runs 状态更新、metadata、jsonb stmt |
| `runtime_errors.py` | RuntimeNodeError、错误归一化、retryable 判定 |

第二批拆分：

```text
backend/app/services/runtime_retry.py
backend/app/services/runtime_context.py
backend/app/services/runtime_nodes/
```

### 8.3 约束

- 不重写 Runtime。
- 不改变 API 响应。
- 不改变错误码。
- 不改变 trace 结构。
- 每次拆分保持测试通过。

### 8.4 验收

- 现有后端测试全部通过。
- smoke 通过。
- DeepSeek 最小真实调用仍通过。
- 手改 generated `workflow.py` 后 `code_modified=true` 仍工作。
- `workflow_code_missing/import_failed/entrypoint_missing` 行为不变。

---

## 9. M9：Ops 与运行恢复 UI

### 9.1 目标

将当前后端 Ops 能力转化为用户可操作的排障页面。

### 9.2 前端任务

Ops 页面增强：

- Worker 表格：
  - worker_id
  - worker_type
  - queue_name
  - status
  - current_run_id
  - current_job_id
  - last_seen_at
  - active/stale 标识
- Queue 表格：
  - main depth
  - processing depth
  - dead-letter depth
  - 更新时间
- Dead-letter 面板：
  - 查看 payload
  - 展示 dead_reason
  - 展示 queue_attempt
  - 展示 run_id/job_id
- Recover 按钮：
  - 二次确认
  - 展示 requeued / acked_terminal / skipped_running / invalid_payloads
- Run retry：
  - failed/cancelled run 显示 retry 按钮
  - 可选覆盖 input
  - 可填写 retry reason

### 9.3 后端任务

后端当前已有基础接口，第二阶段可以补充：

- dead-letter 单条操作。
- dead-letter 单条 requeue。
- dead-letter ignore/delete。
- worker stale threshold 参数。
- run retry 与原 run 的关系查询。

### 9.4 验收

- 停止 `worker-workflow` 后，Ops 页面能看到 stale。
- 创建 failed/cancelled run 后，可从 UI retry。
- dead-letter job 可查看。
- recover 后 UI 显示恢复结果。
- `/metrics` 仍能输出 worker 和 queue 指标。

---

## 10. M10：权限与安全最小闭环

### 10.1 目标

为真实用户试用建立安全底线。

### 10.2 任务

认证：

- 保留 mock user。
- 增加多 mock user 测试能力，或接入 JWT 最小入口。
- current_user 不再固定只有 admin 路径。

权限：

- Workflow owner/editor/viewer 基础判断。
- Run 权限继承 workflow。
- Secret 仅 Admin 或 owner 可管理。
- Tool/Knowledge 按 owner 判断。
- 版本代码查看需要 workflow view 权限。
- regenerate-code 需要 workflow edit 权限。

安全：

- API Node 外呼 allowlist。
- Secret 不进入 generated `workflow.py`。
- Trace 不泄露 secret。
- 错误响应不泄露内部路径、密钥、完整堆栈。
- 上传文件大小和类型限制继续保持。

### 10.3 验收

- 非 owner 不能更新 workflow。
- Viewer 不能发布 workflow。
- Viewer 不能创建 Secret。
- 无权限用户不能查看 version code。
- API Node 不能访问 localhost/private/link-local。
- smoke 中敏感 header 仍被脱敏。

---

## 11. M11：模型与 DeepSeek 产品化

### 11.1 目标

让 DeepSeek 和后续模型配置成为可理解、可测试、可排障的产品能力。

### 11.2 后端任务

- Provider test connection API。
- Model config test call API。
- DeepSeek error 分类：
  - missing_api_key
  - provider_auth_failed
  - provider_rate_limited
  - provider_timeout
  - provider_bad_response
- LLM usage 写入 node metadata。
- 支持 provider default timeout / max_tokens / temperature。

### 11.3 前端任务

Models 页面增强：

- DeepSeek 默认模型卡片。
- API key 状态提示，但不展示密钥。
- 测试连接按钮。
- thinking mode 开关。
- max_tokens、temperature、timeout 配置。
- provider 错误展示。

LLM Node 面板增强：

- 默认选择 DeepSeek V4 Flash。
- 可切 mock/deepseek/openai。
- thinking mode 显式开关。
- 缺 key 时运行前提示。

### 11.4 验收

- 未配置 key 时错误清晰。
- 配置 `DEEPSEEK_API_KEY` 后最小 LLM 工作流 completed。
- Trace 中看到 provider/model/usage。
- thinking mode 默认关闭。

---

## 12. M12：新增节点能力预研与首个节点

### 12.1 目标

在 Runtime 和协议稳定后，新增一个复杂度适中的节点，验证平台扩展方式。

### 12.2 已落地的第一轮新增节点

当前已完成首个低风险扩展节点：

```text
set_variable
```

用途：

- 将输入、节点输出或模板值写入 `variables.*`。
- 为 LLM、API、Knowledge、Branch 之间的数据整理提供轻量节点。
- 不引入数据库迁移或等待态，适合作为节点协议扩展示例。

### 12.3 推荐下一类新增节点

当前已完成 Human Approval 的最小暂停/恢复契约：新增 `waiting_approval` run 状态、`human_approval_tasks` 表、审批任务查询、提交和取消 API，并已接入 Runtime pause/resume。当前运行面板已可在 run 进入 `waiting_approval` 时加载 pending 审批任务，并提交 approve/reject 或取消 pending 审批后刷新运行 trace。前端也已新增最小审批中心，可集中筛选和处理审批任务。

下一步不继续扩展审批体验，审批保持 MVP；开发重心回到普通 Agent 工作流主线：模板创建、发布生成本地代码、运行、Trace 和错误定位。

原因：

- 它能验证 workflow pause/resume 能力。
- 对真实 agent workflow 很有价值。
- 不需要先引入外部数据库或代码沙箱。
- 可以推动 Run 状态机成熟。

### 12.4 Human Approval Node 初步契约

节点类型：

```text
human_approval
```

配置：

```json
{
  "title": "请审批退款请求",
  "description": "{{variables.summary}}",
  "approval_schema": {
    "fields": [
      {"name": "approved", "type": "boolean", "required": true},
      {"name": "comment", "type": "string", "required": false}
    ]
  },
  "timeout_seconds": 86400
}
```

运行行为：

- 节点执行到 human approval 时，run 进入 `waiting_approval` 状态。
- Runtime 创建 `human_approval_tasks` 记录，并将当前节点 trace 标记为 `waiting_approval`。
- 用户提交审批结果后，run 改回 `pending` 并重新入队。
- Worker 从 `state_json.metadata.waiting_approval.next_node_id` 继续执行。
- 用户取消 pending 审批时，task 改为 `cancelled`；如果 run 仍在 `waiting_approval`，run 同步改为 `cancelled`。
- 前端已可拖入和配置人工审批节点。
- 前端当前运行面板已可查询待审批任务、填写 response/comment，并提交同意或拒绝。
- 前端 `Approvals` 页面已可按状态筛选审批任务，并支持 pending 任务单条或批量提交同意、拒绝或取消。

需要新增：

- Run 状态：已落地 `waiting_approval`。
- human task 表：已落地。
- Runtime pause checkpoint：已落地最小版本。
- Runtime resume checkpoint：已落地最小版本。
- 前端当前运行面板审批操作：已落地最小版本。
- 前端独立审批中心：已落地最小版本。
- pending 审批取消闭环：已落地最小版本。

后续增强：

- 审批权限控制。
- 超时过期任务处理。

### 12.5 替代节点

如果暂不做 Human Approval，可选：

- Database Node：读取受控 SQL。
- Loop Node：需要循环协议和最大次数控制。
- Code Node：风险较高，需要沙箱，建议后置。
- Memory Node：需要记忆模型和数据边界，建议后置。

---

## 13. 第二阶段多 Agent 分工建议

如果继续使用多 agent 并行开发，建议按写入边界拆分。

### Agent A：后端 Runtime

负责：

- `backend/app/services/runtime*.py`
- Runtime 拆分
- Runtime tests

不得修改：

- 前端页面
- OpenAPI 之外的文档大改

### Agent B：前端 Workflow/Version

负责：

- `frontend/src/app/page.tsx`
- `frontend/src/app/workflow-editor/**`
- version/code panel
- run/trace panel

不得修改：

- 后端 Runtime
- DB migration

### Agent C：Ops / Worker

负责：

- `backend/app/api/v1/ops.py`
- `backend/app/workers/**`
- Ops 页面
- queue/dead-letter/retry

注意：

- workflow worker 和 document worker 模型不同。
- 不要把 document job 直接强行改成 Redis queue，除非有单独设计。

### Agent D：Security / Auth / Docs

负责：

- `backend/app/core/auth.py`
- PermissionService
- API 权限测试
- README / OPERATIONS / OpenAPI

注意：

- 权限变更必须有测试。
- 不要一次性引入复杂组织模型。

---

## 14. 第二阶段验收矩阵

### 14.1 每轮必跑

```powershell
.\scripts\check-acceptance.ps1
.\scripts\smoke-workflow-core.ps1
```

### 14.2 Compose 验收

```powershell
docker compose ps
Invoke-RestMethod http://localhost:8000/api/v1/ready
Invoke-RestMethod http://localhost:8000/api/v1/ops/workers
Invoke-RestMethod http://localhost:8000/api/v1/ops/queues
```

### 14.3 DeepSeek 验收

- 容器内 `DEFAULT_MODEL_PROVIDER=deepseek`。
- `DEEPSEEK_API_KEY` 已设置。
- 最小 LLM workflow 返回：
  - `provider=deepseek`
  - `model=deepseek-v4-flash`
  - `usage.total_tokens`

### 14.4 Generated Workflow 验收

- 发布生成本地 `workflow.py`。
- v1/v2 目录不覆盖。
- 手改本地代码后运行不阻止。
- trace 记录 `code_modified=true`。
- 缺失文件时报 `workflow_code_missing`。

### 14.5 Ops 验收

- `/ops/workers` 看到 workflow/document worker。
- `/ops/queues` 深度正确。
- 停止 worker 后 stale 可识别。
- dead-letter 可查看。
- failed/cancelled run 可 retry。

### 14.6 安全验收

- Secret 不明文出现在 API response、trace、generated code。
- API Node 阻断内网地址。
- 无权限用户无法操作非授权资源。
- 错误响应不泄露密钥和内部堆栈。

---

## 15. 数据库与迁移建议

当前已有：

- `001_init_agent_workflow_platform_mvp.sql`
- `002_observability_and_governance.sql`
- `003_generated_workflow_code.sql`
- `004_worker_heartbeat_and_runtime_indexes.sql`
- `005_seed_deepseek_default_model.sql`

第二阶段新增 migration 建议从 `006_*.sql` 开始。

可能需要的 migration：

```text
006_run_retry_links.sql
007_permissions_minimal.sql
008_human_approval_tasks.sql
009_trace_events.sql
```

原则：

- migration 幂等。
- 不破坏已有本地 volume。
- `scripts/migrate-db.ps1` 同步补齐。
- Compose initdb 同步挂载。

---

## 16. 文件与 Git 约定

当前已约定：

- `backend/generated_workflows/` 不进 Git。
- `frontend/tsconfig.tsbuildinfo` 不进 Git。
- `.env` 不进 Git。
- 新增 `.md` 默认被 `.gitignore` 忽略。

如果某份文档需要提交，需要强制添加：

```powershell
git add -f "agent flow/开发文档/v1/SECOND_STAGE_DEVELOPMENT_PLAN_v1.md"
```

开发文档建议归档结构：

```text
开发文档/
  v0/
    原 MVP 设计与补充文档
  v1/
    第二阶段开发文档与阶段总结
```

---

## 17. 第二阶段推荐启动任务

建议下一轮开发从以下任务开始：

### Task 1：版本代码体验

- 查看 `workflow.py`
- regenerate-code 确认弹窗
- cleanup dry-run
- code status badge

### Task 2：Runtime 拆分第一批

- `runtime_mapping.py`
- `runtime_generated.py`
- `runtime_persistence.py`
- 保持行为不变

### Task 3：Ops UI 增强

- worker stale
- dead-letter payload
- recover result
- run retry UI

### Task 4：权限最小测试

- 多 mock user
- Workflow owner check
- Secret Admin check
- version code view permission

推荐先做 Task 1 和 Task 2。Task 1 直接提升用户体验；Task 2 降低后续开发成本。

---

## 18. 结论

第二阶段应围绕一个核心判断推进：

```text
当前平台已经能运行工作流；
下一阶段要让它可理解、可维护、可排障、可安全试用。
```

不要优先追求大量新节点。先把版本代码体验、Runtime 模块边界、Ops 恢复链路和权限安全基线打稳，后续新增节点才不会反复撞到基础设施短板。
