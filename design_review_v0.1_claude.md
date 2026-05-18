# Agent 工作流平台设计评审报告 v0.1

## 0. 文档说明

本文档对当前 13 份设计文档 + SQL + OpenAPI 进行完整评审，**不修改原稿**。所有"建议修改"或"建议补充"以 issue 编号形式呈现，可在以下补丁文档中找到具体处理方案：

```text
consistency_patches_v0.1_claude.md      C1-C5、S1-S5 一致性与语义补丁
security_design_v0.1_claude.md          G1-G5、R5 安全/治理补丁
observability_runbook_v0.1_claude.md    G6-G10、G13 观测/运维补丁
implementation_details_v0.1_claude.md   G11-G12、G14-G20、R1-R4 实现细节
```

本报告分为：

```text
1. 评审范围与方法
2. 整体评价
3. 一致性问题 C1-C5
4. 协议语义模糊点 S1-S5
5. 设计缺失 G1-G20
6. 潜在风险 R1-R5
7. Issue 优先级矩阵
8. 推荐处理顺序
```

---

## 1. 评审范围与方法

### 1.1 评审范围

```text
agent_workflow_platform_design_v_1 (1).md        总设计
agent_workflow_platform_mvp_scope_v_1.md          MVP 范围
agent_workflow_platform_tech_stack_decision_v_1.md 技术栈
agent_workflow_platform_node_protocol_v_1.md      节点协议
agent_workflow_platform_runtime_detail_v_1.md     Runtime
agent_workflow_platform_database_er_v_1.md        数据库 ER
agent_workflow_platform_api_design_v_1.md         API 设计
agent_workflow_platform_backend_structure_v_1.md  后端结构
agent_workflow_platform_frontend_editor_design_v_1.md 前端编辑器
agent_workflow_platform_development_task_breakdown_v_1.md 开发任务
agent_workflow_platform_product_prototype_v_1.md  产品原型
agent_workflow_platform_sample_workflows_v_1.md   示例工作流
agent_workflow_platform_testing_deployment_v_1.md 测试与部署
001_init_agent_workflow_platform_mvp.sql           数据库初始化
openapi_agent_workflow_platform_mvp_v1.yaml        OpenAPI
```

### 1.2 评审方法

```text
逐字阅读所有文档
按主题做跨文档一致性比对
按"协议契约 → Runtime 行为 → 持久化 → API 契约 → 前端表现"做正向校验
按"实施者会问的问题"做反向校验
对照常见生产级 LLM 平台（LangChain、Dify、Flowise、n8n、Temporal）做能力盘点
```

---

## 2. 整体评价

### 2.1 优点

1. **协议先行**：Node Protocol → State → input/output mapping → Runtime 这条主链路定义清楚，节点扩展成本可控。
2. **版本不可变 + 草稿/发布分离**：`workflows.draft_graph_json` 与 `workflow_versions.graph_json` 边界严格，Runtime 只读发布版本，是这套架构最稳的工程红线。
3. **Trace 一等公民**：`node_runs` 表结构、`attempt` 字段、`metadata_json`（含 token/usage/api status）齐全。
4. **MVP 范围克制**：明确暂不做循环、并行、暂停恢复、代码沙箱、人工审批，避免常见过度设计。
5. **可演进路径**：技术栈升级路径（RQ→Celery，pgvector→Qdrant，Local→MinIO，Compose→K8s）写得清楚。
6. **示例驱动**：4 个端到端示例 + 失败用例覆盖核心场景，可直接做 CI fixture。
7. **错误处理基础到位**：on_error、retry、timeout 在节点层级都定义了。

### 2.2 短板

总体短板集中在以下几类：

```text
跨文档一致性不足，部分字段两种写法都被默许
变量解析的"上下文"边界未显式说明
安全/治理类细节多以"建议/可选"出现，缺乏强制约束
可观测性（metrics/health/log 格式）几乎空白
向量检索、tokenizer、embedding 维度等关键实现细节缺失
非 admin mock user / graph_migrator / state 大小上限等"演进锚点"未设
```

---

## 3. 一致性问题

| Issue | 描述 | 涉及文档 | 严重度 | 补丁 |
|---|---|---|---|---|
| **C1** | `workflow_runs.status` 在总设计列 8 种，ER+SQL 只有 5 种 | design v1 §5.3, ER §5.2, SQL line 79 | 中 | consistency §3.1 |
| **C2** | `knowledge_base_ids` 在 API 是数字 ID，在节点协议/示例是 `"kb_001"` 字符串 | api_design §5, node_protocol §13.5, samples §3 | **高** | consistency §3.2 |
| **C3** | 节点 ID 生成约定多套：`node_xxx` / `type_xxx` / `llm_abc123` / `llm_1` | node_protocol §5.1, frontend §7.2, samples | 中 | consistency §3.3 |
| **C4** | Branch Node 的 target 是否必须在 Graph 的 edges 中存在，三处都写"建议" | runtime §4.3 §15.2, node_protocol §13.7 | **高** | consistency §3.4 |
| **C5** | 总设计 §6.1 节点类目把 Memory/Database/Loop 列在"必须类目"，MVP 范围把它们排除 | design v1 §6.1 vs mvp_scope §6.2 | 低 | consistency §3.5 |

---

## 4. 协议语义模糊点

| Issue | 描述 | 影响 | 补丁 |
|---|---|---|---|
| **S1** | **config 内 `{{...}}` 的解析上下文未定义**。示例里 `config.query = {{question}}` 引用的是 `input_mapping` 解析后的 `node_input.question`，但 Runtime 文档没有显式说明"config 解析时上下文 = state + node_input"。实现者大概率会写错 | **高** | consistency §4.1 |
| **S2** | Output Node 的 `config.outputs` + `output_mapping: { "outputs": "outputs" }` 双重抽象冗余 | 中 | consistency §4.2 |
| **S3** | 变量类型边缘 case 未定义：`null` 嵌入字符串、`bool` 转字符串大小写、循环对象、Date | 中 | consistency §4.3 |
| **S4** | `condition.right` 的类型推断：字面值 `"10"` 是字符串还是数字？需要类型化比较规则 | 中 | consistency §4.4 |
| **S5** | `enabled: false` 的语义未定义：跳过执行/skip/连通性如何处理 | 低 | consistency §4.5 |

---

## 5. 设计缺失

### 5.1 安全/治理

| Issue | 描述 | 补丁 |
|---|---|---|
| **G1** | Secret 加密算法/master key/轮转策略未定义 | security §2 |
| **G2** | LLM Prompt Injection 防护策略空白 | security §3 |
| **G3** | API Node SSRF/内网访问限制清单未给出 | security §4 |
| **G4** | Trace PII 脱敏的正则/规则列表缺失 | security §5 |
| **G5** | `model_providers` 与 `secrets` 的关联字段缺失 | security §6 |

### 5.2 可观测性/运维

| Issue | 描述 | 补丁 |
|---|---|---|
| **G6** | 缺 `/metrics` Prometheus 端点定义 | observability §3 |
| **G7** | `/health` 与 `/ready` 未分离 | observability §2 |
| **G8** | 日志格式（JSON vs logfmt）未约束 | observability §4 |
| **G9** | `workflow_runs.state_json` 大小上限/告警阈值未设 | observability §5 |
| **G10** | 单 workflow_run 的 token budget / max_llm_calls 兜底未设 | observability §6 |
| **G13** | 错误码完整字典 + retryable 默认值未集中维护 | observability §7 |

### 5.3 实现细节

| Issue | 描述 | 补丁 |
|---|---|---|
| **G11** | pgvector 检索 SQL 模板未给 | implementation §2 |
| **G12** | embedding 维度演进策略未给（SQL 硬编码 1536） | implementation §3 |
| **G14** | `chunk_size_tokens` 用什么 tokenizer 未指定 | implementation §4 |
| **G15** | 异步运行的 trace 增量推送方式未规划（短轮询无增量参数） | implementation §5 |
| **G16** | 上传文件大小/类型白名单具体值未定 | implementation §6 |
| **G17** | `audit_logs.action` 枚举未列出 | implementation §7 |
| **G18** | 节点级事务边界未明 | implementation §8 |
| **G19** | 重试时 input_mapping 是否重新解析未明 | implementation §8 |
| **G20** | 并发同一 workflow 多个 run 的隔离性未明示 | implementation §8 |

---

## 6. 潜在风险

| Risk | 描述 | 处理 |
|---|---|---|
| **R1** | Branch target 不强制在 edges 中存在 → 前端可视化路径丢失 | 见 C4 |
| **R2** | pgvector HNSW 在大数据量时构建慢，文档"可不建"会埋雷 | implementation §3 |
| **R3** | mock user 永远 admin，PermissionService 在 MVP 是空 check，权限边界无验证 | security §7 |
| **R4** | workflow_versions 不可变 + schema_version 演进，但缺 graph_migrator | implementation §9 |
| **R5** | API Node 重试对非幂等 POST 危险，文档承认但无 mitigation | security §8 |

---

## 7. Issue 优先级矩阵

按"动手实施前必须解决"程度排序：

### 7.1 Must-fix（实施前必须收口）

```text
C2 - knowledge_base_ids 类型统一（前后端契约硬伤）
C4 - Branch target 与 edges 关系强制（图校验/可视化基石）
S1 - config 内变量解析上下文定义（实现极易写错）
G1 - Secret 加密算法（生产前必须有具体方案）
G6 - /metrics 端点（部署到测试环境就需要）
G13 - 错误码字典（前后端联调必要物）
G17 - audit action 枚举（落库前要冻结）
R3 - 增加非 admin mock user（权限路径要被覆盖）
```

### 7.2 Should-fix（MVP 第一次发布前收口）

```text
C1, C3, C5 - 其他一致性
S2, S3, S4 - Output Node 简化、类型边缘、Branch 类型比较
G2, G3, G4, G5 - 安全治理细节
G7, G8, G9, G10 - 观测/运维基础
G11, G12, G14, G18, G19, G20 - 实现细节
R5 - API Node 重试警示
```

### 7.3 Nice-to-have（MVP 后第一个迭代收口）

```text
S5 - enabled 语义
G15 - 增量 trace 推送
G16 - 文件限制（先 hard-code，后做可配置）
R2 - HNSW 索引策略
R4 - graph_migrator 框架
```

---

## 8. 推荐处理顺序

```text
Step 1: 合并 consistency_patches_v0.1_claude.md 中 Must-fix 的 5 项到原文档
        (C2, C4, S1) 必须前后端、前后端、Runtime 三方都达成共识

Step 2: 实施前阅读 security_design_v0.1_claude.md 全文
        建立 Secret/SSRF/PII redaction 的"出厂安全基线"

Step 3: 实施期对照 observability_runbook_v0.1_claude.md 
        在 Milestone 0 项目初始化时就把日志格式、健康检查、metrics 一次性接好

Step 4: 实施 Runtime 时对照 implementation_details_v0.1_claude.md
        变量解析、向量检索 SQL、事务边界这些都是"写错难发现"的细节

Step 5: 进入测试环境前回顾 Should-fix 清单逐项确认

Step 6: MVP 完成后启动 Nice-to-have 改进，作为 v0.2 准备工作
```

---

## 9. 结论

当前设计文档已经达到 **"实施级"水平**，绝大多数实施团队拿到这套文档可以开始动手。本评审发现的 35 个 issue 中：

```text
8  个 Must-fix     建议在 Milestone 0 之前的"协议冻结"阶段统一收口
20 个 Should-fix   在 MVP 各 Milestone 实施中逐步处理
7  个 Nice-to-have 作为 v0.2 改进
```

特别需要强调的两条：

```text
1. C2 / C4 / S1 是"前后端契约硬伤"，不处理会让前端、后端、Runtime 各走各的路
2. R3（mock user 全 admin）会让权限校验代码在 MVP 阶段从未被验证；
   只要 seed 一个 viewer 角色测试账号，就能强制覆盖这条代码路径
```

后续详细修订内容见同目录下的 4 份补丁文档。
