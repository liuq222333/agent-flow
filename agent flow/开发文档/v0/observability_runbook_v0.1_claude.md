# Agent 工作流平台可观测性与运维补充 v0.1

## 0. 文档说明

本文档处理 `design_review_v0.1_claude.md` 中的 G6-G10、G13：

```text
G6  /metrics Prometheus 端点
G7  /health 与 /ready 分离
G8  日志格式约束（JSON 结构化）
G9  workflow_runs.state_json 大小上限
G10 单 workflow_run 的 token budget / max_llm_calls
G13 错误码完整字典
```

外加 MVP 上线必备的运维 Runbook 内容：

```text
- 部署时的可观测性接入清单
- 告警阈值建议
- 日志查询模式
- 队列积压排查
- 数据保留与清理
```

本文档目标：让 MVP 不只是能跑，而是**能被运维**。

---

## 1. 可观测性架构

```text
应用日志       结构化 JSON → stdout → Docker → 后续 ELK/Loki
访问日志       同上
Trace          PostgreSQL workflow_runs / node_runs（业务级 trace）
Metrics        /metrics Prometheus 端点
健康检查       /health (shallow) + /ready (deep)
审计           audit_logs 表
告警           Prometheus + Alertmanager（生产）
```

MVP 阶段：

```text
日志：只输出 stdout，不接 ELK
Metrics：暴露 /metrics，本地可选不部署 Prometheus
告警：本地无，文档化阈值供后续接入
```

---

## 2. /health 与 /ready 分离（G7）

### 2.1 端点定义

#### 2.1.1 GET /health（shallow）

```text
用途：进程存活探测
依赖检查：无
响应：始终 200 OK（除非进程崩溃）
```

响应体：

```json
{
  "status": "ok",
  "service": "agent-workflow-api",
  "version": "0.1.0",
  "uptime_seconds": 3600
}
```

#### 2.1.2 GET /ready（deep）

```text
用途：就绪探测，判断是否可接受流量
依赖检查：
  - PostgreSQL 可连接
  - Redis 可连接
  - master key 已加载
  - 默认 model_provider 配置存在
失败：返回 503，body 列出哪个依赖失败
```

响应体（成功）：

```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "redis": "ok",
    "encryption_key": "ok",
    "default_model_provider": "ok"
  }
}
```

响应体（失败）：

```json
{
  "status": "not_ready",
  "checks": {
    "database": "ok",
    "redis": "fail: connection refused",
    "encryption_key": "ok",
    "default_model_provider": "ok"
  }
}
```

#### 2.1.3 GET /alive（liveness，可选）

```text
用途：判断是否需要重启
检查：内部状态机健康
区别于 /health：可能因 deadlock 等内部问题失败
```

MVP 用 /health 兼任即可。

### 2.2 K8s/Compose 配置示例

K8s（v0.2 阶段使用）：

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  periodSeconds: 30
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /ready
    port: 8000
  periodSeconds: 10
  failureThreshold: 3
```

Docker Compose：

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/ready"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 10s
```

### 2.3 OpenAPI 增补

原 OpenAPI 中只有 /health，建议增加：

```yaml
/ready:
  get:
    tags: [Health]
    summary: Readiness check
    security: []
    responses:
      "200":
        description: Service is ready
      "503":
        description: Service not ready
```

---

## 3. /metrics Prometheus 端点（G6）

### 3.1 端点定义

```text
GET /metrics
Content-Type: text/plain; version=0.0.4
返回 Prometheus 格式指标
访问控制：
  生产环境只允许内网访问（通过 nginx/ingress 控制）
  MVP 测试环境可暴露
```

### 3.2 MVP 必须采集指标

#### 3.2.1 API 层

```text
http_requests_total{method,path,status}              Counter
http_request_duration_seconds{method,path}           Histogram（p50/p95/p99）
http_requests_in_flight                              Gauge
```

#### 3.2.2 Workflow Runtime

```text
workflow_runs_total{status}                          Counter
workflow_runs_in_flight                              Gauge
workflow_run_duration_seconds                        Histogram
node_runs_total{node_type, status}                   Counter
node_run_duration_seconds{node_type}                 Histogram
node_retries_total{node_type, error_code}            Counter
```

#### 3.2.3 LLM 调用

```text
llm_calls_total{provider, model, status}             Counter
llm_call_duration_seconds{provider, model}           Histogram
llm_tokens_total{provider, model, kind="prompt"}     Counter
llm_tokens_total{provider, model, kind="completion"} Counter
llm_estimated_cost_total{provider, model}            Counter（USD）
```

#### 3.2.4 Knowledge Base

```text
kb_retrieve_total{kb_id, status}                     Counter
kb_retrieve_duration_seconds                         Histogram
kb_retrieve_returned_chunks                          Histogram
document_processing_total{stage, status}             Counter
document_processing_duration_seconds{stage}          Histogram
```

#### 3.2.5 API Node

```text
api_node_calls_total{status}                         Counter
api_node_call_duration_seconds                       Histogram
api_node_response_size_bytes                         Histogram
```

#### 3.2.6 Queue

```text
queue_depth{queue_name}                              Gauge
queue_processed_total{queue_name, status}            Counter
worker_active{queue_name}                            Gauge
```

#### 3.2.7 数据库

```text
db_connections_active                                Gauge
db_connections_idle                                  Gauge
db_query_duration_seconds{operation}                 Histogram
```

### 3.3 标签基数控制

避免高基数标签：

```text
不允许标签：
  workflow_id（数千上万）
  run_id（百万级）
  node_id
  user_id

允许标签：
  node_type（< 20）
  status（< 10）
  provider（< 10）
  model（< 50）
  queue_name（< 5）
```

### 3.4 集成方式

Python (FastAPI)：使用 `prometheus_client` + `prometheus-fastapi-instrumentator`。

```python
from prometheus_fastapi_instrumentator import Instrumentator

instrumentator = Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
)
instrumentator.instrument(app).expose(app, endpoint="/metrics")
```

业务指标自定义：

```python
from prometheus_client import Counter, Histogram

NODE_RUNS_TOTAL = Counter(
    "node_runs_total",
    "Total node runs",
    ["node_type", "status"],
)

NODE_RUN_DURATION = Histogram(
    "node_run_duration_seconds",
    "Node run duration",
    ["node_type"],
    buckets=(0.05, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 60.0, 120.0),
)
```

在 TraceRecorder.mark_node_success/failed 内统一上报。

---

## 4. 日志格式约束（G8）

### 4.1 格式

**MVP 强制 JSON 结构化日志**，输出到 stdout/stderr。

```json
{
  "timestamp": "2026-05-15T08:30:00.123Z",
  "level": "INFO",
  "logger": "runtime.executor",
  "message": "Node execution completed",
  "service": "agent-workflow-api",
  "request_id": "req_abc123",
  "user_id": 2,
  "workflow_id": 1,
  "version_id": 10,
  "run_id": 2001,
  "node_id": "llm_1",
  "node_type": "llm",
  "duration_ms": 1320,
  "extra": {}
}
```

### 4.2 字段规范

#### 4.2.1 必填字段

```text
timestamp        ISO 8601 with milliseconds, UTC
level            DEBUG | INFO | WARN | ERROR | FATAL
logger           模块路径，dot.separated
message          人类可读消息（英文，避免拼接变量值）
service          服务名 agent-workflow-api / agent-workflow-worker
```

#### 4.2.2 上下文字段（按需）

```text
request_id       由中间件生成，跟踪整个 HTTP 请求
user_id          来自 current_user
workflow_id
version_id
run_id
node_id
node_type
duration_ms
error_code
error_message    （脱敏后）
```

#### 4.2.3 不允许字段

```text
完整 Authorization header
secret 真实值
LLM prompt 完整内容（除非 TRACE_SAVE_PROMPT=true）
完整文件内容
PII（除非已脱敏）
```

### 4.3 日志级别使用规范

```text
DEBUG  开发调试，生产关闭
       变量解析中间结果、内部状态切换
INFO   正常流程
       请求接收、节点开始、节点完成、工作流完成
WARN   异常但可恢复
       重试触发、超时（有 retry）、降级
ERROR  错误
       工作流失败、节点最终失败、依赖不可用
FATAL  进程级故障
       master key 缺失、数据库无法启动连接
```

### 4.4 日志关联

```text
所有日志必须包含 request_id 用于跟踪
异步任务（worker）的日志必须包含 run_id 或 job_id
跨服务调用通过 X-Request-ID header 传递
```

### 4.5 Python 实现

使用 `structlog` 或 `python-json-logger`。

```python
import structlog
import logging

logger = structlog.get_logger()
logger.info(
    "node_execution_completed",
    run_id=run_id,
    node_id=node.id,
    node_type=node.type,
    duration_ms=duration_ms,
)
```

避免 f-string 拼接：

```python
# 不推荐
logger.info(f"Node {node.id} completed in {duration_ms}ms")

# 推荐
logger.info("node_completed", node_id=node.id, duration_ms=duration_ms)
```

### 4.6 错误日志

```python
try:
    ...
except Exception as e:
    logger.exception(
        "node_execution_failed",
        node_id=node.id,
        error_code="llm_provider_error",
    )
```

`logger.exception` 自动附加 traceback。但 traceback 中包含的敏感数据需要在异常类设计时避免，例如不要把 secret 字符串作为异常 message。

---

## 5. workflow_runs.state_json 大小上限（G9）

### 5.1 问题

```text
state_json 是 JSONB
PostgreSQL JSONB 单值理论上限 1GB（TOAST 后）
实际：
  - 单行 > 8KB 走 TOAST，性能下降
  - 单行 > 1MB 严重影响查询和复制
  - state_json 过大时前端 Trace 接口响应慢
```

### 5.2 限制策略

#### 5.2.1 三级限制

```text
单字段（如某个变量值）：1 MB                    超过 → 抛 variable_too_large
单节点 output（output_json）：5 MB              超过 → 抛 node_output_too_large
state_json 总大小：20 MB                        超过 → 抛 state_too_large，workflow_run 失败
```

#### 5.2.2 实施位置

```text
VariableResolver：解析时检查单字段
MappingEngine.apply_output_mapping：检查 node_output 大小
StateManager.persist：检查 state_json 大小，超过则失败
```

#### 5.2.3 大字段分离（v0.2）

MVP 简单做：超过即失败。
v0.2 演进：

```text
新增表 workflow_run_payloads (id, run_id, kind, content_text, content_bytea)
state_json 中只保存引用 {"__ref": "payload:12345"}
读取 Trace 时按需 join
```

### 5.3 环境变量

```text
MAX_VARIABLE_SIZE_BYTES=1048576           1 MB
MAX_NODE_OUTPUT_SIZE_BYTES=5242880        5 MB
MAX_STATE_SIZE_BYTES=20971520             20 MB
```

### 5.4 监控

```text
state_size_bytes (Histogram)               按 percentile 看分布
node_output_size_bytes (Histogram)
oversize_errors_total{kind, error_code}   Counter
```

告警阈值：

```text
state_size_bytes p99 > 10 MB：发出 warning（接近上限）
oversize_errors_total > 10 / 5min：发出 critical（用户工作流频繁失败）
```

---

## 6. LLM 预算与调用上限（G10）

### 6.1 问题

无限制的 LLM 调用会导致：

```text
单次工作流失控 → 大额账单
恶意/失控的 prompt 循环（虽然 MVP 不支持 Loop Node，但 Branch 误配置可能造成事实上的循环）
配额耗尽影响所有用户
```

### 6.2 多层预算

```text
节点级：max_tokens（每次 LLM 调用）
       已在 LLM Node config 中
运行级：单 workflow_run 总 token 上限
工作流级：每个工作流单次运行 token 上限（在 workflow 级别配置）
用户级：每用户每天 token 上限（v0.2）
组织级：每月总预算（v0.2）
```

### 6.3 MVP 实施

#### 6.3.1 运行级硬限

环境变量：

```text
WORKFLOW_RUN_MAX_TOTAL_TOKENS=200000      单次运行总 token 上限
WORKFLOW_RUN_MAX_LLM_CALLS=20             单次运行 LLM 调用次数上限
WORKFLOW_RUN_MAX_API_CALLS=50             API Node 调用次数上限
WORKFLOW_RUN_MAX_DURATION_SECONDS=600     单次运行总时长上限
```

#### 6.3.2 检查时机

```text
LLM Node 执行前：检查累计 tokens 是否已达上限
                  达到则抛 budget_exhausted，工作流失败
API Node 执行前：检查累计调用次数
WorkflowExecutor 每个节点完成后：检查总时长
```

#### 6.3.3 累计统计

State 中增加运行时统计字段（不持久化在 state_json 中，由 Runtime 内存维护）：

```python
class RunBudget:
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    llm_call_count: int = 0
    api_call_count: int = 0
    started_at: datetime

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

    def check_llm(self, max_tokens: int):
        if self.total_tokens + max_tokens > WORKFLOW_RUN_MAX_TOTAL_TOKENS:
            raise RuntimeNodeError(error_code="budget_exhausted")
        if self.llm_call_count + 1 > WORKFLOW_RUN_MAX_LLM_CALLS:
            raise RuntimeNodeError(error_code="llm_call_limit_exceeded")
```

#### 6.3.4 持久化

最终汇总写入 `workflow_runs.metadata_json`：

```json
{
  "budget_used": {
    "total_prompt_tokens": 12000,
    "total_completion_tokens": 3000,
    "llm_call_count": 4,
    "api_call_count": 2,
    "estimated_cost_usd": 0.045
  }
}
```

需要给 workflow_runs 增加 metadata_json 字段（当前 ER 没有）：

```sql
ALTER TABLE workflow_runs
  ADD COLUMN metadata_json JSONB;

CREATE INDEX idx_workflow_runs_metadata_gin
  ON workflow_runs USING GIN(metadata_json);
```

#### 6.3.5 Metrics

```text
workflow_run_tokens_used_total                 Counter
workflow_run_cost_usd_total                    Counter
budget_exhausted_total{kind}                   Counter
```

---

## 7. 错误码完整字典（G13）

### 7.1 命名规范

```text
格式：{category}_{specific}
全小写，下划线分隔
不超过 64 字符
```

### 7.2 字典

#### 7.2.1 配置/请求错误

| code | message | retryable | http_status |
|---|---|---|---|
| invalid_request | 请求参数不合法 | false | 400 |
| validation_failed | 字段校验失败 | false | 400 |
| missing_required_field | 缺少必填字段 | false | 400 |
| invalid_field_value | 字段值不合法 | false | 400 |
| invalid_json | JSON 格式错误 | false | 400 |
| invalid_graph_json | Graph JSON 格式错误 | false | 400 |
| schema_version_unsupported | 不支持的 schema_version | false | 400 |

#### 7.2.2 权限错误

| code | message | retryable | http_status |
|---|---|---|---|
| unauthorized | 未认证 | false | 401 |
| permission_denied | 无权限 | false | 403 |
| not_found | 资源不存在 | false | 404 |
| conflict | 资源状态冲突 | false | 409 |

#### 7.2.3 工作流校验错误

| code | message | retryable | http_status |
|---|---|---|---|
| missing_start_node | 缺少 Start Node | false | - |
| multiple_start_nodes | 多个 Start Node | false | - |
| missing_end_node | 缺少 End Node | false | - |
| duplicate_node_id | 节点 ID 重复 | false | - |
| duplicate_edge_id | 边 ID 重复 | false | - |
| edge_source_not_found | 边的 source 不存在 | false | - |
| edge_target_not_found | 边的 target 不存在 | false | - |
| start_node_has_incoming_edge | Start Node 有入边 | false | - |
| end_node_has_outgoing_edge | End Node 有出边 | false | - |
| non_branch_multiple_outgoing | 非 Branch 节点多出边 | false | - |
| branch_target_not_found | Branch target 不存在 | false | - |
| branch_target_no_edge | Branch target 无对应边 | false | - |
| disconnected_node | 存在孤立节点 | false | - |
| cycle_detected | 检测到环 | false | - |
| disabled_node_in_publish | 发布版本包含禁用节点 | false | - |

#### 7.2.4 Runtime 错误

| code | message | retryable | http_status |
|---|---|---|---|
| variable_not_found | 变量不存在 | false | - |
| invalid_variable_path | 非法变量路径 | false | - |
| variable_too_large | 变量值过大 | false | - |
| variable_type_mismatch | 变量类型不匹配 | false | - |
| output_mapping_error | 输出映射错误 | false | - |
| state_too_large | State 过大 | false | - |
| node_output_too_large | 节点输出过大 | false | - |
| branch_no_match | Branch 无命中且无 default | false | - |
| timeout | 节点超时 | depends | - |
| budget_exhausted | 预算耗尽 | false | - |
| llm_call_limit_exceeded | LLM 调用次数超限 | false | - |
| api_call_limit_exceeded | API 调用次数超限 | false | - |
| run_duration_exceeded | 运行时长超限 | false | - |

#### 7.2.5 LLM Provider 错误

| code | message | retryable | http_status |
|---|---|---|---|
| llm_provider_error | LLM Provider 错误 | true | - |
| llm_provider_unavailable | LLM Provider 不可用 | true | - |
| llm_rate_limit | LLM Rate Limited | true | - |
| llm_context_length_exceeded | 上下文长度超限 | false | - |
| llm_invalid_response | LLM 返回不合法 | false | - |
| llm_content_filter | 内容被过滤 | false | - |

#### 7.2.6 API Node 错误

| code | message | retryable | http_status |
|---|---|---|---|
| api_invalid_url | URL 不合法 | false | - |
| api_forbidden_scheme | 禁止的 scheme | false | - |
| api_forbidden_destination | 目标地址被禁止（SSRF） | false | - |
| api_dns_error | DNS 解析失败 | true | - |
| api_connect_timeout | 连接超时 | true | - |
| api_connect_error | 连接错误 | true | - |
| api_request_error | 请求构造错误 | false | - |
| api_response_error | 响应错误（5xx） | true | - |
| api_response_error_4xx | 响应错误（4xx） | false | - |
| api_response_too_large | 响应体过大 | false | - |
| api_too_many_redirects | 重定向次数过多 | false | - |

#### 7.2.7 Knowledge Base 错误

| code | message | retryable | http_status |
|---|---|---|---|
| knowledge_base_not_found | 知识库不存在 | false | - |
| knowledge_base_empty | 知识库无索引内容 | false | - |
| embedding_provider_error | Embedding Provider 错误 | true | - |
| vector_search_error | 向量检索失败 | true | - |

#### 7.2.8 Secret/Tool 错误

| code | message | retryable | http_status |
|---|---|---|---|
| secret_not_found | Secret 不存在 | false | - |
| secret_unavailable | Secret 不可用 | false | - |
| tool_not_found | Tool 不存在 | false | - |
| tool_test_failed | Tool 测试失败 | false | - |

#### 7.2.9 文档/知识库处理错误

| code | message | retryable | http_status |
|---|---|---|---|
| document_not_found | 文档不存在 | false | - |
| document_parse_failed | 文档解析失败 | depends | - |
| document_unsupported_type | 不支持的文档类型 | false | - |
| document_too_large | 文档过大 | false | - |
| chunk_failed | 切分失败 | true | - |
| embedding_failed | Embedding 生成失败 | true | - |

#### 7.2.10 系统/基础设施错误

| code | message | retryable | http_status |
|---|---|---|---|
| database_error | 数据库错误 | true | 500 |
| redis_error | Redis 错误 | true | 500 |
| storage_error | 存储错误 | true | 500 |
| internal_error | 内部错误 | true | 500 |
| service_unavailable | 服务不可用 | true | 503 |

### 7.3 retryable 的语义

```text
true   → 错误在物理层面可能瞬时，重试可能成功
false  → 重试不会改变结果（配置错误、逻辑错误、权限错误）
depends → 取决于具体场景：
   timeout 对幂等请求可重试，对非幂等不可（见 security §8）
   document_parse_failed 对暂时故障可重试，对损坏文件不可
```

retry_on 配置时应基于此表选择。

### 7.4 错误响应规范

API 响应：

```json
{
  "error": {
    "code": "missing_required_config",
    "message": "LLM Node 缺少 user_prompt",
    "details": {
      "node_id": "llm_1",
      "field": "config.user_prompt"
    }
  },
  "request_id": "req_abc123"
}
```

NodeRun 中：

```json
{
  "error_code": "timeout",
  "error_message": "LLM provider did not respond within 60s",
  "metadata_json": {
    "attempt": 2,
    "elapsed_ms": 60000
  }
}
```

### 7.5 错误码维护

```text
新增节点类型时：在对应 section 增加错误码
新增错误码必须同步更新：
  - 本文档 §7.2 表格
  - 后端 errors.py 常量
  - 前端 i18n 映射
  - GraphValidator 文档（如果是校验错误）
不允许：
  - 直接 raise Exception("xxx") 而无 error_code
  - 同一类错误用不同 code（如 lm_timeout / llm_timed_out）
```

---

## 8. 告警阈值建议

### 8.1 P0（必须告警）

```text
API 错误率 > 5%（持续 5 分钟）
/ready 失败 > 30 秒
数据库连接失败
master key 缺失（启动失败）
workflow_run 失败率 > 30%（持续 10 分钟）
LLM Provider 错误率 > 50%（持续 5 分钟）
```

### 8.2 P1（业务时间告警）

```text
API p95 延迟 > 3 秒
工作流运行 p95 时长 > 5 分钟
node_run 失败率 > 10%
队列积压 > 100（持续 10 分钟）
文档处理失败率 > 20%
state_size_bytes p99 > 10 MB
budget_exhausted_total > 10/5min
```

### 8.3 P2（次日跟踪）

```text
LLM token 用量异常增长（同比 > 2 倍）
LLM 成本日累计 > 阈值
磁盘使用率 > 80%
audit_logs 增长异常
```

---

## 9. 日志查询模式

### 9.1 排查工作流失败

```text
关键字段：run_id
查询：
  level >= ERROR
  AND run_id = <run_id>
  ORDER BY timestamp ASC
```

### 9.2 排查 LLM 调用慢

```text
查询：
  logger = "runtime.llm_executor"
  AND duration_ms > 10000
  GROUP BY model
```

### 9.3 排查 API Node 失败

```text
查询：
  logger = "runtime.api_executor"
  AND error_code IS NOT NULL
  GROUP BY error_code, url_host
```

### 9.4 排查文档处理积压

```text
查询：
  logger = "knowledge.document_processing"
  AND timestamp > 1h ago
  AND status = "running"
```

---

## 10. 数据保留与清理

### 10.1 默认保留策略

```text
workflow_runs        90 天
node_runs            90 天（随 workflow_runs）
audit_logs           180 天
documents（软删除）  30 天后物理删除
knowledge_chunks     随 documents 物理删除
原始文件            30 天（与 documents 软删除同步）
应用日志            14 天（容器层处理）
```

### 10.2 清理任务

```text
每日 03:00 运行清理 job
按表分批 DELETE，避免长事务
清理前导出审计相关数据到对象存储（v0.2）
```

#### 10.2.1 SQL 模板

```sql
-- 清理 90 天前的运行记录
DELETE FROM node_runs
WHERE run_id IN (
  SELECT id FROM workflow_runs
  WHERE created_at < now() - interval '90 days'
);

DELETE FROM workflow_runs
WHERE created_at < now() - interval '90 days';

-- 清理 180 天前的审计日志
DELETE FROM audit_logs
WHERE created_at < now() - interval '180 days';

-- 物理删除软删除超过 30 天的文档
DELETE FROM knowledge_chunks
WHERE document_id IN (
  SELECT id FROM documents
  WHERE deleted_at IS NOT NULL
    AND deleted_at < now() - interval '30 days'
);

DELETE FROM documents
WHERE deleted_at IS NOT NULL
  AND deleted_at < now() - interval '30 days';
```

### 10.3 备份

```text
PostgreSQL 备份：每日 pg_dump，保留 7 天本地 + 30 天远端
secrets 表加密备份（master key 单独保存，不与备份同地）
文件存储备份：每周全量 + 每日增量
```

---

## 11. 队列积压排查 Runbook

### 11.1 现象

```text
queue_depth{queue_name="document_processing"} 持续上升
文档上传后长时间停在 parsing/chunking/embedding 状态
告警触发
```

### 11.2 排查步骤

```text
1. 查看 worker 进程是否在线
   docker compose ps | grep worker
2. 查看 worker 日志最新一条
   docker compose logs --tail=100 worker-document
3. 判断是否卡在某个文档
   查 documents WHERE status IN ('parsing','chunking','embedding') ORDER BY updated_at
4. 判断是否 embedding provider 限流
   查 logs WHERE error_code = "llm_rate_limit"
5. 增加 worker 数量
   docker compose up -d --scale worker-document=3
6. 重启失败任务
   POST /api/v1/documents/{id}/retry
```

### 11.3 临时缓解

```text
降低并发：限制每个 worker 同时处理 N 个文档
切换 embedding provider 或 model
暂停新文档上传（前端开关）
```

---

## 12. 与原文档的衔接

| 修订 | 文档 | 章节 |
|---|---|---|
| /ready 端点 | api_design, openapi | §2.6 后新增 Health 章 |
| /metrics 端点 | api_design, testing | 新增 |
| JSON 日志格式 | backend_structure, testing | §12 替换 |
| state 大小限制 | runtime, ER | §11 后增加，ER §6.4 metadata_json 字段 |
| LLM 预算 | runtime, ER, design v1 | §6.3 + workflow_runs 字段 |
| 错误码字典 | runtime, api_design | §11 后增加完整字典 |
| 告警阈值 | testing | §13 监控指标后增加 |
| 数据保留 | tech_stack, testing | §11 完善 SQL |

---

## 13. 结论

可观测性的本质是"让人能在失败时快速定位"。MVP 阶段：

```text
日志：结构化 JSON + request_id 串联
Metrics：覆盖 API/Runtime/LLM/KB/Queue 五大类
健康检查：/health 进程级 + /ready 依赖级
错误码：完整字典 + retryable 默认值 + 前端 i18n
预算：单 run token / call / duration 三层兜底
保留：90 天 / 180 天 / 30 天三档
```

这套底座建立后，后续不论加多少新节点、新功能，运维都能跟得上。
