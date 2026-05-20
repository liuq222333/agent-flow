# Runtime 优化改动方案 v1

## 1. 背景

当前项目已经具备基础 Runtime 与节点执行能力，核心实现位于：

```text
backend/app/services/runtime.py
```

现有能力包括：

```text
Graph Runtime 执行
Generated Workflow 执行
input_mapping 解析
output_mapping 写入
Branch 路由
LLM / Intent / API / Message / Knowledge 节点执行
node_runs Trace 记录
workflow_runs 状态记录
节点级 retry / timeout 初步能力
稳定错误码初步能力
```

但从长期可维护性和生产可用性角度看，Runtime 仍有几个明显问题：

```text
runtime.py 职责过重，节点执行、变量映射、错误归一、trace 写入、retry/timeout 混在一个文件里
错误码粒度仍偏粗，部分 provider / HTTP / Knowledge 异常还没有精细映射
on_error 策略尚未完整实现
API Node 外呼治理还不够生产化
Trace metadata 还未完全覆盖文档要求
节点 Executor 仍不是独立模块，后续扩展节点类型成本较高
测试覆盖已经有基础，但缺少完整 Runtime 协议合同测试矩阵
```

本方案目标是在不推翻现有 MVP 架构的前提下，把 Runtime 从“能跑”优化为“语义稳定、边界清晰、方便扩展、可观测性更强”。

---

## 2. 优化目标

## 2.1 稳定执行语义

Runtime 应保证：

```text
每个节点执行都有稳定生命周期
每次 attempt 都有独立 node_runs 记录
失败时有稳定 error_code
retry 只基于稳定 error_code 和 retryable 判断
timeout 能取消当前节点执行
on_error 能决定失败后的工作流走向
State 只能由 Runtime 统一写入
Generated Workflow 与 Graph Runtime 行为一致
```

## 2.2 清晰模块边界

将当前 `runtime.py` 拆成多个职责单一的模块：

```text
runtime/context.py
runtime/errors.py
runtime/mapping.py
runtime/retry.py
runtime/trace.py
runtime/state.py
runtime/graph.py
runtime/executors/
```

拆分后 `runtime.py` 只保留对外入口和兼容导出，降低后续维护成本。

## 2.3 可观测性完整

Trace 应能回答：

```text
哪个节点失败
第几次 attempt 失败
为什么失败
是否会重试
用了哪个 provider / model / tool / knowledge_base
HTTP 状态码是什么
LLM token usage 是多少
节点耗时是多少
最终工作流为什么成功或失败
```

## 2.4 安全边界明确

重点强化：

```text
Secret 不进入 input_json / output_json / metadata_json
API Node 默认禁止内网访问
API Node 支持 allowlist / denylist
API 响应体大小受限
敏感 header / body 字段脱敏
错误信息不泄露密钥
```

---

## 3. 现状与差距

## 3.1 已实现能力

当前已具备：

```text
RuntimeNodeError
variable_not_found / timeout / output_mapping_error 等稳定错误码
节点级 timeout
retry.max_attempts / retry_on / backoff
每次 retry attempt 重新解析 input_mapping
每次 attempt 创建 node_runs
节点成功后持久化 workflow_runs.state_json
output_mapping 支持 variables.xxx / outputs.xxx / outputs / messages
Branch target 运行期基础兜底
API secret 解析与 trace 脱敏
API http 模式内网阻断
Knowledge 检索节点
Intent + Branch 路由
LLM mock / OpenAI 调用
```

## 3.2 主要差距

仍需补齐：

```text
on_error 策略完整实现
retrying 状态记录
错误码精细化映射
API Node response_path / query_params / response size limit
HTTP 4xx/5xx 策略化处理
LLM provider 错误精细归类
Knowledge 错误精细归类
Trace metadata 丰富化
Runtime 模块化拆分
State 写入路径完全收口
更完整的协议合同测试
```

---

## 4. 目标目录结构

建议新增目录：

```text
backend/app/services/runtime/
  __init__.py
  context.py
  engine.py
  errors.py
  graph.py
  mapping.py
  retry.py
  state.py
  trace.py
  types.py
  executors/
    __init__.py
    api.py
    branch.py
    intent.py
    knowledge_base.py
    llm.py
    message.py
    output.py
    start_end.py
```

为避免一次性大迁移影响现有 import，可采用两阶段方案：

```text
阶段 1：保留 backend/app/services/runtime.py，对外 API 不变，在内部引入新模块
阶段 2：确认无外部依赖旧私有函数后，将 runtime.py 改为兼容导出层
```

兼容导出示例：

```python
from app.services.runtime.engine import execute_workflow_sync
from app.services.runtime.engine import execute_generated_workflow_sync
from app.services.runtime.errors import RuntimeNodeError
```

---

## 5. 详细改动设计

## 5.1 错误体系

新增或完善：

```text
runtime/errors.py
```

核心类：

```python
class RuntimeNodeError(Exception):
    error_code: str
    error_message: str
    retryable: bool
    error_detail: dict
```

推荐错误码：

```text
variable_not_found
invalid_config
timeout
rate_limit
network_error
llm_provider_error
api_request_error
api_response_error
knowledge_base_error
branch_no_match
branch_target_not_found
output_mapping_error
permission_denied
secret_not_found
response_too_large
unknown_error
```

异常归一规则：

```text
asyncio.TimeoutError -> timeout, retryable=true
httpx.TimeoutException -> timeout, retryable=true
httpx.ConnectError -> network_error, retryable=true
httpx.NetworkError -> network_error, retryable=true
httpx.HTTPStatusError 429 -> rate_limit, retryable=true
httpx.HTTPStatusError 5xx -> api_response_error, retryable=true
httpx.HTTPStatusError 4xx -> api_response_error, retryable=false
OpenAI 429 -> rate_limit, retryable=true
OpenAI 5xx / APIConnectionError -> llm_provider_error, retryable=true
Knowledge 检索异常 -> knowledge_base_error, retryable=true 或按具体异常决定
配置错误 -> invalid_config, retryable=false
变量缺失 -> variable_not_found, retryable=false
```

验收标准：

```text
所有 node_runs.failed 都必须有稳定 error_code
workflow_runs.failed 也使用稳定 error_code
不再使用异常类名作为主要 error_code
error_detail 可记录结构化信息，但不能包含 secret
```

---

## 5.2 retry 优化

当前已有：

```text
max_attempts
retry_on
backoff: none / fixed / exponential
```

继续增强：

```text
失败但将重试的 attempt 标记为 retrying
最终失败的 attempt 标记为 failed
增加 jitter，避免并发重试打外部服务
增加 max_delay_seconds
增加 workflow_run.metadata_json.retry_summary
```

推荐配置：

```json
{
  "retry": {
    "max_attempts": 3,
    "backoff": "exponential",
    "delay_seconds": 1,
    "max_delay_seconds": 10,
    "jitter": true,
    "retry_on": ["timeout", "rate_limit", "network_error", "api_response_error"]
  }
}
```

node_runs 状态建议：

```text
attempt 1 running -> retrying
attempt 2 running -> retrying
attempt 3 running -> success
```

或最终失败：

```text
attempt 1 running -> retrying
attempt 2 running -> retrying
attempt 3 running -> failed
```

验收标准：

```text
retryable=false 不重试
error_code 不在 retry_on 中不重试
每次 attempt 都重新解析 input_mapping
失败的中间 attempt 不写 state
最终成功只写最后一次 output 到 state
node_runs.attempt 从 1 递增
```

---

## 5.3 timeout 优化

当前已有节点级 timeout 包装。

继续增强：

```text
workflow 级总 timeout
节点默认 timeout 按类型配置化
timeout 记录 timeout_seconds
timeout 后确保当前节点任务取消
```

建议环境变量：

```text
WORKFLOW_RUN_DEFAULT_TIMEOUT_SECONDS=300
NODE_DEFAULT_TIMEOUT_SECONDS=10
LLM_NODE_DEFAULT_TIMEOUT_SECONDS=60
KNOWLEDGE_NODE_DEFAULT_TIMEOUT_SECONDS=30
API_NODE_DEFAULT_TIMEOUT_SECONDS=30
INTENT_NODE_DEFAULT_TIMEOUT_SECONDS=30
```

验收标准：

```text
节点超时记录 error_code=timeout
workflow 总超时记录 error_code=timeout
timeout 可参与 retry_on 判断
超时节点不会继续写 state
```

---

## 5.4 on_error 策略

建议先实现三种：

```text
fail_workflow
skip_node
go_to_node
```

配置示例：

```json
{
  "on_error": {
    "strategy": "go_to_node",
    "target": "error_message_1"
  }
}
```

语义：

```text
fail_workflow:
  当前节点最终失败后，workflow_run.status=failed

skip_node:
  当前节点最终失败后，记录 node_runs.failed
  不写该节点 output
  不执行 output_mapping
  继续走普通下一节点

go_to_node:
  当前节点最终失败后，记录 node_runs.failed
  将错误写入 state.metadata.last_error
  下一节点强制跳转到 on_error.target
```

`state.metadata.last_error` 建议结构：

```json
{
  "node_id": "api_1",
  "node_type": "api",
  "error_code": "api_response_error",
  "error_message": "HTTP 500",
  "attempt": 3
}
```

验收标准：

```text
默认策略是 fail_workflow
skip_node 不写失败节点 state
go_to_node target 必须存在
go_to_node target 建议由 GraphValidator 校验
on_error 行为必须写入 trace metadata
```

---

## 5.5 MappingEngine 优化

当前已有：

```text
严格变量缺失
完整变量引用保留原始类型
嵌入字符串变量转字符串
output_mapping 写 variables / outputs / messages
```

继续增强：

```text
支持数组索引路径：variables.chunks[0].content
区分 null 与 missing
禁止写 input / metadata / secrets
支持 messages 数组批量追加
支持 mapping 错误 detail
```

变量路径建议：

```text
input.user_query
variables.kb_context[0].content
outputs.api_1.response.status
metadata.run_id
```

验收标准：

```text
变量不存在 -> variable_not_found
变量值为 null -> 正常解析为 null
非法写入路径 -> output_mapping_error
数组越界 -> variable_not_found
```

---

## 5.6 State 写入收口

原则：

```text
NodeExecutor 不直接修改 state
NodeExecutor 只返回 node_output
Runtime 根据 output_mapping 写 state
Output Node 由 Runtime 写 final_output
兼容历史默认写入，但逐步标记为 deprecated
```

需要调整：

```text
Knowledge 节点不再直接写 state.variables.kb_context
LLM 节点不再隐式写 state.variables.answer
默认兼容映射可以先保留一版，但文档标注迁移路径
```

推荐迁移策略：

```text
v1：保留隐式写入，metadata 标记 implicit_mapping=true
v2：发布校验提示缺少 output_mapping
v3：移除隐式写入
```

验收标准：

```text
所有新工作流必须显式配置 output_mapping
隐式写入不影响老工作流运行
新测试覆盖无隐式写入场景
```

---

## 5.7 TraceRecorder 优化

建议新增：

```text
runtime/trace.py
```

接口：

```python
async def create_node_run(...)
async def mark_node_success(...)
async def mark_node_retrying(...)
async def mark_node_failed(...)
async def persist_state(...)
async def mark_run_failed(...)
async def mark_run_completed(...)
```

node_runs.metadata_json 建议补充：

```json
{
  "runtime": "graph_runtime",
  "attempt": 1,
  "retryable": true,
  "will_retry": false,
  "provider": "openai",
  "model": "gpt-4.1-mini",
  "model_config_id": 12,
  "status_code": 200,
  "duration_ms": 420,
  "token_usage": {
    "prompt_tokens": 100,
    "completion_tokens": 30,
    "total_tokens": 130
  }
}
```

验收标准：

```text
每个节点都有 started_at / ended_at / duration_ms
失败节点有 error_code / error_message
重试节点能看出 will_retry
LLM 节点能看到 model / usage
API 节点能看到 method / url / status_code
Knowledge 节点能看到 top_k / returned_chunks / knowledge_base_ids
```

---

## 5.8 API Node 优化

新增能力：

```text
query_params
response_path
success_status_codes
fail_on_http_error
max_response_bytes
idempotency_key
allowlist / denylist
```

配置示例：

```json
{
  "mode": "http",
  "method": "POST",
  "url": "https://api.example.com/orders",
  "query_params": {
    "tenant": "{{input.tenant_id}}"
  },
  "headers": {
    "Authorization": "Bearer {{secrets.crm_token}}"
  },
  "body": {
    "order_id": "{{input.order_id}}"
  },
  "timeout_seconds": 30,
  "max_response_bytes": 1048576,
  "response_path": "data.result",
  "success_status_codes": [200, 201, 202],
  "fail_on_http_error": true,
  "idempotency_key": "{{metadata.run_id}}:{{node.id}}"
}
```

安全要求：

```text
默认禁止 localhost / private network / link-local / multicast / reserved IP
DNS 解析结果全部检查
不跟随 redirect 或严格限制 redirect
响应体超过 max_response_bytes -> response_too_large
敏感 header 和 body 字段脱敏
```

验收标准：

```text
HTTP 4xx/5xx 可按配置失败
response_path 可提取子对象
超大响应被截断或失败
private network 被阻断
secret 不出现在 trace
```

---

## 5.9 LLM Node 优化

建议：

```text
统一走 model_config_id
保留 provider/model 直配兼容
OpenAI 错误码精细归一
记录 usage 到 metadata_json
支持 response_format
支持 max_tokens
支持 prompt 脱敏策略
```

配置示例：

```json
{
  "model_config_id": 12,
  "system_prompt": "你是客服助手",
  "user_prompt": "{{input.user_query}}",
  "temperature": 0.2,
  "max_tokens": 800,
  "response_format": "text"
}
```

验收标准：

```text
缺少 OpenAI Key -> permission_denied
429 -> rate_limit
5xx -> llm_provider_error
usage 写入 trace metadata
mock provider 不依赖外部网络
```

---

## 5.10 Intent Node 优化

建议：

```text
keyword provider 保留
OpenAI provider 使用 JSON schema 或严格 JSON 输出
intent 必须在候选列表内，否则 fallback
confidence 必须归一到 0-1
raw provider output 只进入安全 metadata
```

验收标准：

```text
模型返回非法 JSON -> fallback_intent
模型返回未知 intent -> fallback_intent
keyword provider 离线可用
Intent 输出可被 Branch 稳定消费
```

---

## 5.11 Knowledge Node 优化

建议：

```text
不直接写 state
检索异常统一 knowledge_base_error
metadata 记录 knowledge_base_ids / top_k / returned_chunks / retrieval_modes
支持 empty_result_policy
支持 context_budget_tokens
```

配置示例：

```json
{
  "knowledge_base_ids": [1, 2],
  "query": "{{question}}",
  "top_k": 5,
  "score_threshold": 0.2,
  "context_budget_tokens": 3000,
  "empty_result_policy": "continue"
}
```

验收标准：

```text
检索失败 -> knowledge_base_error
空结果按策略继续或失败
context_budget_tokens 生效
metadata 能看到 returned_chunks
```

---

## 5.12 Branch Node 优化

当前 Branch 已支持条件判断和 target 选择。

继续增强：

```text
返回 selected_branch_id 和 target
无匹配且无 default -> branch_no_match
运行期校验 target 是否存在且有 edge
GraphValidator 校验 default_target 是否有 edge
```

输出建议：

```json
{
  "selected_branch_id": "refund_path",
  "target": "message_refund"
}
```

兼容当前输出：

```json
{
  "selected": "message_refund"
}
```

验收标准：

```text
Branch 无匹配 -> branch_no_match
Branch target 无 edge -> branch_target_not_found
Branch 出边未映射 -> 发布失败
```

---

## 6. 数据库影响

当前表结构已经支持：

```text
node_runs.attempt
node_runs.status: running / success / failed / skipped / retrying
node_runs.error_code
node_runs.error_message
node_runs.metadata_json
workflow_runs.metadata_json
```

短期不需要新增字段。

可能的后续增强：

```sql
CREATE INDEX idx_node_runs_run_attempt ON node_runs(run_id, node_id, attempt);
CREATE INDEX idx_node_runs_error_code ON node_runs(error_code);
```

是否需要新增 migration：

```text
第一阶段：不需要
第二阶段：如果要优化 trace 查询性能，再补 index migration
```

---

## 7. API 影响

现有 API 基本不需要破坏性改动。

建议增强：

```text
GET /runs/{run_id}/trace 返回 next_after_node_run_id
GET /runs/{run_id}/trace 支持 status / node_type 过滤
GET /runs/{run_id}/trace 返回 retry summary
```

返回示例：

```json
{
  "run": {},
  "nodes": [],
  "graph_json": {},
  "next_after_node_run_id": 123,
  "summary": {
    "total_nodes": 8,
    "failed_nodes": 1,
    "retrying_nodes": 0,
    "total_attempts": 10
  }
}
```

---

## 8. 测试计划

## 8.1 单元测试

新增测试文件建议：

```text
backend/tests/test_runtime_errors.py
backend/tests/test_runtime_mapping.py
backend/tests/test_runtime_retry.py
backend/tests/test_runtime_on_error.py
backend/tests/test_runtime_trace.py
backend/tests/test_runtime_api_node.py
```

覆盖点：

```text
变量不存在 -> variable_not_found
null 值正常解析
数组索引路径解析
非法 output_mapping -> output_mapping_error
retryable=true 且 error_code 命中 retry_on -> 重试
retryable=false -> 不重试
timeout -> error_code=timeout
retrying attempt 不写 state
最终成功写 state
skip_node 继续后续节点
go_to_node 跳转错误处理节点
API secret 不泄漏
API private URL 被阻断
API 500 按配置失败
LLM 429 映射 rate_limit
Knowledge 异常映射 knowledge_base_error
```

## 8.2 集成测试

扩展 smoke：

```text
sync workflow run
async workflow run
retry 成功工作流
retry 最终失败工作流
timeout 工作流
on_error skip_node 工作流
on_error go_to_node 工作流
API + Message + Secret 脱敏
Knowledge + LLM 组合工作流
Intent + Branch + on_error 组合工作流
```

## 8.3 回归命令

```powershell
cd "D:\xm\agent flow\agent flow\backend"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app/services/runtime.py tests/test_runtime_nodes.py
```

如果修复全仓 lint：

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests
```

---

## 9. 分阶段实施计划

## 阶段 1：语义补齐

目标：

```text
on_error
retrying 状态
错误码精细化
Trace metadata 增强
```

改动文件：

```text
backend/app/services/runtime.py
backend/tests/test_runtime_nodes.py
```

验收：

```text
pytest 全绿
Runtime 相关 ruff 全绿
新增 on_error 测试通过
```

## 阶段 2：模块化拆分

目标：

```text
拆 errors / mapping / retry / trace / executors
runtime.py 保留兼容入口
```

改动文件：

```text
backend/app/services/runtime.py
backend/app/services/runtime/*.py
backend/app/services/runtime/executors/*.py
backend/tests/test_runtime_*.py
```

验收：

```text
外部 import 不破坏
generated workflow 继续可运行
pytest 全绿
```

## 阶段 3：API Node 生产化

目标：

```text
query_params
response_path
max_response_bytes
success_status_codes
idempotency_key
allowlist / denylist
```

验收：

```text
API 外呼安全测试通过
secret 脱敏测试通过
大响应限制测试通过
HTTP 状态策略测试通过
```

## 阶段 4：模型与知识节点增强

目标：

```text
LLM model_config_id 主路径
LLM usage metadata
Intent JSON 严格校验
Knowledge metadata 增强
State 隐式写入迁移
```

验收：

```text
LLM / Intent / Knowledge 节点合同测试通过
旧工作流兼容
新工作流显式 mapping
```

---

## 10. 风险与规避

## 10.1 严格变量解析破坏旧工作流

风险：

```text
旧工作流可能依赖变量缺失时替换为空字符串
```

规避：

```text
保留 strict_mapping 默认 true
如需兼容可在 workflow_versions.metadata_json 中加 mapping_mode=legacy
发布新版本时强提示缺失变量风险
```

## 10.2 API Node 重试造成重复副作用

风险：

```text
POST 重试可能重复创建外部资源
```

规避：

```text
默认只对 GET 自动重试
POST/PUT/PATCH 需要配置 idempotency_key 才允许 retry
Trace 记录 idempotency_key
```

## 10.3 模块拆分影响 import

风险：

```text
现有代码和测试直接 import app.services.runtime
```

规避：

```text
runtime.py 保留兼容导出
先移动内部实现，再逐步调整测试 import
```

## 10.4 Trace 数据膨胀

风险：

```text
大 input/output 导致 node_runs 膨胀
```

规避：

```text
API 响应截断
LLM prompt 是否保存可配置
metadata 控制大小
大字段写 preview + truncated=true
```

---

## 11. 验收清单

最终完成后应满足：

```text
RuntimeNodeError 覆盖所有节点失败
node_runs.error_code 全部稳定
retry_on 基于稳定错误码工作
timeout 可取消节点
on_error 支持 fail_workflow / skip_node / go_to_node
每次 attempt 独立 trace
retrying 状态可见
State 只由 Runtime 写入
API Node 外呼安全策略完整
LLM usage 写入 metadata
Knowledge 检索 metadata 完整
Branch target 运行期和发布期双重校验
Generated Workflow 与 Graph Runtime 语义一致
pytest 全绿
Runtime lint 全绿
smoke 覆盖 retry / timeout / on_error
```

---

## 12. 建议优先顺序

推荐优先级：

```text
P0：on_error + retrying 状态 + 错误码精细化
P1：Runtime 模块化拆分
P1：API Node 生产化
P2：LLM / Intent / Knowledge metadata 增强
P2：State 隐式写入迁移
P3：Trace 查询 API 增强
```

最小可交付版本：

```text
on_error 三策略
retrying 状态
HTTP / OpenAI / Knowledge 错误归一
Runtime 协议测试补齐
```

完成这个最小版本后，Runtime 的可靠性会明显提升，后续再做模块化和 API Node 生产化会更稳。
