# Agent Flow Operations

本文档记录 Agent Flow MVP/M6 收尾后的部署运维最终状态、生产部署 checklist 和常见故障排查。当前目标是支持本地 Compose 复现和测试环境试用，不把现有能力表述为企业生产级 KMS、监控、告警或自动化备份平台。

## 1. 当前状态

MVP 核心链路已经完成：

- 工作流创建、保存、校验、发布和版本化。
- 发布时生成 `backend/generated_workflows` 本地 Python 代码，运行时按发布版本加载。
- 同步运行由 API 直接执行，异步运行进入 Redis 队列，由 `worker-workflow` 执行。
- Knowledge 文档上传、worker 处理、pgvector 检索和关键词回退。
- Intent、Branch、API、Message、LLM、Output 等核心节点闭环。
- Trace 展示 generated code metadata、节点 input/output/error/metadata，并对敏感 header 做脱敏。
- `/api/v1/health`、`/api/v1/ready`、`npm run smoke:e2e` 可作为基础部署验收入口。

M6 生产化基础收尾已完成：

- 本地 Compose 编排覆盖 PostgreSQL、Redis、API、Frontend、workflow worker、document worker。
- 数据库补丁脚本 `npm run db:migrate` 可对已有本地 volume 补齐 002/003 migration。
- `.env.example` 提供本地环境变量样例。
- smoke 覆盖 generated workflow、sync/async、Knowledge、Intent/Branch、API/Message 和 trace 脱敏。
- 文档明确本地开发能力、测试环境验收路径、生产部署 checklist 和故障排查边界。

仍属于后续工作：

- 完整认证授权、组织/项目空间/角色/资源级权限。
- 企业生产级 KMS、密钥轮换和审计。
- 集中指标、日志聚合、告警和值班流程。
- 自动化备份恢复、容量规划、灾备和回滚演练。
- 对象存储、病毒扫描、API 外呼 allowlist/网关和更严格公网安全策略。

## 2. 本地 Compose 与生产差异

当前 `compose.yaml` 是开发/测试用途：

- API 使用 `uvicorn --reload --reload-dir app`，前端使用 `npm run dev`。
- 后端和前端源码通过 bind mount 挂入容器，改动会影响运行容器。
- 上传文件存在 `./storage/uploads` 对应的本地文件系统目录。
- Redis 对外端口是 `6380`，容器内部地址是 `redis://redis:6379/0`。
- 默认用户通过 `MOCK_USER_ID` 表达本地测试身份，不是完整身份系统。
- API Node mock 模式用于本地和 smoke；真实 HTTP 模式已有内网地址阻断，但生产仍需外呼治理。
- Secret 当前由应用配置的 `SECRET_ENCRYPTION_KEY` 加密，并在 API/Trace 中脱敏，不等于 KMS。

生产环境应替换为正式镜像、非 reload 进程、受管 PostgreSQL/Redis、持久上传存储、真实认证授权、安全 secret 分发、集中日志和备份回滚流程。

## 3. 生产部署 Checklist

### 3.1 Env / Secrets

- 为每个环境独立维护 `.env` 或等价 secret 配置，不复用 `.env.example` 的默认密码和开发 key。
- 设置 `DATABASE_URL` 指向生产 PostgreSQL，并确认账号权限最小化。
- 设置 `REDIS_URL` 指向生产 Redis，注意容器内外主机名和端口差异。
- 设置 `SECRET_ENCRYPTION_KEY`，长度不少于 32 字符，并通过安全渠道分发。
- 设置 `OPENAI_API_KEY` 或通过平台 Secret 创建 `openai_api_key`；缺少 key 时 OpenAI 节点会明确失败。
- 设置 `CORS_ALLOWED_ORIGINS` 为实际前端域名，删除无关 localhost。
- 设置 `STORAGE_DIR` 到持久化上传目录或替换为后续对象存储方案。
- 检查 `MAX_UPLOAD_BYTES` 和 `ALLOWED_UPLOAD_CONTENT_TYPES` 符合环境要求。

### 3.2 DB Migration

- 新库首次启动需执行 `001_init_agent_workflow_platform_mvp.sql`、`002_observability_and_governance.sql`、`003_generated_workflow_code.sql`。
- 已有库执行 `npm run db:migrate` 或等价 SQL，确认 002/003 已应用。
- 确认 `pgvector` 扩展可用。
- 确认 `knowledge_chunks.embedding` 与当前 1536 维 embedding 约定一致。
- 发布前备份数据库，并记录 migration 文件和应用版本。

### 3.3 Worker

- API、`worker-workflow`、`worker-document` 使用同一套 `DATABASE_URL`、`REDIS_URL`、`STORAGE_DIR`、`SECRET_ENCRYPTION_KEY`。
- 异步工作流必须有 `worker-workflow` 消费 Redis 队列。
- 文档上传后必须有 `worker-document` 轮询并处理 `document_processing_jobs`。
- worker 日志需要能被运维系统查看；当前仓库只提供 stdout/stderr 日志输出。

### 3.4 Health / Ready

- `GET /api/v1/health` 返回 `{"status":"ok"}`。
- `GET /api/v1/ready` 返回 `{"status":"ready"}`。
- `/ready` 的 `checks.database`、`checks.redis`、`checks.encryption_key`、`checks.default_model_provider` 均为 `ok`。
- 若 `/health` 正常但 `/ready` 失败，优先排查数据库、Redis、`SECRET_ENCRYPTION_KEY` 和模型 provider 配置。

### 3.5 Smoke

部署后执行：

```powershell
npm run smoke:e2e
```

该脚本默认访问 `http://localhost:8000/api/v1`。生产或测试环境如果不是本机地址，需要使用等价 smoke 方式或临时代理到目标 API。

需要确认：

- generated workflow 发布成功并写入 code metadata。
- 同步和异步运行均 completed。
- Knowledge 文档 indexed，vector retrieve 返回 chunks。
- Intent + Branch 路由正确。
- API + Message 输出正确，Authorization 在 output/trace 中脱敏。

### 3.6 Backup

- 发布前备份 PostgreSQL。
- 备份上传文件目录或对象存储桶，并确认恢复路径。
- 记录当前镜像 tag、migration 列表、环境变量变更和发布时间。
- 当前仓库没有内置自动备份和恢复编排，生产环境需由外部平台提供。

### 3.7 Logs

- API 日志至少要能按 request/run/workflow/node/error 线索定位问题。
- `worker-workflow` 日志用于定位异步 run pending、failed 或执行异常。
- `worker-document` 日志用于定位文档 parse/index failed。
- PostgreSQL 和 Redis 日志用于定位连接、容量、持久化和启动问题。
- 当前仓库未内置集中日志平台、指标采集或告警规则。

### 3.8 Rollback

- 前端回滚到上一构建。
- API 和 worker 回滚到上一镜像。
- 数据库 migration 应优先保持向前兼容；如需数据回滚，先保全当前数据，再按备份恢复方案执行。
- `workflow_versions` 是不可变发布记录，通常不需要回滚历史版本数据；如代码生成目录丢失，需要从镜像/备份/发布记录恢复对应版本代码。

## 4. 常见故障排查

### 4.1 Redis 端口

现象：

- `/ready` 中 `redis` 失败。
- 异步运行创建后长期 `pending`。
- 本机 `redis-cli -p 6379 ping` 失败。

处理：

- 宿主机访问本地 Compose Redis 使用 `localhost:6380`。
- 容器内部访问 Redis 使用 `redis://redis:6379/0`。
- 检查 `.env` 中 `REDIS_PORT=6380` 和 `REDIS_URL=redis://redis:6379/0` 是否混用到了错误场景。
- 执行 `docker compose exec -T redis redis-cli ping`，应返回 `PONG`。

### 4.2 Docker API

现象：

- `npm run compose:up` 或 `docker compose ps` 报 Docker daemon/API 无响应。

处理：

- 确认 Docker Desktop 已启动。
- 执行 `docker --version`、`docker compose version`、`docker compose ps`。
- 如果 Docker Desktop 刚启动，等待后重试；仍失败时重启 Docker Desktop。
- Windows 环境下确认当前终端可以访问 Docker CLI。

### 4.3 Async Pending

现象：

- `POST /workflows/{id}/run` 使用 `execution_mode=async` 后 run 长期为 `pending`。

处理：

- 检查 `docker compose ps worker-workflow` 是否运行。
- 查看 `docker compose logs worker-workflow` 是否有 Redis、DB 或 generated workflow import 错误。
- 检查 `/api/v1/ready` 的 `database` 和 `redis`。
- 确认 API 和 worker 使用同一个 `REDIS_URL` 和 `DATABASE_URL`。
- 对单个 run 可查询 `GET /api/v1/runs/{run_id}` 和 `GET /api/v1/runs/{run_id}/trace` 定位状态。

### 4.4 generated_workflows reload

现象：

- 手动修改 `backend/generated_workflows/.../workflow.py` 后行为没有立即变化。
- API reload 没有被触发。

处理：

- Compose API reload 只监听 `/app/app` 目录，`backend/generated_workflows` 不触发 reload。
- generated workflow 运行时会按发布版本路径加载，并记录 hash 是否变更。
- 修改后重新运行对应工作流验证；如果 worker 进程缓存或导入路径导致不确定，重启 API 和 worker 后再验证。
- 生产环境不建议手动修改 generated workflow，应该通过重新发布工作流版本生成新目录。

### 4.5 Postgres Volume Migration

现象：

- 新字段不存在，例如 generated code metadata 相关列缺失。
- 重启 Compose 后 migration 没有重新执行。

原因：

- PostgreSQL 只会在首次创建 `postgres_data` volume 时执行 `/docker-entrypoint-initdb.d`。

处理：

- 保留数据时执行：

```powershell
npm run db:migrate
```

- 或手动执行缺失 SQL。
- 只有确认可以丢弃本地数据时，才执行：

```powershell
docker compose down -v
npm run compose:up
```

## 5. 发布验收最小口径

发布完成后至少确认：

- `/api/v1/health` 正常。
- `/api/v1/ready` 为 `ready`。
- 前端可访问，API base URL 指向正确环境。
- workflow 可创建、发布、同步运行、异步运行。
- `worker-workflow` 能消费异步 run。
- 知识库文档可上传并 indexed。
- `worker-document` 能处理文档任务。
- Trace 能查询节点 input/output/error/metadata。
- Secret 列表不返回明文，API/Trace 中敏感 header 脱敏。
- 发布前数据库和上传文件已有备份。
