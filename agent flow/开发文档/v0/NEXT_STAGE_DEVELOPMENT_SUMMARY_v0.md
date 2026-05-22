# Agent Flow 下一阶段开发总结 v0

本文档基于 `开发文档/v0` 目录下现有设计、接口、运行时、部署、安全、可观测性与补充方案整理，用于下一阶段开发接力。它不是替代原始设计文档，而是把当前项目状态、核心契约、剩余边界和推荐推进顺序压缩成一份可执行摘要。

更新时间：2026-05-19

---

## 1. 当前项目状态

当前 Agent Flow 已经从“设计原型”推进到“本地 Compose 可复现、MVP 主链路可运行、可进入下一阶段增强”的状态。

已完成的核心闭环：

- 工作流创建、保存草稿、校验、发布版本。
- 发布时基于 `workflow_versions.graph_json` 生成本地 Python 代码。
- 运行时通过 `workflow_versions.code_path` import 本地 `workflow.py` 执行。
- 同步运行由 API 执行，异步运行通过 Redis 队列交给 `worker-workflow`。
- `workflow_runs`、`node_runs`、trace、code metadata 均已落库。
- Knowledge 文档上传、document worker 处理、pgvector 检索、关键词回退已可用。
- Intent、Branch、LLM、Knowledge、API、Message、Output 等主要节点已可跑通。
- DeepSeek 默认模型已接入，默认 `provider=deepseek`、`model=deepseek-v4-flash`。
- Ops 已支持 workflow/document worker heartbeat、workflow run 队列深度、dead-letter 查看和恢复。
- 前端已有 Workflow / Knowledge / Tools / Secrets / Models / Ops 六个入口。
- 本地 `.\scripts\check-acceptance.ps1`、`.\scripts\smoke-e2e.ps1` 已作为主要回归验收入口。

当前生产化边界：

- 可以用于本地开发、测试环境试用和功能验收。
- 还不是企业生产级系统。
- 暂未具备完整登录、组织、项目空间、RBAC、集中告警、日志聚合、KMS、自动备份、灰度发布和多租户隔离。

---

## 2. 技术栈与运行方式

当前技术栈基线：

| 层级 | 技术 |
| --- | --- |
| Frontend | Next.js + React Flow |
| Backend API | FastAPI |
| Runtime | Generated workflow Python code + controlled runtime context |
| Worker | Redis-backed workflow/document workers |
| Database | PostgreSQL + pgvector |
| File Storage | Local filesystem volume |
| Deployment | Docker Compose |
| Auth | MVP mock user，预留 JWT |
| LLM | DeepSeek/OpenAI-compatible，保留 mock provider |

本地默认服务：

- API: `http://localhost:8000`
- Frontend: `http://localhost:3000`
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6380`

关键命令：

```powershell
cd "D:\xm\agent flow\agent flow"
npm run compose:up
.\scripts\check-acceptance.ps1
.\scripts\smoke-e2e.ps1
```

---

## 3. 当前核心契约

### 3.1 发布阶段

发布阶段的事实来源仍然是数据库：

- 草稿图保存在 `workflows.draft_graph_json`。
- 发布后创建不可变 `workflow_versions.graph_json`。
- 发布成功后生成本地代码目录：

```text
backend/generated_workflows/
  workflow_000001/
    v000001/
      __init__.py
      workflow.py
      manifest.json
```

`workflow_versions` 记录：

- `code_path`
- `code_hash`
- `code_generated_at`

每次发布生成新版本目录，不覆盖旧版本目录。

### 3.2 运行阶段

运行阶段以本地生成代码为准：

1. Run API 找到 workflow 当前版本或指定版本。
2. 根据 `workflow_versions.code_path` 定位 `workflow.py`。
3. 运行前重新计算本地代码 hash。
4. import `workflow.py`。
5. 调用固定入口：

```python
async def run(input_data, context) -> dict:
    ...
```

hash 不一致时：

- 记录 `code_modified=true`。
- 不阻止运行。

只有以下情况阻止运行：

- `workflow_code_missing`
- `workflow_code_import_failed`
- `workflow_entrypoint_missing`

### 3.3 Node Protocol

当前节点协议仍是前后端和 Runtime 的核心契约：

- `graph_json.schema_version`
- `nodes`
- `edges`
- `node.id`
- `node.type`
- `node.config`
- `input_mapping`
- `output_mapping`
- `retry`
- `timeout`
- `on_error`
- `enabled`

变量引用使用 `{{...}}`，核心路径包括：

- `input.*`
- `variables.*`
- `outputs.<node_id>.*`
- `metadata.*`

后续新增节点必须先扩展 Node Protocol，再扩展后端 node schema、Runtime executor、前端配置面板和 smoke 用例。

---

## 4. 已实现能力地图

### 4.1 Workflow / Version / Codegen

已具备：

- Workflow CRUD。
- 草稿保存。
- 图校验。
- 发布版本。
- 本地代码生成。
- 版本 code metadata 展示。
- 查看版本代码。
- 重新生成版本代码。
- generated workflows 清理 API。

下一阶段重点：

- 版本历史体验优化。
- code diff / version diff。
- regenerate-code 的前端确认流程。
- cleanup API 增加 dry-run first 体验。
- 更可读的生成代码结构。

### 4.2 Runtime / Run / Trace

已具备：

- sync run。
- async run。
- pending/running/completed/failed/cancelled 状态。
- node_runs。
- trace 聚合。
- code metadata 进入 run metadata。
- 节点 retry 基础。
- run retry API。
- worker recovery / dead-letter。

下一阶段重点：

- 更完整的 cancel checkpoint。
- 更细粒度 retry 策略 UI。
- Trace events / SSE 实时刷新。
- Runtime 模块拆分，降低 `runtime.py` 复杂度。
- 运行详情页独立化。

### 4.3 Knowledge

已具备：

- 创建知识库。
- 上传文档。
- document worker 处理任务。
- chunks 入库。
- pgvector 检索。
- 关键词回退。
- 文档重试与删除。

下一阶段重点：

- 更多文件类型解析。
- 文档处理失败原因可视化。
- 重建索引 / reindex 管理。
- 更大规模 chunk 管理。
- embedding provider 配置 UI。

### 4.4 Tools / API Node

已具备：

- API tool 创建、编辑、测试。
- API Node mock 模式。
- `mode=http` 公网 HTTP/HTTPS 调用。
- localhost/private/link-local 阻断。
- header 脱敏。
- output mapping。

下一阶段重点：

- 外呼 allowlist。
- API Node 幂等键策略。
- 超时、重试、速率限制 UI。
- 更严格的响应 schema 校验。
- 工具调用审计与失败分析。

### 4.5 Model / Secret / DeepSeek

已具备：

- Model provider / model config。
- Secret 创建与更新。
- Secret 加密存储。
- Secret 脱敏展示。
- DeepSeek 默认配置。
- `DEEPSEEK_API_KEY` 真实调用已验证。

下一阶段重点：

- Provider 测试连接。
- Secret 轮换流程。
- 模型调用预算。
- 模型调用失败分类。
- thinking mode / temperature / max_tokens 的更好 UI。

### 4.6 Ops / Observability

已具备：

- `/health`
- `/ready`
- `/metrics`
- `/ops/workers`
- `/ops/queues`
- `/ops/queues/workflow_runs/dead`
- `/ops/queues/workflow_runs/recover`
- workflow/document worker heartbeat。
- workflow run queue depth。
- dead-letter 查看与恢复。

下一阶段重点：

- Ops 页面补 worker stale 标识。
- dead-letter 单条重放/忽略。
- run retry UI。
- metrics 指标补充和标签基数控制。
- JSON structured logging。
- trace events / SSE。

---

## 5. 下一阶段优先级建议

建议下一阶段不要马上扩张大功能，而是先把 MVP 从“能跑”推进到“可持续开发、可排障、可安全试用”。

### P0：收敛交付基线

目标：让项目进入可稳定提交、可复现、可接力状态。

任务：

- 保持 `backend/generated_workflows/` 和 `frontend/tsconfig.tsbuildinfo` 不再进入 Git。
- 明确 `开发文档/v0` 是当前设计文档归档目录。
- 保持 `.\scripts\check-acceptance.ps1` 与 `.\scripts\smoke-e2e.ps1` 每轮通过。
- 更新 README / OPERATIONS / OpenAPI 与真实实现保持同步。
- 对本地 `.env` 与 `.env.example` 差异建立说明。

验收：

```powershell
.\scripts\check-acceptance.ps1
.\scripts\smoke-e2e.ps1
docker compose ps
Invoke-RestMethod http://localhost:8000/api/v1/ready
Invoke-RestMethod http://localhost:8000/api/v1/ops/workers
```

### P1：Runtime 可维护性重构

目标：降低 `runtime.py` 单文件复杂度，为新增节点做准备。

建议拆分顺序：

1. `runtime_mapping.py`
   - `_build_node_input`
   - `_apply_output_mapping`
   - `_resolve_value`
   - path get/set helper
2. `runtime_generated.py`
   - generated workflow import
   - code path resolve
   - hash check
3. `runtime_persistence.py`
   - run/node_run 创建和状态更新
   - metadata 更新
4. `runtime_errors.py`
   - RuntimeNodeError
   - error normalization
5. 保留核心调度在 `runtime.py`，逐步迁移。

验收：

- 行为不变。
- 现有 93 个后端测试通过。
- smoke 通过。
- 关键错误码不变化。

### P2：前端运行与版本体验

目标：让用户能看清“当前运行的是哪个版本、哪份本地代码、是否被手改”。

任务：

- 版本列表增加更清晰的 code status。
- version detail 增加查看 `workflow.py`。
- regenerate-code 按钮加确认弹窗。
- cleanup generated workflows 支持 dry-run preview。
- Run/Trace 面板显示：
  - `code_path_at_run`
  - `code_hash_published`
  - `code_hash_at_run`
  - `code_modified`

验收：

- 发布 v1/v2 不互相覆盖。
- 修改本地 `workflow.py` 后运行显示 `code_modified=true`。
- regenerate-code 后 hash 更新。

### P3：Ops 和失败恢复体验

目标：减少“运行 pending / worker 卡住 / dead-letter 不知道怎么办”的排障成本。

任务：

- Ops worker 列表增加 stale/active 标识。
- 队列状态增加刷新间隔和更新时间。
- dead-letter 支持单条查看。
- run retry UI 接入 `POST /runs/{run_id}/retry`。
- recover 操作展示结果明细。
- Trace 中突出 worker/retry/dead-letter metadata。

验收：

- 停止 worker 后 Ops 能看出 worker 心跳过期。
- dead-letter job 可被定位。
- failed/cancelled run 可从 UI 重试。

### P4：权限与安全最小闭环

目标：为真实用户试用打基础。

任务：

- 引入真实 JWT 登录入口或至少多 mock user 测试。
- PermissionService 覆盖 Workflow/Run/Secret/Tool/Knowledge。
- Secret API 限制 Admin。
- 版本代码查看接口增加权限校验。
- API Node 外呼 allowlist。
- LLM/API 调用预算与超时上限。
- 上传文件安全策略补齐。

验收：

- 非 owner 不能修改或运行无权限 workflow。
- Viewer 不能创建 Secret。
- API Node 无法访问内网地址。
- Trace 不泄露 secret。

### P5：新增节点能力

目标：在协议稳定后扩展节点类型。

建议顺序：

1. Human Approval Node
2. Loop Node
3. Database Node
4. Code Node
5. Memory Node
6. Info Collection Node

新增节点必须同时改：

- Node Protocol 文档。
- 后端 node schema。
- Graph validation。
- Runtime executor。
- Codegen smoke。
- 前端节点库。
- 前端配置面板。
- trace 展示。

---

## 6. 风险与注意事项

### 6.1 `.md` 已被 gitignore 忽略

当前 `.gitignore` 已加入：

```gitignore
*.md
```

因此新建的开发总结、临时计划、补充文档默认不会进入 Git。若某份文档需要提交，需要显式 `git add -f`。

已跟踪过的 Markdown 文档仍会在修改时出现在 Git 状态中。

### 6.2 generated workflow 是本地运行产物

`backend/generated_workflows/` 已从 Git 跟踪中移除，并由 `.gitignore` 接管。

这符合当前设计：

- 发布时本地生成。
- 运行时以本地代码为准。
- 不作为源码仓库的一部分提交。

下一阶段不要把 smoke 生成的 workflow 目录重新加入 Git。

### 6.3 Codegen 安全边界

当前生成代码由平台生成，原则上不应包含 secret。

后续如果生成代码包含更多节点配置，需要注意：

- 不把 secret 明文写入 `workflow.py`。
- 不允许任意路径 import。
- 代码查看接口必须做权限校验。
- regenerate-code 不能误覆盖手改代码，必须显式 force。

### 6.4 Runtime 手改代码策略

当前策略是 dev-friendly：

- 本地 `workflow.py` 被手改后继续运行。
- 只记录 `code_modified=true`。

后续如果进入生产环境，可以考虑增加 strict mode：

- hash 不一致直接拒绝运行。
- 或只允许 Admin override。

### 6.5 Worker 与队列恢复

workflow worker 已有 processing queue / dead-letter / recover。

document worker 当前已有 heartbeat，但文档任务仍是 DB polling 模式，不是 Redis queue。下一阶段如果要统一队列模型，需要单独设计，不要直接把 workflow queue 逻辑套到 document jobs 上。

---

## 7. 推荐下一阶段开发顺序

建议按以下顺序推进：

```text
1. 提交前整理与文档归档确认
2. Runtime 模块拆分，不改变行为
3. 版本代码查看 / regenerate / cleanup 前端体验
4. Run retry / dead-letter / worker stale 的 Ops UI
5. 权限与安全最小闭环
6. 新增节点类型
```

每一步都应遵守：

```text
小范围改动
先测试后扩展
保持 OpenAPI / README / OPERATIONS 同步
每轮跑 check:local 和 smoke:e2e
```

---

## 8. 下一阶段验收清单

### 基础验收

```powershell
.\scripts\check-acceptance.ps1
.\scripts\smoke-e2e.ps1
docker compose ps
Invoke-RestMethod http://localhost:8000/api/v1/ready
Invoke-RestMethod http://localhost:8000/api/v1/ops/queues
Invoke-RestMethod http://localhost:8000/api/v1/ops/workers
```

### DeepSeek 验收

- 容器内 `DEFAULT_MODEL_PROVIDER=deepseek`。
- 容器内存在 `DEEPSEEK_API_KEY`。
- 最小 LLM 工作流真实返回：
  - `provider=deepseek`
  - `model=deepseek-v4-flash`
  - `usage.total_tokens` 有值。

### Generated Workflow 验收

- 发布后生成 `workflow.py`。
- v1/v2 目录不同。
- 修改本地 `workflow.py` 后运行记录 `code_modified=true`。
- `workflow_code_missing`、`workflow_code_import_failed`、`workflow_entrypoint_missing` 可定位。

### Ops 验收

- `/ops/workers` 同时看到：
  - `worker_type=workflow`
  - `worker_type=document`
- `/ops/queues` 返回 main / processing / dead-letter depth。
- `/metrics` 返回 Prometheus text。
- smoke 后队列深度正常回到 0。

---

## 9. 关键参考文档

下一阶段开发时建议优先阅读：

- `README.md`：当前项目状态、本地启动、MVP 闭环。
- `OPERATIONS.md`：部署、验收、排障边界。
- `openapi_agent_workflow_platform_mvp_v1.yaml`：接口契约。
- `agent_workflow_platform_node_protocol_v_1.md`：节点协议。
- `agent_workflow_platform_runtime_detail_v_1.md`：Runtime 设计。
- `agent_workflow_platform_backend_structure_v_1.md`：后端模块边界。
- `agent_workflow_platform_database_er_v_1.md`：数据库契约。
- `WORKFLOW_PUBLISH_CODEGEN_DESIGN.md`：发布生成代码运行模式。
- `runtime_stability_observability_development_plan_v_1.md`：稳定性、worker、metrics、ops 后续路线。
- `security_design_v0.1_claude.md`：安全与权限基线。

---

## 10. 一句话结论

当前项目已经完成 MVP 主链路，下一阶段不应急着堆新节点，而应先把 Runtime 可维护性、版本代码体验、Ops 排障、权限安全和文档契约稳定下来。这样后续新增 Loop、Human Approval、Database、Code、Memory 等复杂节点时，系统不会被 Runtime、Trace、队列和权限的基础债务拖住。
