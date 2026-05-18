# Agent 工作流平台 MVP 技术栈决策文档 v0.1

## 1. 文档目标

本文档记录 Agent 工作流平台 MVP 阶段的最终技术栈选择、保留项、简化项、取舍理由和后续演进路径。

本文档作为 MVP 开发阶段的技术栈基准，后续开发任务、部署方案和项目脚手架均以本文档为准。

---

## 2. MVP 最终技术栈

```text
Frontend: Next.js + React Flow
API: FastAPI
Worker: RQ + Redis
Database: PostgreSQL + pgvector
File Storage: Local filesystem volume
Deployment: Docker Compose single node
Trace: workflow_runs + node_runs in PostgreSQL
Audit: audit_logs in PostgreSQL
Auth: Mock user for MVP, JWT reserved
```

---

## 3. 技术栈决策表

| 模块 | MVP 选择 | 说明 |
|---|---|---|
| 前端 | Next.js + React Flow | 用于工作流编辑器、节点配置面板、运行调试和 Trace 展示 |
| API 服务 | FastAPI | Python 生态更适合 LLM、RAG、文档处理和快速接口开发 |
| Worker | RQ + Redis | 比 Celery + RabbitMQ 更轻，适合 MVP 单机异步任务 |
| 数据库 | PostgreSQL + pgvector | 业务数据、Graph JSON、Trace、知识库 chunk 和向量检索统一存储 |
| 文件存储 | 本地文件系统 volume | MVP 降低运维复杂度，后续可迁移 MinIO / S3 |
| 部署 | Docker Compose 单机 | 避免 MVP 过早引入 Kubernetes |
| 日志与 Trace | PostgreSQL | 先用 workflow_runs / node_runs / audit_logs 承载，不引入 ClickHouse / Jaeger |
| 认证 | Mock user | MVP 不实现真实登录，后端注入默认用户，预留 JWT 接入点 |

---

## 4. 明确删除或延后项

MVP 不引入：

```text
读写分离
ClickHouse 日志库
Jaeger 分布式追踪
MinIO
Kubernetes
RabbitMQ
Celery
Temporal
```

这些能力不是否定，而是延后到业务验证后按需引入。

---

## 5. 选择 FastAPI 的理由

FastAPI 适合本项目 MVP 的原因：

```text
Python AI 生态成熟
文档解析、Embedding、RAG 实现方便
接口开发速度快
类型提示和自动 OpenAPI 生成能力好
与 RQ / Redis 组合简单
```

后端核心模块：

```text
Workflow API
Runtime
Knowledge Base
Document Processing
Tool API
Model Adapter
Secret Service
Trace Query
```

---

## 6. MVP 认证决策

MVP 阶段先使用 mock user，不做真实登录系统。

默认 mock user：

```json
{
  "id": 1,
  "email": "admin@example.com",
  "username": "admin",
  "display_name": "MVP Admin",
  "role": "admin"
}
```

后端行为：

```text
开发和测试环境默认注入 mock current_user
所有 created_by / updated_by / published_by / run.created_by 使用 mock user id
PermissionService 仍保留 Admin / Editor / Viewer 角色判断
API 层保留 Authorization Header 解析入口
真实 JWT 登录后续再接入
```

环境变量建议：

```text
AUTH_MODE=mock
MOCK_USER_ID=1
MOCK_USER_ROLE=admin
```

后续演进：

```text
mock user → JWT 登录 → 组织/团队/RBAC
```

---

## 7. 选择 RQ + Redis 的理由

RQ 适合 MVP 的原因：

```text
接入简单
依赖少
基于 Redis，Docker Compose 部署方便
适合文档处理和工作流异步运行
Python 代码直接复用 API 项目服务层
```

MVP 队列建议：

```text
workflow_runs
document_processing
embedding
```

RQ 的限制：

```text
复杂任务路由能力弱于 Celery
任务监控能力弱于 Celery
复杂定时任务不是强项
大规模 worker 管理能力有限
```

处理策略：

```text
MVP 接受这些限制
需要复杂调度时再迁移到 Celery 或 Temporal
```

---

## 8. 选择 PostgreSQL + pgvector 的理由

PostgreSQL + pgvector 适合 MVP 的原因：

```text
一套数据库承载业务数据和向量检索
支持 JSONB，适合 graph_json 和节点配置
支持事务，适合发布版本和运行状态
支持全文搜索基础能力
降低运维复杂度
```

MVP 存储内容：

```text
workflows
workflow_versions
workflow_runs
node_runs
knowledge_bases
documents
knowledge_chunks
document_processing_jobs
tools
model_providers
model_configs
secrets
audit_logs
```

后续演进：

```text
向量规模变大后迁移到 Qdrant / Milvus
日志规模变大后拆到 ClickHouse / OpenSearch
读压力变大后再做读写分离
```

---

## 9. 选择本地文件系统的理由

MVP 使用本地文件系统 volume：

```text
部署简单
开发和调试方便
不需要额外对象存储服务
适合单机 Docker Compose
```

必须要求：

```text
上传目录必须挂载 Docker volume
文档原始文件和解析中间文件分目录保存
测试环境需要备份策略
文件路径不能直接暴露给前端
```

建议目录：

```text
/data/agent-workflow/uploads
/data/agent-workflow/documents
/data/agent-workflow/parsed
```

后续演进：

```text
迁移到 MinIO
迁移到 S3 / OSS / COS
```

---

## 10. 选择 Docker Compose 单机部署的理由

MVP 不上 Kubernetes，原因：

```text
降低部署门槛
降低调试复杂度
方便本地和测试环境一致
减少平台工程投入
```

Docker Compose 服务：

```text
frontend
api
worker-workflow
worker-document
postgres
redis
```

可选服务：

```text
adminer / pgadmin
redisinsight
```

---

## 11. Trace 与日志策略

MVP 不引入 Jaeger 和 ClickHouse。

运行 Trace：

```text
workflow_runs
node_runs
```

审计日志：

```text
audit_logs
```

应用日志：

```text
容器 stdout
按 Docker / 部署环境采集
```

MVP 要求：

```text
node_runs 记录节点输入、输出、状态、错误、耗时和 metadata
敏感信息必须脱敏
大字段需要截断策略
运行日志需要保留策略
```

建议保留策略：

```text
workflow_runs 保留 90 天
node_runs 保留 90 天
audit_logs 保留 180 天
上传原始文件按业务策略保留
```

---

## 12. 后续演进路径

当 MVP 验证后，可以按以下顺序升级：

```text
文件存储：Local filesystem → MinIO → S3 / OSS
任务队列：RQ → Celery / Temporal
日志分析：PostgreSQL → ClickHouse / OpenSearch
Trace：node_runs → OpenTelemetry / Jaeger
向量检索：pgvector → Qdrant / Milvus
部署：Docker Compose → Kubernetes
数据库：单 PostgreSQL → 主从 / 读写分离
```

---

## 13. 最终结论

MVP 技术栈以“低复杂度、快落地、可演进”为核心。

最终采用：

```text
Next.js + React Flow
FastAPI
RQ + Redis
PostgreSQL + pgvector
Local filesystem volume
Docker Compose
PostgreSQL Trace / Audit
Mock user auth
```

这套技术栈足够支撑第一版完成：

```text
可视化编辑
工作流发布
Runtime 执行
知识库检索
API 调用
运行 Trace
MVP 单机部署
```
