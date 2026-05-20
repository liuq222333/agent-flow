# Agent 工作流平台运行稳定性与可观测性开发文档 v1

## 1. 文档目的

本文档用于指导 Agent 工作流平台在 MVP 基础上继续增强运行稳定性、Worker 恢复能力、Trace 调试能力、日志指标与运维接口。

当前平台已经具备：

```text
workflow_runs / node_runs 运行记录
同步 / 异步运行
Redis list 异步队列
workflow-run worker
document-processing worker
run cancel 基础接口
run retry 基础接口
Trace 查询与增量参数
/health 与 /ready
/metrics 基础指标
stale async run 基础恢复
```

但距离可长期运行的生产基线仍有差距，主要缺口是：

```text
Worker 心跳与租约不够精确
Redis 队列缺少 ack / processing / dead-letter 语义
running run 取消仍是基础状态更新，不是协作式取消
节点级 retry 尚未完全形成统一执行框架
Trace 仍以查询为主，缺少事件流
日志字段尚未全链路统一
指标覆盖还不够细
运维排障接口不足
```

本文档把后续优化拆成可实施的开发任务，并给出接口、数据结构、状态机、测试和上线顺序。

---

## 2. 设计原则

### 2.1 原 run 不可变

失败、取消或 worker 丢失后的 run 不应被复活。

重试必须创建新的 workflow_run，并通过 metadata 或关联表记录来源：

```text
retry_of_run_id
retry_mode
retry_reason
retry_requested_by
retry_requested_at
original_error_code
```

这样可以保证：

```text
原 Trace 可审计
新 Trace 可独立排查
同一次用户动作不会覆盖历史结果
问题复盘时能看到每次尝试的完整链路
```

### 2.2 running run 不自动重跑

worker 崩溃时，如果 run 已进入 running，不能默认重新执行。

原因：

```text
某些节点可能已经调用外部 API
非幂等 API 可能已经产生副作用
LLM/API/Knowledge 节点可能已经消耗成本
自动重跑可能造成重复发送消息、重复下单或重复扣费
```

因此恢复策略为：

```text
pending 且 stale：可重新入队
running 且 lease 过期：标记 failed / worker_lost
failed / worker_lost：由用户或运维显式 retry
```

### 2.3 状态更新必须受状态机约束

任何状态变更都应通过封装函数完成，并在 SQL 中带原状态条件。

示例：

```sql
UPDATE workflow_runs
SET status = 'running'
WHERE id = :run_id AND status = 'pending'
RETURNING *
```

不要出现无条件：

```sql
UPDATE workflow_runs SET status = ...
```

### 2.4 可观测性先于自动化

在做自动恢复之前，必须先让系统能回答：

```text
哪个 run 卡住了
哪个 worker 领取了它
最后一次 heartbeat 是什么时候
当前节点是什么
是否已经产生外部副作用
是否允许 retry
retry 后创建了哪个新 run
```

### 2.5 MVP 到生产分层

后续实现分三层：

```text
Level 1：MVP 稳定化
  状态机、run retry、stale 恢复、基础 metrics、基础日志

Level 2：可运维
  worker lease、queue ack、DLQ、协作取消、运维接口

Level 3：生产增强
  SSE Trace、完整指标、告警、worker 调度、容量与成本控制
```

---

## 3. 当前能力基线

### 3.1 已有数据表

核心表：

```text
workflow_runs
node_runs
document_processing_jobs
audit_logs
workflow_versions
```

workflow_runs 当前承担：

```text
run 状态
输入输出
state_json
metadata_json
错误信息
开始结束时间
```

node_runs 当前承担：

```text
节点状态
attempt
节点输入
节点输出
错误信息
耗时
metadata_json
```

### 3.2 已有接口

```http
POST /api/v1/workflows/{workflow_id}/run
GET  /api/v1/runs
GET  /api/v1/runs/{run_id}
GET  /api/v1/runs/{run_id}/node-runs
GET  /api/v1/runs/{run_id}/trace
POST /api/v1/runs/{run_id}/cancel
POST /api/v1/runs/{run_id}/retry
GET  /api/v1/health
GET  /api/v1/ready
GET  /api/v1/metrics
```

### 3.3 当前 worker 行为

```text
API 创建 pending workflow_run
API 把 run_id 推入 Redis list
workflow-run worker BRPOP 获取 run_id
worker 查询 workflow_runs
如果 cancelled 则跳过
否则执行 generated workflow
执行结束后写 completed / failed
```

### 3.4 当前恢复行为

已有基础恢复：

```text
stale pending async run：更新 metadata 并重新入队
stale running async run：标记 failed / worker_lost
stale running node_run：标记 failed / worker_lost
```

后续需要升级为 lease + heartbeat。

---

## 4. 目标状态机

### 4.1 workflow_run.status

建议状态：

```text
pending
running
cancel_requested
completed
failed
cancelled
```

当前数据库没有 `cancel_requested`，可以先使用 metadata 表达：

```json
{
  "cancel_requested": true,
  "cancel_requested_at": "2026-05-18T12:00:00Z",
  "cancel_requested_by": 1
}
```

后续 migration 再把状态枚举加入 `cancel_requested`。

### 4.2 状态流转

```text
pending -> running
pending -> cancelled
running -> cancel_requested
cancel_requested -> cancelled
running -> completed
running -> failed
running -> failed(worker_lost)
failed -> terminal
cancelled -> terminal
completed -> terminal
```

不允许：

```text
completed -> running
completed -> failed
failed -> running
cancelled -> running
running -> pending
```

### 4.3 状态机函数

建议在 `app.services.runtime_state` 或 `app.services.runs_state` 中新增：

```python
async def mark_run_claimed(conn, run_id: int, worker_id: str, lease_seconds: int) -> dict:
    ...

async def mark_run_running(conn, run_id: int) -> dict:
    ...

async def request_run_cancel(conn, run_id: int, actor_user_id: int) -> dict:
    ...

async def mark_run_cancelled(conn, run_id: int, state_json: dict | None = None) -> dict:
    ...

async def mark_run_completed(conn, run_id: int, output_json: dict, state_json: dict) -> dict:
    ...

async def mark_run_failed(
    conn,
    run_id: int,
    error_code: str,
    error_message: str,
    state_json: dict | None = None,
) -> dict:
    ...

async def mark_run_worker_lost(conn, run_id: int, worker_id: str | None) -> dict:
    ...
```

每个函数必须：

```text
检查当前状态
只允许合法流转
写 updated_at
必要时写 started_at / ended_at
写 metadata_json 中的状态上下文
返回最新 row
```

---

## 5. Worker 租约与心跳

### 5.1 背景

当前通过 `updated_at` 判断 stale。问题是：

```text
长节点执行期间 updated_at 可能长时间不变
无法判断 worker 是否仍然存活
无法知道 run 被哪个 worker 领取
无法展示 active worker
```

### 5.2 worker_id

worker 启动时生成：

```text
workflow-worker:<hostname>:<pid>:<uuid>
document-worker:<hostname>:<pid>:<uuid>
```

示例：

```text
workflow-worker:api-host-01:7281:6a3b1e5c
```

### 5.3 workflow_runs metadata 字段

在 `metadata_json` 中写入：

```json
{
  "worker": {
    "worker_id": "workflow-worker:host:pid:uuid",
    "queue_name": "workflow_runs",
    "claimed_at": "2026-05-18T12:00:00Z",
    "heartbeat_at": "2026-05-18T12:00:20Z",
    "lease_expires_at": "2026-05-18T12:01:20Z",
    "claim_count": 1
  }
}
```

### 5.4 worker_heartbeats 表

建议新增表：

```sql
CREATE TABLE worker_heartbeats (
  worker_id VARCHAR(255) PRIMARY KEY,
  worker_type VARCHAR(64) NOT NULL,
  queue_name VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL,
  current_run_id BIGINT,
  current_job_id VARCHAR(128),
  hostname VARCHAR(255),
  pid INT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata_json JSONB
);

CREATE INDEX idx_worker_heartbeats_type ON worker_heartbeats(worker_type);
CREATE INDEX idx_worker_heartbeats_queue ON worker_heartbeats(queue_name);
CREATE INDEX idx_worker_heartbeats_last_seen ON worker_heartbeats(last_seen_at);
CREATE INDEX idx_worker_heartbeats_current_run ON worker_heartbeats(current_run_id);
```

`status`：

```text
idle
busy
stopping
error
```

### 5.5 心跳流程

worker 主循环：

```text
1. 启动时 upsert worker_heartbeats status=idle
2. 领取 job 后 status=busy, current_run_id=...
3. 执行中每 HEARTBEAT_INTERVAL 秒更新 last_seen_at
4. 同步更新 workflow_runs.metadata_json.worker.heartbeat_at
5. run 结束后 status=idle, current_run_id=null
6. worker 收到 SIGTERM 时 status=stopping
```

### 5.6 租约过期判断

```text
lease_expires_at < now()
AND workflow_run.status IN ('running', 'cancel_requested')
```

处理：

```text
标记 run failed / worker_lost
标记 running node_runs failed / worker_lost
写 audit_logs action=workflow.worker_lost
增加 metric stale_runs_recovered_total{action="failed"}
```

### 5.7 heartbeat 参数

建议配置：

```text
WORKER_HEARTBEAT_INTERVAL_SECONDS=10
WORKER_LEASE_SECONDS=60
STALE_RUN_RECOVERY_INTERVAL_SECONDS=60
STALE_PENDING_SECONDS=300
```

---

## 6. Redis 队列 ack / processing / DLQ

### 6.1 当前问题

当前 `BRPOP` 从 list 取走 job 后，如果 worker 立刻崩溃，Redis 里已经没有这条 job。

目前靠 DB stale 恢复能兜底，但无法做到：

```text
确认 job 是否被 ack
区分已领取未完成与未领取
查看 processing 队列
限制 queue-level 重试次数
进入 DLQ
```

### 6.2 新队列结构

```text
agent_flow:workflow_runs              主队列
agent_flow:workflow_runs:processing   处理中队列
agent_flow:workflow_runs:dead         死信队列
```

### 6.3 job payload

```json
{
  "job_id": "wrj_01HY...",
  "run_id": 2001,
  "queue_name": "workflow_runs",
  "enqueued_at": "2026-05-18T12:00:00Z",
  "queue_attempt": 1,
  "request_id": "req_abc",
  "retry_of_job_id": null
}
```

### 6.4 enqueue

```text
生成 job_id
LPUSH 主队列
workflow_runs.metadata_json.queue.job_id = job_id
workflow_runs.metadata_json.queue.enqueued_at = now
workflow_runs.metadata_json.queue.queue_attempt = 1
```

### 6.5 dequeue

优先使用 Redis 原子移动：

```text
BLMOVE source=main destination=processing RIGHT LEFT timeout=5
```

Redis 版本不支持时，使用：

```text
BRPOPLPUSH main processing timeout
```

### 6.6 ack

worker 完成后：

```text
LREM processing 1 payload
```

成功 ack 后记录：

```text
queue_processed_total{queue_name="workflow_runs", status="success"} +1
```

### 6.7 processing 恢复

恢复器扫描 processing 队列：

```text
解析 job payload
查询 workflow_runs
如果 run completed/failed/cancelled：从 processing 移除
如果 run pending：重新放回主队列
如果 run running 且 lease 过期：标 failed / worker_lost，并从 processing 移除
如果 payload 无效：移入 dead
```

### 6.8 DLQ 策略

进入 DLQ 的条件：

```text
payload 无法解析
run_id 不存在
queue_attempt 超过 MAX_QUEUE_ATTEMPTS
反复 requeue 但仍 pending 超时
worker 执行入口连续异常
```

建议配置：

```text
MAX_QUEUE_ATTEMPTS=3
```

DLQ payload：

```json
{
  "job": {},
  "dead_reason": "invalid_payload | run_not_found | queue_retry_exhausted",
  "dead_at": "2026-05-18T12:05:00Z",
  "last_error": "..."
}
```

### 6.9 运维动作

后续接口：

```http
GET  /api/v1/ops/queues
GET  /api/v1/ops/queues/workflow_runs/dead
POST /api/v1/ops/queues/workflow_runs/dead/{job_id}/requeue
POST /api/v1/ops/queues/workflow_runs/recover
```

---

## 7. 协作式取消

### 7.1 当前问题

当前 cancel 直接把 pending/running 改成 cancelled。对于 running run，这可能不准确：

```text
worker 可能已经开始执行节点
外部 API 可能正在等待响应
LLM 调用可能正在进行
node_run 可能仍然 running
```

### 7.2 新取消流程

pending：

```text
pending -> cancelled
worker 取到 job 后发现 cancelled，直接 ack 跳过
```

running：

```text
running -> cancel_requested
Runtime 在节点边界检查 cancellation
当前节点结束后停止执行后续节点
run -> cancelled
```

如果当前节点支持取消：

```text
传入 timeout/cancel context
尽快中断
```

### 7.3 Runtime 检查点

检查位置：

```text
run 开始前
每个节点开始前
每个节点结束后
retry sleep 前
长循环内部
```

函数：

```python
async def check_cancel_requested(conn, run_id: int) -> None:
    ...
```

如果已请求取消：

```python
raise RunCancelledError("run_cancelled", "run cancellation requested")
```

### 7.4 Trace 表现

被取消的 node_run：

```text
如果节点未开始：不创建 node_run
如果节点执行中被取消：status=failed, error_code=run_cancelled
如果节点因上游取消未执行：可选 status=skipped
```

workflow_run：

```text
status=cancelled
error_code=run_cancelled
error_message=run cancellation requested
```

### 7.5 前端表现

```text
pending: 取消后显示 已取消
running: 点击取消后显示 取消中
cancel_requested: 禁用再次取消按钮
cancelled: Trace 显示取消点
```

---

## 8. Run retry

### 8.1 已实现基础能力

当前 `POST /runs/{run_id}/retry`：

```text
只允许 failed / cancelled
创建新的 pending async run
复用原 input，或使用请求体 input 覆盖
写 retry metadata
写 audit log
入队执行
```

### 8.2 建议接口扩展

```http
POST /api/v1/runs/{run_id}/retry
```

请求：

```json
{
  "mode": "same_input",
  "input": null,
  "reason": "provider recovered"
}
```

mode：

```text
same_input       复用原输入
override_input   使用新输入
from_failed_node 从失败节点恢复，后续版本实现
```

响应：

```json
{
  "run_id": 3002,
  "status": "pending",
  "retry_of_run_id": 3001,
  "retry_mode": "same_input"
}
```

### 8.3 from_failed_node 后续设计

该模式需要：

```text
每个节点成功后保存 state_json checkpoint
找到最后一个 failed node_run
复用失败前 state
跳过已成功且可复用的节点
从失败节点或其后继节点继续
```

MVP 暂不建议实现，因为：

```text
副作用节点难以保证幂等
Branch 路由路径恢复复杂
state checkpoint 需要更严格版本化
```

### 8.4 retry 关系查询

后续可增加：

```http
GET /api/v1/runs/{run_id}/retries
```

返回：

```json
{
  "root_run_id": 3001,
  "items": [
    {"run_id": 3001, "status": "failed", "attempt_index": 1},
    {"run_id": 3002, "status": "completed", "attempt_index": 2}
  ]
}
```

---

## 9. 节点级 retry

### 9.1 目标

把所有节点执行统一包进 retry wrapper，而不是每个节点自己处理。

### 9.2 节点配置

```json
{
  "retry": {
    "max_attempts": 3,
    "backoff": "fixed",
    "fixed_delay_ms": 1000,
    "retry_on": ["timeout", "rate_limit", "network_error"]
  },
  "timeout": 60
}
```

### 9.3 执行规则

```text
max_attempts 包含第一次执行
每个 attempt 创建一条 node_runs
attempt 从 1 开始递增
每次重试前重新解析 input_mapping
retryable=false 不重试
error_code 不在 retry_on 中不重试
超过 max_attempts 后节点最终失败
```

### 9.4 错误分类

建议错误结构：

```python
class RuntimeNodeError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        detail: dict | None = None,
    ) -> None:
        ...
```

默认 retryable：

```text
timeout                depends
api_connect_timeout    true
api_read_timeout       depends
api_rate_limit         true
api_5xx                true
llm_rate_limit         true
llm_provider_error     true
network_error          true
invalid_config         false
permission_denied      false
variable_not_found     false
branch_no_match        false
```

### 9.5 node_runs 表现

第 1 次失败：

```text
node_runs.status = failed
attempt = 1
error_code = timeout
metadata_json.retry.next_attempt = 2
```

第 2 次成功：

```text
node_runs.status = success
attempt = 2
```

前端 Trace 聚合时：

```text
同 node_id 多条 node_runs 按 attempt 展示
默认展开最后一次
失败历史可折叠查看
```

---

## 10. Trace 事件流

### 10.1 当前查询模式

已有：

```http
GET /api/v1/runs/{run_id}/trace
GET /api/v1/runs/{run_id}/trace?after_node_run_id=100
```

建议补响应字段：

```json
{
  "run": {},
  "nodes": [],
  "graph_json": {},
  "next_after_node_run_id": 120
}
```

### 10.2 workflow_run_events 表

建议新增：

```sql
CREATE TABLE workflow_run_events (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL,
  node_run_id BIGINT,
  event_type VARCHAR(128) NOT NULL,
  sequence BIGINT NOT NULL,
  payload_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_workflow_run_events_run_id ON workflow_run_events(run_id, sequence);
CREATE INDEX idx_workflow_run_events_type ON workflow_run_events(event_type);
CREATE INDEX idx_workflow_run_events_created_at ON workflow_run_events(created_at);
```

### 10.3 事件类型

```text
run.queued
run.claimed
run.started
run.cancel_requested
run.cancelled
run.completed
run.failed
run.worker_lost
node.started
node.succeeded
node.failed
node.retrying
node.skipped
trace.redacted
```

### 10.4 SSE 接口

```http
GET /api/v1/runs/{run_id}/events
Accept: text/event-stream
```

事件示例：

```text
event: node.started
id: 120
data: {"node_run_id":3001,"node_id":"llm_1","attempt":1}

event: node.succeeded
id: 121
data: {"node_run_id":3001,"duration_ms":1320}
```

### 10.5 SSE 实现阶段

第一阶段：

```text
API 轮询 workflow_run_events 表
按 sequence 推送
实现简单，依赖少
```

第二阶段：

```text
worker 写 DB 事件后 Redis pub/sub
API 订阅 Redis channel
低延迟
```

第三阶段：

```text
WebSocket
支持双向控制，例如 cancel
```

---

## 11. Metrics 指标

### 11.1 已有基础指标

```text
agent_flow_workflow_runs_total{status}
agent_flow_node_runs_total{node_type,status}
agent_flow_queue_depth{queue_name}
agent_flow_metrics_scrape_error{component}
```

### 11.2 下一步必须指标

Workflow：

```text
agent_flow_workflow_runs_in_flight
agent_flow_workflow_run_duration_seconds_bucket
agent_flow_workflow_run_duration_seconds_sum
agent_flow_workflow_run_duration_seconds_count
agent_flow_run_retries_total{reason}
agent_flow_run_cancel_requests_total
agent_flow_stale_runs_recovered_total{action}
```

Node：

```text
agent_flow_node_run_duration_seconds_bucket{node_type}
agent_flow_node_retries_total{node_type,error_code}
agent_flow_node_failures_total{node_type,error_code}
```

Queue：

```text
agent_flow_queue_depth{queue_name}
agent_flow_queue_processing_depth{queue_name}
agent_flow_queue_dead_letter_depth{queue_name}
agent_flow_queue_processed_total{queue_name,status}
agent_flow_queue_job_age_seconds{queue_name}
```

Worker：

```text
agent_flow_worker_active{worker_type,queue_name}
agent_flow_worker_busy{worker_type,queue_name}
agent_flow_worker_last_heartbeat_timestamp{worker_id}
agent_flow_worker_current_run{worker_id,run_id}
```

LLM：

```text
agent_flow_llm_calls_total{provider,model,status}
agent_flow_llm_tokens_total{provider,model,kind}
agent_flow_llm_estimated_cost_total{provider,model}
```

### 11.3 指标实现方式

MVP 可直接 SQL 聚合。

生产建议：

```text
进程内 Counter/Histogram 记录实时指标
DB 聚合只用于补充状态类 Gauge
队列深度从 Redis 读取
worker heartbeat 从 worker_heartbeats 读取
```

---

## 12. 结构化日志

### 12.1 统一字段

所有 API / runtime / worker 日志应使用 JSON 格式。

字段：

```text
timestamp
level
logger
message
service
request_id
user_id
workflow_id
version_id
run_id
node_id
node_type
worker_id
job_id
queue_name
error_code
duration_ms
extra
```

### 12.2 request_id

API middleware：

```text
读取 X-Request-ID
没有则生成 req_<uuid>
写入 response header
写入 contextvar
```

异步 run：

```text
创建 run 时写 metadata_json.request_id
入队 job payload 带 request_id
worker 日志继承 request_id
Trace metadata 带 request_id
```

### 12.3 禁止写入日志

```text
Authorization header
secret value
完整 LLM prompt，除非 TRACE_SAVE_PROMPT=true
完整文件内容
PII 原文
```

### 12.4 关键日志点

API：

```text
request received
request completed
run created
run cancel requested
run retry requested
```

Worker：

```text
worker started
worker heartbeat failed
job dequeued
job claimed
run started
run completed
run failed
run cancelled
job acked
job moved to DLQ
stale run recovered
```

Runtime：

```text
node started
node succeeded
node failed
node retry scheduled
cancel requested observed
```

---

## 13. /ready 增强

### 13.1 API ready

当前检查：

```text
database
redis
encryption_key
default_model_provider
```

建议增强：

```text
database ping
redis ping
redis queue write/delete smoke
secret encryption key valid
default model provider exists and active
generated_workflows root readable
upload storage writable
```

### 13.2 Worker ready

worker 不一定暴露 HTTP。可选两种方式：

```text
方式一：worker 写 worker_heartbeats，由 API /ready 间接检查
方式二：worker 启动一个本地 health port
```

MVP 推荐方式一。

### 13.3 ready 响应

```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "redis": "ok",
    "redis_queue_write": "ok",
    "encryption_key": "ok",
    "default_model_provider": "ok",
    "generated_workflows_root": "ok",
    "upload_storage": "ok",
    "workflow_worker_recent": "ok"
  }
}
```

---

## 14. 运维接口

### 14.1 队列状态

```http
GET /api/v1/ops/queues
```

响应：

```json
{
  "queues": [
    {
      "queue_name": "workflow_runs",
      "pending_depth": 12,
      "processing_depth": 1,
      "dead_letter_depth": 0,
      "oldest_job_age_seconds": 45
    }
  ]
}
```

### 14.2 Worker 状态

```http
GET /api/v1/ops/workers
```

响应：

```json
{
  "items": [
    {
      "worker_id": "workflow-worker:host:pid:uuid",
      "worker_type": "workflow",
      "queue_name": "workflow_runs",
      "status": "busy",
      "current_run_id": 2001,
      "last_seen_at": "2026-05-18T12:00:10Z"
    }
  ]
}
```

### 14.3 手动恢复

```http
POST /api/v1/ops/runs/recover-stale
```

请求：

```json
{
  "stale_after_seconds": 900,
  "dry_run": true
}
```

响应：

```json
{
  "requeued": [1001],
  "failed": [1002],
  "skipped": [1003]
}
```

### 14.4 DLQ 操作

```http
GET  /api/v1/ops/queues/workflow_runs/dead
POST /api/v1/ops/queues/workflow_runs/dead/{job_id}/requeue
```

所有 ops 接口必须：

```text
管理员权限
写 audit_logs
支持 dry_run
默认分页
不要返回 secret
```

---

## 15. 前端改造

### 15.1 Run 列表

增加：

```text
状态筛选
失败原因
retry 按钮
cancel 按钮
worker_lost 标签
retry_of_run_id 链接
```

### 15.2 Retry 弹窗

字段：

```text
retry mode
reason
input JSON 编辑器
```

默认：

```text
mode=same_input
input=原 run input，只读预览
```

选择 override 后允许编辑 input。

### 15.3 Trace 面板

增强：

```text
同 node_id 多 attempt 分组
默认展开最后一次 attempt
显示 worker_lost 错误说明
大 JSON 折叠
显示 request_id/job_id/worker_id
显示 run retry 关系
```

### 15.4 实时 Trace

阶段一：

```text
继续使用 after_node_run_id 增量轮询
```

阶段二：

```text
接入 SSE /runs/{run_id}/events
```

---

## 16. 数据库 migration 计划

### 16.1 第一批 migration

```sql
CREATE INDEX IF NOT EXISTS idx_workflow_runs_status_updated_at
  ON workflow_runs(status, updated_at);

CREATE INDEX IF NOT EXISTS idx_node_runs_run_status
  ON node_runs(run_id, status);
```

### 16.2 第二批 migration

```sql
CREATE TABLE IF NOT EXISTS worker_heartbeats (
  worker_id VARCHAR(255) PRIMARY KEY,
  worker_type VARCHAR(64) NOT NULL,
  queue_name VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL,
  current_run_id BIGINT,
  current_job_id VARCHAR(128),
  hostname VARCHAR(255),
  pid INT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata_json JSONB
);
```

### 16.3 第三批 migration

```sql
CREATE TABLE IF NOT EXISTS workflow_run_events (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL,
  node_run_id BIGINT,
  event_type VARCHAR(128) NOT NULL,
  sequence BIGINT NOT NULL,
  payload_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 16.4 可选表：run_retry_links

如果 metadata 查询不方便，可增加：

```sql
CREATE TABLE IF NOT EXISTS run_retry_links (
  id BIGSERIAL PRIMARY KEY,
  source_run_id BIGINT NOT NULL,
  retry_run_id BIGINT NOT NULL,
  retry_mode VARCHAR(64) NOT NULL,
  reason TEXT,
  requested_by BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(retry_run_id)
);
```

---

## 17. 测试计划

### 17.1 状态机测试

```text
pending -> running 成功
pending -> cancelled 成功
running -> completed 成功
running -> failed 成功
completed -> running 失败
failed -> running 失败
cancelled -> running 失败
```

### 17.2 Worker 测试

```text
pending stale run 会重新入队
running stale run 会标 worker_lost
completed run 不会被恢复器修改
cancelled run 被 worker 取到后直接 ack
多个 worker 同时领取同一 run 只有一个成功
processing 队列超时 job 能恢复
无效 payload 进入 DLQ
```

### 17.3 Cancel 测试

```text
cancel pending -> cancelled
cancel running -> cancel_requested
Runtime 节点边界看到 cancel_requested 后停止
cancelled run 不再执行后续节点
node_run 记录取消信息
```

### 17.4 Retry 测试

```text
failed run 可 retry
cancelled run 可 retry
completed run 不可 retry
retry 创建新 run
原 run 不变
新 run metadata 含 retry_of_run_id
retry 后入队
override input 生效
```

### 17.5 Node retry 测试

```text
timeout retry 成功
rate_limit retry 成功
invalid_config 不 retry
max_attempts 生效
每个 attempt 都有 node_run
retry 前 input_mapping 重新解析
```

### 17.6 Metrics 测试

```text
/metrics 返回 text/plain
DB 正常时输出 run/node 指标
Redis 正常时输出 queue_depth
DB 异常时返回 scrape_error，不返回 500
Redis 异常时返回 scrape_error，不返回 500
label 正确 escape
```

### 17.7 Trace 测试

```text
after_node_run_id 只返回增量 node_runs
next_after_node_run_id 正确
多 attempt 节点排序正确
敏感 header 脱敏
secret value 不进入 trace
```

---

## 18. 分阶段实施路线

### Phase 1：稳定状态机与恢复基础

目标：

```text
状态机函数
run retry 完善 mode
stale recovery dry_run
基础 indexes
metrics scrape error 完善
```

验收：

```text
pytest 全量通过
pending stale 可重新入队
running stale 标 worker_lost
failed/cancelled run 可 retry
completed run 不可 retry
```

### Phase 2：Worker lease / heartbeat

目标：

```text
worker_id
worker_heartbeats 表
run claim 写 worker metadata
heartbeat loop
lease 过期恢复
```

验收：

```text
/metrics 可看到 active worker
停止 worker 后 lease 过期 run 被标 worker_lost
长节点执行期间 heartbeat 持续更新
```

### Phase 3：Queue ack / DLQ

目标：

```text
main / processing / dead 队列
BLMOVE 或 BRPOPLPUSH
ack
processing recovery
dead letter
ops queue 接口
```

验收：

```text
worker 崩溃后 job 不丢
无效 job 进入 DLQ
超过 queue attempts 进入 DLQ
可手动 requeue DLQ job
```

### Phase 4：协作式取消

目标：

```text
cancel_requested
Runtime cancellation checkpoint
node_run 取消记录
前端取消中状态
```

验收：

```text
running run 点击取消后不继续执行后续节点
Trace 能看到取消点
cancel pending 仍即时生效
```

### Phase 5：节点级 retry

目标：

```text
统一 node retry wrapper
attempt node_runs
错误分类
backoff
timeout
```

验收：

```text
可重试错误自动 retry
不可重试错误直接失败
Trace 显示每次 attempt
```

### Phase 6：Trace events / SSE

目标：

```text
workflow_run_events
event recorder
SSE API
前端实时 Trace
```

验收：

```text
节点开始/结束实时显示
run 完成后 SSE 自动结束
断线后可通过 Last-Event-ID 恢复
```

---

## 19. 风险与取舍

### 19.1 自动重跑风险

不要自动重跑 running run。必须由用户或运维显式 retry。

### 19.2 metadata 过度膨胀

metadata_json 适合灵活字段，但高频查询字段应表化。

建议表化：

```text
worker heartbeat
run events
retry links
```

### 19.3 指标成本

每次 `/metrics` 做大表聚合可能变慢。

后续可：

```text
增加索引
限制统计窗口
使用进程内 metrics
定时聚合到轻量表
```

### 19.4 SSE 连接数

SSE 会占连接。需要：

```text
连接超时
最大连接数
鉴权
心跳事件
断线重连
```

### 19.5 非幂等节点

API Node、Message Node、未来 Code Node 都可能产生副作用。

需要节点配置：

```json
{
  "idempotency": {
    "safe_to_retry": false,
    "idempotency_key_template": "{{ run_id }}:{{ node_id }}:{{ attempt }}"
  }
}
```

---

## 20. 优先级建议

建议先做：

```text
P0 状态机封装
P0 worker lease / heartbeat
P0 queue processing / ack
P0 running stale 标 worker_lost，不自动重跑
P1 DLQ
P1 协作式取消
P1 节点级 retry
P1 metrics 完整化
P2 SSE Trace
P2 ops UI
```

最小下一步开发包：

```text
1. 新增 workflow_runs(status, updated_at) 和 node_runs(run_id, status) 索引
2. 新增 worker_heartbeats 表
3. workflow-run worker 生成 worker_id
4. claim run 时写 worker metadata
5. heartbeat loop 更新 worker_heartbeats 与 workflow_runs metadata
6. recovery 改为 lease_expires_at 判断
7. /metrics 输出 worker_active 和 worker_last_heartbeat
8. 增加 worker lease 单元测试
```

这一步完成后，平台就能可靠回答：

```text
哪个 worker 在跑哪个 run
worker 是否还活着
run 是真的卡住还是长时间运行
什么时候可以安全标 worker_lost
```

---

## 21. 开发检查清单

每个稳定性功能合入前必须检查：

```text
状态机是否合法
是否会误重跑 running run
是否写 audit log
是否有 metrics
是否有结构化日志
是否保护 secret
是否有单元测试
是否有失败路径测试
是否有文档更新
```

每次上线前检查：

```text
/health ok
/ready ready
/metrics 可返回
workflow sync run 通过
workflow async run 通过
worker 能消费队列
stale pending 恢复测试通过
running worker_lost 测试通过
run retry 测试通过
Trace 可查询
日志可按 run_id 搜索
```
