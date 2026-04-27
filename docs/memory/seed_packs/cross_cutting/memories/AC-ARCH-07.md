---
id: AC-ARCH-07
layer: PLATFORM
tier: hot
type: lesson
language: all
pack: cross_cutting
about_concepts: [message-queue, idempotency, consumer, deduplication, exactly-once]
cites_files: []
created_at: "2026-04-27"
---

# 消息队列消费者必须实现幂等性

## 教训（Lesson）

消息队列（Kafka/RabbitMQ/RocketMQ）无法保证消息只被投递一次（at-most-once）。在网络异常、消费者重启、消息重投等场景下，同一条消息可能被消费多次。**消费者必须实现幂等性（Idempotency），保证多次处理同一消息结果与一次处理相同。**

## 常见幂等实现方案

### 方案 1：数据库唯一约束（最简单，适合订单/支付场景）

```sql
-- 创建幂等键表
CREATE TABLE message_idempotency_keys (
    idempotency_key VARCHAR(64) PRIMARY KEY,
    processed_at    DATETIME NOT NULL,
    result          JSON
);
```

```python
def consume_order_created(message: OrderCreatedEvent):
    idempotency_key = f"order-created:{message.order_id}:{message.version}"

    try:
        with db.begin():
            # 尝试插入幂等键（唯一约束，重复时报错）
            db.execute(
                "INSERT INTO message_idempotency_keys (idempotency_key, processed_at) VALUES (?, NOW())",
                (idempotency_key,)
            )
            # 执行业务逻辑（只在首次执行）
            inventory_service.deduct_stock(message.items)
    except IntegrityError:
        logger.info("message_already_processed", key=idempotency_key)
        return   # 幂等：忽略重复消息
```

### 方案 2：Redis SETNX（适合高吞吐量场景）

```python
def consume_with_redis_lock(message: Event):
    key = f"msg:processed:{message.message_id}"
    # SETNX：如果 key 不存在则设置并返回 True，已存在返回 False
    if not redis.set(key, "1", nx=True, ex=3600):   # 1小时过期
        return   # 已处理，跳过
    process_event(message)
```

### 方案 3：业务操作本身幂等（最优雅）

```sql
-- 使用 INSERT ... ON DUPLICATE KEY UPDATE（MySQL）
-- 或 INSERT ... ON CONFLICT DO NOTHING（PostgreSQL）
INSERT INTO order_notifications (order_id, type, sent_at)
VALUES (?, 'SHIPPED', NOW())
ON CONFLICT (order_id, type) DO NOTHING;   -- 重复发送邮件通知 → 幂等！
```

## 幂等键设计原则

- 幂等键必须来自**消息本身**（`message_id`、`order_id` + `event_type` 组合），不能是时间戳
- 幂等键的有效期应大于消息可能的最大重投时间（如 Kafka retention = 7天）

## 参考

- 《Designing Data-Intensive Applications》第 11 章：流处理
- AWS 文档：[Idempotency with SQS](https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html)
