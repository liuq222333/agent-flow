# Agent 工作流平台 API 接口设计文档 v0.1

## 1. 文档目标

本文档定义 Agent 工作流平台 MVP 阶段的后端 API 接口，包括工作流、发布版本、运行记录、节点 Trace、知识库、文档、API 工具、模型配置、Secret 和节点类型 Schema。

API 设计目标：

```text
支撑前端工作流编辑器
支撑工作流发布和运行
支撑运行详情与 Trace 查询
支撑知识库上传和检索
支撑 API 工具配置和测试
支撑模型与 Secret 管理
```

---

## 2. 通用约定

### 2.1 Base URL

```text
/api/v1
```

### 2.2 Content-Type

```text
application/json
```

文件上传接口使用：

```text
multipart/form-data
```

### 2.3 认证方式

MVP 阶段先使用 mock user，不实现真实登录。

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

后端在 `AUTH_MODE=mock` 时自动注入 `current_user`，用于：

```text
created_by
updated_by
published_by
workflow_runs.created_by
权限判断
审计日志
```

API 层仍预留 Bearer Token 入口，后续接 JWT：

```http
Authorization: Bearer <access_token>
```

MVP mock 模式下，该 Header 可以不传。

### 2.4 时间格式

统一使用 ISO 8601：

```text
2026-05-15T08:30:00Z
```

### 2.5 分页参数

列表接口统一支持：

```text
page       默认 1
page_size  默认 20，最大 100
```

响应格式：

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 100
}
```

### 2.6 通用错误响应

```json
{
  "error": {
    "code": "invalid_request",
    "message": "请求参数不合法",
    "details": {}
  },
  "request_id": "req_001"
}
```

常见错误码：

```text
invalid_request
unauthorized
permission_denied
not_found
conflict
validation_failed
runtime_error
provider_error
rate_limited
internal_error
```

---

## 3. Workflow API

## 3.1 创建工作流

```http
POST /api/v1/workflows
```

请求：

```json
{
  "name": "退款客服 Agent",
  "description": "处理用户退款咨询和申请",
  "draft_graph_json": {
    "schema_version": "1.0",
    "nodes": [],
    "edges": []
  }
}
```

响应：

```json
{
  "id": 1,
  "name": "退款客服 Agent",
  "description": "处理用户退款咨询和申请",
  "status": "draft",
  "current_version_id": null,
  "draft_graph_json": {
    "schema_version": "1.0",
    "nodes": [],
    "edges": []
  },
  "created_at": "2026-05-15T08:30:00Z",
  "updated_at": "2026-05-15T08:30:00Z"
}
```

---

## 3.2 查询工作流列表

```http
GET /api/v1/workflows
```

查询参数：

```text
status       draft / published / archived，可选
keyword      按名称搜索，可选
created_by   创建人，可选
page
page_size
```

响应：

```json
{
  "items": [
    {
      "id": 1,
      "name": "退款客服 Agent",
      "status": "published",
      "current_version_id": 10,
      "current_version": 3,
      "created_by": 1001,
      "updated_at": "2026-05-15T08:30:00Z",
      "latest_run": {
        "run_id": 2001,
        "status": "completed",
        "created_at": "2026-05-15T08:40:00Z"
      }
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1
}
```

---

## 3.3 查询工作流详情

```http
GET /api/v1/workflows/{workflow_id}
```

响应：

```json
{
  "id": 1,
  "name": "退款客服 Agent",
  "description": "处理用户退款咨询和申请",
  "status": "published",
  "current_version_id": 10,
  "draft_graph_json": {},
  "created_by": 1001,
  "created_at": "2026-05-15T08:30:00Z",
  "updated_at": "2026-05-15T08:30:00Z"
}
```

---

## 3.4 更新工作流草稿

```http
PUT /api/v1/workflows/{workflow_id}
```

请求：

```json
{
  "name": "退款客服 Agent",
  "description": "处理退款和订单查询",
  "draft_graph_json": {
    "schema_version": "1.0",
    "nodes": [],
    "edges": []
  }
}
```

说明：

```text
保存草稿时只做弱校验
不影响已发布 workflow_versions
不影响正在运行的 workflow_runs
```

---

## 3.5 删除工作流

```http
DELETE /api/v1/workflows/{workflow_id}
```

MVP 建议软删除：

```json
{
  "success": true
}
```

---

## 3.6 校验工作流图

```http
POST /api/v1/workflows/{workflow_id}/validate
```

请求：

```json
{
  "mode": "publish",
  "graph_json": {
    "schema_version": "1.0",
    "nodes": [],
    "edges": []
  }
}
```

`mode`：

```text
draft     弱校验
publish   强校验
run       运行前校验
```

响应：

```json
{
  "valid": false,
  "errors": [
    {
      "code": "missing_end_node",
      "message": "工作流必须至少包含一个 End Node",
      "path": "nodes"
    }
  ],
  "warnings": [
    {
      "code": "unused_node",
      "message": "存在未从 Start Node 可达的节点",
      "path": "nodes[3]"
    }
  ]
}
```

---

## 3.7 发布工作流版本

```http
POST /api/v1/workflows/{workflow_id}/publish
```

请求：

```json
{
  "release_note": "MVP 第一个可运行版本"
}
```

响应：

```json
{
  "workflow_id": 1,
  "version_id": 10,
  "version": 3,
  "schema_version": "1.0",
  "created_at": "2026-05-15T08:30:00Z"
}
```

发布规则：

```text
读取 workflows.draft_graph_json
执行强校验
创建 workflow_versions
更新 workflows.current_version_id
更新 workflows.status 为 published
```

---

## 3.8 查询版本列表

```http
GET /api/v1/workflows/{workflow_id}/versions
```

响应：

```json
{
  "items": [
    {
      "id": 10,
      "workflow_id": 1,
      "version": 3,
      "schema_version": "1.0",
      "release_note": "MVP 第一个可运行版本",
      "published_by": 1001,
      "created_at": "2026-05-15T08:30:00Z"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1
}
```

---

## 3.9 查询版本详情

```http
GET /api/v1/workflow-versions/{version_id}
```

响应：

```json
{
  "id": 10,
  "workflow_id": 1,
  "version": 3,
  "schema_version": "1.0",
  "graph_json": {},
  "release_note": "MVP 第一个可运行版本",
  "created_at": "2026-05-15T08:30:00Z"
}
```

---

## 4. Run API

## 4.1 运行工作流

```http
POST /api/v1/workflows/{workflow_id}/run
```

请求：

```json
{
  "input": {
    "user_query": "我想申请退款"
  },
  "version_id": 10,
  "trigger_type": "manual",
  "execution_mode": "sync"
}
```

字段说明：

```text
version_id      可选，不传则使用 current_version_id
trigger_type    manual / api / test
execution_mode  sync / async
```

MVP 建议：

```text
调试场景使用 sync
正式或可能耗时的运行使用 async
```

同步响应：

```json
{
  "run_id": 2001,
  "status": "completed",
  "output": {
    "answer": "已为你生成退款说明"
  },
  "started_at": "2026-05-15T08:40:00Z",
  "ended_at": "2026-05-15T08:40:03Z"
}
```

异步响应：

```json
{
  "run_id": 2001,
  "status": "pending"
}
```

---

## 4.2 查询运行列表

```http
GET /api/v1/runs
```

查询参数：

```text
workflow_id
version_id
status
created_by
page
page_size
```

响应：

```json
{
  "items": [
    {
      "id": 2001,
      "workflow_id": 1,
      "version_id": 10,
      "status": "completed",
      "trigger_type": "manual",
      "created_by": 1001,
      "started_at": "2026-05-15T08:40:00Z",
      "ended_at": "2026-05-15T08:40:03Z"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1
}
```

---

## 4.3 查询运行详情

```http
GET /api/v1/runs/{run_id}
```

响应：

```json
{
  "id": 2001,
  "workflow_id": 1,
  "version_id": 10,
  "status": "completed",
  "input_json": {
    "user_query": "我想申请退款"
  },
  "output_json": {
    "answer": "已为你生成退款说明"
  },
  "state_json": {},
  "error_code": null,
  "error_message": null,
  "started_at": "2026-05-15T08:40:00Z",
  "ended_at": "2026-05-15T08:40:03Z"
}
```

---

## 4.4 查询节点运行记录

```http
GET /api/v1/runs/{run_id}/node-runs
```

响应：

```json
{
  "items": [
    {
      "id": 3001,
      "run_id": 2001,
      "node_id": "llm_1",
      "node_type": "llm",
      "node_name": "生成回答",
      "status": "success",
      "attempt": 1,
      "input_json": {},
      "output_json": {},
      "error_code": null,
      "error_message": null,
      "duration_ms": 1320,
      "metadata_json": {
        "model": "gpt-4.1-mini",
        "total_tokens": 1300
      },
      "started_at": "2026-05-15T08:40:01Z",
      "ended_at": "2026-05-15T08:40:02Z"
    }
  ]
}
```

---

## 4.5 查询 Trace 详情

```http
GET /api/v1/runs/{run_id}/trace
```

响应：

```json
{
  "run": {
    "id": 2001,
    "status": "completed",
    "input_json": {},
    "output_json": {}
  },
  "nodes": [
    {
      "node_run_id": 3001,
      "node_id": "llm_1",
      "node_type": "llm",
      "status": "success",
      "duration_ms": 1320,
      "input_json": {},
      "output_json": {},
      "metadata_json": {}
    }
  ],
  "graph_json": {}
}
```

该接口用于运行详情页一次性展示图、路径和 Trace。

---

## 4.6 取消运行

```http
POST /api/v1/runs/{run_id}/cancel
```

MVP 中仅对 `pending` 或 `running` 状态生效。

响应：

```json
{
  "run_id": 2001,
  "status": "cancelled"
}
```

---

## 5. Knowledge Base API

## 5.1 创建知识库

```http
POST /api/v1/knowledge-bases
```

请求：

```json
{
  "name": "售后政策知识库",
  "description": "存放退款、换货、售后规则",
  "embedding_model": "text-embedding-3-small",
  "config": {
    "chunk_size_tokens": 500,
    "chunk_overlap_tokens": 80
  }
}
```

响应：

```json
{
  "id": 101,
  "name": "售后政策知识库",
  "status": "active",
  "created_at": "2026-05-15T08:30:00Z"
}
```

---

## 5.2 查询知识库列表

```http
GET /api/v1/knowledge-bases
```

查询参数：

```text
keyword
status
page
page_size
```

---

## 5.3 查询知识库详情

```http
GET /api/v1/knowledge-bases/{kb_id}
```

---

## 5.4 上传文档

```http
POST /api/v1/knowledge-bases/{kb_id}/documents
```

请求：

```text
multipart/form-data
file=<binary>
metadata_json={"tags":["售后"],"language":"zh"}
```

响应：

```json
{
  "document_id": 5001,
  "knowledge_base_id": 101,
  "file_name": "售后政策.pdf",
  "status": "uploaded",
  "processing_job_id": 7001
}
```

上传后异步执行：

```text
保存原始文件
创建 document
创建 document_processing_job
进入解析、切分、embedding、索引流程
```

---

## 5.5 查询文档列表

```http
GET /api/v1/knowledge-bases/{kb_id}/documents
```

查询参数：

```text
status
file_type
page
page_size
```

响应：

```json
{
  "items": [
    {
      "id": 5001,
      "file_name": "售后政策.pdf",
      "file_type": "pdf",
      "file_size": 102400,
      "status": "indexed",
      "error_stage": null,
      "error_message": null,
      "created_at": "2026-05-15T08:30:00Z"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1
}
```

---

## 5.6 查询文档详情

```http
GET /api/v1/documents/{document_id}
```

响应：

```json
{
  "id": 5001,
  "knowledge_base_id": 101,
  "file_name": "售后政策.pdf",
  "status": "indexed",
  "error_stage": null,
  "error_message": null,
  "metadata_json": {},
  "created_at": "2026-05-15T08:30:00Z"
}
```

---

## 5.7 重试文档处理

```http
POST /api/v1/documents/{document_id}/retry
```

请求：

```json
{
  "from_stage": "embedding"
}
```

响应：

```json
{
  "document_id": 5001,
  "status": "embedding",
  "processing_job_id": 7002
}
```

---

## 5.8 删除文档

```http
DELETE /api/v1/documents/{document_id}
```

响应：

```json
{
  "success": true
}
```

删除规则：

```text
documents 标记 deleted
knowledge_chunks 异步删除或标记无效
原始文件按保留策略清理
```

---

## 5.9 测试检索

```http
POST /api/v1/knowledge-bases/{kb_id}/retrieve
```

请求：

```json
{
  "query": "7 天无理由退款规则是什么？",
  "top_k": 5,
  "score_threshold": 0.65
}
```

响应：

```json
{
  "chunks": [
    {
      "chunk_id": "chunk_001",
      "content": "用户可在签收后 7 天内申请退款...",
      "score": 0.86,
      "source": {
        "document_id": 5001,
        "file_name": "售后政策.pdf",
        "page_start": 3,
        "page_end": 3,
        "section_title": "退款规则"
      }
    }
  ]
}
```

---

## 6. Tool API

## 6.1 创建工具

```http
POST /api/v1/tools
```

请求：

```json
{
  "name": "订单查询 API",
  "type": "api",
  "description": "根据订单号查询订单状态",
  "config": {
    "method": "POST",
    "url": "https://api.example.com/orders/query",
    "headers": {
      "Content-Type": "application/json",
      "Authorization": "Bearer {{secrets.order_api_key}}"
    },
    "body_template": {
      "order_id": "{{order_id}}"
    },
    "timeout": 30
  }
}
```

响应：

```json
{
  "id": 9001,
  "name": "订单查询 API",
  "type": "api",
  "status": "active"
}
```

---

## 6.2 查询工具列表

```http
GET /api/v1/tools
```

查询参数：

```text
type
status
keyword
page
page_size
```

---

## 6.3 查询工具详情

```http
GET /api/v1/tools/{tool_id}
```

响应中可以返回 secret 引用，但不能返回 secret 真实值。

---

## 6.4 更新工具

```http
PUT /api/v1/tools/{tool_id}
```

---

## 6.5 测试工具

```http
POST /api/v1/tools/{tool_id}/test
```

请求：

```json
{
  "input": {
    "order_id": "123456"
  }
}
```

响应：

```json
{
  "success": true,
  "status_code": 200,
  "duration_ms": 420,
  "response": {
    "status": "paid",
    "amount": 199
  }
}
```

---

## 7. Model API

## 7.1 查询模型 Provider

```http
GET /api/v1/model-providers
```

响应：

```json
{
  "items": [
    {
      "id": 1,
      "name": "openai",
      "provider_type": "openai",
      "status": "active"
    }
  ]
}
```

---

## 7.2 查询可用模型

```http
GET /api/v1/model-configs
```

查询参数：

```text
provider_id
model_type     chat / embedding / rerank
status
```

响应：

```json
{
  "items": [
    {
      "id": 11,
      "provider_id": 1,
      "model_name": "gpt-4.1-mini",
      "model_type": "chat",
      "display_name": "GPT-4.1 Mini",
      "context_window": 128000,
      "default_config": {
        "temperature": 0.3,
        "max_tokens": 1000
      }
    }
  ]
}
```

---

## 8. Secret API

## 8.1 创建 Secret

```http
POST /api/v1/secrets
```

请求：

```json
{
  "secret_key": "order_api_key",
  "display_name": "订单 API Key",
  "value": "sk_xxx"
}
```

响应：

```json
{
  "id": 10001,
  "secret_key": "order_api_key",
  "display_name": "订单 API Key",
  "status": "active",
  "created_at": "2026-05-15T08:30:00Z"
}
```

---

## 8.2 查询 Secret 列表

```http
GET /api/v1/secrets
```

响应不返回真实值：

```json
{
  "items": [
    {
      "id": 10001,
      "secret_key": "order_api_key",
      "display_name": "订单 API Key",
      "status": "active",
      "created_at": "2026-05-15T08:30:00Z"
    }
  ]
}
```

---

## 8.3 更新 Secret

```http
PUT /api/v1/secrets/{secret_id}
```

请求：

```json
{
  "display_name": "订单 API Key",
  "value": "sk_new"
}
```

---

## 9. Node Type API

前端编辑器需要根据节点类型渲染配置面板。

## 9.1 查询节点类型列表

```http
GET /api/v1/node-types
```

响应：

```json
{
  "items": [
    {
      "type": "llm",
      "name": "LLM Node",
      "category": "ai",
      "description": "调用大模型生成结果"
    },
    {
      "type": "knowledge_base",
      "name": "Knowledge Base Node",
      "category": "knowledge",
      "description": "从知识库检索相关内容"
    }
  ]
}
```

---

## 9.2 查询节点 Schema

```http
GET /api/v1/node-types/{node_type}/schema
```

响应：

```json
{
  "type": "llm",
  "node_schema": {
    "required": ["id", "type", "name", "config"],
    "properties": {}
  },
  "config_schema": {
    "required": ["model", "user_prompt"],
    "properties": {
      "provider": {
        "type": "string"
      },
      "model": {
        "type": "string"
      },
      "system_prompt": {
        "type": "string"
      },
      "user_prompt": {
        "type": "string"
      }
    }
  },
  "form_schema": {
    "fields": [
      {
        "name": "config.model",
        "label": "模型",
        "component": "select",
        "required": true
      },
      {
        "name": "config.user_prompt",
        "label": "User Prompt",
        "component": "textarea",
        "required": true
      }
    ]
  }
}
```

---

## 10. API 权限矩阵

MVP 简化角色：

```text
Admin
Editor
Viewer
```

建议权限：

```text
Admin   所有接口
Editor  创建、编辑、发布、运行自己有权限的工作流
Viewer  查看工作流和运行记录，不可编辑和发布
```

Secret 接口建议只允许：

```text
Admin
```

工具测试接口建议：

```text
Admin
Editor
```

---

## 11. MVP 接口实现优先级

```text
1. Workflow CRUD
2. Workflow validate / publish
3. Workflow run
4. Run detail / node-runs / trace
5. Node types / schema
6. Model configs
7. Secrets
8. Tools CRUD / test
9. Knowledge base CRUD
10. Documents upload / list / retry
11. Knowledge retrieve test
```

---

## 12. 结论

MVP API 的核心闭环是：

```text
创建工作流
保存草稿
校验草稿
发布版本
运行版本
查询运行结果
查询节点 Trace
```

其中最关键的接口是：

```text
POST /workflows
PUT /workflows/{id}
POST /workflows/{id}/publish
POST /workflows/{id}/run
GET /runs/{run_id}/trace
```

只要这组接口稳定，前端编辑器、Runtime 和 Trace 详情页就可以并行开发。
