---
id: MEM-L-011
layer: L2_infrastructure
module: messaging
dimension: D6_bigdata
type: lesson
tier: hot
description: "Avro 生产端用 fastavro.write；消费端必须用 fastavro.reader；混用 schemaless/container 格式导致解析错误"
tags: [kafka, avro, fastavro, serialization, producer, consumer, format]
source_ep: EP-101
created_at: "2026-03-06"
version: 1
last_accessed: "2026-04-11"
access_count: 12
related_memories: [MEM-L-002, MEM-L-010]
also_in: [L2_infrastructure/D4_resilience]
related_to:
  - id: "MEM-L-002"
    reason: "Avro 格式规范与序列化静默失败根因互为补充"
  - id: "AD-007"
    reason: "NullSafeNormalizer 依赖本记忆的格式规范进行字段类型转换"
cites_files:
  - "backend/app/infrastructure/kafka/"
impacts:
  - "MEM-L-002"
  - "AD-007"
generalized: true
---

# MEM-L-011 · Kafka 生产/消费 Avro 格式必须一致：schemaless vs container

## WHERE（发生层/模块）
Layer 2 基础设施层 → Messaging 模块 → Kafka Producer + LakeWriter Consumer

## WHAT（问题类型）
Dimension 6: 大数据与事件驱动 — Avro 序列化格式不匹配（静默失败）

## WHY（根因与影响）
**触发条件**：Producer 用 `fastavro.schemaless_writer`，Consumer 用 `fastavro.reader`
**症状**：所有消息解码失败，lake_writer 超时 SKIPPED，`rows_affected=0`
**根因**：`schemaless_writer` 写无头部字节流；`fastavro.reader` 期望完整 Avro 容器格式（含头部 magic bytes + schema）。两者二进制格式根本不兼容

## HOW（正确规范）
```python
# ✅ Producer：写完整 Avro 容器格式
import io, fastavro

buf = io.BytesIO()
fastavro.writer(buf, parsed_schema, [record])   # 写完整容器
kafka_producer.send(topic, buf.getvalue())

# ✅ Consumer：读完整 Avro 容器格式（自动推断 schema）
buf = io.BytesIO(kafka_message.value)
for record in fastavro.reader(buf):             # 自动解析头部
    process(record)
```

```python
# ❌ 禁止混用
fastavro.schemaless_writer(buf, schema, record)  # Producer 端禁止
fastavro.schemaless_reader(buf, schema)          # 与上面搭配才能用，但不推荐
```

## WHEN（应用条件）
- ✅ 所有使用 fastavro 的 Kafka 生产者/消费者
- ✅ 跨服务 Avro 消息传递

## 禁止项
- ❌ 混用 schemaless 和 container 格式
- ❌ Producer/Consumer 不使用相同的格式约定
