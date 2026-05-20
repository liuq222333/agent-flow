# Workflow 发布与本地代码生成链路增强设计

## 1. 背景

当前平台已经具备从 Workflow 草稿发布到本地 generated workflow code，再由 Runtime import `workflow.py` 执行的基础闭环：

```text
draft_graph_json
  -> POST /workflows/{workflow_id}/publish
  -> workflow_versions.graph_json
  -> backend/generated_workflows/workflow_xxxxxx/vxxxxxx/workflow.py
  -> workflow_runs.metadata_json.code_path_at_run / code_hash_at_run / code_modified
  -> import workflow.py
  -> workflow.run(input_data, context)
```

这条链路的方向是正确的：发布版本不可变，运行绑定具体版本，运行时以本地生成代码为准，并记录本地代码 hash 是否偏离发布记录。

后续优化目标不是引入复杂的部署系统，而是在本地优先的 MVP 架构下，让发布、生成、查看、清理、运行和排障体验变得更完整、更可信。

## 2. 目标

### 2.1 产品目标

- 发布后用户能明确看到“当前线上版本是什么、对应代码在哪、hash 是否一致”。
- 用户能直接查看某个发布版本对应的 `workflow.py`。
- 如果本地生成代码被修改，运行前能明确提示，Trace 中能留下证据。
- 如果生成目录出现临时残留、孤儿版本或文件缺失，系统能给出可理解的状态，并提供清理或重建能力。
- 发布过程要尽量原子：不能留下 DB 已发布但代码不可用的半成品状态。

### 2.2 工程目标

- 保持 `workflow_versions` 作为不可变发布记录。
- 保持 Runtime 默认 import `workflow_versions.code_path` 指向的本地文件。
- 所有文件路径必须被限制在 `backend/generated_workflows` 下。
- 清理逻辑只删除 DB 未引用的生成目录和临时目录。
- API 返回结构稳定，前端不直接推断文件系统状态。
- 新增行为有测试覆盖，尤其是失败和并发场景。

## 3. 非目标

- 不引入远端制品仓库、对象存储或 Kubernetes 部署机制。
- 不实现完整 CI/CD 发布流水线。
- 不把 generated workflow code 作为用户长期手写代码的主编辑界面。
- 不在 MVP 阶段支持版本差异可视化 diff。
- 不更改 Workflow graph schema 的核心结构。

## 4. 当前状态

### 4.1 已有能力

- 发布 API 会校验草稿 graph，创建 `workflow_versions`，生成本地代码，并更新 `workflows.current_version_id`。
- 生成目录格式：

```text
backend/generated_workflows/
  workflow_000001/
    v000001/
      __init__.py
      workflow.py
      manifest.json
```

- 生成代码固定暴露：

```python
async def run(input_data: dict[str, Any], context) -> dict[str, Any]:
    return await context.execute_graph(GRAPH, input_data)
```

- Runtime 会读取 `code_path`，计算实际 hash，并写入 run metadata：

```json
{
  "runtime": "generated_workflow",
  "code_path_at_run": "...",
  "code_hash_at_run": "sha256:...",
  "code_modified": false
}
```

### 4.2 已补强能力

- 生成代码先写入临时目录，再移动到最终版本目录。
- 版本详情可检查本地代码状态：
  - `code_hash_actual`
  - `code_modified`
  - `code_status`
- 版本代码可通过 API 查看。
- generated workflow 目录可清理未引用版本和临时目录。
- 前端版本面板可展示 hash 状态、查看代码、触发清理。
- 运行前会刷新 hash 状态，发现本地代码变更时提示确认。

## 5. 设计原则

### 5.1 DB 是发布事实来源

`workflow_versions` 是发布记录的事实来源。生成目录只是版本代码的本地制品缓存。

```text
workflow_versions.graph_json      不可变发布图
workflow_versions.code_path       本地代码路径
workflow_versions.code_hash       发布时 workflow.py hash
workflow_versions.code_generated_at  代码生成时间
```

### 5.2 本地代码是运行事实来源

运行时不重新解释 `graph_json`，而是 import 本地 `workflow.py`。如果本地代码被手动修改，运行仍可以继续，但必须记录：

```text
published code_hash != actual code_hash
=> code_modified = true
```

### 5.3 清理不能误删 DB 引用版本

清理功能必须先读取 DB 中所有非空 `workflow_versions.code_path`，转换为版本目录集合，再删除未引用目录。

### 5.4 发布失败不能留下可见半成品

发布过程中的任何失败都应该满足：

- 不更新 `workflows.current_version_id`。
- 不创建对用户可见的 `workflow_versions` 发布记录。
- 不留下最终版本目录。
- 临时目录允许短暂残留，但 cleanup 必须能删除。

## 6. 后端设计

## 6.1 核心模块

### 6.1.1 `workflow_codegen.py`

职责：

- 生成 `workflow.py` 和 `manifest.json`。
- 计算发布 hash。
- 检查本地代码状态。
- 读取版本代码源码。
- 清理 generated workflow 目录。
- 解析并保护 generated workflow 路径。

建议保留的核心函数：

```python
generate_workflow_code(...)
inspect_workflow_code(...)
read_workflow_code_source(...)
cleanup_generated_workflow_dirs(...)
resolve_generated_code_path(...)
remove_generated_workflow_version(...)
```

### 6.1.2 `workflows.py`

职责：

- 发布事务编排。
- 版本查询和代码查询。
- 补生成缺失代码。
- 清理 API 的业务层封装。
- run 前确保版本代码存在。

### 6.1.3 `runtime.py`

职责：

- 加载本地 `workflow.py`。
- 校验 `run` 入口。
- 执行 generated workflow。
- 将 code metadata 写入 run。

## 6.2 发布流程

推荐发布顺序：

```text
1. BEGIN DB transaction
2. SELECT workflow FOR UPDATE
3. validate graph with mode=publish
4. calculate next version number
5. calculate graph_hash
6. generate code into temp dir
7. compile generated source
8. write manifest
9. calculate code_hash
10. atomic rename temp dir to final version dir
11. INSERT workflow_versions
12. UPDATE workflows.current_version_id / status
13. write audit log
14. COMMIT
15. on exception remove final version dir if it was created
```

### 6.2.1 原子性细节

文件系统和 DB 事务无法天然做到跨资源原子。设计上采用补偿策略：

- DB 失败时删除本次生成的最终版本目录。
- 文件生成失败时抛错，DB 事务自然回滚。
- 进程崩溃时可能留下临时目录，后续 cleanup 删除。
- 如果最终版本目录已存在，但 DB 没引用，应判定为 orphan，允许 cleanup 后重试。

### 6.2.2 版本号并发

发布需要对 workflow 行加锁：

```sql
SELECT *
FROM workflows
WHERE id = :workflow_id AND deleted_at IS NULL
FOR UPDATE
```

同一个 workflow 的并发发布会串行化。版本号继续用：

```sql
SELECT COALESCE(max(version), 0) + 1
FROM workflow_versions
WHERE workflow_id = :workflow_id
```

唯一约束 `UNIQUE (workflow_id, version)` 作为最后防线。

## 6.3 发布前后 Preflight

### 6.3.1 发布前 Preflight

发布前检查 graph：

- 必须有 start 节点。
- 必须有 end 节点。
- 必须所有连线 source/target 有效。
- 必须从 start 可达 end。
- publish 模式下阻止孤儿节点。

### 6.3.2 代码 Preflight

生成代码后，在移动到最终目录前做：

```text
compile(workflow_source, "workflow.py", "exec")
```

移动到最终目录后，可选做 import preflight：

```text
import workflow.py with isolated module name
assert inspect.iscoroutinefunction(module.run)
```

建议阶段 1 只做 compile，阶段 2 再加 import preflight。原因是 import 会执行顶层代码，当前生成代码较安全，但以后生成更丰富代码后要格外小心。

## 6.4 版本详情 API

### 6.4.1 查询版本详情

```http
GET /api/v1/workflow-versions/{version_id}
```

响应建议：

```json
{
  "id": 10,
  "workflow_id": 1,
  "version": 3,
  "schema_version": "1.0",
  "graph_hash": "sha256-or-raw-graph-hash",
  "graph_json": {},
  "code_path": "backend/generated_workflows/workflow_000001/v000003/workflow.py",
  "code_hash": "sha256:published",
  "code_hash_actual": "sha256:actual",
  "code_modified": false,
  "code_status": "ok",
  "code_generated_at": "2026-05-18T08:30:00Z",
  "release_note": "release note",
  "created_at": "2026-05-18T08:30:00Z"
}
```

`code_status` 枚举：

```text
ok                 文件存在，hash 与发布记录一致
modified           文件存在，hash 与发布记录不一致
missing_file       code_path 有值，但本地文件不存在
missing_metadata   code_path 为空
invalid_path       code_path 不在 generated_workflows 下
```

### 6.4.2 查询版本代码

```http
GET /api/v1/workflow-versions/{version_id}/code
```

响应建议：

```json
{
  "id": 10,
  "workflow_id": 1,
  "version": 3,
  "schema_version": "1.0",
  "code_path": "backend/generated_workflows/workflow_000001/v000003/workflow.py",
  "code_hash": "sha256:published",
  "code_hash_actual": "sha256:actual",
  "code_modified": false,
  "code_status": "ok",
  "code_generated_at": "2026-05-18T08:30:00Z",
  "source": "from __future__ import annotations\n..."
}
```

错误：

```text
404 workflow_code_missing
400 workflow_code_invalid_path
```

## 6.5 重新生成版本代码

### 6.5.1 需求

当发布记录存在，但本地 `workflow.py` 缺失时，用户应能从不可变 `workflow_versions.graph_json` 重新生成该版本代码。

### 6.5.2 API

```http
POST /api/v1/workflow-versions/{version_id}/regenerate-code
```

请求：

```json
{
  "force": false
}
```

行为：

- `force=false`：
  - 如果代码状态是 `ok` 或 `modified`，拒绝覆盖。
  - 如果代码状态是 `missing_file` 或 `missing_metadata`，允许生成。
- `force=true`：
  - 允许重新生成，但必须先把旧目录移到 quarantine 或删除未引用目录。
  - 如果旧代码是 modified，建议拒绝或要求二次确认。

响应：

```json
{
  "version_id": 10,
  "workflow_id": 1,
  "version": 3,
  "code_path": "backend/generated_workflows/workflow_000001/v000003/workflow.py",
  "code_hash": "sha256:new",
  "code_generated_at": "2026-05-18T09:00:00Z",
  "regenerated": true
}
```

### 6.5.3 注意事项

重新生成会改变 `workflow_versions.code_hash`，这和“发布版本不可变”有张力。

推荐策略：

- 默认只在 `code_path` 缺失或文件缺失时更新 code metadata。
- 如果本地文件存在且 hash modified，不允许静默覆盖。
- 记录 audit log：

```text
workflow_version.regenerate_code
```

## 6.6 generated_workflows 清理

### 6.6.1 API

```http
POST /api/v1/generated-workflows/cleanup?dry_run=true
POST /api/v1/generated-workflows/cleanup?dry_run=false
```

响应：

```json
{
  "dry_run": false,
  "removed_temp_dirs": [],
  "removed_orphan_version_dirs": [],
  "removed_empty_workflow_dirs": [],
  "kept_version_dirs": [],
  "removed_total": 0,
  "kept_total": 10
}
```

### 6.6.2 清理对象

允许删除：

- `.v000001.tmp-*`
- DB 未引用的 `workflow_xxxxxx/vxxxxxx`
- 删除孤儿版本后变空的 `workflow_xxxxxx`

禁止删除：

- DB 仍引用的版本目录。
- `backend/generated_workflows` 之外的任何目录。
- 非标准命名目录，除非后续加白名单规则。

### 6.6.3 前端交互

推荐分两步：

1. 点击“扫描”调用 `dry_run=true`。
2. 显示将删除的目录列表。
3. 用户确认后调用 `dry_run=false`。

当前 MVP 可以先保留“一键清理”，但后续应改为 dry-run first。

## 7. Runtime 设计

## 7.1 加载流程

```text
1. read workflow_versions.code_path/code_hash
2. resolve code_path under backend/generated_workflows
3. file exists check
4. calculate actual_hash
5. import workflow.py with module key based on path + actual_hash
6. validate async def run
7. update workflow_runs.metadata_json:
   - code_path_at_run
   - code_hash_at_run
   - code_modified
8. execute run(input_data, context)
```

## 7.2 hash 变更策略

### 7.2.1 dev 模式

允许运行 modified code，但必须记录：

```json
{
  "code_modified": true,
  "code_hash_at_run": "sha256:actual"
}
```

### 7.2.2 strict 模式

后续可增加配置：

```text
GENERATED_WORKFLOW_HASH_POLICY=warn|block
```

- `warn`：记录并允许运行。
- `block`：返回失败，不执行代码。

strict 模式适合 staging/prod。

## 7.3 错误码

建议统一错误码：

```text
workflow_code_missing          code_path 为空或本地文件缺失
workflow_code_invalid_path     code_path 不在 generated_workflows 下
workflow_code_import_failed    import workflow.py 失败
workflow_entrypoint_missing    缺少 async run(input_data, context)
workflow_code_hash_modified    strict 模式下 hash 不一致
workflow_code_regenerate_blocked 重新生成被策略阻止
```

## 8. 前端设计

## 8.1 版本代码面板

当前工作流上方显示：

```text
发布版本        v3
代码状态        Hash 一致 / Hash 已变更 / 文件缺失
生成时间        2026/5/18 09:00:00
Hash            sha256:xxxx
按钮            路径 / 代码 / 清理
```

展开详情：

```text
路径
完整发布 Hash
本地 Hash
Version ID
```

查看代码：

- 调用 `GET /workflow-versions/{id}/code`。
- 显示 `workflow.py`。
- 支持复制代码。
- 如果返回 `workflow_code_missing`，显示“文件缺失，可重新生成”。

## 8.2 版本列表

建议新增一个版本抽屉或右侧 tab：

```text
版本历史
  v5 current  ok        2026/5/18 10:00
  v4          modified  2026/5/18 09:30
  v3          ok        2026/5/18 09:00
```

每个版本可操作：

- 查看版本详情。
- 查看 `workflow.py`。
- 复制 code path。
- 用该版本运行。
- 如果缺失代码，重新生成。

## 8.3 发布后反馈

发布成功 toast/status line 应包含：

```text
已发布 v3 · code hash sha256:abcd1234 · workflow.py 已生成
```

如果发布失败：

```text
发布失败：代码生成失败，未更新线上版本
```

## 8.4 运行前提示

运行前刷新版本详情：

- `code_modified=false`：直接运行。
- `code_modified=true`：提示确认。
- `missing_file`：阻止运行，建议重新生成。
- `invalid_path`：阻止运行，提示联系开发者或检查 DB。

提示文案：

```text
当前版本的本地 workflow.py hash 与发布记录不一致。
继续运行会以本地代码为准，并在 Trace 中记录 code_modified=true。
```

## 8.5 Trace 展示

Trace 顶部应展示：

```text
runtime              generated_workflow
code_path_at_run     backend/generated_workflows/...
published hash       sha256:...
actual hash          sha256:...
code_modified        true/false
```

如果 `code_modified=true`，使用 warning 样式。

## 9. 数据与 API 契约

## 9.1 `workflow_versions`

当前字段已经够用：

```sql
code_path TEXT
code_hash VARCHAR(128)
code_generated_at TIMESTAMPTZ
```

短期不需要新增 DB 字段。

`code_hash_actual` 和 `code_status` 是动态检查结果，不应持久化到 `workflow_versions`，因为它们反映本地文件系统的当前状态。

## 9.2 `workflow_runs.metadata_json`

建议标准结构：

```json
{
  "execution_mode": "sync",
  "runtime": "generated_workflow",
  "code_path_at_run": "backend/generated_workflows/workflow_000001/v000003/workflow.py",
  "code_hash_published": "sha256:published",
  "code_hash_at_run": "sha256:actual",
  "code_modified": false
}
```

当前已有 `code_hash_at_run` 和 `code_modified`，建议后续补 `code_hash_published`，便于 Trace 不再额外查版本。

## 10. 安全设计

### 10.1 路径安全

所有 code path 必须满足：

```text
resolved_path.relative_to(BACKEND_ROOT / "generated_workflows")
```

禁止：

```text
../
绝对路径指向 generated_workflows 之外
符号链接逃逸 generated_workflows
```

### 10.2 源码查看安全

`workflow.py` 由平台生成，当前不应包含 secrets。后续如果生成代码内嵌节点配置，要继续确保：

- 不把 secret 明文写入 `workflow.py`。
- 只保留 secret placeholder。
- Trace 中继续脱敏敏感 header 和 token。

### 10.3 import 风险

import `workflow.py` 会执行顶层代码。当前生成代码顶层只包含 imports 和 `GRAPH = json.loads(...)`，风险可控。

如果后续生成更复杂的顶层代码，需要限制：

- 不生成网络请求。
- 不生成文件写入。
- 不生成环境变量读取。
- 顶层只做常量定义。

## 11. 测试设计

## 11.1 单元测试

### Codegen

- 生成 v1 目录。
- 生成 v2 不覆盖 v1。
- 已存在最终目录时报错。
- 残留同版本 temp 目录会被清理。
- `workflow.py` source 可 compile。
- manifest 内容完整。
- code hash 与文件内容一致。

### Code inspection

- 文件存在且 hash 一致：`ok`。
- 文件存在但被修改：`modified`。
- 文件缺失：`missing_file`。
- `code_path` 为空：`missing_metadata`。
- path 逃逸：`invalid_path`。

### Cleanup

- 删除 temp 目录。
- 删除 DB 未引用版本目录。
- 不删除 DB 引用版本目录。
- 删除空 workflow 目录。
- `dry_run=true` 不实际删除。
- path 逃逸不会被纳入 kept set。

### Runtime

- import 成功并运行。
- 缺少 `run` 报 `workflow_entrypoint_missing`。
- import 报错包装为 `workflow_code_import_failed`。
- hash 变化记录 `code_modified=true`。
- missing file 报 `workflow_code_missing`。

## 11.2 集成测试

- 发布 workflow 后：
  - DB 有 workflow_version。
  - 本地有 workflow.py。
  - 版本详情返回 `code_status=ok`。
  - 版本代码 API 返回 source。
- 发布后删除本地文件：
  - 版本详情返回 `missing_file`。
  - 运行失败或提示重新生成。
- 手动修改 workflow.py：
  - 版本详情返回 `modified`。
  - 运行后 Trace 中 `code_modified=true`。
- 清理 orphan：
  - 手动创建未引用 `v999999`。
  - cleanup 删除它。
  - 已引用目录保留。

## 11.3 并发测试

- 同一个 workflow 并发发布两次：
  - 最终生成两个版本，版本号不重复。
  - current_version 指向后提交版本。
  - 两个版本目录都存在。
- DB insert 失败模拟：
  - 不更新 current_version。
  - 不留下最终版本目录。
- rename 后进程异常模拟：
  - cleanup 可以删除未引用目录。

## 12. 实施计划

### Phase 1：稳定当前链路

- 发布时做 temp 清理和 compile 校验。
- 版本详情返回 `code_status`。
- 版本代码 API。
- cleanup API。
- 前端版本面板展示 hash 状态和代码查看。
- 运行前 hash 提示。

验收：

```text
发布后能查看 workflow.py
手动改 workflow.py 后 UI 显示 Hash 已变更
运行后 Trace 显示 code_modified=true
cleanup 不删除 DB 引用版本
```

### Phase 2：版本历史与重生成

- 版本历史列表 UI。
- 任意版本代码查看。
- 指定版本运行。
- `regenerate-code` API。
- missing file 时 UI 提供重新生成入口。
- cleanup 增加 dry-run 确认 UI。

验收：

```text
可以查看历史 v1/v2 的 workflow.py
可以运行指定历史版本
删除本地 workflow.py 后可以从 graph_json 重新生成
cleanup dry-run 可预览删除列表
```

### Phase 3：严格策略与可观测性

- `GENERATED_WORKFLOW_HASH_POLICY=warn|block`。
- Trace 补 `code_hash_published`。
- Audit log 覆盖 cleanup 和 regenerate。
- 发布事件中记录 code artifact metadata。

验收：

```text
strict 模式下 modified code 被阻止
Trace 同时展示 published hash 和 actual hash
所有代码治理操作可审计
```

### Phase 4：生成代码可读性增强

当前 `workflow.py` 固化 graph 并调用 `context.execute_graph`。后续可生成更可读的步骤代码：

```python
async def run(input_data, context):
    await context.execute_node("start_1", "start")
    await context.execute_node("input_1", "input")
    await context.execute_node("llm_1", "llm")
    return context.finish(...)
```

此阶段要谨慎推进，因为会扩大 codegen 复杂度。

验收：

```text
生成代码可读
行为与 graph runtime 一致
节点级 Trace 不回退
分支和循环策略明确
```

## 13. 风险与对策

### 13.1 文件系统与 DB 不一致

风险：DB 提交成功但文件被删除。

对策：

- 版本详情动态检查文件状态。
- 提供 regenerate。
- 运行前阻止 missing file。

### 13.2 清理误删

风险：cleanup 删除仍被引用目录。

对策：

- 所有 DB code_path 转成 resolved version dir。
- 删除前必须确认目录不在 referenced set。
- 只删除标准命名目录。
- 优先支持 dry-run。

### 13.3 本地手改代码导致行为不可预期

风险：用户以为运行的是发布 graph，实际运行的是修改后的 workflow.py。

对策：

- UI 明确提示 hash modified。
- Trace 记录 actual hash。
- strict 模式阻止运行。

### 13.4 import 执行不可信顶层代码

风险：未来生成代码变复杂后 import 有副作用。

对策：

- 生成规范要求顶层无副作用。
- import 前 compile。
- 后续可增加静态 AST 检查。

## 14. 开放问题

- 重新生成版本代码是否应该更新 `workflow_versions.code_hash`，还是保留原 hash 并新增 `regenerated_code_hash`？
- strict hash policy 是否按全局配置，还是按 workflow/project 配置？
- cleanup 是否需要支持 quarantine，而不是直接删除？
- 版本代码查看是否需要权限控制，避免未来展示敏感节点配置？
- 未来生成可读代码时，分支节点应该生成 Python 分支逻辑，还是继续交给 `context.execute_graph`？

## 15. 推荐下一步

建议接下来按以下顺序推进：

```text
1. 为 cleanup 增加 dry-run UI 和确认清理
2. 增加版本历史列表和任意版本代码查看
3. 增加 regenerate-code API 和 missing file 自愈入口
4. Trace metadata 补 code_hash_published
5. 增加 strict hash policy
```

这组工作能在不扩大架构复杂度的前提下，显著提升发布链路的可信度和排障效率。
