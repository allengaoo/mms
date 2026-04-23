# Data Pipeline Manifest

> 适用：Ingestion Worker / Kafka / Iceberg / 连接器 / Schema Registry EP
> 补充加载：`@.cursor/skills/data-pipeline/SKILL.md`
> **维护者**：@gaobin · 最后更新：EP-102

---

## 红线约束（静默失败专区）

1. **Kafka 发送前必须归一化**：`normalized = [normalize_record(row) for row in batch]`，禁止发送含原生 PG 类型（`datetime.date`、`Decimal`、`UUID`、`asyncpg` 对象）的原始 batch。
2. **流式读取强制**：从 S3/File/DB Cursor 读取数据必须用 `yield`，禁止 `read()` / `fetchall()`（内存爆炸）。
3. **Worker 必须用 JobExecutionScope**：`async with JobExecutionScope(job_id, session) as scope`，禁止散落 try/except 管理 `job.status`。
4. **`rows_affected` 计数陷阱**：`scope.rows_affected += len(batch)` 中的 `+=` 依赖累积，**不能用 `or`**（`0 or default` 会覆盖正确的 0）。
5. **Schema Evolution via Avro**：Kafka 消息必须走 Schema Registry；新增字段必须有 `default` 值以保持向后兼容。

---

## 核心代码骨架

### Ingestion Worker 标准流程
```python
async with JobExecutionScope(job_id, session) as scope:
    async for batch in source_adapter.stream_batches(ctx, config):
        normalized = [normalize_record(row) for row in batch]  # 归一化
        await kafka_producer.emit(
            topic=build_topic_name(ctx.tenant_id, table_name),
            value={"batch": normalized, "job_id": str(job_id)},
            headers={"trace_id": ctx.trace_id},
        )
        scope.rows_affected += len(batch)   # 直接 += 而非 or
```

### NullSafeNormalizer 扩展（新数据源）
```python
from app.infrastructure.connector.normalizer import NullSafeNormalizer

normalizer = NullSafeNormalizer()
# 注册新类型处理器（如 MyCustomType）
normalizer.register_type_handler(MyCustomType, lambda v: str(v))
```

---

## 必读文件

| 文件 | 说明 | 优先级 |
|:---|:---|:---|
| `docs/architecture/e2e_traceability.md §2 DataLink` | 本域代码文件全层索引（Worker/Infra/API/Model/Tests） | 变更前必须 |
| `.cursor/skills/data-pipeline/SKILL.md` | 管道架构核心概念 | 必须 |
| `backend/app/infrastructure/connector/normalizer.py` | NullSafeNormalizer 实现 | 必须 |
| `backend/app/workers/base.py` | JobExecutionScope 实现 | 必须 |
| `docs/specs/connector_sync.md` | 同步规约（含 RecordNormalizer 说明） | 必须 |
| `.cursor/rules/bigdata_gen.mdc` | PySpark/Kafka/Iceberg 代码规范 | 按需 |
| `backend/app/infrastructure/mq/kafka_producer.py` | KafkaDataProducer 实现 | 按需 |

---

## 关键决策点

| 遇到 X | 选 A 而非 B | 理由 |
|:---|:---|:---|
| 新数据源类型（MySQL/FTP/S3） | 扩展 `NullSafeNormalizer` 注册器 | 统一归一化层，避免在各 adapter 中散落转换逻辑 |
| 第三方库类型（NumPy/asyncpg） | 依赖 duck-typing probe（`.item()` / `.isoformat()`） | 零依赖，不 import 第三方库到 normalizer |
| Kafka topic 命名 | `build_topic_name(tenant_id, table_name)` | 保证多租户隔离，禁止手拼字符串 |
| 分批写入时计数 | `scope.rows_affected += len(batch)` | `len()` 返回 int，`+=` 安全；避免 `or` 覆盖 0 值 |
| 新 Avro 字段 | 必须加 `"default": null` | Schema Registry BACKWARD 兼容策略要求 |
