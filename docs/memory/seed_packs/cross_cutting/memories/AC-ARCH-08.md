---
id: AC-ARCH-08
layer: PLATFORM
tier: warm
type: pattern
language: all
pack: cross_cutting
about_concepts: [outbox-pattern, domain-event, eventual-consistency, distributed-transaction, message-queue]
cites_files: []
contradicts: []
created_at: "2026-04-27"
---

# Outbox 模式：领域事件必须与业务写操作在同一事务中持久化

## 模式（Pattern）

在微服务架构中，**业务状态写入 + 领域事件发布**必须是原子的。直接在 Service 层调用 `mq.publish()` 无法保证"订单已创建，但消息因网络故障未发送"的一致性问题。

## 问题场景（Two-Phase Commit 的陷阱）

```python
# ❌ 危险：两步操作不是原子的
def create_order(dto: OrderCreateDTO):
    order = order_repo.save(dto)           # 步骤 1：写 DB
    mq.publish("order.created", order)    # 步骤 2：发 MQ
    # 问题：步骤 1 成功，步骤 2 因网络抖动失败
    # → 订单已创建，但库存服务永远不知道！
```

## Outbox 模式实现

```python
# ✅ 正确：Outbox 模式（同一事务内写入 outbox 表）
def create_order(dto: OrderCreateDTO):
    with db.begin():
        order = order_repo.save(dto)

        # 将"待发送的事件"写入 outbox 表（同一事务！）
        outbox_repo.save(OutboxEvent(
            aggregate_id=str(order.id),
            event_type="order.created",
            payload=order.to_dict(),
            status="PENDING",
        ))
    # 事务提交：订单创建 + outbox 记录原子完成

# 独立的 Outbox Relay 进程：轮询 outbox 表，发送到 MQ
def relay_outbox_events():
    pending = outbox_repo.find_pending(limit=100)
    for event in pending:
        mq.publish(event.event_type, event.payload)
        outbox_repo.mark_sent(event.id)   # 标记已发送
```

## 消息顺序保证

Outbox 表按 `created_at` 排序发送，保证同一聚合根（`aggregate_id`）的事件顺序与写入顺序一致。

## 开源实现

| 实现 | 语言 | 说明 |
|---|---|---|
| Debezium | Java | CDC（Change Data Capture），监听 binlog 触发事件 |
| Transactional Outbox (Spring) | Java | `@TransactionalEventListener` |
| pg-boss | Node.js/TypeScript | PostgreSQL 事务内队列 |
| outboxer | Go | 通用 Outbox 实现 |

## 参考

- Microservices.io：[Transactional Outbox Pattern](https://microservices.io/patterns/data/transactional-outbox.html)
- 《Designing Data-Intensive Applications》第 11 章
