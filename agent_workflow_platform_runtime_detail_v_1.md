# Agent 工作流平台 Runtime 详细设计文档 v0.1

## 1. 文档目标

本文档定义 Agent 工作流平台 MVP 阶段 Workflow Runtime 的详细设计，包括运行时架构、执行流程、State 管理、变量解析、节点执行生命周期、分支解析、重试超时、Trace 记录、错误处理和各类 MVP 节点执行器职责。

Runtime 的目标是：

```text
加载已发布工作流版本
初始化运行 State
按 Graph 执行节点
解析变量和输入输出映射
调用对应 NodeExecutor
处理分支、错误、重试和超时
记录完整 Trace
输出最终结果
```

---

## 2. MVP Runtime 边界

MVP 支持：

```text
单 Start Node
至少一个 End Node
有向无环图
顺序执行
条件分支
变量引用
节点输入输出映射
节点重试
节点超时
失败终止工作流
运行 Trace
同步运行和异步运行
```

MVP 暂不支持：

```text
循环
并行
暂停恢复
人工审批
长时间等待回调
分布式恢复
补偿事务
调度运行
代码沙箱
```

---

## 3. Runtime 总体架构

```mermaid
flowchart TD
  API["Run API"] --> RunService["WorkflowRunService"]
  RunService --> GraphLoader["GraphLoader"]
  RunService --> GraphValidator["GraphValidator"]
  RunService --> Executor["WorkflowExecutor"]

  Executor --> StateManager["StateManager"]
  Executor --> VariableResolver["VariableResolver"]
  Executor --> MappingEngine["MappingEngine"]
  Executor --> NodeRegistry["NodeExecutorRegistry"]
  Executor --> TraceRecorder["TraceRecorder"]
  Executor --> NextResolver["NextNodeResolver"]
  Executor --> RetryController["RetryController"]
  Executor --> TimeoutController["TimeoutController"]

  NodeRegistry --> StartExecutor["StartExecutor"]
  NodeRegistry --> InputExecutor["InputExecutor"]
  NodeRegistry --> LLMExecutor["LLMExecutor"]
  NodeRegistry --> KBExecutor["KnowledgeBaseExecutor"]
  NodeRegistry --> IntentExecutor["IntentExecutor"]
  NodeRegistry --> BranchExecutor["BranchExecutor"]
  NodeRegistry --> APIExecutor["APIExecutor"]
  NodeRegistry --> MessageExecutor["MessageExecutor"]
  NodeRegistry --> OutputExecutor["OutputExecutor"]
  NodeRegistry --> EndExecutor["EndExecutor"]
```

---

## 4. 核心组件职责

## 4.1 WorkflowRunService

负责运行入口：

```text
接收运行请求
选择 workflow_version
创建 workflow_run
选择同步或异步执行
返回 run_id 或最终结果
```

---

## 4.2 GraphLoader

负责加载工作流版本：

```text
根据 version_id 加载 workflow_versions.graph_json
如果未指定 version_id，使用 workflows.current_version_id
保证运行只依赖发布版本，不读取 draft_graph_json
```

---

## 4.3 GraphValidator

负责运行前强校验：

```text
schema_version 合法
节点类型合法
节点 ID 唯一
边 ID 唯一
必须有且只有一个 Start Node
必须至少有一个 End Node
Start Node 不能有入边
End Node 不能有出边
所有 edge.source / edge.target 必须存在
除 disabled 节点外，业务节点必须可从 Start Node 到达
MVP 不支持环，检测到环应发布失败或运行失败
Branch Node 的 target 必须存在
Branch Node 的 target 建议同时存在对应出边，便于前端展示和 Trace
```

---

## 4.4 WorkflowExecutor

Runtime 核心执行器：

```text
初始化 State
找到 Start Node
循环执行当前节点
创建 node_run
调用 NodeExecutor
写回 State
解析下一节点
更新 workflow_run 状态
```

---

## 4.5 StateManager

负责 State 的读写和持久化：

```text
创建初始 State
读取路径值
写入路径值
合并节点输出
每个节点成功后保存 state_json
最终写入 output_json
```

---

## 4.6 VariableResolver

负责解析 Mustache 变量：

```text
解析 input_mapping
解析 config 内需要运行时替换的字段
解析 Output Node 的 outputs
解析 Message Node 的 template
解析 API Node 的 headers / body / query_params
解析 secrets 引用
```

可引用域：

```text
input
variables
messages
outputs
metadata
secrets
```

说明：

```text
secrets 是服务端专用解析域
前端只能看到 secret_key，不能看到真实值
Trace 中不得记录 secret 真实值
```

---

## 4.7 MappingEngine

负责输入输出映射：

```text
input_mapping → node_input
node_output + output_mapping → state
```

---

## 4.8 NodeExecutorRegistry

根据 node.type 获取对应执行器：

```text
start             StartNodeExecutor
input             InputNodeExecutor
llm               LLMNodeExecutor
knowledge_base    KnowledgeBaseNodeExecutor
intent            IntentNodeExecutor
branch            BranchNodeExecutor
api               APINodeExecutor
message           MessageNodeExecutor
output            OutputNodeExecutor
end               EndNodeExecutor
```

---

## 4.9 TraceRecorder

负责写入：

```text
workflow_runs
node_runs
错误信息
耗时
token usage
API 调用元数据
知识库检索元数据
```

---

## 4.10 NextNodeResolver

负责解析下一节点：

```text
普通节点：根据出边找到下一个节点
Branch Node：根据 selected target 找到下一个节点
End Node：结束工作流
```

---

## 5. Runtime 数据结构

## 5.1 State

MVP State：

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

约束：

```text
input 运行开始后只读
metadata 运行开始后只读
variables 用于节点间交换数据
messages 用于用户可见消息
outputs 用于最终业务输出
```

---

## 5.2 RuntimeContext

NodeExecutor 执行时接收上下文：

```json
{
  "run_id": 2001,
  "workflow_id": 1,
  "version_id": 10,
  "user_id": 1001,
  "request_id": "req_001",
  "logger": {},
  "secrets": {},
  "services": {}
}
```

`services` 可包含：

```text
llm_client
embedding_client
knowledge_service
http_client
tool_service
trace_recorder
```

---

## 6. 执行入口

## 6.1 同步运行

适合调试和短流程：

```text
POST /workflows/{id}/run
execution_mode = sync
```

规则：

```text
API 请求等待 Runtime 完成
超过 API 网关超时时间前应返回超时错误
建议只用于编辑器调试
```

---

## 6.2 异步运行

适合正式运行：

```text
POST /workflows/{id}/run
execution_mode = async
```

规则：

```text
API 创建 workflow_run 后返回 run_id
后台任务执行 Runtime
前端轮询 /runs/{run_id} 或 /runs/{run_id}/trace
```

---

## 7. 运行生命周期

```mermaid
sequenceDiagram
  participant Client
  participant API
  participant RunService
  participant Runtime
  participant DB
  participant Executor

  Client->>API: POST /workflows/{id}/run
  API->>RunService: create run
  RunService->>DB: insert workflow_run pending
  RunService->>Runtime: execute run
  Runtime->>DB: update workflow_run running
  Runtime->>Executor: execute nodes
  Executor->>DB: insert/update node_runs
  Executor->>DB: update state_json
  Runtime->>DB: update workflow_run completed/failed
  Runtime-->>RunService: result
  RunService-->>API: response
  API-->>Client: run result
```

---

## 8. 详细执行流程

```text
1. 接收运行请求
2. 校验用户是否有运行权限
3. 加载 workflow 和 workflow_version
4. 运行 GraphValidator 强校验
5. 创建 workflow_run，状态 pending
6. 初始化 State
7. workflow_run 更新为 running
8. 找到 Start Node
9. 执行当前节点
10. 记录 node_run
11. 应用 output_mapping 写回 State
12. 持久化 workflow_runs.state_json
13. 解析下一节点
14. 重复 9-13
15. 到达 End Node
16. 写入 workflow_runs.output_json
17. workflow_run 标记 completed
18. 返回结果
```

失败流程：

```text
1. 捕获 RuntimeError
2. 写 node_run failed
3. 判断 retry 策略
4. 如果可重试，创建下一次 attempt
5. 如果不可重试，应用 on_error
6. MVP 默认 fail_workflow
7. workflow_run 标记 failed
8. 保存 error_code / error_message
```

---

## 9. 变量解析规则

## 9.1 变量引用语法

```text
{{input.user_query}}
{{variables.kb_context}}
{{variables.intent_result.intent}}
{{metadata.user_id}}
{{secrets.order_api_key}}
```

---

## 9.2 完整变量引用

如果整个字段是一个变量引用，则保留原始类型。

输入：

```json
{
  "context": "{{variables.kb_context}}"
}
```

如果 `variables.kb_context` 是数组，解析后仍为数组。

---

## 9.3 嵌入字符串变量

如果变量嵌入字符串，则转为字符串。

输入：

```text
问题：{{input.user_query}}
资料：{{variables.kb_context}}
```

规则：

```text
string / number / boolean 转为字符串
object / array 转为紧凑 JSON 字符串
null 转为空字符串或严格报错，MVP 建议严格报错
```

---

## 9.4 变量不存在

MVP 使用严格模式：

```json
{
  "error_code": "variable_not_found",
  "error_message": "Variable not found: variables.order_id",
  "retryable": false
}
```

---

## 10. input_mapping 处理

执行节点前：

```text
1. 读取 node.input_mapping
2. 递归解析变量引用
3. 得到 node_input
4. 写入 node_runs.input_json
5. 传给 NodeExecutor
```

示例：

```json
{
  "input_mapping": {
    "question": "{{input.user_query}}",
    "context": "{{variables.kb_context}}"
  }
}
```

解析后：

```json
{
  "question": "退款规则是什么？",
  "context": [
    {
      "content": "用户可在签收后 7 天内申请退款..."
    }
  ]
}
```

---

## 11. output_mapping 处理

NodeExecutor 返回：

```json
{
  "answer": "可以在 7 天内申请退款",
  "confidence": 0.91
}
```

output_mapping：

```json
{
  "answer": "variables.final_answer",
  "confidence": "variables.answer_confidence"
}
```

写入 State：

```json
{
  "variables": {
    "final_answer": "可以在 7 天内申请退款",
    "answer_confidence": 0.91
  }
}
```

---

## 11.1 写入规则

允许写入：

```text
variables.xxx
outputs.xxx
messages
outputs
```

不允许写入：

```text
input.xxx
metadata.xxx
secrets.xxx
```

特殊规则：

```text
target = messages，表示追加消息到 state.messages
target = outputs，表示将对象 merge 到 state.outputs
target = variables.xxx，表示覆盖该变量路径
target = outputs.xxx，表示覆盖该输出路径
```

如果 `messages` 写入值是数组，则逐条追加；如果是对象，则追加一条。

---

## 12. 节点执行生命周期

```text
1. validate_node_config
2. resolve_input_mapping
3. create_node_run(status=running, attempt=n)
4. execute_node_with_timeout
5. validate_node_output
6. apply_output_mapping
7. update_node_run_success
8. persist_state
9. resolve_next_node
```

失败：

```text
1. catch error
2. normalize error
3. update_node_run_failed
4. check retry policy
5. retry or apply on_error
6. update workflow_run failed if needed
```

---

## 13. NodeExecutor 接口

建议接口：

```python
class NodeExecutor:
    def execute(self, node, node_input, state, context):
        pass
```

返回值：

```text
必须是 JSON-serializable object
不能返回二进制对象
不能直接修改 State
```

State 只能由 Runtime 根据 `output_mapping` 写入，避免节点绕过协议。

---

## 14. MVP 节点执行器设计

## 14.1 StartNodeExecutor

职责：

```text
不执行业务逻辑
返回空对象
```

输出：

```json
{}
```

---

## 14.2 InputNodeExecutor

职责：

```text
根据 config.fields 校验 state.input
检查 required 字段
检查基础类型
可通过 output_mapping 把 input 字段复制到 variables
```

建议输出：

```json
{
  "user_query": "我想申请退款"
}
```

说明：

```text
Input Node 不负责向用户提问
MVP 没有暂停恢复能力
多轮信息收集留给 Info Collection Node
```

---

## 14.3 LLMNodeExecutor

职责：

```text
读取 provider / model / prompt / temperature / max_tokens
使用 node_input 解析 system_prompt 和 user_prompt
调用 LLM Provider
返回 answer 和 usage
记录 token usage 到 metadata_json
```

执行步骤：

```text
1. 解析 config.system_prompt
2. 解析 config.user_prompt
3. 构造模型请求
4. 调用模型
5. 提取文本结果
6. 返回 answer / usage
```

输出：

```json
{
  "answer": "模型生成的回答",
  "usage": {
    "prompt_tokens": 1000,
    "completion_tokens": 300,
    "total_tokens": 1300
  }
}
```

---

## 14.4 KnowledgeBaseNodeExecutor

职责：

```text
解析 query
生成 query embedding
按 knowledge_base_ids 检索 chunks
应用 top_k 和 score_threshold
返回内容和来源
```

执行步骤：

```text
1. 使用 node_input 解析 config.query
2. 调用 embedding model 生成 query embedding
3. 在 knowledge_chunks 中执行向量检索
4. 加入 knowledge_base_id / status / 权限过滤
5. 返回 top_k chunks
```

输出：

```json
{
  "chunks": [
    {
      "chunk_id": "chunk_001",
      "content": "相关文档内容",
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

## 14.5 IntentNodeExecutor

职责：

```text
根据 config.intents 构造分类 prompt
调用轻量 LLM
返回 intent 和 confidence
失败时可使用 fallback_intent
```

输出：

```json
{
  "intent": "refund_request",
  "confidence": 0.92
}
```

MVP 建议要求模型返回 JSON，并做解析校验。

---

## 14.6 BranchNodeExecutor

职责：

```text
按顺序计算 branches
命中第一个条件后返回 target
没有命中时使用 default
没有 default 则失败
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
```

输出：

```json
{
  "selected_branch_id": "branch_refund",
  "target": "llm_refund_1"
}
```

注意：

```text
Branch Node 不执行任意代码表达式
condition.left 可以是变量引用
condition.right 可以是常量或变量引用
```

---

## 14.7 APINodeExecutor

职责：

```text
解析 method / url / headers / query_params / body
解析 secrets
发送 HTTP 请求
应用 timeout
限制响应体大小
提取 response_path
返回 response 和 status_code
```

输出：

```json
{
  "response": {
    "status": "paid",
    "amount": 199
  },
  "status_code": 200
}
```

安全规则：

```text
Trace 中 headers 必须脱敏
Authorization 不写入 node_runs.input_json
默认禁止访问内网地址，除非管理员允许
响应体大小需要限制
```

---

## 14.8 MessageNodeExecutor

职责：

```text
解析 template
生成用户可见消息
通过 output_mapping 追加到 state.messages
```

输出：

```json
{
  "message": {
    "type": "text",
    "content": "这里是回复内容"
  }
}
```

---

## 14.9 OutputNodeExecutor

职责：

```text
解析 config.outputs
生成最终 outputs
通过 output_mapping 写入 state.outputs
```

输出：

```json
{
  "outputs": {
    "answer": "最终回答",
    "sources": []
  }
}
```

---

## 14.10 EndNodeExecutor

职责：

```text
不执行业务逻辑
通知 WorkflowExecutor 结束运行
```

输出：

```json
{}
```

---

## 15. 下一节点解析

## 15.1 普通节点

规则：

```text
普通节点在 MVP 中建议只有一条出边
如果没有出边且不是 End Node，则运行失败
如果有多条出边且不是 Branch Node，则发布校验失败
```

---

## 15.2 Branch Node

规则：

```text
Branch Node 的 NodeExecutor 返回 target
Runtime 根据 target 找到下一节点
target 必须存在
如果 Graph 中维护了 Branch 出边，target 建议必须在出边列表中
```

---

## 15.3 End Node

规则：

```text
执行到 End Node 后结束
workflow_run.status = completed
workflow_run.output_json = state.outputs
```

---

## 16. 重试策略

节点配置：

```json
{
  "retry": {
    "max_attempts": 3,
    "backoff": "exponential",
    "retry_on": ["timeout", "rate_limit", "network_error"]
  }
}
```

规则：

```text
max_attempts 包含第一次执行
每次 attempt 创建一条 node_runs
只有 retryable=true 且 error_code 在 retry_on 中才重试
超过 max_attempts 后应用 on_error
```

backoff：

```text
none          不等待
fixed         固定等待，例如 1s
exponential   1s, 2s, 4s，上限可配置
```

MVP 可先实现：

```text
max_attempts
none / fixed
```

---

## 17. 超时控制

节点级 timeout：

```json
{
  "timeout": 60
}
```

规则：

```text
每个节点单独计时
超过 timeout 后终止该节点执行
记录 error_code = timeout
根据 retry_on 判断是否重试
```

建议默认值：

```text
LLM Node：60s
Knowledge Base Node：30s
API Node：30s
Intent Node：30s
其他节点：10s
```

---

## 18. 错误处理

统一错误格式：

```json
{
  "error_code": "llm_provider_error",
  "error_message": "LLM provider returned 500",
  "error_detail": {},
  "retryable": true
}
```

常见错误：

```text
variable_not_found
invalid_config
timeout
llm_provider_error
api_request_error
api_response_error
knowledge_base_error
branch_no_match
output_mapping_error
permission_denied
unknown_error
```

MVP on_error：

```text
fail_workflow
```

预留：

```text
skip_node
go_to_node
wait_for_human
```

---

## 19. Trace 记录策略

每个节点执行记录：

```text
node_id
node_type
node_name
status
attempt
input_json
output_json
error_code
error_message
duration_ms
metadata_json
started_at
ended_at
```

敏感信息处理：

```text
secrets 真实值不进入 input_json
Authorization 等敏感 Header 必须脱敏
LLM Prompt 是否完整保存可做系统配置
API 响应体过大时截断
```

LLM metadata：

```json
{
  "model": "gpt-4.1-mini",
  "prompt_tokens": 1000,
  "completion_tokens": 300,
  "total_tokens": 1300,
  "estimated_cost": 0.01
}
```

API metadata：

```json
{
  "method": "POST",
  "url": "https://api.example.com/orders/query",
  "status_code": 200,
  "duration_ms": 420
}
```

Knowledge Base metadata：

```json
{
  "knowledge_base_ids": ["kb_001"],
  "top_k": 5,
  "returned_chunks": 4
}
```

---

## 20. Runtime 伪代码

```python
class WorkflowExecutor:
    def run(self, workflow_version, initial_input, context):
        graph = self.graph_loader.load(workflow_version.id)
        self.graph_validator.validate_for_run(graph)

        state = self.state_manager.create_initial_state(
            input_json=initial_input,
            metadata={
                "workflow_id": workflow_version.workflow_id,
                "version_id": workflow_version.id,
                "run_id": context.run_id,
                "user_id": context.user_id,
            },
        )

        self.trace.mark_run_running(context.run_id)
        current_node = graph.get_start_node()

        while current_node:
            node_output = self.execute_node_with_retry(
                node=current_node,
                state=state,
                context=context,
            )

            state = self.mapping_engine.apply_output_mapping(
                state=state,
                node=current_node,
                node_output=node_output,
            )

            self.state_manager.persist(context.run_id, state)

            if current_node.type == "end":
                break

            current_node = self.next_resolver.resolve(
                graph=graph,
                node=current_node,
                node_output=node_output,
                state=state,
            )

        self.trace.mark_run_completed(
            run_id=context.run_id,
            output_json=state["outputs"],
            state_json=state,
        )

        return state
```

---

## 21. execute_node_with_retry 伪代码

```python
def execute_node_with_retry(self, node, state, context):
    retry = node.get("retry", {"max_attempts": 1, "backoff": "none"})
    max_attempts = retry.get("max_attempts", 1)

    for attempt in range(1, max_attempts + 1):
        started_at = now()
        node_input = None
        node_run_id = None

        try:
            node_input = self.mapping_engine.resolve_input_mapping(node, state, context)
            node_run_id = self.trace.create_node_run(
                run_id=context.run_id,
                node=node,
                attempt=attempt,
                input_json=self.redactor.redact(node_input),
            )

            executor = self.registry.get(node["type"])
            node_output = self.timeout_controller.run(
                timeout_seconds=node.get("timeout", 60),
                func=lambda: executor.execute(node, node_input, state, context),
            )

            self.trace.mark_node_success(
                node_run_id=node_run_id,
                output_json=self.redactor.redact(node_output),
                duration_ms=duration_since(started_at),
                metadata_json=self.metadata_extractor.extract(node, node_output),
            )

            return node_output

        except RuntimeNodeError as error:
            self.trace.mark_node_failed(
                node_run_id=node_run_id,
                error=error,
                duration_ms=duration_since(started_at),
            )

            if not self.retry_controller.should_retry(error, retry, attempt):
                raise error

            self.retry_controller.sleep(retry, attempt)
```

---

## 22. 运行一致性策略

MVP 建议：

```text
workflow_run 创建后绑定 version_id，不随 current_version_id 变化
每个节点成功后持久化 state_json
node_run 先创建 running，再更新 success / failed
workflow_run 最终状态只能从 running 进入 completed / failed / cancelled
重复查询 run 只读，不触发再次执行
```

幂等建议：

```text
Run API 可后续增加 idempotency_key
API Node 默认不保证业务幂等
高风险写接口后续应接 Human Approval Node
```

---

## 23. 安全策略

Runtime 必须处理：

```text
运行权限校验
知识库权限过滤
Secret 服务端解析
Trace 敏感信息脱敏
API Node 内网访问限制
API Node 响应体大小限制
上传文档类型和大小限制
LLM Prompt 变量转义
```

MVP 可以先实现：

```text
Secret 脱敏
API 超时
响应体大小限制
知识库基础权限过滤
```

---

## 24. Runtime 实现优先级

```text
1. GraphLoader
2. GraphValidator
3. StateManager
4. VariableResolver
5. MappingEngine
6. TraceRecorder
7. NodeExecutorRegistry
8. Start / End / Input / Output Executor
9. LLM Executor
10. NextNodeResolver
11. RetryController
12. KnowledgeBase Executor
13. Intent Executor
14. Branch Executor
15. API Executor
16. Message Executor
17. 异步运行队列
18. Trace 详情聚合
```

---

## 25. 结论

MVP Runtime 的核心不是支持复杂 DAG，而是稳定执行节点协议：

```text
加载发布版本
初始化 State
解析 input_mapping
执行 NodeExecutor
应用 output_mapping
解析下一节点
记录 Trace
输出结果
```

第一版只要保证：

```text
顺序执行稳定
分支执行明确
变量解析严格
State 写入可控
Trace 足够完整
错误可定位
```

后续扩展循环、并行、暂停恢复、人工审批和代码节点时，就可以在现有 Runtime 内核上增量演进。

