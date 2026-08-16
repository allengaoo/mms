---
id: MEM-L-006
layer: L2_infrastructure
module: messaging
dimension: D6_bigdata
type: lesson
tier: hot
description: "Schema Registry BACKWARD 兼容：新增字段必须有 default 值；缺 default 会导致旧版 Consumer 反序列化失败"
tags: [avro, schema-registry, backward-compat, default, field-addition]
source_ep: EP-097
created_at: "2026-02-20"
version: 1
last_accessed: "2026-04-11"
access_count: 6
related_memories: [MEM-L-011, MEM-L-002]
also_in: []
generalized: true
---

# MEM-L-006 · Schema Registry BACKWARD 兼容策略

## WHERE（发生层/模块）
Layer 2 基础设施层 → Messaging 模块 → Confluent Schema Registry

## WHAT（问题类型）
Dimension 6: 大数据与事件驱动 — Schema 兼容性

## WHY（根因与影响）
**触发条件**：向已有 Avro schema 新增字段时，未设置 `"default": null`
**症状**：Schema Registry BACKWARD 检查失败，发布被拒绝
**根因**：BACKWARD 兼容要求新 schema 能读取旧消息；没有 default 的新字段在旧消息中不存在，导致兼容性检查失败

## HOW（规范）
```json
// ✅ 新增字段必须有 default
{
  "name": "new_field",
  "type": ["null", "string"],
  "default": null
}

// ❌ 错误：无 default 的新字段
{
  "name": "new_field",
  "type": "string"
}
```

**字段操作风险矩阵**：
- 新增字段（有 default）→ BACKWARD 兼容 ✅
- 新增字段（无 default）→ BACKWARD 不兼容 ❌
- 删除字段 → 破坏性更强，需要 FULL 兼容模式

## WHEN（应用条件）
- ✅ 所有通过 Schema Registry 注册的 Avro schema 修改
- ✅ 新增可选字段时固定用 `["null", "string"]` union 类型
