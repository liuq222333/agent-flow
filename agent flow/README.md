# Agent Flow

Agent 工作流平台 MVP 环境骨架。

## 当前进度

截至 Milestone 6 收尾阶段，M0-M5 核心闭环已基本完成，M6 生产化基础收尾已完成到“可本地 Compose 复现、可测试环境试用、可按清单部署验收”的状态。当前项目已经支持：

- Generated workflow code：发布版本时生成本地版本化 Python workflow，并在运行时按发布记录加载。
- sync / async run：同步运行直接由 API 执行，异步运行通过 Redis 队列交给 `worker-workflow`。
- Knowledge vector retrieve：知识库 chunks 支持 pgvector cosine 检索，必要时回退关键词检索。
- Intent + Branch：支持意图识别输出和分支路由。
- API + Message：支持 API 节点响应映射、Message 追加和敏感 header 脱敏。
- Trace code metadata：运行 trace 可看到生成代码路径、hash、是否被本地修改等代码元数据。
- Trace 节点 input/output 展开：前端 trace 面板可展开节点输入、输出、错误与 metadata，便于定位问题。
- Ops 队列与 worker 运维入口已覆盖 workflow/document worker 心跳、workflow run 队列深度、dead-letter 查看和恢复动作。

仍需后续增强：

- 更完整的权限系统，包括组织 / 项目空间 / 角色 / 资源级授权。
- 生产级监控、指标采集、告警与日志聚合。
- 生产级 secret / KMS 集成、密钥轮换和更细粒度审计。
- 更多文件类型解析、文档解析质量增强和更大规模索引能力。
- 更严格的生产部署基线，例如公网访问策略、备份恢复、容量规划和发布回滚演练。

当前生产化边界：

- 已具备基础 health / ready / metrics 检查、Ops 队列入口、幂等数据库补丁脚本、本地 Compose 编排、workflow/document worker、端到端 smoke、Secret 脱敏和 trace 定位能力。
- 本仓库当前没有声明已具备企业生产级 KMS、集中监控告警、日志聚合、自动化备份恢复、灰度发布或完整多租户权限体系。
- 生产部署前请以 [OPERATIONS.md](OPERATIONS.md) 和 [agent_workflow_platform_testing_deployment_v_1.md](agent_workflow_platform_testing_deployment_v_1.md) 的 checklist 为准逐项确认。

## 技术栈

- Frontend: Next.js + React Flow
- API: FastAPI
- Worker: Redis-backed workflow/document workers
- Database: PostgreSQL + pgvector
- File storage: local filesystem volume
- Deployment: Docker Compose

## 本地启动

请先确保 Docker Desktop 已启动。

```powershell
cd "D:\xm\agent flow\agent flow"
.\scripts\check-env.ps1
npm run compose:up
npm run compose:ps
npm run smoke:e2e
npm run compose:down
```

`npm run compose:up` 会先启动 PostgreSQL/Redis，然后执行幂等数据库补丁脚本，再启动 API、前端和 worker。
`npm run compose:ps` 用于查看容器状态，`npm run compose:down` 用于停止 Compose 环境。

完整服务包括：

- PostgreSQL + pgvector
- Redis
- FastAPI API
- Next.js frontend
- workflow worker
- document worker

如果只需要启动基础设施：

```powershell
.\scripts\dev.ps1
```

该脚本同样会自动执行 `002_observability_and_governance.sql` 和 `003_generated_workflow_code.sql`，用于补齐已有本地数据卷的 schema。

如果需要不依赖 Docker 运行后端与前端：

```powershell
cd "D:\xm\agent flow\agent flow\backend"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

```powershell
cd "D:\xm\agent flow\agent flow\frontend"
npm install
npm run dev -- --hostname 0.0.0.0 --port 3000
```

## 验收检查

本机检查：

```powershell
cd "D:\xm\agent flow\agent flow"
npm run check:local
```

容器内检查：

```powershell
docker compose exec -T api pytest
docker compose exec -T api ruff check .
docker compose exec -T frontend npm run typecheck
docker compose exec -T frontend npm run lint
```

连通性检查：

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/ready
docker compose exec -T redis redis-cli ping
docker compose exec -T postgres psql -U agent_flow -d agent_flow -c "select count(*) as tables from information_schema.tables where table_schema='public';"
```

## 服务地址

- API health: http://localhost:8000/api/v1/health
- API ready: http://localhost:8000/api/v1/ready
- API metrics: http://localhost:8000/api/v1/metrics
- Ops queues: http://localhost:8000/api/v1/ops/queues
- API docs: http://localhost:8000/api/docs
- Frontend: http://localhost:3000
- PostgreSQL: localhost:5432
- Redis: localhost:6380

Redis 对外端口默认使用 `6380`，避免和本机已有 Redis 的常用 `6379` 端口冲突。容器内部仍使用 `redis://redis:6379/0`。

Docker Compose 中 API 服务使用 `uvicorn --reload --reload-dir app`，只监听容器内 `/app/app` 目录。`backend/generated_workflows` 是运行时生成代码目录，不会触发 API reload；手动修改 generated workflow 后需要重新运行工作流或重启相关服务来验证行为。

Docker / 端口验收时请同时确认 Docker Desktop 已启动、`docker compose ps` 中 api/frontend/worker/postgres/redis 均为运行状态，宿主机访问 Redis 使用 `localhost:6380`，前端如切到 `3001` 需同步检查 `CORS_ALLOWED_ORIGINS`。

## 本地 Compose 与生产差异

当前 `compose.yaml` 面向本地开发和测试验收：

- API 使用 `uvicorn --reload`，前端使用 `npm run dev`，适合快速开发，不等同于生产进程模型。
- `./backend:/app` 和 `./frontend:/app` 以 bind mount 进入容器，`./storage/uploads:/data/uploads` 使用本地文件系统保存上传文件。
- Redis 对外端口映射为 `6380:6379`，容器内部仍使用 `redis://redis:6379/0`。
- 默认用户来自 `MOCK_USER_ID`，属于本地 / 测试边界，不是完整登录、组织、角色和资源级授权。
- API Node 默认可使用 mock 模式；`mode=http` 虽有内网地址阻断，但生产外呼策略仍需要额外网关、allowlist、审计和超时预算。
- Secret 当前是应用侧加密和接口脱敏，不代表已接入 KMS、密钥轮换或企业审计系统。

生产部署需要至少替换为正式镜像、非 reload 进程、生产数据库和 Redis、持久化上传存储、真实认证授权、受管 secret 策略、日志采集、备份恢复和回滚流程。

## 生产部署 Checklist

上线前逐项确认：

- Env / secrets：`.env` 不使用示例密码；`DATABASE_URL`、`REDIS_URL`、`SECRET_ENCRYPTION_KEY`、`DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`CORS_ALLOWED_ORIGINS`、`STORAGE_DIR`、上传大小和类型限制均按环境配置；`SECRET_ENCRYPTION_KEY` 长度不少于 32 字符并由安全渠道分发。
- DB migration：空库已执行 `001`，已有库已执行 `npm run db:migrate` 或等价 SQL；`pgvector` 可用；`knowledge_chunks.embedding` 为当前 1536 维约定。
- Worker：`worker-workflow` 和 `worker-document` 均独立运行；异步工作流和文档处理不会长期停留在 `pending`。
- Ops：前端 Ops 页面和 `/api/v1/ops/*` 已支持 workflow/document worker 心跳、Redis 队列积压、dead-letter 查看和恢复动作；document worker 处理详情仍通过 `docker compose logs worker-document` 和文档任务状态验证。
- Health / ready：`/api/v1/health` 返回 `ok`，`/api/v1/ready` 返回 `ready`，并检查 database、redis、encryption_key、default_model_provider。
- Smoke：部署后执行 `npm run smoke:e2e` 或等价脚本，覆盖 generated workflow、sync/async、Knowledge、Intent/Branch、API/Message 和 trace 脱敏。
- Backup：发布前备份 PostgreSQL；确认上传文件目录或对象存储已有备份策略；记录当前镜像 tag、migration 版本和 `.env` 变更。
- Logs：确认 API、workflow worker、document worker、PostgreSQL、Redis 日志可查看；生产环境应接入集中日志，但当前仓库只提供应用日志输出。
- Rollback：前端回滚到上一构建，后端和 worker 回滚到上一镜像；数据库变更优先向前兼容，回滚前先恢复或保全数据备份。

更细的上线步骤和排障见 [OPERATIONS.md](OPERATIONS.md)。

## 当前 MVP 闭环

目前已经实现第一条纵向链路：

- 创建工作流：`POST /api/v1/workflows`
- 保存草稿：`PUT /api/v1/workflows/{workflow_id}`
- 图校验：`POST /api/v1/workflows/{workflow_id}/validate`
- 发布版本：`POST /api/v1/workflows/{workflow_id}/publish`
- 同步 / 异步运行：`POST /api/v1/workflows/{workflow_id}/run`
- 查询运行与 trace：`GET /api/v1/runs/{run_id}/trace`
- 节点类型目录：`GET /api/v1/node-types`
- 知识库与文档：`/api/v1/knowledge-bases`、`/api/v1/documents/{document_id}`
- API 工具：`/api/v1/tools`
- Secret 元数据：`/api/v1/secrets`
- 模型配置：`/api/v1/model-providers`、`/api/v1/model-configs`

Runtime 当前使用本地 generated workflow 执行模式：发布工作流时生成版本化 Python 代码，运行时 import 对应版本的本地代码执行，并真实写入 `workflow_runs` 和 `node_runs`。同步运行直接在 API 内执行；异步运行会创建 pending run 并通过 Redis list 交给 `worker-workflow` 执行。

前端控制台目前包含 Workflow / Knowledge / Tools / Secrets / Models / Ops 六个入口。Workflow 编辑器支持节点库、连线同步、节点 JSON 配置、发布、同步/异步运行和 trace 定位。Trace 面板支持查看 code metadata，并可展开每个节点的 input、output、error 和 metadata。Knowledge 可以创建知识库、上传文档、重试/删除文档，并由 `worker-document` 解析为 chunks 后检索。Tools 支持创建、编辑和测试 API tool；Secrets 支持创建与更新，但列表只展示脱敏元数据；Ops 支持查看 workflow/document worker 心跳、workflow run 队列、dead-letter 和恢复动作。

当前 LLM Node 默认使用 DeepSeek 配置项：`provider=deepseek`、`model=deepseek-v4-flash`，界面展示为 DeepSeek V4-Flash；运行时会使用 `DEEPSEEK_API_KEY` 或 active secret `deepseek_api_key` 通过 `https://api.deepseek.com` 调用 OpenAI-compatible Chat Completions。DeepSeek 默认以 `thinking_mode=false` 调用，后续可在节点配置中显式开启。缺少 key 时 DeepSeek 节点会明确失败。保留 `provider=mock` 本地模拟模式；如果节点配置 `provider=openai`，运行时会使用 `OPENAI_API_KEY` 或 active secret `openai_api_key` 调用 OpenAI。Intent Node 支持本地关键词分类，也可以配置 OpenAI 分类。API Node 默认使用安全 mock 模式，`mode=http` 仅允许公共 HTTP/HTTPS 地址，会阻止 localhost、private network、link-local 等目标。Knowledge Base Node 会优先使用 `knowledge_chunks.embedding` 走 pgvector cosine 检索；没有向量或向量检索不可用时自动回退到关键词检索。默认 `local-hash` / `local-embedding` 模式可离线生成 1536 维向量，配置 `embedding_provider=openai` 时会使用 OpenAI embedding。

`npm run smoke:e2e` 会创建测试知识库、上传文档、验证 vector retrieve、发布 generated workflow code，并分别跑同步/异步工作流、Knowledge Runtime、Intent + Branch、API + Message 工作流；其中 API smoke 会验证变量映射、Message/最终输出和敏感 header trace 脱敏，适合作为每轮开发后的回归验收。

如果前端临时使用 `3001` 等非默认端口，请在 `.env` 中调整 `CORS_ALLOWED_ORIGINS`。默认已经放行 `http://localhost:3000`、`http://127.0.0.1:3000`、`http://localhost:3001` 和 `http://127.0.0.1:3001`。

## Generated Workflow Runtime / Codegen

当前版本已经实现本地工作流代码生成与运行：

- 发布工作流时基于 `workflow_versions.graph_json` 自动生成 `workflow.py` 和 `manifest.json`。
- 运行工作流时优先使用发布版本记录的 `code_path` import 本地生成代码执行。
- 运行前重新计算本地代码 hash；hash 与发布记录不一致时记录 `code_modified=true`，但不阻止运行。
- 生成代码是本地可编辑源码；如果手动修改 `workflow.py`，后续运行按修改后的本地文件执行。

生成目录按 `workflow_id + version` 隔离，不引入业务区域、项目空间或文件夹模型：

```text
backend/generated_workflows/
  workflow_000001/
    v000001/
      __init__.py
      workflow.py
      manifest.json
```

约定：

- 草稿阶段仍只保存 `workflows.draft_graph_json`。
- 发布阶段仍创建不可变 `workflow_versions.graph_json`，同时写入生成代码路径与 hash。
- 每次发布生成新的版本目录，例如 `v000001`、`v000002`，不覆盖旧版本代码。

## 数据库初始化

`compose.yaml` 会在 PostgreSQL 首次创建数据卷时自动执行：

1. `001_init_agent_workflow_platform_mvp.sql`
2. `002_observability_and_governance.sql`
3. `003_generated_workflow_code.sql`

如果已有旧数据卷，PostgreSQL 不会自动重跑初始化 SQL。保留数据时请手动执行 003 migration：

```powershell
docker compose exec -T postgres psql -U agent_flow -d agent_flow -f /docker-entrypoint-initdb.d/003_generated_workflow_code.sql
```

也可以直接运行项目脚本补齐幂等补丁：

```powershell
npm run db:migrate
```

如果可以丢弃本地数据库，也可以重建 volume，让 initdb 重新执行全部 SQL：

```powershell
docker compose down -v
npm run compose:up
```

## 常见故障排查

- Redis 端口：宿主机访问 `localhost:6380`，容器内访问 `redis://redis:6379/0`。如果连接 `localhost:6379` 失败，先确认使用的是宿主机还是容器内地址。
- Docker API：`npm run compose:up` 前确认 Docker Desktop 已启动，`docker compose ps` 可返回服务列表；如果 Docker API 无响应，重启 Docker Desktop 后再执行。
- Async pending：异步 run 长期 `pending` 时检查 `docker compose ps worker-workflow`、`docker compose logs worker-workflow`、`/api/v1/ops/queues`、`/api/v1/ops/workers` 和 `/api/v1/ready` 的 redis/database 检查。
- `generated_workflows` reload：Compose API reload 只监听 `app` 目录，手改 `backend/generated_workflows` 不会触发 API 重载；重新运行工作流或重启 API / worker 后验证。
- Postgres volume migration：已有 `postgres_data` volume 不会自动重跑 `/docker-entrypoint-initdb.d`；保留数据请执行 `npm run db:migrate`，可丢弃本地数据时才使用 `docker compose down -v`。

## 当前已知事项

- `npm audit --audit-level=high` 通过。
- `npm audit` 仍会报告 Next.js 依赖链上的 PostCSS moderate 级别提示；当前自动修复建议会强制降级 Next.js，暂不建议执行 `npm audit fix --force`。
