# Agent 工作流平台前端编辑器详细设计文档 v0.1

## 1. 文档目标

本文档定义 Agent 工作流平台 MVP 阶段前端产品结构、工作流编辑器、React Flow 画布、节点库、节点配置面板、运行调试面板、Trace 面板、状态管理和接口对接方式。

本文档服务于：

```text
前端页面开发
React Flow 节点组件开发
节点配置表单开发
工作流调试体验设计
前后端接口对接
MVP 验收测试
```

---

## 2. MVP 前端目标

用户在前端需要完成完整闭环：

```text
创建工作流
进入编辑器
拖拽节点
配置节点
连接节点
保存草稿
发布版本
输入测试数据
运行工作流
查看输出
查看 Trace
定位错误
```

第一版不做：

```text
多人实时协作
复杂版本 Diff
复杂权限后台
插件市场
自定义节点 SDK 页面
复杂调度配置
代码节点 IDE
```

---

## 3. 前端页面结构

MVP 页面：

```text
/workflows                         工作流列表页
/workflows/:workflow_id/editor     工作流编辑器页
/runs/:run_id                      运行详情页，可选
/knowledge-bases                   知识库列表页
/knowledge-bases/:kb_id            知识库详情页
/tools                             API 工具配置页
/models                            模型配置页，可选
/secrets                           Secret 管理页，可选，仅 Admin
```

最小必须页面：

```text
工作流列表页
工作流编辑器页
运行详情/Trace 面板
知识库管理页
工具/API 配置页
```

---

## 4. 工作流列表页

## 4.1 页面目标

让用户快速查看、创建、进入和运行工作流。

## 4.2 列表字段

```text
工作流名称
描述
状态：draft / published / archived
当前版本
创建人
更新时间
最近运行状态
操作
```

## 4.3 操作

```text
创建工作流
进入编辑器
复制工作流，可选
删除工作流
查看运行记录
```

## 4.4 接口

```text
GET /api/v1/workflows
POST /api/v1/workflows
DELETE /api/v1/workflows/{workflow_id}
```

---

## 5. 工作流编辑器整体布局

页面布局：

```text
顶部工具栏
  ├─ 工作流名称
  ├─ 保存草稿
  ├─ 校验
  ├─ 发布
  ├─ 运行
  └─ 当前版本/状态

左侧节点库
  ├─ 输入输出
  ├─ AI
  ├─ 知识库
  ├─ 工具
  └─ 控制流

中间画布
  ├─ React Flow
  ├─ 节点
  ├─ 连线
  ├─ 小地图
  └─ 缩放控件

右侧配置面板
  ├─ 基础信息
  ├─ 输入映射
  ├─ 节点配置
  ├─ 输出映射
  ├─ 重试与超时
  └─ 错误处理

底部调试面板
  ├─ 测试输入
  ├─ 运行结果
  ├─ 节点 Trace
  └─ 错误详情
```

---

## 6. React Flow 画布设计

## 6.1 Graph 数据映射

后端协议：

```json
{
  "schema_version": "1.0",
  "nodes": [],
  "edges": []
}
```

前端 React Flow 内部：

```typescript
type EditorNode = {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: WorkflowNode;
};

type EditorEdge = {
  id: string;
  source: string;
  target: string;
  label?: string;
  data?: WorkflowEdge;
};
```

保存前转换为 Node Protocol：

```text
React Flow nodes[].data → graph_json.nodes
React Flow edges[].data → graph_json.edges
React Flow node.position → node.position
```

---

## 6.2 节点视觉状态

节点需要展示：

```text
节点名称
节点类型图标
节点简要描述
配置是否完整
运行状态
错误标记
耗时，可选
```

运行状态：

```text
idle
running
success
failed
skipped
```

颜色建议：

```text
idle      默认边框
running   蓝色边框
success   绿色边框
failed    红色边框
skipped   灰色边框
```

---

## 6.3 节点组件

MVP 节点组件：

```text
StartNodeView
InputNodeView
LLMNodeView
KnowledgeBaseNodeView
IntentNodeView
BranchNodeView
APINodeView
MessageNodeView
OutputNodeView
EndNodeView
```

第一版可以使用统一基础节点组件：

```text
BaseWorkflowNode
  ├─ icon
  ├─ title
  ├─ type label
  ├─ status indicator
  ├─ input handle
  └─ output handle
```

不同节点只替换图标、颜色和 handle 规则。

---

## 6.4 连线规则

MVP 连线规则：

```text
Start Node 不能有入边
End Node 不能有出边
普通节点最多一条出边
Branch Node 可以多条出边
不能连接到自己
不能重复连接同一 source / target
第一版不支持环
```

前端需要做即时提示，最终以后端发布强校验为准。

---

## 6.5 Branch 连线展示

Branch Node 的真实路由来源于：

```text
node.config.branches[].target
```

前端建议：

```text
Branch Node 出边 label 显示 branch id 或条件名称
配置 Branch 时选择 target 节点
保存时同步 config.branches[].target
出边用于可视化展示
后端强校验 target 必须存在
```

---

## 7. 节点库设计

## 7.1 节点分类

```text
输入输出
  Start
  Input
  Output
  End

AI
  LLM
  Intent Recognition

知识
  Knowledge Base

工具
  API

控制流
  Branch

消息
  Message
```

---

## 7.2 节点默认模板

拖拽创建节点时，前端生成默认节点：

```json
{
  "id": "llm_abc123",
  "type": "llm",
  "name": "生成回答",
  "description": "",
  "position": {
    "x": 300,
    "y": 100
  },
  "input_mapping": {},
  "output_mapping": {},
  "config": {},
  "retry": {
    "max_attempts": 1,
    "backoff": "none"
  },
  "timeout": 60,
  "on_error": {
    "strategy": "fail_workflow"
  },
  "enabled": true
}
```

节点模板来源：

```text
优先从 GET /api/v1/node-types/{node_type}/schema 获取
前端可内置一份兜底模板
后端 schema 是最终契约
```

---

## 8. 右侧节点配置面板

## 8.1 通用区域

所有节点都有：

```text
基础信息
  name
  description

输入映射
  input_mapping

节点配置
  config

输出映射
  output_mapping

高级设置
  retry
  timeout
  on_error
  enabled
```

MVP 默认隐藏高级设置，只在展开后显示。

---

## 8.2 Start Node 配置

显示：

```text
节点名称
描述
```

规则提示：

```text
只能有一个 Start Node
只能有出边
```

---

## 8.3 Input Node 配置

字段配置：

```text
字段名 name
字段类型 type
显示名称 label
是否必填 required
默认值 default
```

MVP 支持字段类型：

```text
string
number
boolean
object
```

---

## 8.4 LLM Node 配置

配置项：

```text
provider
model
system_prompt
user_prompt
temperature
max_tokens
response_format
```

输入映射常用：

```json
{
  "question": "{{input.user_query}}",
  "context": "{{variables.kb_context}}"
}
```

输出映射常用：

```json
{
  "answer": "variables.answer"
}
```

---

## 8.5 Knowledge Base Node 配置

配置项：

```text
knowledge_base_ids
query
retrieval_mode
top_k
score_threshold
context_budget_tokens
```

输出映射常用：

```json
{
  "chunks": "variables.kb_context"
}
```

知识库选择数据来自：

```text
GET /api/v1/knowledge-bases
```

---

## 8.6 Intent Node 配置

配置项：

```text
model
intents
fallback_intent
```

Intent 列表字段：

```text
name
description
```

输出映射常用：

```json
{
  "intent": "variables.intent_result.intent",
  "confidence": "variables.intent_result.confidence"
}
```

---

## 8.7 Branch Node 配置

配置项：

```text
branches
```

每个分支：

```text
id
condition.left
condition.operator
condition.right
target
```

支持操作符：

```text
eq
neq
contains
gt
gte
lt
lte
exists
not_exists
default
```

target 从当前画布节点中选择。

---

## 8.8 API Node 配置

配置项：

```text
method
url
headers
query_params
body
response_path
timeout
```

MVP 支持：

```text
GET
POST
JSON Body
基础 Header
```

Secret 引用：

```text
{{secrets.order_api_key}}
```

前端只展示引用文本，不解析真实值。

---

## 8.9 Message Node 配置

配置项：

```text
message_type
template
```

输出映射常用：

```json
{
  "message": "messages"
}
```

---

## 8.10 Output Node 配置

配置项：

```text
outputs
```

示例：

```json
{
  "answer": "{{variables.answer}}",
  "sources": "{{variables.kb_context}}"
}
```

输出映射常用：

```json
{
  "outputs": "outputs"
}
```

---

## 9. 表单渲染策略

MVP 推荐两层实现：

```text
通用 JSON 编辑能力
常用节点专属表单
```

原因：

```text
专属表单保证体验
JSON 编辑保证协议可调试
后续节点扩展时不阻塞前端发版
```

表单 Schema 来源：

```text
GET /api/v1/node-types/{node_type}/schema
```

---

## 10. 编辑器状态管理

建议状态结构：

```typescript
type WorkflowEditorState = {
  workflow: WorkflowDetail | null;
  graph: WorkflowGraph;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  dirty: boolean;
  validation: GraphValidationResult | null;
  run: CurrentRunState | null;
  nodeRunMap: Record<string, NodeRun[]>;
};
```

状态来源：

```text
workflow       GET /api/v1/workflows/{workflow_id}
node schemas   GET /api/v1/node-types
models         GET /api/v1/model-configs
knowledge      GET /api/v1/knowledge-bases
tools          GET /api/v1/tools
```

---

## 11. 保存草稿流程

```text
1. 用户编辑画布或节点配置
2. 前端状态 dirty = true
3. 点击保存
4. 将 React Flow 状态转换为 graph_json
5. PUT /api/v1/workflows/{workflow_id}
6. 后端弱校验
7. 保存 workflows.draft_graph_json
8. 前端 dirty = false
```

失败处理：

```text
展示错误消息
保留本地编辑状态
允许用户继续修改后重试
```

---

## 12. 发布流程

```text
1. 用户点击发布
2. 前端先保存草稿
3. POST /api/v1/workflows/{workflow_id}/validate mode=publish
4. 如果有 errors，展示错误列表并定位节点
5. 如果校验通过，POST /api/v1/workflows/{workflow_id}/publish
6. 更新 current_version_id 和版本号
```

校验错误展示：

```text
顶部错误摘要
画布节点红色标记
右侧面板显示字段错误
```

---

## 13. 运行调试流程

```text
1. 用户输入测试 JSON
2. 点击运行
3. POST /api/v1/workflows/{workflow_id}/run
4. execution_mode = sync 或 async
5. 前端展示 running 状态
6. 查询 /api/v1/runs/{run_id}/trace
7. 将 node_runs 映射到画布节点状态
8. 展示最终 output 和 messages
```

MVP 可先使用同步运行，后续切换异步轮询。

异步轮询：

```text
每 1s 查询一次 trace
completed / failed / cancelled 后停止
```

---

## 14. Trace 面板设计

Trace 面板展示：

```text
整体运行状态
运行输入
最终输出
节点运行列表
节点输入
节点输出
错误信息
耗时
LLM token usage
API status_code
Knowledge returned_chunks
```

节点列表字段：

```text
节点名称
节点类型
状态
耗时
attempt
开始时间
结束时间
```

点击节点：

```text
画布选中对应节点
右侧或底部展示该节点 node_run 详情
```

---

## 15. 运行状态映射

workflow_run.status：

```text
pending     等待中
running     运行中
completed   成功
failed      失败
cancelled   已取消
```

node_run.status：

```text
running     运行中
success     成功
failed      失败
skipped     跳过
retrying    重试中
```

前端画布映射：

```text
没有 node_run       idle
最新 node_run running    running
最新 node_run success    success
最新 node_run failed     failed
```

---

## 16. 知识库页面设计

## 16.1 知识库列表

功能：

```text
创建知识库
查看知识库列表
查看文档数量
查看更新时间
进入详情
```

接口：

```text
GET /api/v1/knowledge-bases
POST /api/v1/knowledge-bases
```

---

## 16.2 知识库详情

功能：

```text
上传文档
查看文档列表
查看处理状态
查看失败原因
重试处理
删除文档
测试检索
```

接口：

```text
POST /api/v1/knowledge-bases/{kb_id}/documents
GET /api/v1/knowledge-bases/{kb_id}/documents
POST /api/v1/documents/{document_id}/retry
DELETE /api/v1/documents/{document_id}
POST /api/v1/knowledge-bases/{kb_id}/retrieve
```

---

## 17. 工具/API 配置页面

功能：

```text
创建 API 工具
配置 method / url / headers / body
测试工具
查看测试响应
编辑工具
```

接口：

```text
GET /api/v1/tools
POST /api/v1/tools
GET /api/v1/tools/{tool_id}
PUT /api/v1/tools/{tool_id}
POST /api/v1/tools/{tool_id}/test
```

---

## 18. Secret 页面

MVP 可以只给 Admin 使用。

功能：

```text
创建 Secret
查看 Secret 列表
更新 Secret
不展示真实 value
```

接口：

```text
GET /api/v1/secrets
POST /api/v1/secrets
PUT /api/v1/secrets/{secret_id}
```

---

## 19. 前端 API Client

建议统一封装：

```text
workflowApi
runApi
nodeTypeApi
knowledgeBaseApi
toolApi
modelApi
secretApi
```

统一处理：

```text
Authorization Header
request_id
错误响应
分页参数
loading 状态
```

---

## 20. 用户体验细节

MVP 必须保证：

```text
未保存离开页面时提醒
发布前自动保存或提醒保存
运行前提示必须先发布
校验错误能定位到节点
运行失败能看到错误详情
JSON 输入格式错误时前端即时提示
长文本 Prompt 使用多行编辑器
Trace 中大 JSON 支持折叠
```

---

## 21. 权限展示

角色：

```text
Admin
Editor
Viewer
```

前端行为：

```text
Viewer 只能查看，不能保存、发布、运行
Editor 可以创建、编辑、发布、运行
Admin 可以管理模型、工具、Secret
```

注意：

```text
前端权限只负责体验
后端权限才是最终安全边界
```

---

## 22. 前端测试重点

单元测试：

```text
graph_json 与 React Flow 转换
节点默认模板生成
变量引用输入校验
Branch target 配置
```

集成测试：

```text
创建工作流
保存草稿
发布工作流
运行工作流
查看 Trace
上传文档
测试 API 工具
```

端到端测试：

```text
Start → Input → LLM → Output → End
Start → Input → Knowledge Base → LLM → Output → End
Start → Input → Intent → Branch → LLM/API → Output → End
```

---

## 23. 实现优先级

```text
1. 工作流列表页
2. 编辑器基础布局
3. React Flow 画布
4. 节点库和默认模板
5. 节点配置面板
6. 保存草稿
7. 发布和校验错误展示
8. 运行调试面板
9. Trace 面板
10. 知识库页面
11. 工具/API 页面
12. Secret / Model 配置页面
```

---

## 24. 结论

前端 MVP 的关键是让用户真正完成一条工作流，而不是堆很多页面。

第一版最重要的体验闭环是：

```text
画布可搭建
节点可配置
草稿可保存
版本可发布
运行可调试
Trace 可定位
```

只要编辑器和 Runtime 的协议稳定，后续新增节点时只需要补节点表单、节点视图和少量校验提示，整体前端架构不需要重写。

