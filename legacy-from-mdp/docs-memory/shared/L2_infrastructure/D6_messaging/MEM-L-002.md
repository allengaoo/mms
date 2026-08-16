---
id: MEM-L-002
layer: L2_infrastructure
module: messaging
dimension: D6_bigdata
type: lesson
tier: hot
description: "Kafka 发送前必须调 normalize_record()；含 date/Decimal/UUID 原生类型的 batch 直接发送会导致 Avro 序列化静默失败"
tags: [avro, fastavro, normalization, serialization, uuid, datetime, decimal, postgresql]
source_ep: EP-098
created_at: "2026-02-24"
version: 1
last_accessed: "2026-04-11"
access_count: 15
related_memories: [MEM-L-001, MEM-L-011, AD-007]
also_in: [L4_application/workers]
generalized: true
related_to:
  - id: "AD-007"
    reason: "NullSafeNormalizer 是修复本问题的架构方案"
  - id: "MEM-L-011"
    reason: "Avro 格式规范与序列化静默失败根因互为补充"
  - id: "MEM-L-001"
    reason: "or 默认值在 Avro 序列化场景中是高频触发点"
cites_files:
  - "backend/app/infrastructure/kafka/"
  - "backend/app/workers/"
impacts:
  - "MEM-L-010"
  - "MEM-L-011"
---

# MEM-L-002 · Avro 序列化静默失败的根因模式

## WHERE（发生层/模块）
Layer 2 基础设施层 → Messaging 模块 → Kafka Producer 前的归一化层

## WHAT（问题类型）
Dimension 6: 大数据与事件驱动 — 原生 Python 类型导致 fastavro 静默失败

## WHY（根因与影响）
**触发条件**：原始 DB 数据（含 `asyncpg.pgproto.UUID`、`datetime.date`、`Decimal`）直接送入 fastavro
**症状**：`rows_affected=0`，消息静默丢失
**根因**：fastavro 对类型极其严格；不在 Avro schema 原生类型集合内的 Python 对象导致 `ValueError`；在批处理循环中被宽泛的 except 吞掉

## HOW（修复方案）
```python
# ✅ 必须在发送 Kafka 前调用 normalize_record()
from app.infrastructure.connector.normalizer import normalize_record

async for batch in source_adapter.read_batches():
    for row in batch:
        normalized = normalize_record(row)   # 归一化门
        await kafka_producer.send(topic, normalized)
```

```python
# normalize_record 核心逻辑（NullSafeNormalizer 模式）
def normalize_value(value):
    if value is None:
        return None
    # Duck-typing 处理第三方类型（不直接 import）
    if hasattr(value, 'item'):          # numpy scalar
        return value.item()
    if hasattr(value, 'isoformat'):     # datetime / date / UUID
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    return value
```

## WHEN（应用条件）
- ✅ 所有数据源到 Kafka 的 Ingestion Worker
- ✅ 新增任何数据源时（MySQL/S3/FTP/Kafka），必须经过归一化门

## 禁止项
- ❌ 发送含 asyncpg.UUID / datetime.date / Decimal 的原始 batch
- ❌ 在批处理循环中用宽泛 `except Exception:` 吞掉序列化错误
