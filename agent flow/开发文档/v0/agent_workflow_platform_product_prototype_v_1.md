# Agent 工作流平台产品原型与页面交互文档 v0.1

## 1. 文档目标

本文档定义 Agent 工作流平台 MVP 阶段的页面原型、核心用户路径、交互细节、空状态、错误状态和验收口径。

本文档重点回答：

```text
用户从哪里开始
每个页面展示什么
每个按钮做什么
异常时如何提示
运行调试时如何反馈
Trace 如何帮助定位问题
```

---

## 2. MVP 产品主路径

第一版主路径：

```text
工作流列表
→ 创建工作流
→ 进入编辑器
→ 拖拽节点
→ 配置节点
→ 连线
→ 保存草稿
→ 发布版本
→ 输入测试数据
→ 运行
→ 查看输出
→ 查看 Trace
```

辅助路径：

```text
知识库管理
→ 创建知识库
→ 上传文档
→ 等待处理
→ 测试检索
→ 在 Knowledge Base Node 中选择知识库

工具管理
→ 创建 API 工具
→ 配置 Secret
→ 测试工具
→ 在 API Node 中调用
```

---

## 3. 信息架构

```text
Agent 工作流平台
  ├─ 工作流
  │   ├─ 工作流列表
  │   ├─ 工作流编辑器
  │   └─ 运行详情
  ├─ 知识库
  │   ├─ 知识库列表
  │   └─ 知识库详情
  ├─ 工具
  │   ├─ API 工具列表
  │   └─ API 工具编辑
  ├─ 模型
  │   └─ 模型配置
  └─ 设置
      └─ Secret 管理
```

MVP 可以把“模型”和“Secret”放在设置中，只对 Admin 显示。

---

## 4. 全局布局

页面基础结构：

```text
左侧导航
  ├─ 工作流
  ├─ 知识库
  ├─ 工具
  └─ 设置

顶部栏
  ├─ 当前页面标题
  ├─ 面包屑
  ├─ 当前用户
  └─ 环境标识

主内容区
  └─ 当前页面内容
```

MVP 可以采用单栏工作台风格，不做营销首页。

---

## 5. 工作流列表页

## 5.1 页面目标

用户进入系统后的默认页面，用于查看和创建工作流。

## 5.2 页面结构

```text
标题区
  ├─ 标题：工作流
  └─ 主按钮：创建工作流

筛选区
  ├─ 搜索框：按名称搜索
  ├─ 状态筛选：全部 / 草稿 / 已发布 / 已归档
  └─ 创建人筛选，可选

列表区
  ├─ 工作流名称
  ├─ 状态
  ├─ 当前版本
  ├─ 最近运行状态
  ├─ 更新时间
  └─ 操作
```

## 5.3 操作行为

创建工作流：

```text
点击“创建工作流”
→ 弹窗输入名称和描述
→ POST /api/v1/workflows
→ 创建成功后跳转编辑器
```

进入编辑器：

```text
点击工作流名称或“编辑”
→ 跳转 /workflows/:workflow_id/editor
```

删除：

```text
点击删除
→ 二次确认
→ DELETE /api/v1/workflows/:id
→ 列表刷新
```

## 5.4 空状态

无工作流时展示：

```text
标题：还没有工作流
说明：创建第一个工作流，开始编排你的 Agent 流程。
按钮：创建工作流
```

## 5.5 错误状态

列表加载失败：

```text
展示错误提示
提供“重试”按钮
保留页面结构
```

---

## 6. 创建工作流弹窗

字段：

```text
名称，必填
描述，可选
模板，可选，MVP 可先不做
```

默认 draft_graph_json：

```json
{
  "schema_version": "1.0",
  "nodes": [
    {
      "id": "start_1",
      "type": "start",
      "name": "开始",
      "position": { "x": 120, "y": 160 },
      "config": {}
    },
    {
      "id": "end_1",
      "type": "end",
      "name": "结束",
      "position": { "x": 640, "y": 160 },
      "config": {}
    }
  ],
  "edges": []
}
```

交互：

```text
名称为空时禁用确认按钮
创建中按钮 loading
创建失败展示错误
创建成功直接进入编辑器
```

---

## 7. 工作流编辑器页面

## 7.1 页面目标

编辑器是 MVP 的核心页面，用于完成节点编排、配置、发布和调试。

## 7.2 页面布局

```text
顶部工具栏，高度固定
左侧节点库，宽度固定
中间画布，自适应
右侧配置面板，宽度固定
底部调试面板，可折叠
```

顶部工具栏：

```text
返回
工作流名称
状态 Badge
当前版本
保存草稿
校验
发布
运行
```

---

## 8. 编辑器顶部工具栏

## 8.1 保存草稿

按钮状态：

```text
dirty = false：按钮可用但显示“已保存”
dirty = true：按钮显示“保存草稿”
保存中：loading
保存失败：展示错误
```

行为：

```text
转换 React Flow 状态为 graph_json
PUT /api/v1/workflows/{workflow_id}
成功后 dirty = false
```

## 8.2 校验

行为：

```text
POST /api/v1/workflows/{workflow_id}/validate
mode = publish
返回 errors / warnings
```

展示：

```text
无错误：提示“校验通过”
有错误：打开校验面板，并在节点上标记
有 warnings：黄色提示，不阻塞发布
```

## 8.3 发布

行为：

```text
如果 dirty = true，先保存草稿
执行发布校验
校验通过后 POST /api/v1/workflows/{workflow_id}/publish
成功后更新 current_version_id 和 version
```

发布成功提示：

```text
已发布 v{version}
```

## 8.4 运行

行为：

```text
如果没有 current_version_id，提示先发布
打开底部调试面板
用户输入测试 JSON
点击运行
POST /api/v1/workflows/{workflow_id}/run
```

---

## 9. 左侧节点库

节点分类：

```text
输入输出
AI
知识库
工具
控制流
消息
```

每个节点卡片展示：

```text
图标
节点名称
一句话说明
```

拖拽行为：

```text
从节点库拖到画布
生成唯一 id
使用默认 config
放置在鼠标位置
自动选中新节点
右侧打开配置面板
dirty = true
```

点击行为：

```text
点击节点卡片也可在画布中心新增节点
```

---

## 10. 中间画布

## 10.1 画布能力

MVP 必须支持：

```text
拖拽节点
移动节点
删除节点
连线
删除连线
缩放
适应画布
小地图，可选
```

## 10.2 节点状态

节点展示状态：

```text
未配置
已配置
运行中
成功
失败
跳过
```

未配置判断：

```text
缺少必填 config
缺少必要 input_mapping
缺少必要 output_mapping
```

## 10.3 节点点击

行为：

```text
选中节点
右侧展示配置面板
如果已有运行记录，底部 Trace 定位到该节点
```

## 10.4 连线点击

行为：

```text
选中连线
右侧可展示连线信息
MVP 连线配置可以很轻，只支持删除
```

---

## 11. 右侧配置面板

## 11.1 面板状态

未选中节点：

```text
展示工作流基础信息
展示发布状态
展示 Graph 概览
```

选中节点：

```text
展示节点配置表单
```

选中连线：

```text
展示 source / target
提供删除按钮
```

## 11.2 节点配置保存

编辑字段后：

```text
立即更新本地 graph 状态
dirty = true
不立即请求后端
点击保存草稿时统一保存
```

## 11.3 字段校验

前端即时校验：

```text
必填字段为空
JSON 格式错误
变量引用格式明显错误
数值范围错误
```

后端发布校验为最终结果。

---

## 12. 底部调试面板

## 12.1 Tab

```text
测试输入
运行结果
节点 Trace
错误详情
```

## 12.2 测试输入

默认示例：

```json
{
  "user_query": "我想申请退款"
}
```

交互：

```text
JSON 格式错误时禁用运行按钮
支持格式化 JSON
支持恢复示例
```

## 12.3 运行结果

展示：

```text
workflow_run.status
outputs
messages
duration
run_id
```

## 12.4 节点 Trace

展示：

```text
节点名称
节点类型
状态
耗时
attempt
输入
输出
metadata
错误
```

---

## 13. 运行反馈

运行中：

```text
顶部运行按钮 loading
底部面板显示 running
当前正在执行节点高亮
已完成节点标绿
失败节点标红
```

运行成功：

```text
展示 outputs
展示 messages
所有执行节点状态同步到画布
```

运行失败：

```text
展示 error_code / error_message
定位失败节点
打开失败节点 Trace
提供“复制错误信息”
```

---

## 14. 校验错误定位

校验错误返回：

```json
{
  "code": "missing_required_config",
  "message": "LLM Node 缺少 user_prompt",
  "path": "nodes[2].config.user_prompt",
  "node_id": "llm_1"
}
```

前端处理：

```text
如果有 node_id，画布定位并选中节点
右侧表单定位字段
校验面板展示错误列表
```

---

## 15. 知识库管理原型

## 15.1 知识库列表

展示：

```text
知识库名称
描述
文档数量
状态
更新时间
操作
```

操作：

```text
创建知识库
进入详情
删除，可选
```

## 15.2 知识库详情

区域：

```text
基础信息
文档列表
上传文档
测试检索
```

文档列表字段：

```text
文件名
文件类型
文件大小
状态
错误阶段
上传时间
操作
```

状态展示：

```text
uploaded
parsing
chunking
embedding
indexed
failed
```

失败文档：

```text
展示 error_stage / error_message
提供重试按钮
```

测试检索：

```text
输入 query
配置 top_k
点击检索
展示 chunk 内容、score、source
```

---

## 16. 工具/API 配置原型

## 16.1 工具列表

展示：

```text
工具名称
类型
状态
更新时间
操作
```

## 16.2 API 工具编辑

字段：

```text
名称
描述
Method
URL
Headers
Query Params
Body Template
Timeout
```

测试区域：

```text
输入测试 JSON
点击测试
展示 status_code
展示 duration_ms
展示 response
展示错误
```

Secret 引用提示：

```text
可以使用 {{secrets.xxx}} 引用密钥，真实值只在服务端解析。
```

---

## 17. Secret 管理原型

仅 Admin 可见。

列表字段：

```text
secret_key
display_name
status
created_at
updated_at
```

创建/更新：

```text
secret_key
display_name
value
```

注意：

```text
value 只在创建或更新时输入
保存后不再展示明文
```

---

## 18. 运行详情页

如果底部调试面板足够，MVP 可以先不做独立详情页。但建议预留：

```text
/runs/:run_id
```

页面展示：

```text
运行基础信息
输入
输出
Graph 执行路径
节点 Trace 列表
错误详情
```

适用场景：

```text
从工作流列表查看历史运行
分享给研发排查问题
审计查看
```

---

## 19. 空状态与错误状态汇总

空状态：

```text
无工作流
无知识库
无文档
无工具
无运行记录
无 Trace
```

错误状态：

```text
接口加载失败
保存失败
发布校验失败
运行失败
文档处理失败
工具测试失败
权限不足
```

所有错误都应提供：

```text
错误摘要
可读说明
可操作按钮
技术详情，可折叠
```

---

## 20. MVP 原型验收标准

工作流列表：

```text
可以创建工作流
可以进入编辑器
可以看到状态和版本
```

编辑器：

```text
可以新增节点
可以配置节点
可以连线
可以保存草稿
可以发布
可以运行
可以看 Trace
```

知识库：

```text
可以创建知识库
可以上传文档
可以查看处理状态
可以测试检索
```

工具：

```text
可以创建 API 工具
可以测试 API 工具
可以使用 Secret 引用
```

---

## 21. 结论

MVP 产品原型的核心不是复杂，而是闭环清晰。

第一版必须让用户明确感受到：

```text
我能搭建流程
我能配置节点
我能发布运行
我能看到结果
我能定位错误
```

只要这五件事顺畅，后续复杂节点和企业能力就有了稳定承载面。
