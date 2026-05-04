---
id: AD-SEED-PAL-001
layer: CC
module: architecture
type: decision
tier: hot
tags: [palantir, cqrs, hexagonal, control-plane, data-plane, seed]
source_ep: EP-130
created_at: 2026-04-18
version: 1
generalized: true
---

# AD-SEED-PAL-001: Palantir 风格 Control/Data Plane 分离

## 决策

系统分为 Control Plane（元数据管理）和 Data Plane（数据处理），两平面严格隔离。

## 核心约束

1. **Control Plane**（`services/control/`）：只操作 MySQL，禁止直写向量库/搜索引擎
2. **Data Plane**（`workers/`）：通过事件总线（Kafka）接收 Control Plane 的指令
3. **查询侧**（`services/query/`）：只读，走 ES/Milvus，不走 MySQL
4. **Infrastructure 层**：所有外部依赖通过 Ports & Adapters 模式封装

## 禁止的跨层导入

```python
# ❌ Control Plane 禁止直接导入
from pymilvus import connections      # 数据平面专属
from elasticsearch import Elasticsearch
from aiokafka import AIOKafkaProducer  # 走 infrastructure adapter

# ✅ 正确：通过 infrastructure 抽象层
from app.infrastructure.kafka import KafkaProducerPort
from app.infrastructure.search import SearchPort
```

## CQRS 模式

- **写操作（Command）**：→ Control Service → MySQL → 事件发布 → Worker 异步处理
- **读操作（Query）**：→ Query Service → ES/Milvus（最终一致性，允许短暂延迟）
