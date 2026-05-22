# 第二阶段验收清单 v1

本文档定义每轮开发合入前必须执行的验收入口、判定标准和可选真实环境检查。适用范围为第二阶段开发中的后端、前端、Docker、数据库迁移、核心 workflow smoke、Human Approval smoke 以及 DeepSeek 真实调用验收。

## 0. 验收原则

- 不回滚或覆盖其他开发者改动；验收前先确认 `git status --short`，只对本轮归属文件负责。
- 必跑检查必须全部通过；任何命令非 0 退出、测试失败、lint/typecheck 报错、Docker 配置无法解析、迁移 dry-run 找不到脚本都视为不通过。
- 在线 smoke 会创建测试工作流、运行记录、知识库/文档或审批任务，属于非破坏性验收数据；不要在共享生产库运行。
- DeepSeek 真实验收是可选项，只在修改 LLM provider、模型配置、密钥传递、运行时 LLM 节点或发布前需要真实模型背书时执行。

## 1. 每轮必跑命令

在仓库根目录执行：

```powershell
.\scripts\check-acceptance.ps1
```

该入口会依次执行：

```powershell
.\scripts\check-env.ps1
.\scripts\check-local.ps1
docker compose -f .\compose.yaml --project-directory . config
.\scripts\migrate-db.ps1 -DryRun
```

判定标准：

- `check-env.ps1` 能输出 Python、Node、npm、Docker、Docker Compose 版本。
- `check-local.ps1` 中后端 `pytest`、`ruff check .` 全部通过。
- `check-local.ps1` 中前端 `npm run typecheck`、`npm run lint` 全部通过。
- `docker compose config` 能成功解析完整 Compose 配置。
- `migrate-db.ps1 -DryRun` 能列出计划中的迁移文件，且不执行数据库写入。

## 2. 后端验收

必跑命令已由总入口覆盖；需要单独定位后端问题时执行：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

判定标准：

- 所有 `backend/tests` 测试通过，无 skipped 之外的失败或错误。
- Ruff 无 `E/F/I/UP/B` 规则报错。
- 若修改 API contract、runtime、worker、graph validation、knowledge、human approval 或 codegen，必须补充或更新对应测试；不能只依赖手工验证。

## 3. 前端验收

必跑命令已由总入口覆盖；需要单独定位前端问题时执行：

```powershell
cd frontend
npm run typecheck
npm run lint
```

判定标准：

- TypeScript 无类型错误。
- ESLint 无错误。
- 涉及编辑器、节点面板、连线、表单或状态管理的改动，需要本地打开页面做一次人工冒烟：能加载编辑器、拖拽/选择节点、查看配置面板、保存相关交互不出现控制台红色错误。

## 4. Docker 验收

每轮必跑 Docker 配置解析：

```powershell
docker compose -f .\compose.yaml --project-directory . config
```

涉及 Dockerfile、Compose、环境变量、依赖安装或启动命令时，加跑镜像构建：

```powershell
.\scripts\check-acceptance.ps1 -IncludeDockerBuild
```

需要完整容器启动验收时执行：

```powershell
docker compose up -d --build
docker compose ps
```

判定标准：

- `config` 成功退出。
- 构建时 `api`、`worker-workflow`、`worker-document`、`frontend` 镜像都能构建成功。
- 完整启动后 `postgres`、`redis`、`api` 为 healthy；worker 服务持续运行；frontend 可访问 `http://localhost:3000`。

## 5. 迁移验收

每轮必跑 dry-run：

```powershell
.\scripts\migrate-db.ps1 -DryRun
```

涉及 SQL 迁移、schema、索引、种子数据或持久化模型时，在本地开发库执行：

```powershell
docker compose up -d postgres
.\scripts\migrate-db.ps1
```

判定标准：

- Dry-run 输出包含 `002_observability_and_governance.sql` 到 `007_human_approval_node_status.sql` 的迁移计划。
- 真实执行时每个 migration 都显示 Applying 且无 `psql` 错误。
- 重复执行不会破坏已有数据；若某迁移不是幂等的，必须在合入前明确风险和执行窗口。

## 6. 核心 Workflow Smoke

本检查覆盖健康检查、发布生成代码、同步/异步运行、知识库检索、intent + branch、API + message、secret 脱敏等核心路径。

准备：

```powershell
docker compose up -d --build
.\scripts\migrate-db.ps1
```

执行：

```powershell
.\scripts\smoke-e2e.ps1
.\scripts\smoke-workflow-core.ps1
```

也可通过总入口执行核心 smoke：

```powershell
.\scripts\check-acceptance.ps1 -IncludeOnlineSmoke
```

判定标准：

- `/health` 和 `/ready` 返回正常状态。
- 发布返回 `backend/generated_workflows/...` 的 `code_path`。
- 运行最终状态为 `completed`。
- trace 包含预期节点，generated runtime 元数据包含 `code_path_at_run`、`sha256:` 格式的 `code_hash_at_run`、`runtime=generated_workflow`。
- API 节点输出中的 Authorization 只出现 `Bearer ***`，trace 不泄漏真实 secret。

## 7. Human Approval Smoke

当修改人工审批节点、运行状态、任务 API、worker 等待/恢复逻辑或前端审批入口时必须执行。

```powershell
docker compose up -d --build
.\scripts\migrate-db.ps1
.\scripts\smoke-human-approval.ps1 --base-url http://localhost:8000/api/v1 --timeout 180
```

也可通过总入口执行：

```powershell
.\scripts\check-acceptance.ps1 -IncludeHumanApprovalSmoke -Timeout 180
```

判定标准：

- workflow 发布成功。
- 异步 run 进入 `waiting_approval`。
- 能查询到 pending human approval task。
- 提交 approve 后 run 最终为 `completed`。
- run output 和 trace output 包含 `decision=approve`、`approved=true`，审批节点和输出节点 trace 状态正确。

## 8. DeepSeek 可选真实验收

仅在需要真实模型闭环时执行。执行前确认 `.env` 或运行环境中配置了有效 `DEEPSEEK_API_KEY`，且当前网络能访问 DeepSeek。

```powershell
docker compose up -d --build
.\scripts\migrate-db.ps1
.\scripts\check-deepseek-real.ps1 --base-url http://localhost:8000/api/v1 --timeout 180
```

或通过总入口执行：

```powershell
.\scripts\check-acceptance.ps1 -IncludeDeepSeekReal -Timeout 180
```

判定标准：

- DeepSeek workflow 发布成功。
- 异步 run 最终为 `completed`。
- 输出中 `answer` 非空。
- trace 中 `llm_1` 节点为 `success`。
- 若返回认证、限流、网络或模型错误，本项不通过；记录错误响应并确认是配置/额度问题还是代码回归。

## 9. 验收分级

- 普通后端/前端小改：执行 `.\scripts\check-acceptance.ps1`。
- 影响 Docker、依赖或启动链路：执行 `.\scripts\check-acceptance.ps1 -IncludeDockerBuild`，并人工确认 `docker compose ps`。
- 影响运行时、worker、knowledge、codegen、secret、workflow 节点：加跑 `.\scripts\check-acceptance.ps1 -IncludeOnlineSmoke`。
- 影响 Human Approval：加跑 `.\scripts\check-acceptance.ps1 -IncludeHumanApprovalSmoke -Timeout 180`。
- 影响 LLM provider、DeepSeek、模型密钥或发布前需要真实模型证明：加跑 `.\scripts\check-acceptance.ps1 -IncludeDeepSeekReal -Timeout 180`。

## 10. 验收记录模板

每轮开发完成后在任务回复或 PR 描述中记录：

```text
验收日期：
代码范围：
必跑：
- .\scripts\check-acceptance.ps1：通过/失败，摘要
可选：
- .\scripts\check-acceptance.ps1 -IncludeDockerBuild：未跑/通过/失败，原因
- .\scripts\check-acceptance.ps1 -IncludeOnlineSmoke：未跑/通过/失败，原因
- .\scripts\check-acceptance.ps1 -IncludeHumanApprovalSmoke：未跑/通过/失败，原因
- .\scripts\check-acceptance.ps1 -IncludeDeepSeekReal：未跑/通过/失败，原因
遗留风险：
```
