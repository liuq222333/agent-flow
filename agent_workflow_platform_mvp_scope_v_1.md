# Agent 工作流平台 MVP 范围与开发边界文档 v0.1

## 1. 文档目标

本文档用于明确 Agent 工作流平台第一版 MVP 的开发范围、核心功能、非目标范围、用户流程、验收标准和里程碑拆分。

本文档的目标不是描述完整平台愿景，而是帮助研发团队明确：

```text
第一版必须做什么
第一版暂时不做什么
哪些能力需要做到可用
哪些能力只需要预留扩展点
如何判断第一版开发完成
```

---

## 2. MVP 定位

第一版 MVP 的定位是：

> 一个可以通过可视化节点搭建、保存、发布、运行和调试简单 Agent 工作流的平台。

第一版不追求覆盖所有 Agent 能力，而是优先跑通从“创建工作流”到“执行工作流”再到“查看运行日志”的完整闭环。

MVP 重点能力：

```text
工作流可创建
节点可配置
画布可连线
工作流可保存
工作流可发布
工作流可运行
节点可执行
运行过程可追踪
执行结果可查看
失败原因可定位
```

---

## 3. 第一版核心目标

### 3.1 产品目标

用户可以在平台中完成以下操作：

1. 创建一个工作流
2. 在画布中拖拽和配置节点
3. 将节点通过连线组成流程
4. 保存工作流草稿
5. 发布工作流版本
6. 输入测试数据并运行工作流
7. 查看每个节点的输入、输出、状态和错误
8. 获取最终输出结果

### 3.2 技术目标

研发团队需要完成以下技术闭环：

1. 定义标准 Workflow Graph JSON
2. 定义标准 Node Protocol
3. 实现工作流版本管理
4. 实现最小 Runtime 执行器
5. 实现基础节点执行器
6. 实现 State 读写与变量解析
7. 实现节点运行日志 Trace
8. 实现前端可视化编辑器
9. 实现基础 API 接口
10. 实现基础权限和安全边界

---

## 4. MVP 用户角色

第一版可以先支持简单角色，不做复杂企业权限。

### 4.1 Admin

管理员。

权限：

```text
管理全部工作流
管理模型配置
管理知识库
管理 API 工具
查看全部运行记录
```

### 4.2 Editor

工作流编辑者。

权限：

```text
创建工作流
编辑工作流
发布工作流
运行工作流
查看自己有权限的运行记录
```

### 4.3 Viewer

查看者。

权限：

```text
查看工作流
查看运行结果
不能编辑和发布
```

MVP 阶段也可以先不实现完整 RBAC，只保留字段和接口扩展点。

---

## 5. MVP 核心页面

第一版建议包含以下页面。

## 5.1 工作流列表页

功能：

```text
查看工作流列表
创建新工作流
查看工作流状态
进入编辑器
进入运行记录
删除工作流，可选
复制工作流，可选
```

列表字段：

```text
工作流名称
状态：draft / published / archived
当前版本
创建人
更新时间
最近运行状态
操作按钮
```

---

## 5.2 工作流编辑器页

页面布局：

```text
左侧：节点库
中间：React Flow 画布
右侧：节点配置面板
底部：调试与运行日志面板
顶部：保存、发布、运行按钮
```

核心功能：

```text
拖拽节点到画布
移动节点
删除节点
配置节点
连接节点
删除连线
保存草稿
发布版本
运行测试
查看运行结果
```

---

## 5.3 工作流运行详情页

功能：

```text
查看某次运行的整体状态
查看输入数据
查看最终输出
查看每个节点的运行状态
查看节点输入输出
查看错误信息
查看耗时
查看 token 使用量，可选
```

---

## 5.4 知识库管理页

MVP 可以做轻量版。

功能：

```text
创建知识库
上传文档
查看文档处理状态
查看文档列表
删除文档
重新处理失败文档
```

---

## 5.5 工具/API 配置页

MVP 可以做简单版。

功能：

```text
创建 API 工具
配置 URL、Method、Headers、Body
测试 API 工具
在 API 节点中选择 API 工具
```

---

## 6. MVP 节点范围

第一版建议只实现最小但完整的节点集合。

## 6.1 必须实现节点

### 6.1.1 Start Node

用途：工作流起点。

能力：

```text
标记流程开始
只能有一个 Start Node
只能有出边，不能有入边
```

---

### 6.1.2 Input Node

用途：定义工作流输入。

能力：

```text
接收用户输入
定义输入字段
写入 state.input
支持文本输入
支持 JSON 输入，可选
```

示例输入：

```json
{
  "user_query": "我想申请退款"
}
```

---

### 6.1.3 LLM Node

用途：调用大模型生成结果。

能力：

```text
选择模型
配置 system prompt
配置 user prompt
引用变量
调用 LLM
输出结果写入 state.variables
记录 token 使用量
记录错误信息
```

MVP 支持：

```text
文本输入
文本输出
变量插值
基础模型参数：temperature、max_tokens
```

MVP 暂不支持：

```text
复杂 function calling
多模态输入
复杂 structured output 校验
Agent 自主工具调用
```

---

### 6.1.4 Knowledge Base Node

用途：从知识库检索相关内容。

能力：

```text
选择知识库
配置 query
配置 top_k
执行向量检索
返回相关 chunks
写入 state.variables.kb_context
保留来源信息
```

MVP 支持：

```text
PDF / DOCX / TXT / Markdown 文档上传
自动切分
Embedding
向量检索
top_k 返回
基础引用来源
```

MVP 暂不支持：

```text
复杂 OCR
高级 Rerank
复杂表格理解
多模态文档解析
外部知识源同步
```

---

### 6.1.5 Intent Recognition Node

用途：识别用户意图。

能力：

```text
配置意图列表
根据输入文本判断意图
输出 intent 和 confidence
写入 state.variables.intent_result
```

输出示例：

```json
{
  "intent": "refund_request",
  "confidence": 0.92
}
```

---

### 6.1.6 Branch Node

用途：根据条件选择下一条路径。

能力：

```text
读取 state 中变量
配置多个条件
命中条件后进入对应目标节点
支持 default 分支
```

MVP 支持简单条件：

```text
等于
不等于
包含
大于
小于
默认分支
```

MVP 不直接执行任意代码表达式。

---

### 6.1.7 API Node

用途：调用 HTTP API。

能力：

```text
配置 method
配置 URL
配置 headers
配置 query params
配置 body
引用变量
发送请求
保存响应到 state.variables
记录状态码和错误
```

MVP 支持：

```text
GET
POST
JSON Body
基础 Header
超时设置
```

MVP 暂不支持：

```text
复杂 OAuth
文件上传 API
流式 API
Webhook 回调等待
```

---

### 6.1.8 Message Node

用途：生成最终消息或中间回复。

能力：

```text
配置消息模板
引用变量
输出消息内容
写入 state.messages
可作为用户可见回复
```

MVP 支持：

```text
文本消息
变量插值
```

MVP 暂不支持：

```text
正式邮件发送
短信发送
企业微信/Slack 发送
多渠道消息
```

---

### 6.1.9 Output Node

用途：定义工作流最终输出。

能力：

```text
读取 state.variables
生成 state.outputs
标记业务输出
```

---

### 6.1.10 End Node

用途：结束工作流。

能力：

```text
标记流程结束
只能有入边，不能有出边
工作流执行到 End Node 后完成
```

---

## 6.2 MVP 暂不实现节点

以下节点第一版只预留设计，不进入 MVP 开发范围：

```text
Memory Read Node
Memory Write Node
Database Node
Info Collection Node
Code Node
Loop Node
Parallel Node
Merge Node
Human Approval Node
Guardrail Node
Evaluation Node
Scheduler Node
```

---

## 7. MVP 工作流能力范围

## 7.1 必须支持

```text
单起点
单终点或多终点
节点顺序执行
条件分支
变量引用
节点输入输出映射
节点执行日志
节点失败后终止工作流
手动重新运行工作流
```

## 7.2 暂不支持

```text
循环执行
并行执行
暂停与恢复
人工审批
长时间等待外部回调
定时调度
分布式工作流恢复
复杂补偿事务
```

---

## 8. Workflow Graph JSON 范围

MVP 的工作流配置由 nodes 和 edges 组成。

示例：

```json
{
  "version": "1.0",
  "nodes": [
    {
      "id": "start_1",
      "type": "start",
      "name": "开始",
      "position": { "x": 100, "y": 100 },
      "config": {}
    },
    {
      "id": "llm_1",
      "type": "llm",
      "name": "生成回答",
      "position": { "x": 300, "y": 100 },
      "input_mapping": {
        "question": "{{input.user_query}}"
      },
      "output_mapping": {
        "answer": "variables.answer"
      },
      "config": {
        "model": "gpt-4.1-mini",
        "system_prompt": "你是一个客服助手",
        "user_prompt": "请回答：{{question}}"
      }
    }
  ],
  "edges": [
    {
      "id": "edge_1",
      "source": "start_1",
      "target": "llm_1"
    }
  ]
}
```

---

## 9. State 范围

MVP 使用统一 State。

```json
{
  "input": {},
  "variables": {},
  "messages": [],
  "outputs": {},
  "metadata": {
    "workflow_id": "",
    "version_id": "",
    "run_id": "",
    "user_id": ""
  }
}
```

MVP 暂不实现完整 memory 字段，只预留扩展。

---

## 10. 变量引用范围

MVP 支持 Mustache 风格变量引用。

示例：

```text
{{input.user_query}}
{{variables.kb_context}}
{{variables.answer}}
{{metadata.user_id}}
```

变量解析要求：

```text
变量不存在时返回错误
变量类型不匹配时返回错误
变量引用需要在节点执行前完成解析
节点输出写入 output_mapping 指定路径
```

---

## 11. Runtime 范围

## 11.1 执行流程

```text
1. 创建 workflow_run
2. 加载已发布 workflow_version
3. 初始化 state
4. 找到 Start Node
5. 根据边找到下一个节点
6. 执行节点
7. 写入 node_run 日志
8. 合并节点输出到 state
9. 解析下一节点
10. 到达 End Node
11. 写入 outputs
12. 标记 workflow_run completed
```

## 11.2 Runtime MVP 不支持

```text
循环
并行
暂停恢复
长任务恢复
跨服务事务
复杂 DAG 拓扑优化
```

---

## 12. Trace 与日志范围

MVP 必须记录 workflow_run 和 node_run。

### workflow_run 记录

```text
run_id
workflow_id
version_id
status
input_json
output_json
state_json
error_message
started_at
ended_at
created_at
```

### node_run 记录

```text
node_run_id
run_id
node_id
node_type
status
input_json
output_json
error_message
started_at
ended_at
duration_ms
```

LLM Node 额外记录：

```text
model
prompt_tokens
completion_tokens
total_tokens
estimated_cost，可选
```

API Node 额外记录：

```text
method
url
status_code
duration_ms
error_message
```

---

## 13. 知识库 MVP 范围

## 13.1 必须支持

```text
创建知识库
上传文档
保存原始文件
异步解析文档
自动切分 chunk
生成 embedding
写入向量索引
知识库节点检索 top_k chunks
返回来源信息
文档处理失败可查看错误
```

## 13.2 文件类型

MVP 支持：

```text
PDF
DOCX
TXT
Markdown
```

CSV / HTML 可以作为增强项。

## 13.3 切分策略

MVP 默认使用自动切分。

默认参数：

```json
{
  "chunk_size_tokens": 500,
  "chunk_overlap_tokens": 80,
  "min_chunk_size_tokens": 100,
  "max_chunk_size_tokens": 800
}
```

---

## 14. API 接口 MVP 范围

第一版至少需要以下接口。

### Workflow API

```text
POST /api/workflows
GET /api/workflows
GET /api/workflows/:id
PUT /api/workflows/:id
DELETE /api/workflows/:id
POST /api/workflows/:id/publish
POST /api/workflows/:id/run
```

### Run API

```text
GET /api/runs/:run_id
GET /api/runs/:run_id/node-runs
```

### Knowledge Base API

```text
POST /api/knowledge-bases
GET /api/knowledge-bases
POST /api/knowledge-bases/:id/documents
GET /api/knowledge-bases/:id/documents
GET /api/documents/:id
POST /api/documents/:id/retry
```

### Tool API

```text
POST /api/tools
GET /api/tools
GET /api/tools/:id
PUT /api/tools/:id
POST /api/tools/:id/test
```

---

## 15. 数据库 MVP 范围

MVP 至少需要以下表：

```text
users
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
secrets，可选
```

第一版可以弱化组织、团队、多租户权限表。

---

## 16. 安全 MVP 范围

第一版必须包含：

```text
API Key 不明文暴露到前端
工具调用参数校验
API Node 超时限制
LLM Prompt 变量转义
上传文件大小限制
上传文件类型限制
工作流运行权限校验
基础审计日志
```

第一版暂不包含：

```text
完整企业 RBAC
复杂数据权限继承
代码节点沙箱
数据库写操作审批
多租户计费隔离
```

---

## 17. 非 MVP 范围

以下内容不进入第一版：

```text
完整多租户系统
复杂 RBAC 权限
多人实时协作编辑
插件市场
自定义节点 SDK
完整代码沙箱
循环节点
并行节点
人工审批节点
数据库节点
长期记忆节点
复杂评估系统
定时调度
Webhook 回调等待
企业微信/Slack/邮件正式发送
复杂 OCR 和多模态文档理解
```

这些能力可以在后续版本中逐步加入。

---

## 18. MVP 验收标准

第一版完成后，应该能够跑通以下场景。

## 18.1 场景一：简单 LLM 工作流

流程：

```text
Start → Input → LLM → Output → End
```

验收：

```text
用户可以创建该工作流
用户可以配置 LLM Prompt
用户可以保存并发布
用户可以输入问题并运行
系统返回 LLM 生成结果
系统记录每个节点运行日志
```

---

## 18.2 场景二：知识库问答工作流

流程：

```text
Start → Input → Knowledge Base → LLM → Output → End
```

验收：

```text
用户可以创建知识库
用户可以上传文档
文档可以被解析、切分、向量化
知识库节点可以检索相关 chunk
LLM 可以基于 kb_context 生成答案
答案可以展示来源信息
```

---

## 18.3 场景三：意图识别 + 分支工作流

流程：

```text
Start → Input → Intent Recognition → Branch
                                  ├─ 分支 A → LLM → Output → End
                                  └─ 分支 B → API → LLM → Output → End
```

验收：

```text
用户可以配置多个意图
系统可以识别意图
Branch Node 可以根据意图进入不同分支
API Node 可以调用外部接口
最终输出正确生成
Trace 中能看到每个节点执行路径
```

---

## 19. 里程碑拆分

## Milestone 1：基础数据模型与 API

目标：完成后端基础能力。

任务：

```text
设计数据库表
实现 workflow CRUD
实现 workflow_version 发布
实现 workflow_run 创建
实现 node_run 记录
实现基础模型配置
```

验收：

```text
可以通过 API 创建、保存、发布和运行一个静态工作流
```

---

## Milestone 2：Runtime 最小执行器

目标：跑通最小工作流。

任务：

```text
实现 Graph 加载
实现 State 初始化
实现节点顺序执行
实现变量解析
实现 LLM Node
实现 Output Node
实现 Trace 记录
```

验收：

```text
Start → Input → LLM → Output → End 可以完整运行
```

---

## Milestone 3：前端工作流编辑器

目标：用户可以可视化搭建流程。

任务：

```text
实现工作流列表页
实现 React Flow 画布
实现节点拖拽
实现节点配置面板
实现连线保存
实现保存草稿
实现发布按钮
实现运行按钮
实现运行结果展示
```

验收：

```text
用户可以在页面上搭建并运行简单 LLM 工作流
```

---

## Milestone 4：知识库能力

目标：支持 RAG 工作流。

任务：

```text
实现知识库 CRUD
实现文档上传
实现文档解析
实现 chunk 切分
实现 embedding
实现向量检索
实现 Knowledge Base Node
```

验收：

```text
Start → Input → Knowledge Base → LLM → Output → End 可以运行
```

---

## Milestone 5：分支与 API 能力

目标：支持更接近业务流程的工作流。

任务：

```text
实现 Intent Recognition Node
实现 Branch Node
实现 API Node
实现 Message Node
实现条件判断
实现 API 工具配置
```

验收：

```text
可以根据用户意图进入不同分支，并在某个分支中调用 API
```

---

## Milestone 6：稳定性与上线准备

目标：让 MVP 可试用。

任务：

```text
补充错误处理
补充节点重试
补充运行详情页
补充上传限制
补充基础权限
补充部署配置
补充日志和监控
```

验收：

```text
MVP 可以部署到测试环境并支持真实用户试用
```

---

## 20. 第一版成功标准

MVP 成功的判断标准：

```text
用户可以独立创建一个工作流
用户可以通过画布配置节点和连线
用户可以发布工作流
用户可以运行工作流
系统可以执行 LLM、知识库、API、分支等基础节点
系统可以记录并展示完整运行日志
开发团队可以基于节点协议继续扩展新节点
```

最小成功闭环：

```text
创建工作流 → 配置节点 → 保存草稿 → 发布版本 → 输入数据 → 执行工作流 → 查看输出 → 查看 Trace
```

---

## 21. 后续版本方向

MVP 完成后，后续可以按以下顺序扩展：

```text
V0.2：数据库节点、信息收集节点、记忆节点
V0.3：循环节点、人工审批节点、错误处理节点
V0.4：代码节点沙箱、并行节点、Guardrail 节点
V0.5：企业权限、多租户、团队协作
V1.0：插件市场、自定义节点 SDK、评估系统、生产级调度
```

---

## 22. 结论

第一版 MVP 的核心不是“做全所有节点”，而是完成一个稳定的工作流执行闭环。

第一版应优先保证：

```text
节点协议稳定
State 结构稳定
Runtime 可运行
Trace 可查看
前端可配置
知识库可检索
LLM 可生成
API 可调用
分支可流转
```

只要这些能力稳定，后续增加记忆、数据库、循环、代码、人工审批等复杂节点，就会变成可控的增量开发。

