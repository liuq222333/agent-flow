# Agent 工作流平台 MVP 开发任务拆解文档 v0.1

## 1. 文档目标

本文档用于把 Agent 工作流平台 MVP 拆解成可执行的研发任务、里程碑、依赖关系、验收标准和推荐开发顺序。

本文档承接：

```text
平台总设计文档
MVP 范围与开发边界文档
节点协议设计文档
数据库 ER 设计文档
API 接口设计文档
Runtime 详细设计文档
```

目标是让研发团队可以按模块并行开发，并持续交付可运行闭环。

---

## 2. MVP 总目标

MVP 成功闭环：

```text
创建工作流
→ 拖拽节点并配置
→ 保存草稿
→ 发布版本
→ 发布生成本地 workflow.py
→ 输入测试数据
→ 执行工作流
→ 查看最终输出
→ 查看节点 Trace
```

第一版不追求复杂 Agent 能力，优先保证：

```text
节点协议稳定
Runtime 可运行
前端可配置
Trace 可定位
知识库可检索
LLM 可生成
API 可调用
Branch 可流转
```

---

## 3. 研发主线拆分

MVP 可拆成 6 条研发主线：

```text
1. 基础工程与数据库
2. 工作流管理与发布
3. Runtime 与节点执行器
4. 前端工作流编辑器
5. 知识库与文档处理
6. 工具、模型、Secret 与安全
```

推荐优先级：

```text
基础工程与数据库
→ 工作流管理与发布
→ Workflow Codegen
→ Runtime 最小闭环
→ 前端编辑器最小闭环
→ 知识库节点
→ Intent / Branch / API / Message
→ 稳定性与上线准备
```

---

## 4. Milestone 0：项目初始化

目标：建立可持续开发的基础工程。

### 4.1 后端初始化

任务：

```text
创建后端项目
配置环境变量
配置数据库连接
配置 Redis，作为 RQ 队列依赖
配置日志
配置统一错误响应
配置接口路由前缀 /api/v1
配置 mock user 认证中间件
配置数据库迁移工具
```

验收：

```text
后端服务可启动
/health 返回正常
可以连接数据库
可以执行一次空迁移
接口错误响应格式统一
所有接口可获得 mock current_user
```

---

### 4.2 前端初始化

任务：

```text
创建前端项目
配置路由
配置 API Client
配置基础布局
配置 React Flow
配置状态管理
配置表单组件
配置运行环境变量
```

验收：

```text
前端服务可启动
可以访问工作流列表页占位
可以请求后端 /health
React Flow 画布可以渲染
```

---

### 4.3 数据库初始化

任务：

```text
创建 users 表
创建 workflows 表
创建 workflow_versions 表
创建 workflow_runs 表
创建 node_runs 表
创建 model_providers 表
创建 model_configs 表
创建 secrets 表
创建 tools 表
创建 knowledge_bases 表
创建 documents 表
创建 knowledge_chunks 表
创建 document_processing_jobs 表
创建 audit_logs 表
```

验收：

```text
数据库迁移可重复执行
核心索引已创建
本地开发库可初始化
可以插入一条测试用户
```

---

## 5. Milestone 1：工作流 CRUD 与发布

目标：完成工作流草稿保存、图校验和版本发布。

### 5.1 Workflow API

任务：

```text
实现 POST /api/v1/workflows
实现 GET /api/v1/workflows
实现 GET /api/v1/workflows/{workflow_id}
实现 PUT /api/v1/workflows/{workflow_id}
实现 DELETE /api/v1/workflows/{workflow_id}
```

验收：

```text
可以创建工作流
可以保存 draft_graph_json
可以查询工作流详情
可以分页查询工作流列表
删除使用软删除
```

---

### 5.2 Graph Validator

任务：

```text
实现弱校验
实现强校验
校验 schema_version
校验节点 ID 唯一
校验边 ID 唯一
校验 Start Node 唯一
校验至少一个 End Node
校验 edge source / target 存在
校验 Start 无入边
校验 End 无出边
校验非 Branch 普通节点最多一条出边
校验 Branch target 存在
校验 Branch target 必须有对应 edge
校验 Branch 出边必须能映射回 branches[].target
校验发布版本不允许 enabled: false
校验不支持环
```

验收：

```text
POST /api/v1/workflows/{id}/validate 可返回 errors / warnings
非法 Graph 无法发布
合法 Graph 可以通过强校验
```

---

### 5.3 Workflow Publish

任务：

```text
实现 POST /api/v1/workflows/{workflow_id}/publish
读取 workflows.draft_graph_json
执行强校验
生成 workflow_versions.version 自增
写入 workflow_versions.graph_json
调用 WorkflowCodegenService 生成本地 workflow.py
生成 manifest.json
写入 workflow_versions.code_path / code_hash / code_generated_at
更新 workflows.current_version_id
更新 workflows.status = published
写 audit_logs
```

验收：

```text
草稿可发布成不可变版本
同一工作流 version 递增
发布后修改草稿不影响旧版本
发布 v1 / v2 会生成不同版本目录
旧版本代码不会被覆盖
Runtime 默认加载 workflow_versions.code_path 指向的本地 workflow.py
workflow_versions.graph_json 继续作为不可变发布快照和 codegen 输入
```

---

### 5.4 Workflow Codegen

任务：

```text
实现 WorkflowCodegenService
生成 backend/generated_workflows/workflow_000001/v000001/
生成 __init__.py
生成 workflow.py
生成 manifest.json
workflow.py 固定暴露 async def run(input_data, context) -> dict
计算 workflow.py 的 code_hash
不引入 area / project / folder 模型
每次发布生成新版本目录，不覆盖旧版本代码
```

验收：

```text
发布 v1 生成 backend/generated_workflows/workflow_000001/v000001/
发布 v2 生成 backend/generated_workflows/workflow_000001/v000002/
v1 目录在发布 v2 后仍保持不变
manifest.json 记录 workflow_id / version / graph_hash / code_hash / generated_at
手动修改 workflow.py 后，运行以本地文件为准
手动修改 workflow.py 后，Runtime 可记录 code_modified = true
workflow.py 缺失时返回 workflow_code_missing
workflow.py import 失败时返回 workflow_code_import_failed
run 入口缺失时返回 workflow_entrypoint_missing
代码生成失败时不产生可见的已发布版本
```

---

## 6. Milestone 2：Runtime 最小闭环

目标：跑通最小工作流：

```text
Start → Input → LLM → Output → End
```

### 6.1 Runtime Core

任务：

```text
实现 GeneratedWorkflowLoader
实现 StateManager
实现 VariableResolver
实现 MappingEngine
实现 NodeExecutorRegistry
实现 TraceRecorder
实现 RuntimeContext 受控方法
实现 WorkflowExecutor
```

验收：

```text
可以加载已发布 workflow_version
可以读取 workflow_versions.code_path
可以 import 生成的 workflow.py
可以调用 run(input_data, context)
可以初始化 State
可以按边执行节点
可以写 workflow_runs
可以写 node_runs
可以写 state_json
可以写 code_path_at_run / code_hash_at_run / code_modified
可以输出 state.outputs
```

---

### 6.2 变量与映射

任务：

```text
实现 Mustache 变量解析
支持 input / variables / messages / outputs / metadata
预留 secrets 服务端解析域
完整变量引用保留原始类型
嵌入字符串变量转字符串
变量不存在时报 variable_not_found
实现 input_mapping 到 node_input
实现 node.config 到 resolved_config
实现 output_mapping 写入 State
支持 target = messages 追加
支持 target = outputs merge
支持 Output Node 的 node_output.outputs merge 到 state.outputs
```

验收：

```text
{{input.user_query}} 可以解析
{{variables.kb_context}} 数组类型可保留
不存在变量会导致节点失败
config 中 {{question}} 可解析为 node_input.question
output_mapping 不能写 input / metadata / secrets
```

---

### 6.3 最小节点执行器

任务：

```text
实现 StartNodeExecutor
实现 InputNodeExecutor
实现 OutputNodeExecutor
实现 EndNodeExecutor
实现 LLMNodeExecutor
```

验收：

```text
Input Node 可以校验输入字段
LLM Node 可以调用模型生成文本
Output Node 可以生成最终 outputs
End Node 可以结束 workflow_run
Trace 中可以看到每个节点输入、输出、耗时、状态
```

---

### 6.4 Run API

任务：

```text
实现 POST /api/v1/workflows/{workflow_id}/run
实现 GET /api/v1/runs
实现 GET /api/v1/runs/{run_id}
实现 GET /api/v1/runs/{run_id}/node-runs
实现 GET /api/v1/runs/{run_id}/trace
```

验收：

```text
可以同步运行一个已发布工作流
可以查询运行详情
可以查询节点 Trace
失败时 workflow_run.status = failed
成功时 workflow_run.status = completed
```

---

## 7. Milestone 3：前端编辑器最小闭环

目标：用户可以在页面上创建、配置、发布和运行简单 LLM 工作流。

### 7.1 工作流列表页

任务：

```text
展示工作流列表
支持创建工作流
支持搜索
支持状态筛选
支持进入编辑器
支持进入运行记录
```

验收：

```text
用户可以创建并进入一个空工作流
列表中显示状态、版本、更新时间、最近运行状态
```

---

### 7.2 工作流编辑器页

任务：

```text
实现左侧节点库
实现 React Flow 画布
实现拖拽新增节点
实现节点移动
实现节点删除
实现连线
实现删除连线
实现顶部保存按钮
实现顶部发布按钮
实现顶部运行按钮
```

验收：

```text
用户可以搭建 Start → Input → LLM → Output → End
节点位置可以保存
连线可以保存
保存后刷新页面图仍然存在
```

---

### 7.3 节点配置面板

任务：

```text
实现基础信息配置 name / description
实现 Input Node 字段配置
实现 LLM Node 模型和 Prompt 配置
实现 Output Node 输出配置
实现 input_mapping 配置
实现 output_mapping 配置
实现 timeout / retry 基础配置，可折叠
```

验收：

```text
用户可以配置 LLM user_prompt
用户可以配置 output_mapping
表单保存后写入 draft_graph_json
```

---

### 7.4 运行调试面板

任务：

```text
支持输入 JSON 测试数据
支持运行当前已发布版本
支持展示 workflow_run 状态
支持展示最终 output
支持展示 node_runs 列表
支持点击节点查看输入输出
```

验收：

```text
用户可以在编辑器中运行工作流
可以看到 LLM 输出
可以定位节点错误
```

---

## 8. Milestone 4：知识库能力

目标：跑通知识库问答工作流：

```text
Start → Input → Knowledge Base → LLM → Output → End
```

### 8.1 Knowledge Base API

任务：

```text
实现 POST /api/v1/knowledge-bases
实现 GET /api/v1/knowledge-bases
实现 GET /api/v1/knowledge-bases/{kb_id}
实现 POST /api/v1/knowledge-bases/{kb_id}/documents
实现 GET /api/v1/knowledge-bases/{kb_id}/documents
实现 GET /api/v1/documents/{document_id}
实现 POST /api/v1/documents/{document_id}/retry
实现 DELETE /api/v1/documents/{document_id}
实现 POST /api/v1/knowledge-bases/{kb_id}/retrieve
```

验收：

```text
可以创建知识库
可以上传文档
可以查看文档处理状态
可以测试检索
```

---

### 8.2 文档处理 Pipeline

任务：

```text
保存原始文件
识别文件类型
解析 PDF / DOCX / TXT / Markdown
自动切分 chunk
计算 token_count
调用 embedding model
写入 knowledge_chunks.embedding
更新 documents.status
失败时记录 error_stage / error_message
```

验收：

```text
上传文档后可以异步处理到 indexed
失败文档可以看到错误信息
失败文档可以重试
```

---

### 8.3 KnowledgeBaseNodeExecutor

任务：

```text
解析 config.query
生成 query embedding
执行向量检索
按 knowledge_base_ids 过滤
按 score_threshold 过滤
返回 top_k chunks
返回 source 信息
写 Trace metadata
```

验收：

```text
Knowledge Base Node 可以返回 kb_context
LLM Node 可以引用 kb_context 生成答案
Output 中可以返回 sources
```

---

## 9. Milestone 5：Intent / Branch / API / Message

目标：跑通接近业务流程的分支工作流。

### 9.1 Intent Node

任务：

```text
实现 IntentNodeExecutor
根据 config.intents 构造分类 prompt
要求模型返回 JSON
解析 intent / confidence
支持 fallback_intent
记录 token usage
```

验收：

```text
输入“我要退款”可以识别 refund_request
输入普通咨询可以识别 general_question
Trace 中能看到 intent 输出
```

---

### 9.2 Branch Node

任务：

```text
实现 BranchNodeExecutor
支持 eq / neq / contains / gt / gte / lt / lte / exists / not_exists
支持 default
返回 selected_branch_id / target
生成代码使用 target 选择下一段编排
```

验收：

```text
Branch 可以根据 variables.intent_result.intent 进入不同路径
没有命中且没有 default 时工作流失败
```

---

### 9.3 Tool 与 API Node

任务：

```text
实现 Tool CRUD
实现 Tool Test
实现 APINodeExecutor
支持 GET / POST
支持 headers / query_params / JSON body
支持变量引用
支持 secrets 引用
支持 timeout
支持响应体大小限制
Trace 中敏感信息脱敏
```

验收：

```text
API Node 可以调用一个测试 HTTP API
响应可以写入 variables
错误状态码可以记录到 Trace
Authorization 不出现在 Trace 明文中
```

---

### 9.4 Message Node

任务：

```text
实现 MessageNodeExecutor
支持 text message
支持 template 变量引用
通过 output_mapping 追加到 state.messages
前端展示 messages
```

验收：

```text
工作流可以生成用户可见消息
messages 不会覆盖历史消息
```

---

## 10. Milestone 6：稳定性与上线准备

目标：MVP 可部署到测试环境并给真实用户试用。

### 10.1 错误处理与重试

任务：

```text
统一 RuntimeError 格式
实现节点 timeout
实现 retry.max_attempts
实现 retry_on
实现 fixed backoff
实现 workflow_run failed 终态
补充错误码文档
```

验收：

```text
LLM/API 超时可重试
重试 attempt 都有 node_runs
最终失败可在运行详情页看到原因
```

---

### 10.2 安全

任务：

```text
API Key 不返回前端
Secret 加密存储
Trace 脱敏
上传文件大小限制
上传文件类型限制
API Node 超时限制
API Node 响应大小限制
基于 mock user 的工作流运行权限校验
基础审计日志
```

验收：

```text
前端无法看到 secret 明文
敏感 header 不进入 Trace
非法文件类型无法上传
无权限用户无法运行工作流
```

---

### 10.3 部署与运维

任务：

```text
编写开发环境启动说明
编写测试环境部署说明
配置数据库迁移命令
配置后台 worker
配置日志输出
配置基础监控
配置健康检查
```

验收：

```text
测试环境可部署
服务异常有日志
文档处理 worker 可运行
数据库迁移可执行
```

---

## 11. 任务依赖关系

关键依赖：

```text
数据库迁移 → Workflow API
Workflow API → 前端列表页 / 编辑器保存
GraphValidator → 发布接口
发布接口 → Workflow Codegen
Workflow Codegen → Runtime 运行
Runtime Core → Run API / Trace 页面
Model Config / Secret → LLM Node / API Node
Knowledge Base API → Knowledge Base Node
Intent Node → Branch Node 场景
Tool API → API Node
```

并行建议：

```text
前端编辑器可以在 Workflow API 完成后开始
Runtime Core 可以在 workflow_versions.code_path 契约完成后开始
知识库 Pipeline 可以和前端编辑器并行
Tool / Secret 可以和 Knowledge Base 并行
```

---

## 12. 推荐开发顺序

```text
1. 建库与迁移
2. Workflow CRUD
3. GraphValidator
4. Publish
5. Workflow Codegen
6. Runtime Core
7. Start / Input / LLM / Output / End
8. Run API / Trace API
9. 前端列表页和编辑器
10. 编辑器运行调试
11. 知识库文档处理
12. Knowledge Base Node
13. Intent Node
14. Branch Node
15. Tool / Secret / API Node
16. Message Node
17. 错误处理、重试、权限、部署
```

---

## 13. MVP 验收用例

### 13.1 简单 LLM 工作流

流程：

```text
Start → Input → LLM → Output → End
```

验收：

```text
可视化搭建
保存草稿
发布版本
生成本地 workflow.py
输入 user_query 运行
返回 answer
Trace 显示所有节点 success
```

---

### 13.2 知识库问答工作流

流程：

```text
Start → Input → Knowledge Base → LLM → Output → End
```

验收：

```text
上传文档后可 indexed
Knowledge Base Node 返回 chunks
LLM 基于 chunks 回答
Output 返回 answer 和 sources
```

---

### 13.3 意图分支工作流

流程：

```text
Start → Input → Intent → Branch
                         ├─ refund_request → LLM → Output → End
                         └─ general_question → Knowledge Base → LLM → Output → End
```

验收：

```text
Intent 输出 intent / confidence
Branch 进入正确路径
Trace 显示实际执行路径
未执行路径没有 node_run
```

---

### 13.4 API 调用工作流

流程：

```text
Start → Input → API → LLM → Message → Output → End
```

验收：

```text
API Node 调用测试接口成功
响应写入 variables
LLM 可以引用 API 响应
Message 追加到 state.messages
敏感 header 脱敏
```

---

## 14. 风险与处理建议

### 14.1 Runtime 和前端协议不一致

风险：

```text
前端保存的 graph_json 与 Node Protocol / Codegen 期望结构不一致
```

建议：

```text
以 Node Protocol 为唯一契约
后端提供 /node-types/{type}/schema
保存草稿弱校验
发布强校验
Codegen 只消费发布强校验通过的 graph_json
```

---

### 14.2 LLM 和 Embedding Provider 不稳定

风险：

```text
外部模型超时、限流、失败
```

建议：

```text
节点级 timeout
retry_on
错误码标准化
Trace 记录 provider 错误
```

---

### 14.3 知识库处理耗时

风险：

```text
文档解析和 embedding 较慢，影响用户体验
```

建议：

```text
异步处理
文档状态可见
失败可重试
第一版限制文件大小和类型
```

---

### 14.4 Secret 泄露

风险：

```text
Secret 被写入 graph_json、Trace 或前端响应
```

建议：

```text
只允许保存 secret_key 引用
服务端解析 secrets
Trace 写入前统一 redactor 脱敏
Secret API 不返回 value
```

---

## 15. 第一版完成定义

MVP 完成必须满足：

```text
用户可以创建工作流
用户可以在画布搭建节点
用户可以保存草稿
用户可以发布版本
系统可以为已发布版本生成本地 workflow.py
用户可以运行工作流
运行时以 workflow_versions.code_path 指向的本地代码为准
系统可以执行 LLM / Knowledge Base / Intent / Branch / API / Message / Output
系统可以记录 workflow_run 和 node_run
用户可以查看完整 Trace
知识库文档可以上传、处理、检索
API Key 不明文暴露
测试环境可以部署
```

---

## 16. 结论

MVP 开发应坚持一个顺序：

```text
先稳定协议
再跑通 Runtime
再补齐前端体验
再扩展知识库和业务节点
最后做稳定性、安全和部署
```

只要第一版完整跑通四个验收用例，平台就具备继续扩展 Memory、Database、Info Collection、Loop、Code、Human Approval 等复杂节点的基础。
