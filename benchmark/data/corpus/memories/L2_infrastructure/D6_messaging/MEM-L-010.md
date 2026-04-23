---
id: MEM-L-010
layer: L2_infrastructure
module: messaging
dimension: D6_bigdata
type: lesson
tier: hot
description: "本地/测试 Kafka 单节点必须在 Topic 配置中设 replication.factor=1，否则 Topic 创建失败"
tags: [kafka, replication, k8s, single-node, consumer-group]
source_ep: EP-101
created_at: "2026-03-06"
version: 1
last_accessed: "2026-04-11"
access_count: 8
related_memories: [MEM-L-011]
also_in: []
related_to:
  - id: "MEM-L-011"
    reason: "K8s 单节点配置与 Avro 格式规范共同影响 Kafka 的可靠性"
  - id: "ENV-001"
    reason: "K8s 单节点是 OrbStack 环境的配置特征，需与环境快照一起理解"
cites_files:
  - "deploy/"
impacts:
  - "ENV-001"
generalized: true
---

# MEM-L-010 · Kafka 单节点必须显式设置 offsets.topic.replication.factor=1

## WHERE（发生层/模块）
Layer 2 基础设施层 → Messaging 模块 → K8s Kafka StatefulSet 配置

## WHAT（问题类型）
Dimension 6: 大数据与事件驱动 — Kafka Consumer Group 协调失败

## WHY（根因与影响）
**触发条件**：K8s 单 broker 部署 + 使用 `AIOKafkaConsumer`
**症状**：`GroupCoordinatorNotAvailableError`，Consumer 无限重试，协程挂死
**根因**：默认 `replication.factor=3` 使 `__consumer_offsets` 无法满足 ISR → Consumer Group 无法协调
**关键陷阱**：`AIOKafkaConsumer.start()` 内部无限重试 FindCoordinator，**不向外抛异常**，导致整个协程静默挂死

## HOW（修复方案）
```bash
# K8s patch（无需修改 StatefulSet yaml，避免 resourceVersion 冲突）
kubectl patch statefulset kafka -n mdp --type=json -p='[
  {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR","value":"1"}},
  {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR","value":"1"}},
  {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"KAFKA_TRANSACTION_STATE_LOG_MIN_ISR","value":"1"}}
]'
```

```python
# 二次保险：consumer.start() 加超时
await asyncio.wait_for(consumer.start(), timeout=kafka_connect_timeout_seconds)
```

## WHEN（应用条件）
- ✅ 所有 K8s 单节点/开发环境 Kafka 部署
- ✅ Docker Compose 本地 Kafka
- ❌ 不适用：3+ broker 生产集群（保持默认 replication.factor=3）

## 禁止项
- ❌ 单节点环境中使用默认 `replication.factor=3`
- ❌ `consumer.start()` 不加超时保护
