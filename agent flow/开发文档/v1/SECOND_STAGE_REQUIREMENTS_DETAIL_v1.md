# Agent Flow 第二阶段需求细化文档 v1

本文档基于 `SECOND_STAGE_DEVELOPMENT_PLAN_v1.md` 继续细化第二阶段需求，用于拆分开发任务、安排多 Agent 并行实现、制定验收标准。

第二阶段不改变第一阶段的核心方向：前端创建工作流，后端在发布时生成本地 Python 代码，运行时以本地生成代码为准。第二阶段的重点不是重做架构，而是把现有 MVP 打磨成稳定、可排障、可扩展的工程版本。

## 1. 第二阶段总体目标

第二阶段目标是完成以下能力：

1. 让用户清楚知道当前工作流发布到了哪个版本、生成了哪个本地代码文件、实际运行使用哪个代码文件。
2. 让 Runtime 从“功能可用”提升到“职责清晰、错误明确、后续可扩展”。
3. 让失败运行、Worker、队列、死信任务可以被前端查看和恢复。
4. 建立最小权限与安全边界，避免 Secret、模型密钥、本地代码执行路径失控。
5. 将 DeepSeek 模型接入从“能调用”整理成“可配置、可观察、可稳定失败处理”的产品能力。
6. 为后续新增节点建立统一开发方式，并落地第一个增强节点能力。

## 2. 范围边界

### 2.1 本阶段必须包含

- Workflow 版本与代码产物展示优化。
- Generated Workflow 运行链路的错误分类与可观察性补齐。
- Runtime 内部模块拆分。
- Ops 页面增强，包括 Worker 状态、队列状态、失败任务、恢复操作。
- DeepSeek 默认模型配置产品化。
- Secret 引用和运行日志脱敏。
- 新增节点能力的最小协议和至少一个可落地节点设计。
- 单元测试、集成测试、Smoke 测试补齐。

### 2.2 本阶段不包含

- 不引入 area、project、folder、workspace 等业务空间模型。
- 不做复杂多租户权限系统。
- 不把 generated workflow 改成远程沙箱执行。
- 不覆盖旧版本生成代码。
- 不把 `workflow_versions.graph_json` 从数据库中移除。
- 不把本地手改代码强制恢复为发布时内容。

## 3. 需求优先级

| 优先级 | 含义 | 说明 |
| --- | --- | --- |
| P0 | 第二阶段必须完成 | 不完成会影响当前主链路稳定性 |
| P1 | 应优先完成 | 不完成不阻塞主链路，但影响可维护性和使用体验 |
| P2 | 可排期完成 | 适合在 P0/P1 稳定后继续增强 |

## 4. R1：版本与代码产物体验

### 4.1 需求目标

当前系统已经能在发布后生成 `backend/generated_workflows/workflow_xxxxxx/vxxxxxx/workflow.py`，但前端展示偏工程字段，用户不容易理解这些字段代表什么。

本需求要求把版本和代码产物变成清晰的产品体验，让用户知道：

- 当前工作流是否已发布。
- 当前工作流最新版本是多少。
- 每个版本对应哪个本地代码文件。
- 当前运行默认使用哪个版本。
- 代码是否被手动修改过。
- 本地代码缺失、入口缺失、导入失败时应该如何提示。

### 4.2 用户故事

作为工作流创建者，我发布工作流后，可以看到本次发布生成的版本号和本地代码路径。

作为开发者，我可以打开 `workflow.py` 进行手动调整，之后运行仍然使用我修改后的本地代码。

作为调试者，我可以看到某次运行使用的 `code_hash_at_run`、`code_path_at_run` 和 `code_modified`。

### 4.3 后端需求

- Publish API 响应必须包含：
  - `version`
  - `code_path`
  - `code_hash`
  - `code_generated_at`
- WorkflowVersion 列表和详情必须包含：
  - `id`
  - `workflow_id`
  - `version`
  - `created_at`
  - `code_path`
  - `code_hash`
  - `code_generated_at`
- Run API 创建运行时必须在 `workflow_runs.metadata_json` 中记录：
  - `code_path_at_run`
  - `code_hash_at_run`
  - `code_modified`
- 当本地代码 hash 与发布 hash 不一致时：
  - 不阻止运行。
  - 记录 `code_modified=true`。
  - trace 或 run detail 中可查看该状态。
- 当本地代码不存在时：
  - 返回明确错误码 `workflow_code_missing`。
- 当本地代码导入失败时：
  - 返回明确错误码 `workflow_code_import_failed`。
- 当本地代码没有 `async def run(input_data, context)` 入口时：
  - 返回明确错误码 `workflow_entrypoint_missing`。

### 4.4 前端需求

- 工作流详情页需要有清晰的发布状态区：
  - 草稿未发布。
  - 已发布版本。
  - 当前默认运行版本。
  - 最近生成时间。
- 版本列表不直接堆大块 `code_path/code_hash/generated_at` 文本，应使用紧凑布局：
  - 版本号作为主信息。
  - 代码路径允许复制。
  - hash 默认截断显示，悬停或点击查看完整值。
  - `code_modified` 使用状态标签展示。
- Run 详情中展示本次运行使用的代码信息：
  - 代码路径。
  - 运行时 hash。
  - 是否和发布时 hash 一致。
- 错误提示需要面向开发者可读：
  - “本地代码文件不存在，请重新发布或恢复文件。”
  - “本地代码导入失败，请检查 workflow.py 语法或依赖。”
  - “本地代码缺少 run 入口。”

### 4.5 数据契约

`workflow_versions` 继续使用以下字段：

- `code_path TEXT`
- `code_hash VARCHAR(128)`
- `code_generated_at TIMESTAMPTZ`

`workflow_runs.metadata_json` 继续保留以下字段：

- `code_hash_at_run`
- `code_modified`
- `code_path_at_run`

### 4.6 验收标准

- 发布 v1 后生成 `workflow_000001/v000001/workflow.py`。
- 发布 v2 后生成 `workflow_000001/v000002/workflow.py`。
- v2 发布不会覆盖 v1 文件。
- 手动修改 v1 的 `workflow.py` 后运行 v1，运行成功且记录 `code_modified=true`。
- 删除 `workflow.py` 后运行，返回 `workflow_code_missing`。
- 将 `workflow.py` 改成语法错误后运行，返回 `workflow_code_import_failed`。
- 删除 `run` 函数后运行，返回 `workflow_entrypoint_missing`。
- 前端版本区域在桌面宽度下不出现大面积空白和横向撑破。

### 4.7 优先级

P0。

## 5. R2：Runtime 模块拆分

### 5.1 需求目标

当前 Runtime 已经能执行生成代码，但后续会继续增加节点类型、模型调用、工具调用、恢复机制，因此需要先把运行链路拆成清晰模块。

目标是让 Runtime 具备以下边界：

- 版本解析。
- 代码定位。
- 代码 hash 校验。
- 动态导入。
- 入口检查。
- 执行上下文构建。
- 运行结果和 trace 记录。
- 错误标准化。

### 5.2 建议模块

后端可按现有目录风格小范围拆分，不要求一次性重构所有代码。

建议模块：

- `WorkflowVersionResolver`
  - 根据 `workflow_id` 和可选 `version` 找到运行版本。
- `WorkflowCodeLocator`
  - 从 `workflow_versions.code_path` 解析本地文件位置。
- `WorkflowCodeVerifier`
  - 计算本地 hash，判断 `code_modified`。
- `WorkflowCodeImporter`
  - 动态导入 `workflow.py`。
- `WorkflowEntrypointValidator`
  - 检查是否存在 `async def run(input_data, context)`。
- `RuntimeContextBuilder`
  - 构造运行上下文，包括 workflow、version、run、secrets、model config 等。
- `RuntimeErrorMapper`
  - 将内部异常映射为稳定错误码。

### 5.3 后端需求

- 不改变 Run API 的外部调用方式。
- 不改变 generated workflow 的入口协议。
- 拆分后应保持同步运行和异步运行行为一致。
- Runtime 错误码应稳定，不因内部异常类名变化而改变。
- trace 中应能看到关键阶段：
  - `resolve_version`
  - `verify_code`
  - `import_code`
  - `execute_workflow`
  - `finalize_run`

### 5.4 测试需求

- 单元测试覆盖每个 Runtime 子模块。
- 集成测试覆盖完整 Run API。
- 需要覆盖以下异常：
  - version 不存在。
  - code_path 为空。
  - 文件不存在。
  - hash 不一致。
  - import 失败。
  - entrypoint 缺失。
  - run 执行抛异常。

### 5.5 验收标准

- 现有 Smoke 测试通过。
- 新增 Runtime 单测通过。
- Run API 仍能执行已发布工作流。
- 异步 Worker 执行路径和同步执行路径返回一致的错误码。
- 主要 Runtime 文件职责清晰，单个文件不继续无限膨胀。

### 5.6 优先级

P0。

## 6. R3：Ops 与运行恢复 UI

### 6.1 需求目标

当前已有基础 Ops API 和 Worker 心跳能力，第二阶段需要让前端可以更完整地查看运行状态和恢复失败任务。

目标是让系统出问题时可以回答：

- Worker 是否在线。
- 队列里还有多少任务。
- 哪些任务失败了。
- 失败原因是什么。
- 是否可以恢复或重试。
- 恢复后是否成功重新入队。

### 6.2 后端需求

- Ops API 继续提供 Worker 列表。
- Ops API 继续提供队列状态。
- Ops API 需要提供失败运行列表，字段至少包括：
  - `run_id`
  - `workflow_id`
  - `workflow_version_id`
  - `status`
  - `error_code`
  - `error_message`
  - `created_at`
  - `updated_at`
- 恢复接口需要返回：
  - 恢复是否成功。
  - 新队列任务 ID 或恢复后的 run 状态。
  - 不能恢复时的错误原因。
- 对重复恢复要有幂等保护：
  - 已在运行中的 run 不应重复入队。
  - 已成功的 run 不应恢复。

### 6.3 前端需求

Ops 页面至少包含四个区域：

- Worker 状态。
- 队列状态。
- 失败运行。
- 恢复操作结果。

失败运行列表需要支持：

- 查看错误码。
- 查看错误摘要。
- 查看 workflow/run 基本信息。
- 点击恢复。
- 恢复后刷新状态。

需要给用户明确反馈：

- 恢复成功。
- 已在运行中，无需恢复。
- 该运行已成功，不能恢复。
- 恢复失败，展示错误原因。

### 6.4 验收标准

- 关闭 worker 后，Ops 页面能看到 worker 心跳异常或离线。
- 制造失败运行后，失败列表能展示 run。
- 点击恢复后，run 能重新进入队列或重新执行。
- 重复点击恢复不会产生多个重复任务。
- Ops 页面刷新后状态与后端一致。

### 6.5 优先级

P0。

## 7. R4：权限与安全最小闭环

### 7.1 需求目标

第二阶段不做完整企业权限，但必须建立基本安全边界，避免模型密钥泄露、本地代码路径被滥用、运行日志暴露敏感信息。

### 7.2 Secret 安全需求

- API 响应不返回 Secret 明文。
- 前端不展示 Secret 明文。
- 运行日志和 trace 不记录 Secret 明文。
- DeepSeek API Key 从环境变量或 Secret 引用读取。
- Secret 更新时允许覆盖，但返回值必须脱敏。

### 7.3 本地代码执行安全需求

- `workflow_versions.code_path` 应限制在 `backend/generated_workflows/` 下。
- Runtime 解析路径时必须防止路径穿越。
- 不允许通过 API 任意指定系统路径作为 workflow code。
- 错误信息不返回服务器敏感绝对路径细节，必要时返回项目内相对路径。

### 7.4 API 最小鉴权需求

如果项目已有认证机制，第二阶段应补测试和接口保护。

如果项目暂时没有完整登录体系，第二阶段至少需要：

- 为敏感接口预留认证中间件位置。
- 对 Ops、Secrets、Models 等接口标记安全等级。
- 在文档中明确开发环境和生产环境差异。

敏感接口包括：

- Secret 管理。
- Model 配置。
- Ops 恢复。
- Workflow 发布。
- Run 创建。

### 7.5 验收标准

- Secret 列表和详情不返回明文。
- trace 中不存在 DeepSeek API Key。
- 通过构造 `../` 路径不能让 Runtime 导入 `generated_workflows` 之外的文件。
- Ops 恢复接口不能恢复已成功 run。
- 安全策略在 OpenAPI 或开发文档中有说明。

### 7.6 优先级

P1。

## 8. R5：DeepSeek 模型产品化

### 8.1 需求目标

当前项目已经能通过 `DEEPSEEK_API_KEY` 真实调用 DeepSeek。第二阶段要把它整理成默认可用、可配置、可观测的模型能力。

默认模型目标：

- provider：`deepseek`
- model：`deepseek-v4-flash`

### 8.2 后端需求

- 默认模型配置使用 `deepseek-v4-flash`。
- 支持从环境变量读取 `DEEPSEEK_API_KEY`。
- 模型调用结果需要记录：
  - provider
  - model
  - request duration
  - token usage，如果供应商返回
  - error code
  - error message 摘要
- 模型调用失败时返回稳定错误：
  - `model_api_key_missing`
  - `model_request_failed`
  - `model_response_invalid`
  - `model_timeout`
- 不能在错误中泄露 API Key。

### 8.3 前端需求

- Models 页面默认能看到 DeepSeek 选项。
- LLM 节点默认模型应使用 `deepseek-v4-flash`。
- 节点配置中可以选择 provider 和 model。
- 如果 API Key 缺失，运行错误应提示配置环境变量或 Secret。
- Run 详情或 trace 能看到实际调用的 provider/model。

### 8.4 验收标准

- `.env` 中配置 `DEEPSEEK_API_KEY` 后，LLM 节点可以真实调用 DeepSeek。
- 未配置 key 时，返回 `model_api_key_missing`，不出现堆栈泄露。
- 前端创建 LLM 节点时默认模型是 `deepseek-v4-flash`。
- Run 详情能看到 provider/model。
- Smoke 测试不强依赖真实 DeepSeek，可使用 mock 或跳过真实调用。

### 8.5 优先级

P1。

## 9. R6：新增节点能力与节点协议

### 9.1 需求目标

第二阶段需要开始建立新增节点的标准方式。重点不是堆节点数量，而是让后续添加节点时有清晰协议、测试方式和代码生成规则。

### 9.2 节点协议要求

每个节点类型需要明确：

- `type`
- `config`
- `input_mapping`
- `output_mapping`
- 是否允许禁用。
- 是否参与代码生成。
- 运行失败时的错误码。
- trace 中的展示方式。

### 9.3 已落地的第一轮增强节点

当前已完成首个低风险增强节点：

```text
set_variable
```

配置示例：

```json
{
  "assignments": {
    "normalized_query": "{{input.user_query}}",
    "customer.id": "{{input.customer_id}}"
  }
}
```

运行行为：

- 将配置中的值解析后写入 `variables.*`。
- `assignments` 对象 key 没有 `variables.` 前缀时会自动补齐。
- 支持对象和数组两种配置形式。
- 不引入等待态和数据库迁移。

### 9.4 推荐下一类增强节点

当前已完成 Human Approval 的最小暂停/恢复契约：新增 `waiting_approval` run 状态、`human_approval_tasks` 表、审批任务查询、提交和取消 API，并已接入 Runtime pause/resume。当前运行面板已补齐最小审批操作 UI，用户可以不离开工作流编辑页完成 approve/reject 或取消 pending 审批。前端也已新增最小 `Approvals` 审批中心，支持按状态集中查看和处理任务，并可选择多个 pending 任务批量同意、拒绝或取消。

它还不是完整审批产品，权限控制和超时过期等能力仍在后续范围；当前取消能力只覆盖人工主动取消 pending 审批的最小闭环。

节点类型：

```text
human_approval
```

配置示例：

```json
{
  "title": "退款审批",
  "description": "需要人工确认是否允许退款",
  "options": ["approve", "reject"],
  "default_timeout_seconds": 86400
}
```

输出示例：

```json
{
  "decision": "approve",
  "approved_by": "user_001",
  "approved_at": "2026-05-19T10:00:00Z"
}
```

### 9.5 最小实现建议

如果本阶段时间有限，`Human Approval Node` 可以先保持当前暂停/恢复和运行面板审批能力，不强行实现完整审批中心 UI。

若要实现最小可用版本，建议范围：

- 执行到该节点时 run 进入 `waiting_approval`。
- API 提供审批提交接口。
- trace 记录等待节点。
- 提交后 run 改回 `pending`、重新入队，并由 worker 从 checkpoint 继续执行。
- 当前运行面板在 `waiting_approval` 状态下展示 pending task，支持填写 `response/comment` 并提交 approve/reject，也支持取消 pending 任务。
- `Approvals` 页面支持按 `pending/approved/rejected/cancelled/expired/all` 筛选任务，pending 任务可单条或批量提交 approve/reject/cancel。

### 9.6 替代候选节点

如果不做人工审批，可以选择以下节点之一：

- HTTP Request Node 增强版。
- Code Transform Node。
- Knowledge Rerank Node。
- Document Extract Node。

选择原则：

- 优先选择能验证节点协议和代码生成规则的节点。
- 避免一开始选择依赖过重的节点。

### 9.7 验收标准

- 新节点有明确文档。
- 新节点有 graph JSON 示例。
- 新节点有 codegen 输出示例。
- 新节点有运行错误码定义。
- 如果实现，则至少有一个端到端测试或可重复的手动验收路径。
- Human Approval 最小链路要求：run 等待审批、运行面板或审批中心提交审批、worker 从 checkpoint 继续、trace 刷新到恢复后的状态；取消 pending 审批时任务进入 `cancelled`，对应等待中的 run 也进入 `cancelled`。

### 9.8 优先级

P2。

## 10. R7：测试与验收体系

### 10.1 需求目标

第二阶段需要把“能跑一次”升级为“每轮开发后可验证”。测试重点围绕发布、生成代码、运行、恢复、模型调用和 UI 基础交互。

### 10.2 必跑测试

每轮开发结束至少运行：

```powershell
npm run check:local
npm run smoke:e2e
```

如果只改后端，可运行后端单测。

如果只改前端，可运行前端类型检查和相关组件测试。

### 10.3 后端测试范围

- Workflow 发布。
- Codegen 生成。
- Runtime 导入。
- Runtime hash 检查。
- Run 成功与失败。
- Worker 异步执行。
- Ops 恢复。
- Secret 脱敏。
- DeepSeek mock 调用。

### 10.4 前端测试范围

- 节点可拖动到画布。
- 节点拖动时跟随鼠标。
- 节点可连线。
- 连线可删除。
- 版本信息展示正常。
- Run 测试输入可执行。
- Ops 页面能展示 worker/queue/failed run。

### 10.5 手动验收流程

建议每次大功能合并前执行：

1. 启动 Docker 基础设施。
2. 启动 API、worker、frontend。
3. 新建工作流。
4. 拖入节点并连线。
5. 保存草稿。
6. 发布工作流。
7. 检查生成目录。
8. 同步运行一次。
9. 异步运行一次。
10. 修改 `workflow.py`。
11. 再运行并检查 `code_modified=true`。
12. 制造失败运行。
13. 在 Ops 页面恢复。

### 10.6 验收标准

- 自动测试通过。
- 关键手动验收通过。
- 新增错误码在 API 文档中可查。
- 前端无明显空白、撑破、拖拽失效、状态不同步问题。

### 10.7 优先级

P0。

## 11. R8：文档和接口契约同步

### 11.1 需求目标

第二阶段开始后，开发文档、OpenAPI、数据库 ER、任务拆分必须同步更新，避免代码和文档再次分叉。

### 11.2 文档更新要求

涉及以下变化时必须同步文档：

- API 请求或响应字段变化。
- 数据表字段变化。
- 错误码变化。
- workflow graph JSON 契约变化。
- node config 契约变化。
- generated workflow 文件结构变化。
- Runtime 运行生命周期变化。
- 环境变量变化。

### 11.3 需要维护的文档

- `开发文档/v1/SECOND_STAGE_DEVELOPMENT_PLAN_v1.md`
- `开发文档/v1/SECOND_STAGE_REQUIREMENTS_DETAIL_v1.md`
- API 设计文档。
- OpenAPI YAML。
- 数据库 ER 文档。
- Runtime 细节文档。
- Development task breakdown。

### 11.4 Git 注意事项

当前项目 `.gitignore` 包含：

```text
*.md
```

因此新增 Markdown 文档默认不会进入 Git。

如果需要提交 v1 文档，需要使用：

```powershell
git add -f "agent flow/开发文档/v1/SECOND_STAGE_DEVELOPMENT_PLAN_v1.md"
git add -f "agent flow/开发文档/v1/SECOND_STAGE_REQUIREMENTS_DETAIL_v1.md"
```

### 11.5 验收标准

- 新增接口字段能在 OpenAPI 中找到。
- 新增 DB 字段能在 ER 文档中找到。
- 新增错误码能在 API 文档中找到。
- 新增节点类型能在 Runtime 或 Node Protocol 文档中找到。
- 文档和实现不出现明显冲突。

### 11.6 优先级

P1。

## 12. 第二阶段任务拆分建议

### Task A：版本与代码产物体验

负责人建议：前端 Agent + 后端 Agent。

范围：

- 调整 Publish 响应确认。
- 调整 WorkflowVersion API 确认。
- 优化前端版本展示。
- 增加复制 code_path/hash。
- 增加 run detail 的 code metadata 展示。

验收：

- 用户不需要理解数据库字段，也能知道当前运行代码来自哪里。

优先级：P0。

### Task B：Runtime 拆分与错误码稳定

负责人建议：后端 Runtime Agent。

范围：

- 拆出版本解析、代码定位、hash 校验、导入、入口校验。
- 统一 Runtime 错误码。
- 补单元测试。

验收：

- Runtime 逻辑可读，错误码稳定，原有 Run API 不变。

优先级：P0。

### Task C：Ops 页面与恢复闭环

负责人建议：Ops Agent + 前端 Agent。

范围：

- Worker 状态展示。
- Queue 状态展示。
- Failed run 列表。
- Recover 操作。
- 幂等保护和错误提示。

验收：

- 失败任务能被看到、理解、恢复。

优先级：P0。

### Task D：DeepSeek 产品化

负责人建议：模型 Agent。

范围：

- 默认 provider/model。
- 环境变量读取。
- 模型错误码。
- 调用信息记录。
- 前端模型选择。

验收：

- LLM 节点默认可以使用 `deepseek-v4-flash`。

优先级：P1。

### Task E：安全最小闭环

负责人建议：安全/后端 Agent。

范围：

- Secret 脱敏。
- code_path 路径限制。
- sensitive API 标记。
- 测试路径穿越和日志泄露。

验收：

- 不泄露密钥，不能导入 generated workflow 之外的任意文件。

优先级：P1。

### Task F：新增节点协议与首个节点

负责人建议：后端 Agent + 前端 Agent。

范围：

- 定义节点协议。
- 设计 Human Approval Node 或替代节点。
- 补 graph JSON 示例。
- 补 codegen 示例。
- 若时间允许，实现最小可用版本。

验收：

- 后续新增节点有模板可循。

优先级：P2。

## 13. 第二阶段推荐开发顺序

建议按以下顺序推进：

1. R1 版本与代码产物体验。
2. R2 Runtime 模块拆分。
3. R7 测试与验收体系补齐。
4. R3 Ops 与运行恢复 UI。
5. R5 DeepSeek 模型产品化。
6. R4 权限与安全最小闭环。
7. R6 新增节点能力。
8. R8 文档和接口契约同步。

如果使用多 Agent 并行，可以这样安排：

- Agent 1：R2 Runtime 拆分。
- Agent 2：R1 前端版本体验。
- Agent 3：R3 Ops UI 和恢复。
- Agent 4：R4/R5 安全与模型配置。

并行时必须遵守：

- 不同时修改同一个大文件。
- API 字段先对齐再开发。
- 每个 Agent 结束时说明改动文件、测试结果、剩余风险。

## 14. 第二阶段完成定义

第二阶段完成需要满足：

- 用户可以稳定创建、编辑、保存、发布、运行工作流。
- 发布后的本地代码版本清晰可见。
- Runtime 以本地代码为准，手改代码可运行并被标记。
- 常见 Runtime 错误有稳定错误码和前端提示。
- Worker、队列、失败任务可以在 Ops 页面查看。
- 失败任务可以恢复，且不会重复入队。
- DeepSeek 默认模型可配置、可调用、可观察。
- Secret 和本地代码路径有基本安全保护。
- 新增节点有明确协议和扩展样例。
- 自动测试和 Smoke 测试通过。

## 15. 结论

第二阶段的核心不是增加大量新功能，而是把当前项目从“功能闭环”推进到“工程闭环”。

最重要的三条主线是：

1. 让 generated workflow 的发布、版本、运行、手改代码策略对用户可见、可验证。
2. 让 Runtime 和 Ops 具备清晰边界，失败时能定位、能恢复。
3. 让模型、Secret、新节点扩展进入可长期维护的契约体系。

## 16. 当前实现同步状态

截至 2026-05-19，第二阶段已有一轮实现落地，详细接口和错误码契约见：

```text
开发文档/v1/SECOND_STAGE_CONTRACT_SYNC_v1.md
```

当前状态：

| 需求 | 状态 | 说明 |
| --- | --- | --- |
| R1：版本与代码产物体验 | 部分完成 | 已有版本代码面板、code metadata、Trace code 信息，后续继续做 UI 细节验收 |
| R2：Runtime 模块拆分 | 已完成第一轮 | generated workflow 加载逻辑已拆到 `backend/app/services/generated_runtime.py` |
| R3：Ops 与运行恢复 UI | 已完成第一轮 | 已支持 failed runs 列表、dead queue、单条恢复和队列恢复 |
| R4：权限与安全最小闭环 | 已完成第一轮 | Secret 响应脱敏、审计 detail 脱敏、generated workflow 路径越界测试已补齐 |
| R5：DeepSeek 模型产品化 | 已完成第一轮 | 稳定错误码、模型 metadata、token usage、错误脱敏已补齐 |
| R6：新增节点能力与节点协议 | 已完成第四轮 | 已新增 `set_variable` 节点，补齐 API Node 小步生产化配置，并新增 Human Approval 最小暂停/恢复契约 |
| R7：测试与验收体系 | 已更新基线 | 后端 `129 passed`，前端 lint/typecheck/build 通过 |
| R8：文档和接口契约同步 | 进行中 | 本次新增实现同步文档，后续还需更新 OpenAPI/API 设计文档 |

新增后端错误码：

- `model_api_key_missing`
- `model_request_failed`
- `model_response_invalid`
- `model_timeout`

新增 Ops 接口：

- `GET /api/v1/ops/workflow_runs/failed?limit=20`
- `POST /api/v1/ops/workflow_runs/{run_id}/recover`
