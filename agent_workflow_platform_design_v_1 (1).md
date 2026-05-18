# Agent 工作流平台初版设计文档 v0.1

## 1. 文档目标

本文档用于定义一个初版 Agent 工作流平台的产品形态、系统架构、节点体系、数据模型、运行时设计和 MVP 落地范围。

平台目标是提供一个可视化、可配置、可执行、可追踪的 Agent 工作流编排系统，使用户能够通过节点方式搭建包含 LLM、知识库、记忆、API、数据库、分支、循环、信息收集、消息和代码执行等能力的智能业务流程。

---

## 2. 平台定位

本平台不是单一 Chatbot，而是一个节点式 Agent Workflow Platform。

核心能力包括：

1. 可视化工作流编排
2. 多类型节点配置与执行
3. 大模型调用与 Prompt 编排
4. 知识库检索与 RAG
5. 用户/会话/业务记忆管理
6. API、数据库、代码等工具调用
7. 条件分支与循环控制
8. 信息收集与多轮交互
9. 消息发送与用户反馈
10. 执行日志、Trace、错误重试与审计

平台最终目标是让用户可以像搭积木一样搭建 Agent 应用。

---

## 3. 典型使用场景

### 3.1 智能客服

用户输入问题后，系统识别意图，根据不同意图进入不同流程：

- 普通咨询：查询知识库后由 LLM 生成回答
- 订单查询：收集订单号，调用数据库或 API 查询订单状态
- 退款申请：收集必要信息，判断是否满足自动退款规则，必要时转人工审批

### 3.2 企业知识问答

用户提问后，系统从知识库中检索相关文档片段，通过 LLM 生成带引用的答案，并记录用户偏好和上下文记忆。

### 3.3 自动化业务流程

例如：

- 销售线索收集
- 客户资料补全
- 邮件草稿生成
- 数据查询与报告生成
- 内部审批流
- 多步骤研究任务

### 3.4 数据分析助手

用户提出分析需求后，系统识别意图，调用数据库查询数据，使用代码节点做计算，再由 LLM 生成分析结论。

---

## 4. 总体架构

### 4.1 架构概览

```text
前端应用
  ├─ 工作流编辑器
  ├─ 节点配置面板
  ├─ 运行调试面板
  ├─ Trace 日志面板
  └─ 知识库/工具/模型管理

后端 API 服务
  ├─ 用户与权限管理
  ├─ 工作流管理
  ├─ 节点配置管理
  ├─ 工作流发布与版本管理
  ├─ 运行任务管理
  └─ 日志与审计查询

Workflow Runtime
  ├─ 工作流执行器
  ├─ 节点执行器
  ├─ 状态管理器
  ├─ 条件路由器
  ├─ 工具调用器
  ├─ 错误处理器
  └─ Trace 记录器

基础设施
  ├─ PostgreSQL / MySQL
  ├─ Redis
  ├─ 向量数据库 / pgvector
  ├─ 对象存储
  ├─ 消息队列
  └─ 监控与日志系统
```

### 4.2 MVP 最终技术栈

MVP 阶段采用低复杂度、快落地、可演进的单机技术栈：

```text
前端：Next.js + React Flow
后端 API：FastAPI
数据库：PostgreSQL + pgvector
缓存与任务队列：Redis
Worker：RQ + Redis
向量检索：pgvector
文件存储：本地文件系统 volume
部署：Docker Compose 单机
Trace 与审计：PostgreSQL 中的 workflow_runs / node_runs / audit_logs
LLM 适配层：OpenAI API / LiteLLM / 自定义 Provider Adapter
```

MVP 阶段明确不引入：

```text
读写分离
ClickHouse 日志库
Jaeger 分布式追踪
MinIO / S3
Kubernetes
RabbitMQ / Celery
Temporal
```

后续随着数据量和生产要求提升，可再演进为：

```text
文件存储：本地文件系统 → MinIO / S3 / OSS
任务队列：RQ → Celery / Temporal
日志分析：PostgreSQL → ClickHouse / OpenSearch
Trace：node_runs → OpenTelemetry / Jaeger
向量检索：pgvector → Qdrant / Milvus
部署：Docker Compose → Kubernetes
数据库：单 PostgreSQL → 主从 / 读写分离
```

---

## 5. 核心模块设计

## 5.1 工作流管理模块

负责工作流的创建、编辑、保存、发布、复制、删除和版本管理。

核心对象：

```text
Workflow
WorkflowVersion
WorkflowNode
WorkflowEdge
WorkflowRun
NodeRun
```

工作流支持两种状态：

```text
draft       草稿
published   已发布
archived    已归档
```

工作流每次发布都会生成一个不可变版本，运行时使用已发布版本，避免用户编辑草稿影响线上执行。

---

## 5.2 节点管理模块

节点是平台最核心的抽象。

每个节点都包含：

```text
节点 ID
节点类型
节点名称
节点描述
输入映射
输出映射
节点配置
重试策略
超时设置
权限要求
前端位置信息
```

统一节点结构：

```json
{
  "id": "node_llm_001",
  "type": "llm",
  "name": "生成回答",
  "description": "根据知识库内容生成最终回复",
  "input_mapping": {
    "question": "{{input.user_query}}",
    "context": "{{variables.kb_context}}"
  },
  "output_mapping": {
    "answer": "variables.final_answer"
  },
  "config": {},
  "retry": {
    "max_attempts": 2,
    "backoff": "exponential"
  },
  "timeout": 60,
  "position": {
    "x": 100,
    "y": 200
  }
}
```

---

## 5.3 Workflow Runtime 模块

Runtime 负责真正执行工作流。

主要职责：

1. 加载工作流版本
2. 初始化运行状态 State
3. 按节点和边执行流程
4. 调用不同类型节点执行器
5. 管理节点输入输出
6. 处理分支、循环、暂停、恢复
7. 记录每一步 Trace
8. 处理异常、重试和超时
9. 输出最终结果

运行状态：

```text
pending
running
waiting_for_user
waiting_for_approval
completed
failed
cancelled
paused
```

---

## 5.4 工具调用模块

工具调用模块负责统一管理 API、数据库、代码执行、Webhook、文件操作等外部能力。

工具调用需要具备：

1. 参数校验
2. 权限校验
3. 密钥管理
4. 超时控制
5. 重试机制
6. 日志审计
7. 错误封装

---

## 5.5 知识库模块

知识库模块用于 RAG 检索。

主要能力：

1. 文档上传
2. 文档解析
3. 文档切分
4. Embedding 生成
5. 向量检索
6. 元数据过滤
7. Rerank
8. 引用来源返回

知识库节点只负责检索，不直接生成最终答案。

---

### 5.5.5 Embedding 与索引

每个 chunk 都需要生成 embedding 后写入向量索引。

推荐字段：

```text
chunk_id
knowledge_base_id
document_id
content
embedding
metadata_json
created_at
updated_at
```

Embedding 处理流程：

```text
读取待处理 chunk
  ↓
调用 embedding model
  ↓
生成向量
  ↓
写入 knowledge_chunks.embedding
  ↓
更新 chunk 状态为 indexed
```

第一版可以直接使用 PostgreSQL + pgvector 存储向量。如果后续文档规模变大，可以迁移到 Qdrant、Milvus 或 Elasticsearch/OpenSearch + 向量检索。

推荐第一版索引方案：

```text
主库：PostgreSQL
向量扩展：pgvector
全文搜索：PostgreSQL full-text search
元数据过滤：JSONB + 普通索引
```

后续增强方案：

```text
向量库：Qdrant / Milvus
全文搜索：OpenSearch / Elasticsearch
Rerank：专门 reranker model
```

### 5.5.6 检索流程

知识库节点运行时不应该直接把整个文档塞给 LLM，而是按查询进行检索。

标准检索流程：

```text
用户问题 / 上游节点输入
  ↓
Query Rewrite，可选
  ↓
生成 query embedding
  ↓
向量检索 top_k
  ↓
关键词检索，可选
  ↓
元数据过滤
  ↓
结果合并
  ↓
Rerank，可选
  ↓
截断到上下文 token budget
  ↓
返回 kb_context 给后续 LLM 节点
```

知识库节点输出示例：

```json
{
  "kb_context": [
    {
      "chunk_id": "chunk_001",
      "content": "用户可在签收后 7 天内申请退款...",
      "score": 0.86,
      "source": {
        "document_id": "doc_001",
        "file_name": "售后政策.pdf",
        "page_start": 3,
        "page_end": 3,
        "section_title": "退款规则"
      }
    }
  ]
}
```

LLM 节点再基于 `kb_context` 生成最终回答。

### 5.5.7 混合检索

第一版可以只做向量检索，但更推荐支持混合检索。

混合检索包括：

```text
向量检索：适合语义相近的问题
关键词检索：适合精确术语、编号、产品名、条款名
元数据过滤：适合限定知识库、文档、时间、权限、标签
Rerank：提升最终召回片段排序质量
```

示例：用户问“7天无理由退款规则是什么？”

检索策略：

```text
1. 向量搜索召回语义相关片段
2. 关键词搜索召回包含“7天”“退款”的片段
3. 合并去重
4. Rerank
5. 返回前 3 - 5 个片段
```

### 5.5.8 知识库权限设计

知识库必须支持权限控制，避免用户检索到无权限文档。

权限可以分为：

```text
知识库级权限
文档级权限
团队级权限
用户级权限
标签级权限
```

检索时必须带上当前用户上下文：

```json
{
  "user_id": "user_001",
  "team_id": "team_001",
  "role": "member",
  "allowed_knowledge_base_ids": ["kb_001", "kb_002"]
}
```

检索 SQL 或向量查询中必须加入权限过滤条件。

### 5.5.9 文档处理失败与重试

文档上传后处理可能失败，例如：

```text
文件损坏
文件过大
解析失败
OCR 失败
embedding 调用失败
向量写入失败
```

每个文档应记录处理状态和错误信息：

```json
{
  "document_id": "doc_001",
  "status": "failed",
  "error_stage": "embedding",
  "error_message": "embedding provider timeout",
  "retry_count": 2
}
```

建议支持：

```text
自动重试
手动重试
重新解析
重新切分
重新生成 embedding
删除并重建索引
```

### 5.5.10 知识库相关数据表

#### documents

```sql
CREATE TABLE documents (
  id BIGSERIAL PRIMARY KEY,
  knowledge_base_id BIGINT NOT NULL,
  file_name VARCHAR(512) NOT NULL,
  file_type VARCHAR(64),
  file_size BIGINT,
  storage_url TEXT,
  status VARCHAR(64) NOT NULL DEFAULT 'uploaded',
  error_stage VARCHAR(64),
  error_message TEXT,
  uploaded_by BIGINT,
  metadata_json JSONB,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_documents_kb_id ON documents(knowledge_base_id);
CREATE INDEX idx_documents_status ON documents(status);
```

#### knowledge_chunks

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE knowledge_chunks (
  id BIGSERIAL PRIMARY KEY,
  knowledge_base_id BIGINT NOT NULL,
  document_id BIGINT NOT NULL,
  chunk_index INT NOT NULL,
  content TEXT NOT NULL,
  token_count INT,
  embedding vector(1536),
  status VARCHAR(64) NOT NULL DEFAULT 'created',
  metadata_json JSONB,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_chunks_kb_id ON knowledge_chunks(knowledge_base_id);
CREATE INDEX idx_chunks_document_id ON knowledge_chunks(document_id);
CREATE INDEX idx_chunks_status ON knowledge_chunks(status);
CREATE INDEX idx_chunks_metadata ON knowledge_chunks USING GIN(metadata_json);
```

如果使用 pgvector，可以后续根据数据规模增加向量索引，例如 HNSW 或 IVFFlat。

#### document_processing_jobs

```sql
CREATE TABLE document_processing_jobs (
  id BIGSERIAL PRIMARY KEY,
  document_id BIGINT NOT NULL,
  job_type VARCHAR(64) NOT NULL,
  status VARCHAR(64) NOT NULL DEFAULT 'pending',
  error_message TEXT,
  retry_count INT DEFAULT 0,
  started_at TIMESTAMP,
  ended_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_doc_jobs_document_id ON document_processing_jobs(document_id);
CREATE INDEX idx_doc_jobs_status ON document_processing_jobs(status);
```

### 5.5.11 知识库节点配置

Knowledge Base Node 配置示例：

```json
{
  "knowledge_base_ids": ["kb_001"],
  "query": "{{input.user_query}}",
  "retrieval_mode": "hybrid",
  "top_k": 5,
  "score_threshold": 0.65,
  "rerank": true,
  "filters": {
    "document_tags": ["售后", "产品政策"],
    "language": "zh"
  },
  "context_budget_tokens": 3000,
  "save_to": "variables.kb_context"
}
```

输出示例：

```json
{
  "kb_context": [
    {
      "content": "退款规则正文...",
      "score": 0.91,
      "source": {
        "file_name": "售后政策.pdf",
        "page_start": 3,
        "section_title": "退款规则"
      }
    }
  ]
}
```

### 5.5.12 切分策略配置

知识库可以允许用户选择切分策略。

推荐第一版内置以下策略：

```text
auto        自动策略，默认推荐
fixed       固定 token 长度切分
heading     按标题层级切分
paragraph   按段落切分
qa          FAQ 问答对切分
table       表格行组切分
```

配置示例：

```json
{
  "chunking_strategy": "auto",
  "chunk_size_tokens": 500,
  "chunk_overlap_tokens": 80,
  "preserve_headings": true,
  "preserve_tables": true
}
```

不同文档类型的默认策略：

```text
PDF：auto + paragraph + token fallback
DOCX：heading + paragraph
Markdown：heading + block
FAQ：qa
CSV：table
HTML：heading + paragraph
```

### 5.5.13 引用与溯源

知识库检索结果必须保留来源信息，方便最终回答展示引用。

来源信息至少包括：

```text
document_id
file_name
page_start
page_end
section_title
chunk_id
score
```

后续 LLM 生成回答时可以要求模型引用来源，例如：

```text
请基于 kb_context 回答问题，并在相关句子后标注来源文件和页码。
```

### 5.5.14 第一版实现建议

第一版建议实现范围：

```text
支持 PDF / DOCX / TXT / Markdown 上传
支持异步文档处理
支持自动切分
支持 pgvector 向量检索
支持 top_k 检索
支持基本元数据和来源引用
支持文档处理失败重试
```

第一版暂不做：

```text
复杂 OCR
复杂表格理解
多模态图片解析
高级 Rerank
跨知识库复杂权限继承
外部知识源同步
```

## 5.6 记忆模块

记忆模块负责存储和检索长期或短期上下文。

记忆类型：

```text
session_memory      当前会话记忆
user_memory         用户长期偏好
workflow_memory     工作流运行状态记忆
entity_memory       业务实体记忆，例如客户、订单、项目
```

记忆写入必须受策略控制，避免自动保存敏感或无意义信息。

---

## 5.7 Trace 与日志模块

Trace 是平台的关键能力，必须从第一版开始实现。

每次运行需要记录：

1. 工作流运行记录
2. 每个节点的输入
3. 每个节点的输出
4. 节点状态
5. 错误信息
6. 执行耗时
7. LLM token 使用量
8. 模型调用成本
9. API 调用状态
10. 用户交互记录

节点运行日志示例：

```json
{
  "run_id": "run_001",
  "node_id": "node_llm_001",
  "node_type": "llm",
  "status": "success",
  "input": {},
  "output": {},
  "error": null,
  "duration_ms": 1320,
  "token_usage": {
    "prompt_tokens": 1000,
    "completion_tokens": 300
  }
}
```

---

# 6. 节点体系设计

## 6.1 节点分类

### 输入输出类

```text
Start Node
Input Node
Output Node
Message Node
Info Collection Node
Form Node
```

### AI 类

```text
LLM Node
Intent Recognition Node
Text Classification Node
Extractor Node
Summarizer Node
Prompt Template Node
```

### 知识类

```text
Knowledge Base Retrieve Node
Document Loader Node
Vector Search Node
Rerank Node
Citation Node
```

### 记忆类

```text
Memory Read Node
Memory Write Node
Session State Node
User Profile Node
```

### 工具类

```text
API Node
Database Node
Code Node
Webhook Node
File Node
```

### 控制流类

```text
Branch Node
Loop Node
Parallel Node
Merge Node
Delay Node
Retry Node
```

### 人工协作类

```text
Human Approval Node
Human Input Node
Review Node
Escalation Node
```

### 安全与校验类

```text
Validator Node
Guardrail Node
PII Detection Node
Permission Check Node
Rate Limit Node
```

---

## 6.2 MVP 第一版节点

第一版建议实现以下节点：

1. Start Node
2. Input Node
3. LLM Node
4. Knowledge Base Node
5. Intent Recognition Node
6. Branch Node
7. API Node
8. Message Node
9. Output Node
10. End Node

第二版再增加：

1. Memory Read Node
2. Memory Write Node
3. Database Node
4. Info Collection Node
5. Code Node
6. Loop Node

第三版增加：

1. Parallel Node
2. Merge Node
3. Human Approval Node
4. Guardrail Node
5. Evaluation Node
6. Scheduler Node

---

# 7. 关键节点设计

## 7.1 LLM Node

用途：调用大模型完成生成、总结、分类、抽取、改写、结构化输出等任务。

配置项：

```json
{
  "provider": "openai",
  "model": "gpt-4.1",
  "system_prompt": "你是一个专业客服助手",
  "user_prompt": "请根据以下资料回答问题：{{context}}\n问题：{{question}}",
  "temperature": 0.3,
  "max_tokens": 2000,
  "response_format": "text",
  "save_to": "variables.answer"
}
```

输出：

```json
{
  "answer": "模型生成的回答"
}
```

---

## 7.2 Knowledge Base Node

用途：根据查询文本从知识库中检索相关内容。

配置项：

```json
{
  "knowledge_base_id": "kb_product_docs",
  "query": "{{input.user_query}}",
  "top_k": 5,
  "score_threshold": 0.7,
  "rerank": true,
  "save_to": "variables.kb_context"
}
```

输出：

```json
{
  "kb_context": [
    {
      "content": "相关文档片段",
      "source": "产品手册.pdf",
      "score": 0.86
    }
  ]
}
```

---

## 7.3 Memory Node

建议拆为 Memory Read Node 和 Memory Write Node。

Memory Read Node：

```json
{
  "memory_scope": "user",
  "query": "{{input.user_query}}",
  "top_k": 5,
  "save_to": "variables.user_memory"
}
```

Memory Write Node：

```json
{
  "memory_scope": "user",
  "content": "{{variables.important_preference}}",
  "metadata": {
    "source": "conversation"
  }
}
```

---

## 7.4 API Node

用途：调用 HTTP API。

配置项：

```json
{
  "method": "POST",
  "url": "https://api.example.com/search",
  "headers": {
    "Authorization": "Bearer {{secrets.api_key}}"
  },
  "query_params": {},
  "body": {
    "query": "{{input.user_query}}"
  },
  "timeout": 30,
  "save_to": "variables.api_result"
}
```

API Node 必须支持：

1. GET / POST / PUT / PATCH / DELETE
2. Header 配置
3. Query 参数
4. Body 参数
5. 鉴权配置
6. 超时
7. 重试
8. 返回值映射

---

## 7.5 Intent Recognition Node

用途：识别用户意图，为分支器提供条件。

配置项：

```json
{
  "intents": [
    {
      "name": "query_order",
      "description": "查询订单状态"
    },
    {
      "name": "refund_request",
      "description": "用户申请退款"
    },
    {
      "name": "general_question",
      "description": "普通咨询问题"
    }
  ],
  "model": "gpt-4.1-mini",
  "save_to": "variables.intent_result"
}
```

输出：

```json
{
  "intent_result": {
    "intent": "refund_request",
    "confidence": 0.92
  }
}
```

---

## 7.6 Branch Node

用途：根据条件进入不同路径。

配置项：

```json
{
  "branches": [
    {
      "condition": "variables.intent_result.intent == 'query_order'",
      "target": "node_query_order"
    },
    {
      "condition": "variables.intent_result.intent == 'refund_request'",
      "target": "node_refund"
    },
    {
      "condition": "default",
      "target": "node_general_answer"
    }
  ]
}
```

条件表达式第一版建议使用 JSONLogic 或简单表达式引擎，不建议直接执行任意代码。

---

## 7.7 Loop Node

用途：重复执行一组节点，直到满足退出条件。

配置项：

```json
{
  "loop_type": "while",
  "condition": "variables.missing_fields.length > 0",
  "max_iterations": 5,
  "body_nodes": ["node_collect_info", "node_validate_info"]
}
```

循环节点必须具备：

1. 最大循环次数
2. 超时时间
3. 中断条件
4. 每轮 Trace
5. 错误处理

第一版可以不实现 Loop Node，第二版再加入。

---

## 7.8 Database Node

用途：查询或写入数据库。

配置项：

```json
{
  "connection_id": "main_db",
  "operation": "select",
  "query_template_id": "query_order_by_id",
  "params": {
    "order_id": "{{variables.order_id}}"
  },
  "save_to": "variables.order_info"
}
```

安全要求：

1. 不允许 LLM 直接拼接 SQL
2. 必须使用参数化查询
3. 写操作需要权限控制
4. 高风险写操作需要人工审批
5. 记录完整审计日志

---

## 7.9 Info Collection Node

用途：在用户信息不完整时，暂停工作流并向用户追问。

配置项：

```json
{
  "required_fields": [
    {
      "name": "order_id",
      "description": "订单号",
      "question": "请提供你的订单号"
    },
    {
      "name": "refund_reason",
      "description": "退款原因",
      "question": "请说明退款原因"
    }
  ],
  "save_to": "variables.collected_info"
}
```

该节点需要 Runtime 支持暂停和恢复。

---

## 7.10 Message Node

用途：向用户或外部系统发送消息。

配置项：

```json
{
  "channel": "chat",
  "message": "你的订单状态是：{{variables.order_info.status}}",
  "message_type": "text"
}
```

后续可支持：

```text
chat
email
sms
webhook
slack
企业微信
钉钉
```

---

## 7.11 Code Node

用途：执行受控代码，用于数据处理、格式转换、复杂逻辑计算。

配置项：

```json
{
  "language": "python",
  "code": "result = len(items)",
  "inputs": {
    "items": "{{variables.api_result.items}}"
  },
  "save_to": "variables.code_result",
  "timeout": 10
}
```

安全要求：

1. 必须沙箱化执行
2. 限制运行时间
3. 限制内存
4. 限制文件系统访问
5. 默认禁止网络访问
6. 限制依赖包
7. 记录执行日志

第一版建议先做表达式节点，暂缓完整代码执行。

---

# 8. 工作流状态 State 设计

所有节点通过统一 State 读写数据。

```json
{
  "input": {
    "user_query": "我想申请退款"
  },
  "variables": {
    "intent_result": {
      "intent": "refund_request",
      "confidence": 0.92
    },
    "order_id": "123456",
    "kb_context": []
  },
  "memory": {
    "session": {},
    "user": {}
  },
  "messages": [],
  "outputs": {},
  "metadata": {
    "user_id": "user_001",
    "workflow_id": "wf_001",
    "run_id": "run_001"
  }
}
```

设计原则：

1. 节点之间不直接互相调用
2. 节点通过 State 交换数据
3. 所有中间变量统一存储在 variables
4. input 只读，outputs 存最终输出
5. metadata 存运行上下文

---

# 9. 工作流图 Graph 设计

工作流由 nodes 和 edges 组成。

```json
{
  "nodes": [
    {
      "id": "start_1",
      "type": "start",
      "name": "开始"
    },
    {
      "id": "intent_1",
      "type": "intent",
      "name": "识别意图"
    }
  ],
  "edges": [
    {
      "id": "edge_1",
      "source": "start_1",
      "target": "intent_1"
    }
  ]
}
```

条件边示例：

```json
{
  "id": "edge_refund",
  "source": "branch_1",
  "target": "refund_flow_1",
  "condition": "variables.intent_result.intent == 'refund_request'"
}
```

---

# 10. 数据库设计

## 10.1 workflows

```sql
CREATE TABLE workflows (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  description TEXT,
  status VARCHAR(32) NOT NULL DEFAULT 'draft',
  current_version_id BIGINT,
  created_by BIGINT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 10.2 workflow_versions

```sql
CREATE TABLE workflow_versions (
  id BIGSERIAL PRIMARY KEY,
  workflow_id BIGINT NOT NULL,
  version INT NOT NULL,
  graph_json JSONB NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (workflow_id, version)
);
```

## 10.3 workflow_runs

```sql
CREATE TABLE workflow_runs (
  id BIGSERIAL PRIMARY KEY,
  workflow_id BIGINT NOT NULL,
  version_id BIGINT NOT NULL,
  status VARCHAR(32) NOT NULL,
  input_json JSONB,
  output_json JSONB,
  state_json JSONB,
  error_message TEXT,
  started_at TIMESTAMP,
  ended_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 10.4 node_runs

```sql
CREATE TABLE node_runs (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL,
  node_id VARCHAR(128) NOT NULL,
  node_type VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  input_json JSONB,
  output_json JSONB,
  error_message TEXT,
  started_at TIMESTAMP,
  ended_at TIMESTAMP,
  duration_ms INT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_node_runs_run_id ON node_runs(run_id);
CREATE INDEX idx_node_runs_node_id ON node_runs(node_id);
CREATE INDEX idx_node_runs_status ON node_runs(status);
```

## 10.5 tools

```sql
CREATE TABLE tools (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  type VARCHAR(64) NOT NULL,
  description TEXT,
  config_json JSONB,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 10.6 knowledge_bases

```sql
CREATE TABLE knowledge_bases (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  description TEXT,
  embedding_model VARCHAR(255),
  config_json JSONB,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 10.7 knowledge_chunks

如果使用 pgvector：

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE knowledge_chunks (
  id BIGSERIAL PRIMARY KEY,
  knowledge_base_id BIGINT NOT NULL,
  document_id BIGINT,
  content TEXT NOT NULL,
  embedding vector(1536),
  metadata_json JSONB,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 10.8 memories

```sql
CREATE TABLE memories (
  id BIGSERIAL PRIMARY KEY,
  scope VARCHAR(64) NOT NULL,
  user_id BIGINT,
  entity_id VARCHAR(255),
  content TEXT NOT NULL,
  embedding vector(1536),
  metadata_json JSONB,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

# 11. Runtime 执行流程

## 11.1 基本执行流程

```text
1. 创建 workflow_run
2. 加载 workflow_version
3. 初始化 state
4. 找到 start node
5. 执行当前节点
6. 写入 node_run 日志
7. 合并节点输出到 state
8. 根据 edge / branch / loop 解析下一个节点
9. 重复执行直到 End Node
10. 写入最终 output
11. 标记 workflow_run completed / failed
```

## 11.2 执行器伪代码

```python
class WorkflowExecutor:
    def run(self, workflow_version, initial_input):
        state = self.create_initial_state(initial_input)
        current_node_id = workflow_version.start_node_id

        while current_node_id:
            node = workflow_version.get_node(current_node_id)

            try:
                self.log_node_start(node, state)
                result = self.node_executor.execute(node, state)
                state = self.merge_result(state, result)
                self.log_node_success(node, result)
            except PauseExecution as pause:
                self.mark_run_waiting(pause)
                return state
            except Exception as e:
                self.log_node_error(node, e)
                current_node_id = self.handle_error(node, e)
                continue

            current_node_id = self.resolve_next_node(workflow_version, node, state)

        return state
```

---

# 12. 前端产品设计

## 12.1 页面结构

### 工作流列表页

功能：

1. 查看所有工作流
2. 创建工作流
3. 复制工作流
4. 发布状态展示
5. 最近运行状态展示

### 工作流编辑器页

布局：

```text
左侧：节点库
中间：画布
右侧：节点配置面板
底部：运行日志 / 调试面板
```

### 运行调试页

功能：

1. 输入测试数据
2. 运行整个工作流
3. 单步运行节点
4. 查看每个节点输入输出
5. 查看错误和耗时

### Trace 详情页

功能：

1. 查看完整运行链路
2. 查看每个节点日志
3. 查看 LLM token 使用量
4. 查看 API 请求响应
5. 查看错误堆栈
6. 复制调试数据

---

# 13. 权限与安全设计

## 13.1 权限控制

建议至少支持：

```text
Owner
Editor
Viewer
Operator
Admin
```

权限粒度：

1. 工作流查看
2. 工作流编辑
3. 工作流发布
4. 工作流运行
5. 查看运行日志
6. 配置工具
7. 使用敏感工具
8. 管理密钥

## 13.2 密钥管理

API Key、数据库密码、模型密钥不能明文出现在节点配置中。

应使用 Secret 管理：

```text
secret_id
secret_name
encrypted_value
created_by
updated_at
```

节点配置中只引用：

```json
{
  "Authorization": "Bearer {{secrets.crm_api_key}}"
}
```

## 13.3 高风险操作审批

以下操作建议默认需要审批：

1. 发送正式邮件
2. 修改数据库
3. 删除数据
4. 调用支付/退款 API
5. 调用生产系统写接口
6. 对外发送通知

---

# 14. 错误处理与重试

节点级别支持：

```json
{
  "retry": {
    "max_attempts": 3,
    "backoff": "exponential",
    "retry_on": ["timeout", "rate_limit", "network_error"]
  },
  "on_error": {
    "strategy": "go_to_node",
    "target": "node_error_handler"
  }
}
```

错误处理策略：

1. fail_workflow：直接失败
2. retry：重试当前节点
3. skip_node：跳过当前节点
4. go_to_node：进入错误处理节点
5. wait_for_human：等待人工处理

---

# 15. MVP 范围

## 15.1 第一版必须包含

1. 用户可以创建工作流
2. 用户可以拖拽节点并连线
3. 支持 Start / Input / LLM / Knowledge Base / Intent / Branch / API / Message / Output / End 节点
4. 支持保存草稿
5. 支持发布版本
6. 支持运行工作流
7. 支持查看每个节点的输入输出
8. 支持失败日志
9. 支持简单知识库检索
10. 支持模型配置

## 15.2 第一版暂不包含

1. 完整代码沙箱
2. 多人实时协作
3. 复杂循环
4. 并行执行
5. 复杂权限体系
6. 插件市场
7. 复杂评估系统
8. 多租户计费

---

# 16. 迭代路线

## 阶段 1：MVP

目标：跑通基础工作流。

功能：

1. 工作流 CRUD
2. 可视化编辑器
3. LLM 节点
4. API 节点
5. 知识库节点
6. 意图识别节点
7. 分支节点
8. 消息节点
9. Trace 日志

## 阶段 2：业务可用

目标：支持真实业务流程。

新增：

1. 数据库节点
2. 记忆节点
3. 信息收集节点
4. 人工审批节点
5. 错误处理节点
6. Secret 管理
7. 工作流版本回滚

## 阶段 3：生产增强

目标：支持规模化和稳定性。

新增：

1. 循环节点
2. 并行节点
3. 代码节点沙箱
4. Guardrail 节点
5. 评估节点
6. 成本统计
7. 监控告警
8. 多租户隔离

## 阶段 4：平台化

目标：形成完整 Agent 应用平台。

新增：

1. 模板市场
2. 插件市场
3. 自定义节点 SDK
4. 复杂权限体系
5. 企业集成
6. Workflow Scheduler
7. 批量任务
8. Agent 评测与优化闭环

---

# 17. 示例工作流：退款客服 Agent

## 17.1 流程图

```text
Start
  ↓
Input Node
  ↓
Intent Recognition Node
  ↓
Branch Node
  ├─ general_question → Knowledge Base Node → LLM Node → Message Node → End
  └─ refund_request → Info Collection Node → Database Node → Branch Node
                                              ├─ eligible → API Node → Message Node → End
                                              └─ not_eligible → Human Approval Node → Message Node → End
```

## 17.2 执行过程

1. 用户输入：“我要退款”
2. 意图识别节点输出 refund_request
3. 信息收集节点发现缺少订单号，向用户追问
4. 用户提供订单号
5. 数据库节点查询订单信息
6. 分支节点判断是否符合自动退款条件
7. API 节点提交退款申请
8. 消息节点通知用户处理结果
9. 工作流结束

---

# 18. 关键设计原则

1. 节点标准化
2. State 统一管理
3. 节点之间低耦合
4. 所有运行过程可追踪
5. 高风险动作必须可控
6. 工具调用必须有权限和审计
7. 工作流版本不可变
8. 草稿与发布版本分离
9. 第一版优先跑通闭环，不追求大而全
10. 复杂节点延后实现，先保证平台内核稳定

---

# 19. 初版结论

初版 Agent 工作流平台应优先实现一个稳定的节点运行时，而不是一开始追求大量复杂功能。

推荐第一版聚焦：

```text
可视化工作流编辑器
LLM 节点
知识库节点
API 节点
意图识别节点
分支节点
消息节点
运行日志 Trace
工作流版本发布
```

在基础闭环稳定后，再逐步加入：

```text
记忆节点
数据库节点
信息收集节点
循环节点
代码节点
人工审批节点
Guardrail 节点
```

最终平台应成为一个可配置、可追踪、可扩展、可安全落地的 Agent 应用运行平台。
