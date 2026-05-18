# Agent 工作流平台实现细节补丁 v0.1

## 0. 文档说明

本文档处理 `design_review_v0.1_claude.md` 中余下的实现细节缺失（G11-G12、G14-G20）与残留风险（R1-R4）：

```text
G11 pgvector 检索 SQL 模板
G12 embedding 维度演进策略
G14 tokenizer 选型
G15 异步运行 trace 增量推送
G16 文件上传具体限制
G17 audit action 枚举
G18 节点级事务边界
G19 重试时 input_mapping 重新解析
G20 并发同一 workflow 多 run 隔离
R1  Branch target 强约束（已在 consistency C4 处理，本文档收录补充实现）
R2  pgvector 索引策略
R4  graph_migrator 框架
```

本文档目标：让实施者拿到代码模板和清单，避免"自由发挥"。

---

## 1. 通用约定

```text
所有数据库 SQL：PostgreSQL 14+ 方言
所有 Python 代码片段：FastAPI + SQLAlchemy 2.x + Pydantic v2
所有时间戳：TIMESTAMPTZ，UTC 存储，前端转本地时区
所有 ID：DB 主键 BIGINT，graph 内引用同 BIGINT
所有变量名：snake_case
所有错误：raise RuntimeNodeError(error_code, message)，不 raise 通用 Exception
```

---

## 2. pgvector 检索 SQL 模板（G11）

### 2.1 基础检索

```sql
-- 输入参数：
--   $1 = query embedding，vector(1536)
--   $2 = knowledge_base_ids BIGINT[]
--   $3 = score_threshold（如 0.65）
--   $4 = top_k（如 5）
--   $5 = status filter（默认 'indexed'）
SELECT
  c.id AS chunk_id,
  c.knowledge_base_id,
  c.document_id,
  c.chunk_index,
  c.content,
  c.token_count,
  c.metadata_json,
  d.file_name,
  d.metadata_json AS document_metadata,
  1 - (c.embedding <=> $1::vector) AS score
FROM knowledge_chunks c
JOIN documents d ON d.id = c.document_id
WHERE c.knowledge_base_id = ANY($2)
  AND c.status = $5
  AND d.deleted_at IS NULL
  AND c.embedding IS NOT NULL
  AND (1 - (c.embedding <=> $1::vector)) >= $3
ORDER BY c.embedding <=> $1::vector
LIMIT $4;
```

`<=>` 是 pgvector 的 cosine distance 运算符。`1 - distance` 转为 cosine similarity。

### 2.2 元数据过滤扩展

```sql
-- 增加元数据过滤，例如 metadata_json @> '{"tags": ["售后"]}'
SELECT ...
FROM knowledge_chunks c
JOIN documents d ON d.id = c.document_id
WHERE c.knowledge_base_id = ANY($2)
  AND c.status = 'indexed'
  AND d.deleted_at IS NULL
  AND (1 - (c.embedding <=> $1::vector)) >= $3
  AND ($6::jsonb IS NULL OR d.metadata_json @> $6::jsonb)
ORDER BY c.embedding <=> $1::vector
LIMIT $4;
```

`$6` 是 metadata filter，例如 `'{"tags": ["售后"], "language": "zh"}'::jsonb`。

### 2.3 混合检索（v0.2）

向量 + 关键词（PostgreSQL `tsvector`）：

```sql
-- 假设 knowledge_chunks 增加 content_tsv tsvector 字段并建索引
SELECT
  c.id,
  c.content,
  -- 加权融合
  0.6 * (1 - (c.embedding <=> $1::vector)) +
  0.4 * ts_rank_cd(c.content_tsv, plainto_tsquery('simple', $2)) AS score
FROM knowledge_chunks c
WHERE c.knowledge_base_id = ANY($3)
  AND c.status = 'indexed'
  AND (
    (1 - (c.embedding <=> $1::vector)) >= 0.5
    OR c.content_tsv @@ plainto_tsquery('simple', $2)
  )
ORDER BY score DESC
LIMIT $4;
```

MVP 不需要做，留 v0.2。

### 2.4 RetrievalService 伪代码

```python
class RetrievalService:
    async def retrieve(
        self,
        kb_ids: list[int],
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.65,
        filters: dict | None = None,
    ) -> list[Chunk]:
        # 1. 生成 query embedding
        query_vec = await self.embedding_client.embed_one(query)

        # 2. 校验所有 kb 使用同一 embedding 维度
        kbs = await self.kb_repo.get_many(kb_ids)
        dims = {kb.embedding_dim for kb in kbs}
        if len(dims) > 1:
            raise RuntimeNodeError(
                error_code="vector_search_error",
                message="cannot mix knowledge bases with different embedding dims",
            )

        # 3. 调用 repository
        rows = await self.chunk_repo.vector_search(
            kb_ids=kb_ids,
            query_vec=query_vec,
            score_threshold=score_threshold,
            top_k=top_k,
            filters=filters,
        )

        # 4. 截断 context_budget_tokens
        return self._trim_to_budget(rows, budget=...)
```

### 2.5 索引选择（R2）

#### 2.5.1 阶段化策略

```text
chunks < 10,000：无索引也可接受（顺序扫描）
10,000 - 1,000,000：HNSW 索引（推荐）
> 1,000,000：HNSW + 分区或 IVFFlat
```

#### 2.5.2 HNSW 索引

```sql
-- pgvector >= 0.5.0 支持
CREATE INDEX idx_chunks_embedding_hnsw
  ON knowledge_chunks
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
```

参数说明：

```text
m              每个节点的连接数，越大召回越好，构建越慢，默认 16
ef_construction 构建质量，建议 64-128
查询时可以调整 ef_search:
  SET hnsw.ef_search = 100;  -- 默认 40
```

#### 2.5.3 IVFFlat 索引（备选）

```sql
-- 适合海量数据，但需要先有数据再建索引
CREATE INDEX idx_chunks_embedding_ivfflat
  ON knowledge_chunks
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
```

```text
lists 经验值：sqrt(N) 或 N/1000
查询时调整：SET ivfflat.probes = 10;
```

#### 2.5.4 索引重建触发

```text
触发场景：
  1. KB 内 chunks 数量首次超过 10000 → 创建 HNSW
  2. chunks 超过 1000000 → 评估迁移 IVFFlat
  3. embedding model 切换 → 重建索引

实施：
  Document Processing Worker 每次完成 indexing 后检查 chunk 数量
  超过阈值时入队"建索引"任务
  建索引使用 CONCURRENTLY 避免锁表
```

#### 2.5.5 索引大小估算

```text
1536 维 vector，单条 ≈ 6KB（含 HNSW 元数据 ≈ 8KB）
100 万 chunks ≈ 8 GB 索引
内存：HNSW 推荐 RAM 容纳整个索引
```

如果 8GB 内存吃不下，切 IVFFlat。

---

## 3. embedding 维度演进策略（G12）

### 3.1 当前问题

```text
SQL: embedding vector(1536) 硬编码
ER: knowledge_bases.embedding_model 字段存模型名
关联：1536 维 = OpenAI text-embedding-3-small / -large
若 KB A 用 OpenAI（1536），KB B 用 BGE-M3（1024），同一列存不下
```

### 3.2 MVP 策略：单维度锁定

#### 3.2.1 表结构改动

```sql
ALTER TABLE knowledge_bases
  ADD COLUMN embedding_dim INT NOT NULL DEFAULT 1536;

ALTER TABLE knowledge_bases
  ADD CONSTRAINT chk_kb_embedding_dim
    CHECK (embedding_dim = 1536);
```

#### 3.2.2 KB 创建时锁定

```text
创建 KB：
  请求中 embedding_model 必填
  后端查 model_configs 拿到 dimensions
  写入 knowledge_bases.embedding_dim
  之后永不允许修改

向量列保持 vector(1536)（容纳当前主流）
若 dim < 1536：在前 dim 维存有效数据，后面 padding 0
  检索时使用相同 padding，cosine 距离不变（数学上等价）
若 dim > 1536：拒绝（v0.2 解决）
```

#### 3.2.3 KnowledgeBase API 校验

```python
@router.post("/knowledge-bases")
async def create_kb(req: CreateKBRequest):
    model_config = await get_model_config(req.embedding_model)
    if model_config.model_type != "embedding":
        raise HTTPException(400, "not an embedding model")
    dim = model_config.default_config_json.get("dimensions")
    if dim not in {768, 1024, 1536}:
        raise HTTPException(400, "unsupported embedding dim")
    # 创建 KB，写入 embedding_dim
    ...
```

#### 3.2.4 RetrievalService 跨 KB 校验

见 §2.4 第 2 步：检索时如果多个 kb_id 的 embedding_dim 不同，拒绝。

### 3.3 v0.2 演进：多列或分表

#### 3.3.1 多列方案

```sql
ALTER TABLE knowledge_chunks
  ADD COLUMN embedding_768  vector(768),
  ADD COLUMN embedding_1024 vector(1024),
  ADD COLUMN embedding_3072 vector(3072);

-- 触发器或应用层确保只有对应维度列被填充
```

#### 3.3.2 分表方案

```sql
CREATE TABLE knowledge_chunks_768 (...) INHERITS (knowledge_chunks_base);
CREATE TABLE knowledge_chunks_1024 (...);
CREATE TABLE knowledge_chunks_1536 (...);
```

按 KB 的 embedding_dim 路由到对应表。

#### 3.3.3 何时迁移

```text
触发条件：
  业务需要接入维度 ≠ 1536 的本地模型（BGE / M3E 等）
  或需要使用 OpenAI text-embedding-3-large (3072 维)
迁移方式：
  新方案上线后，旧 KB 维持 vector(1536) 不变
  新 KB 默认用对应维度列/表
  提供 KB-level 迁移任务（重新 embed 所有 chunks）
```

---

## 4. Tokenizer 选型（G14）

### 4.1 选型

MVP 强制：

```text
切分用 tokenizer：tiktoken cl100k_base
  适用：OpenAI gpt-3.5/4 系列、text-embedding-ada-002、text-embedding-3-*
  Python 包：tiktoken
  特点：BPE 编码，速度快，结果可复现

非 OpenAI 模型（如 Anthropic Claude、Gemini、本地模型）：
  MVP 不接入
  v0.2 引入对应模型时，每个 KB 独立选择 tokenizer
  KnowledgeBase 增加字段 tokenizer，与 embedding_model 一起锁定
```

### 4.2 ChunkingService 实现

```python
import tiktoken

class ChunkingService:
    def __init__(self):
        self.encoder = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        return len(self.encoder.encode(text))

    def split_by_tokens(
        self,
        text: str,
        chunk_size_tokens: int = 500,
        chunk_overlap_tokens: int = 80,
    ) -> list[str]:
        tokens = self.encoder.encode(text)
        chunks = []
        start = 0
        while start < len(tokens):
            end = min(start + chunk_size_tokens, len(tokens))
            chunk_tokens = tokens[start:end]
            chunks.append(self.encoder.decode(chunk_tokens))
            if end == len(tokens):
                break
            start = end - chunk_overlap_tokens
        return chunks
```

### 4.3 token_count 字段语义

```text
knowledge_chunks.token_count 必须以 cl100k_base 为准
检索时按此 token_count 控制 context_budget_tokens
LLM Node 实际计费 token 可能与此不同（不同模型 tokenizer 略有差异）
```

### 4.4 表结构补充

```sql
ALTER TABLE knowledge_bases
  ADD COLUMN tokenizer VARCHAR(64) NOT NULL DEFAULT 'cl100k_base';
```

---

## 5. 异步运行 Trace 增量推送（G15）

### 5.1 问题

```text
当前异步运行的轮询：
  每 1s 调用 GET /runs/{run_id}/trace
  每次返回完整 trace（含所有 node_runs）

问题：
  长工作流（几十个节点）每次返回数十 KB
  网络浪费 + 服务端重复查询
  无法实时感知"刚启动一个新节点"
```

### 5.2 方案 1：增量轮询参数（MVP 推荐）

```text
GET /runs/{run_id}/trace?after_node_run_id={id}

响应：
  仅返回 id > after_node_run_id 的 node_runs
  附 workflow_run.status 用于前端判断是否停止轮询
```

实现：

```python
@router.get("/runs/{run_id}/trace")
async def get_trace(run_id: int, after_node_run_id: int = 0):
    run = await run_repo.get(run_id)
    node_runs = await node_run_repo.list_after(
        run_id=run_id,
        after_id=after_node_run_id,
    )
    return {
        "run": run,
        "node_runs": node_runs,
        "next_after_node_run_id": node_runs[-1].id if node_runs else after_node_run_id,
    }
```

前端：

```typescript
let afterNodeRunId = 0;
while (run.status === "running" || run.status === "pending") {
    const resp = await fetch(`/runs/${runId}/trace?after_node_run_id=${afterNodeRunId}`);
    const data = await resp.json();
    appendNodeRuns(data.node_runs);
    afterNodeRunId = data.next_after_node_run_id;
    run = data.run;
    await sleep(1000);
}
```

### 5.3 方案 2：SSE（Server-Sent Events，v0.2 推荐）

```text
GET /runs/{run_id}/stream
Content-Type: text/event-stream

事件流：
event: node_run_started
data: {"node_id": "llm_1", "id": 3001}

event: node_run_completed
data: {"node_id": "llm_1", "id": 3001, ...}

event: run_completed
data: {"status": "completed", "output_json": {}}
```

服务端实现：Worker 处理节点时通过 Redis pub/sub 推送事件，API 层订阅并通过 SSE 转发。

### 5.4 方案 3：WebSocket（v1.0+）

适合需要双向交互（人工审批节点、Info Collection 节点）的场景。MVP 不做。

### 5.5 OpenAPI 修订

```yaml
/runs/{run_id}/trace:
  get:
    parameters:
      - $ref: "#/components/parameters/RunId"
      - name: after_node_run_id
        in: query
        schema:
          type: integer
          default: 0
```

---

## 6. 上传文件具体限制（G16）

### 6.1 大小

```text
单文件：
  PDF      50 MB
  DOCX     30 MB
  TXT      10 MB
  Markdown 10 MB

环境变量：
  UPLOAD_MAX_FILE_SIZE_PDF_MB=50
  UPLOAD_MAX_FILE_SIZE_DOCX_MB=30
  UPLOAD_MAX_FILE_SIZE_TXT_MB=10
  UPLOAD_MAX_FILE_SIZE_MD_MB=10
  UPLOAD_MAX_FILE_SIZE_DEFAULT_MB=10
```

### 6.2 类型白名单

```python
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
}

# 魔数（前 N 字节）
MAGIC_NUMBERS = {
    "pdf": [b"%PDF-"],
    "docx": [b"PK\x03\x04"],  # DOCX 实际是 ZIP
    "txt": None,  # 无固定魔数
    "md": None,
}
```

### 6.3 校验流程

```python
async def validate_upload(file: UploadFile) -> tuple[str, str]:
    # 1. 扩展名校验
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "document_unsupported_type")

    # 2. 大小校验（流式，避免全读入内存）
    max_size = get_max_size(ext)
    size = 0
    chunks = []
    async for chunk in file.stream():
        size += len(chunk)
        if size > max_size:
            raise HTTPException(400, "document_too_large")
        chunks.append(chunk)
    content = b"".join(chunks)

    # 3. 魔数校验（PDF/DOCX）
    magic = MAGIC_NUMBERS.get(ext.lstrip("."))
    if magic and not any(content.startswith(m) for m in magic):
        raise HTTPException(400, "document_invalid_magic")

    # 4. MIME 推断（用 python-magic）
    detected_mime = magic_lib.from_buffer(content[:8192], mime=True)
    if detected_mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, "document_unsupported_type")

    return content, detected_mime
```

### 6.4 文件名清理

```python
def safe_filename(name: str) -> str:
    # 移除路径分隔符
    name = name.replace("/", "_").replace("\\", "_")
    # 限制长度
    if len(name) > 200:
        ext = Path(name).suffix
        base = Path(name).stem[: 200 - len(ext)]
        name = base + ext
    return name
```

### 6.5 存储路径

```text
存储路径不使用用户控制的文件名：

/data/agent-workflow/documents/{kb_id}/{document_id}/original{ext}

其中：
  kb_id = knowledge_bases.id（数字）
  document_id = documents.id（数字）
  ext = 校验后的扩展名

用户原文件名只存数据库 file_name 字段，不参与路径
```

---

## 7. audit_logs.action 枚举（G17）

### 7.1 命名规范

```text
格式：{resource}.{verb}
全小写，点分
verb 使用过去式或动词原形
```

### 7.2 完整枚举

#### 7.2.1 Workflow

```text
workflow.created
workflow.updated         保存草稿
workflow.deleted
workflow.validated       校验
workflow.published
workflow.archived
workflow.run             启动运行
workflow.run.cancelled
```

#### 7.2.2 Run / Node Run

```text
run.completed
run.failed
run.cancelled

node_run.failed_final    最终失败（重试用尽后）
```

#### 7.2.3 Knowledge Base

```text
knowledge_base.created
knowledge_base.updated
knowledge_base.deleted

document.uploaded
document.processed       indexed 完成
document.failed
document.retried
document.deleted

knowledge.retrieve_tested  POST /knowledge-bases/:id/retrieve 测试检索
```

#### 7.2.4 Tool

```text
tool.created
tool.updated
tool.deleted
tool.tested
```

#### 7.2.5 Secret

```text
secret.created
secret.updated
secret.deleted
secret.accessed_for_run    运行时解密使用（v0.2 启用，会很噪）
```

#### 7.2.6 Model

```text
model_provider.created
model_provider.updated
model_provider.disabled

model_config.created
model_config.updated
```

#### 7.2.7 User

```text
user.created           v0.2
user.role_changed      v0.2
user.disabled          v0.2
```

#### 7.2.8 System

```text
system.startup
system.config_changed
```

### 7.3 表约束（可选）

PostgreSQL 不需要 ENUM，但可以加 CHECK：

```sql
ALTER TABLE audit_logs
  ADD CONSTRAINT chk_audit_logs_action_format
    CHECK (action ~ '^[a-z][a-z_]*\.[a-z][a-z_]*(\.[a-z][a-z_]*)?$');
```

不建议在 CHECK 中枚举所有 action，应用层维护即可。

### 7.4 detail_json 规范

每种 action 的 detail_json 字段：

```text
workflow.published:
  { "workflow_id": 1, "version_id": 10, "version": 3, "release_note": "..." }

workflow.run:
  { "workflow_id": 1, "version_id": 10, "run_id": 2001, "trigger_type": "manual" }

document.uploaded:
  { "document_id": 5001, "file_name": "xxx.pdf", "file_size": 102400 }

secret.created:
  { "secret_id": 10001, "secret_key": "openai_api_key" }
  注：detail_json 不含 value

tool.tested:
  { "tool_id": 9001, "duration_ms": 420, "status_code": 200 }
  注：不含 request/response body
```

### 7.5 AuditService 接口

```python
class AuditService:
    async def record(
        self,
        actor_user_id: int | None,
        action: str,
        resource_type: str,
        resource_id: str,
        request_id: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        detail: dict | None = None,
    ):
        # 1. 校验 action 格式
        # 2. detail 通过 Redactor
        # 3. 写表（独立短事务，失败不影响主流程）
        ...
```

---

## 8. 节点级事务边界 + 重试时 mapping + 并发隔离（G18-G20）

### 8.1 事务边界

#### 8.1.1 推荐策略

```text
workflow_run 创建：单事务
每个 node_run 创建/更新：独立短事务
state_json 持久化：节点完成后独立短事务
workflow_run 最终状态写入：单事务
```

**禁止**：跨多个节点的长事务（PostgreSQL 长事务会拖垮性能）。

#### 8.1.2 节点执行的事务边界

```python
async def execute_node_with_retry(node, state, context):
    for attempt in range(1, max_attempts + 1):
        # T1: 创建 node_run (running)
        async with db.begin():
            node_run_id = await trace.create_node_run(
                run_id, node, attempt, ...
            )

        # T0: 节点执行不在数据库事务内
        try:
            output = await executor.execute(node, ...)
        except Exception as e:
            # T2: 更新 node_run (failed)
            async with db.begin():
                await trace.mark_node_failed(node_run_id, e, ...)
            ...

        # T3: 更新 node_run (success) + 写 state
        async with db.begin():
            await trace.mark_node_success(node_run_id, output, ...)
            await state_manager.persist(run_id, state)

        return output
```

#### 8.1.3 异常下的一致性

```text
T1 成功，T0 失败但未抛异常（卡死）：
  超时控制兜底，TimeoutController 触发 cancel
  T2 写入 failed

T3 失败（数据库挂了）：
  Runtime 在内存中已经有 output 但写不进 DB
  重试 T3 几次
  仍失败：抛 internal_error，工作流标记 failed
  下次手动查询时 trace 不完整，但 workflow_run.status 是 failed
```

### 8.2 重试时 input_mapping 重新解析

```text
规则：每次 attempt 都重新解析 input_mapping
原因：
  - 失败的 attempt 不写 state，但其它并发 node 可能（理论上 MVP 不会）
  - 重试间隔 state.metadata.attempt 等字段可能更新
保证：每次 attempt 创建独立的 node_run，input_json 记录当次解析结果
```

伪代码：

```python
for attempt in range(1, max_attempts + 1):
    # 每次都重新解析
    node_input = await resolver.resolve_input_mapping(node, state, context)
    resolved_config = await resolver.resolve_config(node, node_input, state, context)

    node_run_id = await trace.create_node_run(
        run_id, node, attempt,
        input_json=redact(node_input),
    )

    try:
        output = await executor.execute(node, node_input, resolved_config, state, context)
        ...
    except ...:
        ...
```

### 8.3 失败 attempt 不写 state

```text
节点最终成功 → state 写一次（最后一次 attempt 的 output）
节点最终失败 → state 不写（保持节点执行前的状态）
失败的中间 attempt → 写 node_runs 但不写 state
```

### 8.4 并发同一 workflow 多 run 隔离

```text
保证：每个 workflow_run 持有独立 state，互不影响
机制：
  - state 在内存中独立维护，落地到 workflow_runs.state_json
  - 不存在 workflow 级别的共享变量
  - workflow_versions.graph_json 只读，并发安全
  - node_runs 通过 run_id 隔离

潜在问题：
  - API Node 调用外部服务，外部服务可能有共享状态（自然行为，不在 Runtime 范畴）
  - Knowledge Base 检索是只读，并发安全
```

### 8.5 同一 run_id 不能被多个 worker 同时执行

```text
约束：
  - 创建 workflow_run 时状态 pending
  - worker 从队列拿到 run_id 后，先 SELECT FOR UPDATE 锁定行
  - 检查 status = pending，更新为 running
  - 重复任务（重复入队）会发现 status != pending，直接跳过
```

伪代码：

```python
async def run_workflow(run_id: int):
    async with db.begin():
        run = await db.execute(
            select(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .with_for_update(skip_locked=True)
        )
        if run is None or run.status != "pending":
            return  # 已被其它 worker 处理或不存在
        run.status = "running"
        run.started_at = datetime.utcnow()

    # 锁释放后继续执行
    try:
        ...
    except Exception:
        await mark_failed(run_id, ...)
```

---

## 9. graph_migrator 框架（R4）

### 9.1 问题

```text
workflow_versions.graph_json 不可变
但节点协议会升级：1.0 → 1.1 → 2.0
旧版本的 graph_json 如何被新 Runtime 加载？
```

### 9.2 设计

```text
Runtime 加载 graph_json：
  1. 读取 schema_version
  2. 若 schema_version < CURRENT_SCHEMA_VERSION：
     依次应用 migrations 转换为 CURRENT_SCHEMA_VERSION
  3. 转换结果只用于 Runtime 内存
     不回写 workflow_versions（保持不可变）

migration 注册：
  1.0 → 1.1: add_default_retry()
  1.1 → 1.2: rename_field_x_to_y()
  ...
```

伪代码：

```python
class GraphMigrator:
    def __init__(self):
        self.migrations = {
            "1.0->1.1": self._mig_1_0_to_1_1,
            "1.1->1.2": self._mig_1_1_to_1_2,
        }

    def migrate(self, graph: dict, target: str) -> dict:
        current = graph.get("schema_version", "1.0")
        while current != target:
            next_version = self._next_version(current)
            key = f"{current}->{next_version}"
            if key not in self.migrations:
                raise InvalidGraphError(f"no migration from {current}")
            graph = self.migrations[key](graph)
            current = next_version
        return graph
```

### 9.3 兼容矩阵

| Runtime 版本 | 支持 schema | 不支持 schema | 行为 |
|---|---|---|---|
| Runtime v1.0 | 1.0 | 1.1+ | "schema_version_unsupported" |
| Runtime v1.1 | 1.0, 1.1 | 1.2+ | 自动 migrate 1.0 → 1.1 |
| Runtime v1.2 | 1.0, 1.1, 1.2 | 1.3+ | 自动 migrate 1.0 → 1.2 |

### 9.4 弃用窗口

```text
新增字段：默认 backward-compatible
删除字段：先标记 deprecated 一个版本，下个版本删除
重命名字段：通过 migration 自动转换
更改字段语义：禁止；改用新字段
```

### 9.5 MVP 阶段

```text
MVP 只有 schema_version = "1.0"
不实现 GraphMigrator
预留 GraphLoader 内部一个 migrate(graph) 入口
v0.2 引入新版本时再实现具体 migration 逻辑
```

---

## 10. Branch target 与 edges 强约束的实现补充（R1）

C4 已经从协议层面强约束，本节补 Runtime 与 Validator 实现细节。

### 10.1 GraphValidator 规则

```python
class GraphValidator:
    def _validate_branch_edges(self, graph: dict) -> list[ValidationError]:
        errors = []
        for node in graph["nodes"]:
            if node["type"] != "branch":
                continue

            branches = node.get("config", {}).get("branches", [])
            targets = [b["target"] for b in branches if "target" in b]

            # 1. target 必须在 nodes 中
            node_ids = {n["id"] for n in graph["nodes"]}
            for target in targets:
                if target not in node_ids:
                    errors.append(
                        ValidationError(
                            code="branch_target_not_found",
                            message=f"Branch {node['id']} target '{target}' not in nodes",
                            path=f"nodes[{node['id']}].config.branches",
                        )
                    )

            # 2. 每个 target 必须有对应 edge
            outgoing_edges = [
                e for e in graph["edges"] if e["source"] == node["id"]
            ]
            outgoing_targets = {e["target"] for e in outgoing_edges}
            for target in targets:
                if target not in outgoing_targets:
                    errors.append(
                        ValidationError(
                            code="branch_target_no_edge",
                            message=f"Branch {node['id']} target '{target}' has no edge",
                            path=f"edges",
                        )
                    )

            # 3. 所有出边必须能映射回某个 branch.target
            for edge in outgoing_edges:
                if edge["target"] not in targets:
                    errors.append(
                        ValidationError(
                            code="orphan_branch_edge",
                            message=f"Edge {edge['id']} from Branch {node['id']} not declared in branches",
                            path=f"edges[{edge['id']}]",
                        )
                    )

        return errors
```

### 10.2 NextNodeResolver 实现

```python
def resolve_next_for_branch(graph, node, node_output) -> str:
    target = node_output.get("target")
    if not target:
        raise RuntimeNodeError("branch_no_match")

    # 校验 target 在 graph 中
    node_ids = {n["id"] for n in graph["nodes"]}
    if target not in node_ids:
        raise RuntimeNodeError(
            "branch_target_not_found",
            message=f"target {target} not in graph",
        )

    return target
```

GraphValidator 在发布时已经校验，Runtime 校验是防御性兜底。

---

## 11. 节点 ID 生成具体实现（C3 实现补充）

```python
import secrets
import string

NANOID_ALPHABET = string.ascii_letters + string.digits  # 62 chars
NANOID_LENGTH = 8

def nanoid() -> str:
    return "".join(secrets.choice(NANOID_ALPHABET) for _ in range(NANOID_LENGTH))

def new_node_id(node_type: str) -> str:
    return f"{node_type}_{nanoid()}"

def new_edge_id() -> str:
    return f"e_{nanoid()}"
```

碰撞概率：62^8 ≈ 2.18 × 10^14，单 workflow 几千节点完全够。

ID 校验正则：

```text
node_id: ^[a-z_]+_[A-Za-z0-9]{8}$
edge_id: ^e_[A-Za-z0-9]{8}$
```

GraphValidator 在保存/发布时校验。

---

## 12. 完整修订执行清单

### 12.1 SQL 迁移补丁（新增 migration 002）

```sql
-- 002_observability_and_governance.sql

-- knowledge_bases 增加 embedding_dim 和 tokenizer
ALTER TABLE knowledge_bases
  ADD COLUMN embedding_dim INT NOT NULL DEFAULT 1536,
  ADD COLUMN tokenizer VARCHAR(64) NOT NULL DEFAULT 'cl100k_base',
  ADD COLUMN slug VARCHAR(64);

ALTER TABLE knowledge_bases
  ADD CONSTRAINT chk_kb_embedding_dim
    CHECK (embedding_dim = 1536);

CREATE UNIQUE INDEX uk_knowledge_bases_slug
  ON knowledge_bases(slug)
  WHERE deleted_at IS NULL;

-- secrets 增加 key_version 字段
ALTER TABLE secrets
  ADD COLUMN key_version INT NOT NULL DEFAULT 1;

-- workflow_runs 增加 metadata_json
ALTER TABLE workflow_runs
  ADD COLUMN metadata_json JSONB;

CREATE INDEX idx_workflow_runs_metadata_gin
  ON workflow_runs USING GIN(metadata_json);

-- audit_logs action 格式约束
ALTER TABLE audit_logs
  ADD CONSTRAINT chk_audit_logs_action_format
    CHECK (action ~ '^[a-z][a-z_]*\.[a-z][a-z_]*(\.[a-z][a-z_]*)?$');

-- HNSW 索引（如未在 001 中建）
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
  ON knowledge_chunks
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
```

### 12.2 Seed 数据补充

```sql
-- 003_seed_mock_users.sql
INSERT INTO users (id, email, username, display_name, role, status)
VALUES
  (1, 'admin@example.com',  'admin',  'MVP Admin',  'admin',  'active'),
  (2, 'editor@example.com', 'editor', 'MVP Editor', 'editor', 'active'),
  (3, 'viewer@example.com', 'viewer', 'MVP Viewer', 'viewer', 'active')
ON CONFLICT (id) DO NOTHING;

-- 重置 users 序列
SELECT setval('users_id_seq', GREATEST(3, (SELECT MAX(id) FROM users)));
```

### 12.3 OpenAPI 修订

```yaml
# 增加 /ready 端点
/ready:
  get:
    tags: [Health]
    summary: Readiness check
    security: []
    responses:
      "200": ...
      "503": ...

# 增加 /metrics 端点（不放 OpenAPI 也可）

# 修订 /runs/{run_id}/trace
/runs/{run_id}/trace:
  get:
    parameters:
      - $ref: "#/components/parameters/RunId"
      - name: after_node_run_id
        in: query
        schema:
          type: integer
          default: 0
```

### 12.4 环境变量清单（汇总）

```text
# Auth & Security
AUTH_MODE=mock
MOCK_USERS=admin:1,editor:2,viewer:3
DEFAULT_MOCK_USER=admin
SECRET_ENCRYPTION_KEY=<base64>

# Runtime Limits
MAX_VARIABLE_SIZE_BYTES=1048576
MAX_NODE_OUTPUT_SIZE_BYTES=5242880
MAX_STATE_SIZE_BYTES=20971520
MAX_INPUT_LENGTH=4000
WORKFLOW_RUN_MAX_TOTAL_TOKENS=200000
WORKFLOW_RUN_MAX_LLM_CALLS=20
WORKFLOW_RUN_MAX_API_CALLS=50
WORKFLOW_RUN_MAX_DURATION_SECONDS=600

# API Node
API_NODE_ALLOW_PRIVATE_NETWORK=false
API_NODE_MAX_RESPONSE_SIZE_MB=10
API_NODE_MAX_REDIRECTS=5
API_NODE_DEFAULT_TIMEOUT_SECONDS=30

# Upload
UPLOAD_MAX_FILE_SIZE_PDF_MB=50
UPLOAD_MAX_FILE_SIZE_DOCX_MB=30
UPLOAD_MAX_FILE_SIZE_TXT_MB=10
UPLOAD_MAX_FILE_SIZE_MD_MB=10

# Trace / Logging
TRACE_SAVE_PROMPT=true
TRACE_FIELD_MAX_BYTES=32768
REDACT_PII_IN_TRACE=false
SANITIZE_PROMPT_INPUTS=true
STRICT_NULL_IN_STRING=true

# Default LLM
DEFAULT_LLM_PROVIDER=openai
DEFAULT_CHAT_MODEL=gpt-4.1-mini
DEFAULT_EMBEDDING_MODEL=text-embedding-3-small

# Data Retention
RETENTION_WORKFLOW_RUNS_DAYS=90
RETENTION_AUDIT_LOGS_DAYS=180
RETENTION_DELETED_DOCUMENTS_DAYS=30
```

---

## 13. 与原文档衔接索引

| 修订 | 原文档 | 章节 |
|---|---|---|
| pgvector SQL | runtime, backend_structure | §14.4 KB Executor, §4.4 Knowledge Module |
| embedding_dim 字段 | ER | §6.6 knowledge_bases |
| tokenizer 选型 | runtime, mvp_scope | §14.4, §13.3 |
| trace 增量参数 | api_design, frontend | §4.5, §13 |
| 上传限制 | mvp_scope, testing | §16, §6.2 |
| audit action 枚举 | ER, testing | §6.14 audit_logs, §14 |
| 事务边界 | runtime, backend_structure | §11, §11 |
| 并发隔离 | runtime | §22 |
| graph_migrator | node_protocol, runtime | §17, §4.2 GraphLoader |
| Branch 校验 | node_protocol, runtime | §13.7, §4.3 GraphValidator |
| ID 生成实现 | frontend, node_protocol | §6.1, §5.1 |
| HNSW 索引策略 | ER, tech_stack | §6.8, §8 |

---

## 14. 结论

实施细节是"魔鬼藏在哪里"的地方。本文档把以下几件事一次性钉死：

```text
1. pgvector 检索有标准 SQL 模板，不让每人写一套
2. embedding 维度有明确的锁定/演进策略
3. tokenizer 强制 cl100k_base，避免切分/计费混乱
4. trace 增量参数让前端轮询不浪费
5. 文件上传具体限制，不再"待定"
6. audit action 完整枚举 + 格式约束
7. 事务边界、重试解析、并发隔离三条原则
8. graph_migrator 框架，为协议演进留口
```

加上前面三份补丁（一致性、安全、观测），整个 MVP 阶段不再有"模糊地带"。开发团队拿到这 5 份文档加原 13 份，可以直接进入实施期，预计返工成本能降到原来的 1/3 以下。
