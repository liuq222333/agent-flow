# 一致性与语义补丁 v0.1

## 0. 文档说明

本文档逐项处理 `design_review_v0.1_claude.md` 中的 C1-C5（一致性）与 S1-S5（协议语义）。每个 issue 给出：

```text
问题描述
影响范围
推荐解决方案
具体修订位置（哪份文档、哪节）
建议的新文本
```

建议把这些修订合并回原文档而不是新增另一套，避免文档分歧再扩大。

---

## 1. 通用约定

为了让后续补丁可直接落地，先约定两条贯穿整个补丁的命名/类型公约。

### 1.1 ID 体系约定

```text
所有业务表主键：BIGINT（数据库自增）
所有节点 id (Graph 内)：字符串，格式 {type}_{nanoid8}
所有边 id (Graph 内)：字符串，格式 e_{nanoid8}
所有 secret_key (引用)：字符串，蛇形小写
跨实体外部引用（如 graph_json 中引用 knowledge_base）：数字，对应 DB 主键
```

### 1.2 类型对齐约定

```text
ER/SQL 是单一事实源
其它文档示例中的 ID 必须与之类型匹配
JSON 中即使是 BIGINT 也写成数字字面值，而非字符串
```

---

## 2. C1：workflow_runs.status 范围统一

### 2.1 问题

- 总设计文档 §5.3 列了 8 种 status：pending / running / waiting_for_user / waiting_for_approval / completed / failed / cancelled / paused
- ER 文档 §5.2、SQL 第 79 行约束只有 5 种：pending / running / completed / failed / cancelled

### 2.2 影响

- 阅读总设计文档的开发者会以为 MVP 要实现 waiting_for_user / paused，浪费精力
- 这两组状态对应的字段（resumed_at、pause_reason 等）也跟着出现/缺失，引发后续混乱

### 2.3 推荐方案

**保持 SQL/ER 的 5 状态为 MVP 实现，在总设计中显式标注哪些是 v0.2/v0.3 的预留。**

### 2.4 修订位置

文件：`agent_workflow_platform_design_v_1 (1).md`
位置：§5.3 "运行状态" 列表

### 2.5 建议新文本

```markdown
运行状态：

MVP 实现：
```text
pending
running
completed
failed
cancelled
```

v0.2 预留（Human Approval / Info Collection 加入后）：
```text
waiting_for_user
waiting_for_approval
paused
```

注意：CHECK 约束在 MVP 阶段只允许 MVP 5 种值；预留状态需要在引入对应节点时配合 migration 放开约束。
```

---

## 3. C2：knowledge_base_ids 类型统一（**Must-fix**）

### 3.1 问题

- API 设计 `POST /knowledge-bases` 返回 `id: 101`（数字）
- 节点协议 §13.5 示例 `"knowledge_base_ids": ["kb_001"]`（字符串）
- 示例工作流 §3.2 直接说"如果数据库 ID 使用数字，实际运行时把 kb_001 替换为对应 ID 字符串或数字，前后端保持一致即可"——把决策延后，会让前后端各走一条路

### 3.2 影响

- 前端编辑器把 `knowledge_base_ids` 当成字符串数组，KnowledgeBaseNodeExecutor 用数字查库，要么强转要么报错
- 多人协作时 graph_json 在不同 workflow_version 中既有字符串又有数字，运维灾难

### 3.3 推荐方案

**统一为数字 BIGINT，与 DB 主键类型一致。** 前端展示如果需要 "kb_001" 这样的 slug 形式，单独加 `slug` 字段。

### 3.4 修订位置

#### 3.4.1 节点协议文档 §13.5（Knowledge Base Node）

将所有 `"knowledge_base_ids": ["kb_001"]` 改为 `"knowledge_base_ids": [101]`。

#### 3.4.2 示例工作流文档 §3

将 `kb_001` 替换为示例 ID 数字 `101`，并删除 §3.2 中那段"前后端保持一致即可"的妥协说法。

#### 3.4.3 节点协议文档新增一条规则

```markdown
## 6.5 引用类型规则

graph_json 中跨实体引用的字段（knowledge_base_ids、tool_id、model_provider_id、model_config_id）
必须使用对应数据库主键的数字类型 BIGINT。

不允许使用字符串 slug 或 UUID。

如果未来引入 slug 显示需求，应在对应表上新增 slug 字段，前端展示用 slug，
graph_json 仍存数字 ID。
```

### 3.5 知识库表补充建议

如确实希望保留 `kb_001` 这种人类可读 ID，建议给 `knowledge_bases` 加：

```sql
ALTER TABLE knowledge_bases
  ADD COLUMN slug VARCHAR(64);

CREATE UNIQUE INDEX uk_knowledge_bases_slug
  ON knowledge_bases(slug)
  WHERE deleted_at IS NULL;
```

但 graph_json 中**仍然只保存数字 ID**，slug 只用于前端展示和导入导出。

---

## 4. C3：节点 ID/边 ID 生成规范

### 4.1 问题

文档中节点 ID 多套约定：

```text
node_protocol §5.1   "推荐格式：node_xxx 或 type_xxx"
frontend §7.2        "llm_abc123"（随机后缀，长度未定）
samples              "llm_1"（递增数字）
```

### 4.2 影响

- 前端拖拽创建节点时，不同实现会给出不同 ID 格式
- 同一 workflow_version 内可能混用，看起来很乱
- 复制工作流时 ID 冲突难以预防

### 4.3 推荐方案

```text
节点 id 格式：{type}_{nanoid8}      例：llm_4kx9mPq2
边   id 格式：e_{nanoid8}            例：e_7zR1aS3w
```

- 使用 8 字符 nanoid（base64url 字母数字，无歧义字符）
- 由前端生成，保存时后端只校验唯一性
- 复制工作流时**全部 ID 重新生成**

### 4.4 修订位置

#### 4.4.1 节点协议文档 §5.1（id）

```markdown
## 5.1 id

节点唯一 ID。

要求：

```text
同一个 workflow_version 内唯一
前端创建节点时生成
发布后不可变
格式：{type}_{nanoid8}，例：llm_4kx9mPq2
nanoid 字母表：0-9A-Za-z，长度 8
不允许包含连字符、空格或大小写敏感冲突字符
```

边 ID 同理：

```text
边 ID 格式：e_{nanoid8}
```
```

#### 4.4.2 前端编辑器文档 §6.1

```markdown
节点生成器：

```typescript
import { customAlphabet } from "nanoid";
const nanoid = customAlphabet("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz", 8);

function newNodeId(type: string) {
  return `${type}_${nanoid()}`;
}
function newEdgeId() {
  return `e_${nanoid()}`;
}
```

复制工作流时调用 remapAllIds(graph)，重新生成所有节点和边的 id，同时更新：
- edges[].source
- edges[].target
- branch.target
- 任何变量引用中如出现 node id（MVP 没有）
```

#### 4.4.3 示例工作流文档说明

在示例工作流文档开头加一行：

```markdown
注：示例中的节点 ID（如 llm_1、kb_1）只为可读性使用简短形式，
实际运行时由前端按 {type}_{nanoid8} 规则生成。
```

---

## 5. C4：Branch target 与 edges 关系（**Must-fix**）

### 5.1 问题

文档三处都写"建议"：

- `node_protocol §13.7`：未明确
- `runtime §4.3`：Branch target 建议同时存在对应出边
- `runtime §15.2`：如果 Graph 中维护了 Branch 出边，target 建议必须在出边列表中

### 5.2 影响

如果 target 在 edges 中**不必存在**：

- 前端画布画不出分支路径（用户看到的 Graph 与运行实际路径不一致）
- Validator 无法静态检测"Branch 指向不存在的节点"
- Trace 视图无法在画布上回放执行路径

### 5.3 推荐方案

**Branch Node 的每个 target（含 default）必须有对应 edge，且 edge.source = Branch Node 的 id，edge.target = target 节点的 id。** 这是图校验的硬约束。

### 5.4 修订位置

#### 5.4.1 节点协议文档 §13.7（Branch Node）

在示例后追加约束：

```markdown
## 13.7.1 Branch Node 与 edges 的关系

约束（强制，发布前必须满足）：

```text
1. Branch Node 的每个 branches[].target 必须在 graph.nodes 中存在
2. 必须有一条 edge，其 source = Branch Node id，target = branches[].target
3. default 分支也必须有对应 edge
4. Branch Node 不允许通过非 branches[].target 出边到达其它节点
   （即所有出边都应能映射回某个 branch.target）
5. 同一 target 可以被多个 branch 复用，对应一条 edge 即可
```

edge 上可选维护 `meta.branch_id` 字段，方便前端绘制 label：

```json
{
  "id": "e_branch_refund",
  "source": "branch_1",
  "target": "llm_refund_1",
  "meta": { "branch_id": "branch_refund" }
}
```
```

#### 5.4.2 GraphValidator 文档 §10

在校验规则列表中**加入**：

```text
Branch Node 的每个 branches[].target 必须存在于 nodes
Branch Node 的每个 branches[].target 必须有对应 edge（source=Branch, target=branches[].target）
Branch Node 的所有出边必须能映射回某个 branches[].target
```

#### 5.4.3 Runtime 文档 §15.2

将"建议"改为"必须"：

```markdown
Branch Node 的 NodeExecutor 返回 target
Runtime 根据 target 找到下一节点
target 必须存在于 nodes
target 必须有对应 edge（在 GraphValidator 中已强制）
Runtime 仅做运行时再次校验，校验失败抛 branch_target_not_found
```

---

## 6. C5：节点类目与 MVP 边界对齐

### 6.1 问题

- 总设计 §6.1 把 Memory Read/Write、Database、Loop、Info Collection 等列在"必须类目"
- MVP 范围明确这些节点 v0.2 才加

### 6.2 推荐方案

在总设计 §6.1 表头加 MVP 标记，每个节点后标注：

```text
MVP    第一版必须实现
v0.2   第二版加入
v0.3   第三版加入
v1.0+  平台化阶段加入
```

### 6.3 修订位置

文件：`agent_workflow_platform_design_v_1 (1).md`
位置：§6.1 节点分类列表

### 6.4 建议新文本片段

```markdown
### 输入输出类

```text
Start Node                MVP
Input Node                MVP
Output Node               MVP
Message Node              MVP
Info Collection Node      v0.2
Form Node                 v0.3
```

### AI 类

```text
LLM Node                  MVP
Intent Recognition Node   MVP
Text Classification Node  v0.3
Extractor Node            v0.3
Summarizer Node           v0.3
Prompt Template Node      v0.3
```

### 知识类

```text
Knowledge Base Retrieve Node    MVP
Document Loader Node             v0.3
Vector Search Node               v0.3
Rerank Node                      v0.3
Citation Node                    v0.3
```

(其他类目类似)
```

---

## 7. S1：config 内变量解析上下文（**Must-fix**）

### 7.1 问题

节点协议示例中存在"二级引用"：

```json
{
  "input_mapping": {
    "question": "{{input.user_query}}"
  },
  "config": {
    "query": "{{question}}"
  }
}
```

- 第一行：从 state 解析得到 `node_input.question`
- 第二行：`{{question}}` 引用的是 `node_input.question`，不是 state.question

但 Runtime 文档没有显式说明"config 中的 `{{...}}` 解析时，上下文 = state + node_input"。**实现者只看 VariableResolver 文档，会以为所有 `{{...}}` 都只查 state。**

### 7.2 影响

- LLM Node 的 user_prompt 中所有 `{{xxx}}` 全部解析失败
- 实施期至少要花半天定位

### 7.3 推荐方案

**显式区分两种解析时机和上下文：**

```text
Phase 1 - resolve_input_mapping:
  输入：node.input_mapping
  上下文：state（input/variables/messages/outputs/metadata/secrets）
  产出：node_input

Phase 2 - resolve_config:
  输入：node.config（递归扫描所有字符串字段中的 {{...}}）
  上下文：node_input（优先） + state（fallback） + secrets
  产出：resolved_config

执行节点：executor.execute(node, node_input, resolved_config, state, context)
```

变量解析优先级（同名时谁覆盖谁）：

```text
node_input.xxx        > state.variables.xxx
state.input.xxx       > state.variables.xxx
secrets.xxx           只在服务端、只在 config/headers/body 中可引用
```

### 7.4 修订位置

#### 7.4.1 节点协议文档新增 §6.5（变量解析时机与作用域）

```markdown
## 6.5 变量解析时机与作用域

节点执行过程有两次变量解析：

### 6.5.1 解析 input_mapping

时机：节点开始执行前。
输入：node.input_mapping 中的每个值（含 {{...}}）。
上下文：state 全域，含 input / variables / messages / outputs / metadata。
**不可引用** node_input（此时还不存在）。
**不可引用** secrets（input_mapping 用途是业务变量传递，不应承担密钥下发）。

### 6.5.2 解析 config

时机：input_mapping 解析完成后、调用 NodeExecutor 前。
输入：node.config 中所有字符串字段（递归）中的 {{...}}。
上下文（优先级从高到低）：
1. node_input（input_mapping 解析后的结果）
2. state.input / state.variables / state.outputs / state.messages / state.metadata
3. secrets（仅服务端解析，仅允许在 config 中引用；Trace 写入前由 Redactor 移除）

不允许在 config 中引用 metadata 之外的 state 子树中含 secret 的字段。

### 6.5.3 解析 output 路径

output_mapping 的 value 是写入路径，**不解析 {{...}}**。
Output Node 的 config.outputs 中的 {{...}} 与上述 §6.5.2 规则一致。
```

#### 7.4.2 Runtime 文档 §10 / §11 更新

将"input_mapping 处理"与"config 解析"显式拆为两步，伪代码：

```python
def execute_node(node, state, context):
    # Phase 1
    node_input = variable_resolver.resolve(
        node.input_mapping,
        scopes={"state": state}
    )

    # Phase 2
    resolved_config = variable_resolver.resolve(
        node.config,
        scopes={"node_input": node_input, "state": state, "secrets": context.secrets}
    )

    # Execute
    output = executor.execute(node, node_input, resolved_config, state, context)
    return output
```

---

## 8. S2：Output Node 双重 mapping 简化

### 8.1 问题

当前协议：

```json
{
  "type": "output",
  "config": {
    "outputs": {
      "answer": "{{variables.answer}}"
    }
  },
  "output_mapping": {
    "outputs": "outputs"
  }
}
```

`config.outputs` 已经声明输出，`output_mapping` 又重复写回，纯冗余。

### 8.2 推荐方案

**Output Node 不需要 output_mapping。** OutputNodeExecutor 把 `resolved_config.outputs` 直接写入 `state.outputs`（merge）。

### 8.3 修订位置

节点协议文档 §13.10，简化为：

```markdown
## 13.10 Output Node

用途：生成最终输出。

config schema：

```json
{
  "outputs": {
    "answer": "{{variables.answer}}",
    "sources": "{{variables.kb_context}}"
  }
}
```

完整节点示例：

```json
{
  "id": "output_1",
  "type": "output",
  "name": "最终输出",
  "config": {
    "outputs": {
      "answer": "{{variables.answer}}",
      "sources": "{{variables.kb_context}}"
    }
  }
}
```

特殊规则：

```text
Output Node 不使用 output_mapping
OutputNodeExecutor 把 resolved_config.outputs 整体合并到 state.outputs
合并语义：浅合并，同名键覆盖
```
```

Message Node 同理也可简化（output_mapping 固定为 messages），但 Message Node 当前的 output_mapping 写法已足够清晰，建议保留。

---

## 9. S3：变量类型边缘 case

### 9.1 推荐规则

#### 9.1.1 完整变量引用（整个字段就是一个 `{{xxx}}`）

```text
保留原始类型
null → null
undefined / 缺失 → 抛 variable_not_found 错误
```

#### 9.1.2 嵌入字符串中的变量引用

| 原值类型 | 转字符串规则 |
|---|---|
| string | 原样拼接 |
| number | JSON 数字（含小数点） |
| boolean | "true" / "false" |
| null | "" 或抛错（由 STRICT_NULL_IN_STRING 配置决定，MVP 默认抛错） |
| array / object | `JSON.stringify`，紧凑（无空格、无换行） |
| Date | ISO 8601 |
| 循环对象 | 抛 invalid_variable_value 错误 |

#### 9.1.3 大小限制

```text
单个变量引用解析后字符串长度 > 1MB：抛 variable_too_large 错误
（避免一个引用把 prompt 撑爆）
```

### 9.2 修订位置

节点协议文档 §6.3 替换为上表。同样的内容在 Runtime 文档 §9.3 也要同步。

---

## 10. S4：Branch 类型化比较规则

### 10.1 问题

```json
{
  "condition": {
    "left": "{{variables.intent_result.intent}}",
    "operator": "eq",
    "right": "refund_request"
  }
}
```

- `left` 是字符串变量引用，解析后是字符串 "refund_request"
- `right` 是字符串字面值 "refund_request"
- eq 直接字符串比较，OK

但：

```json
{
  "condition": {
    "left": "{{variables.order.amount}}",
    "operator": "gt",
    "right": "100"
  }
}
```

- `left` 是数字 199
- `right` 是字符串 "100"
- gt 比较时 199 > "100" 在不同语言中行为不同

### 10.2 推荐规则

```text
1. left 解析后保留原始类型
2. right 字面值类型：
   - 数字字面值（无引号或显式 number）：number
   - "true" / "false"（小写）：boolean
   - "null"：null
   - 其它字符串：string
   - 数组/对象：原样

3. 比较前对齐类型：
   - eq / neq：类型不一致 → 直接 false（不报错）
   - gt / gte / lt / lte：类型不一致 → 抛 type_mismatch
   - contains：
     - left 字符串，right 字符串：substring 包含
     - left 数组，right 任意：数组成员包含
     - 其它：抛 type_mismatch
   - exists / not_exists：忽略 right，检查 left 解析时是否报 variable_not_found
```

为避免歧义，建议前端在配置 Branch 时：

```text
- right 字段提供"类型"下拉：string / number / boolean / null / variable
- 选 variable 时让用户填变量引用路径
```

### 10.3 修订位置

节点协议文档 §13.7 在 condition 规则下追加"类型化比较"小节。

---

## 11. S5：enabled 字段语义

### 11.1 推荐语义

MVP 阶段：**enabled 字段保留在 schema 中，但发布版本中不允许出现 enabled: false。**

```text
草稿模式：允许 enabled: false
发布前：GraphValidator 强校验，发现 enabled: false 则报 disabled_node_in_publish
发布版本：每个节点都视为 enabled
```

v0.2 引入禁用语义时：

```text
enabled: false 的节点视为透明节点
入边的 source → 自动指向该节点的所有出边的 target
（即"短路"）
连通性检查时该节点不算节点
```

### 11.2 修订位置

节点协议文档 §5.12 替换为：

```markdown
## 5.12 enabled

节点是否启用。

```json
{
  "enabled": true
}
```

MVP 阶段语义：

```text
默认值：true
草稿模式允许设为 false
发布时 GraphValidator 强校验，发现 enabled: false 报 disabled_node_in_publish
发布版本节点必须 enabled = true
```

v0.2+ 将引入"透明节点"语义，此处不展开。
```

---

## 12. 修订执行清单

| Issue | 修订文件 | 章节 | 修订类型 |
|---|---|---|---|
| C1 | design_v_1 (1).md | §5.3 | 改写 |
| C2 | node_protocol.md, samples.md | §13.5, §3 | 全文替换 ID |
| C2 | node_protocol.md | 新增 §6.5 | 新增小节 |
| C3 | node_protocol.md, frontend.md, samples.md | §5.1, §6.1, 开头 | 改写 + 新增 |
| C4 | node_protocol.md, runtime.md | §13.7, §15.2 | 改写 + 强约束 |
| C4 | backend_structure.md GraphValidator | §10 | 校验规则补 |
| C5 | design_v_1 (1).md | §6.1 | 表格加 MVP 标记 |
| S1 | node_protocol.md | 新增 §6.5 | 新增小节 |
| S1 | runtime.md | §10, §11 | 拆解为两 phase |
| S2 | node_protocol.md | §13.10 | 简化 |
| S3 | node_protocol.md, runtime.md | §6.3, §9.3 | 替换为类型矩阵 |
| S4 | node_protocol.md | §13.7 | 新增类型化比较 |
| S5 | node_protocol.md | §5.12 | 改写 |

---

## 13. 结论

13 项修订全部完成后：

```text
前后端契约统一（C2、C3、C4）
Runtime 变量解析语义清晰（S1、S2、S3、S4）
设计文档内部不再自相矛盾（C1、C5）
为 v0.2 预留正确的扩展点（S5、C5）
```

特别是 C2、C4、S1 三项 Must-fix，**必须在 Milestone 0 启动开发前完成修订**，否则在 Runtime 实施期会反复返工。
