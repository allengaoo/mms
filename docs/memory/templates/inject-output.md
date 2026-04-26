# MMS 记忆注入输出模板 v1.0
# 说明：此文件由 `mms inject <任务描述>` 命令自动生成并填充。
# 用法：将 <!-- MMS-INJECT ... --> ... <!-- END-MMS-INJECT --> 整块粘贴到对话或 Cursor 上下文的开头。
# Token 预算：默认 ≤3K（压缩模式）；--no-compress 时约 8-15K。

---

<!-- MMS-INJECT | task: {任务描述} | memories: {N} | tokens: ~{N} | generated: {timestamp} -->

## 相关记忆（自动注入，基于 MMS v2.2 推理式检索）

**任务**: {任务描述}
**检测到的层**: {层节点列表，如 L5, L5-D8, L3-ontology}

---

### 1. 🔥 [{记忆ID}] {记忆标题}

**如何做**：
```
{HOW 段落的关键代码/规则，截取 ≤600 字符}
```

**何时触发**：
{WHEN 段落，截取 ≤300 字符}

> 原文: `docs/memory/{文件路径}`

---

### 2. ⚡ [{记忆ID}] {记忆标题}

**如何做**：
{...}

**何时触发**：
{...}

> 原文: `docs/memory/{文件路径}`

---

<!-- 更多记忆条目 ... -->

<!-- END-MMS-INJECT -->

---

## 使用指南

### 快速注入（推荐工作流）

```bash
# 1. 生成注入上下文
./mms inject "新增 ObjectType API，带 ProTable 和 Zustand Store" > /tmp/ctx.md

# 2. 查看估算 token 数（输出文件第一行 <!-- MMS-INJECT ... tokens: ~N -->）
head -1 /tmp/ctx.md

# 3. 将 /tmp/ctx.md 内容粘贴到 Cursor 对话上下文开头（或 @/tmp/ctx.md 引用）
```

### 常见任务 → 注入命令映射

| 任务类型 | 建议命令 |
|:---|:---|
| 新增后端 API | `mms inject "新增 {Domain} {HTTP方法} API" --top-k 5` |
| 新增前端页面 | `mms inject "新增 {模块名} 管理页面 React ProTable" --top-k 5` |
| 修复 Kafka 问题 | `mms inject "Kafka Avro 序列化失败" --top-k 3` |
| 本体层新增 Action | `mms inject "新增 ActionDef 回写 overlay" --top-k 5` |
| 权限配置 | `mms inject "RBAC PermissionGate 权限 ont:object:edit" --top-k 3` |
| 数据管道 Worker | `mms inject "IngestionWorker JobExecutionScope" --top-k 4` |
| 写事务安全 | `mms inject "MySQL 事务 session begin autobegin" --top-k 3` |

### 输出结构说明

| 字段 | 说明 |
|:---|:---|
| `memories: N` | 注入的记忆条数 |
| `tokens: ~N` | 估算 token 数（1 token ≈ 1.5 中文字 / 4 英文字） |
| 🔥 hot | 高频使用记忆，通常是平台红线规则 |
| ⚡ warm | 中频记忆，领域最佳实践 |
| ❄️ cold | 低频记忆，特定场景专项知识 |

### 私有工作区配合使用

```bash
# 初始化 EP 私有工作区
./mms private init EP-111 --desc "新功能开发"

# 开发过程中添加草稿笔记
./mms private note EP-111 "API 设计决策草稿" "决定使用 cursor-based 分页"

# 开发完成后将有价值的草稿升级为公有记忆
./mms private promote EP-111 notes/20260412_api_design.md ADAPTER/D8_api MEM-L-028

# 清理工作区
./mms private close EP-111
```

### 调试注入效果

```bash
# 查看匹配了哪些记忆（不输出正文，仅看 ID 和分数）
./mms search kafka avro replication --top-k 8

# 完整正文模式（适合记忆数量少时）
./mms inject "Kafka 序列化" --no-compress

# 预览最高匹配记忆的正文
./mms search kafka --preview
```
