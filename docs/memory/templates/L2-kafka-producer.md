# 模版：ADAPTER 层 · Kafka 生产者 / Ingestion Worker（小模型优化版）
# 适用：新增数据源接入 / Kafka 发送逻辑 / Avro schema 变更
# Token 预算：≤3.5K

---

## [TASK] 任务描述
**目标**：{一句话，包含：数据源类型 + 目标 Kafka Topic}
**层级坐标**：Layer 2 (infrastructure/messaging) × Dimension 6 (大数据与事件驱动)
**涉及文件**：
- `backend/app/workers/ingestion.py`（或新 Worker 文件）
- `backend/app/infrastructure/connector/normalizer.py`
- `backend/app/infrastructure/mq/kafka_producer.py`

---

## [MEMORY] 本次必须遵守的记忆（3条核心）

**MEM-L-002**：Avro 序列化前必须过归一化门
- 规则：发 Kafka 前必须调 `normalize_record(row)`
- ❌ 禁止：直接发送含 asyncpg.UUID / datetime.date / Decimal 的原始数据

**MEM-L-011**：Avro 格式 Producer/Consumer 必须一致（container 格式）
- ✅ Producer：`fastavro.writer(buf, schema, [record])` — 完整容器格式
- ❌ 禁止：`fastavro.schemaless_writer` 与 `fastavro.reader` 混用

**MEM-L-006**：Schema Registry 新增字段必须有 default
- ✅ 正确：`{"name": "new_field", "type": ["null", "string"], "default": null}`
- ❌ 错误：无 default 的新字段（BACKWARD 兼容失败）

---

## [STATE] 系统状态
- EP: {当前EP编号} | 后端镜像: {version}
- Kafka Bootstrap: {KAFKA_BOOTSTRAP_SERVERS 值}
- 是否新增 Avro Schema: 是 / 否

---

## [CONSTRAINTS] 本层必守红线（5条）
- ✅ Worker 必须使用 `async with JobExecutionScope(job_id, ctx) as scope:` 包裹
- ✅ 读 S3/File/DB Cursor 必须用 `yield` 流式处理，禁止 `fetchall()`
- ✅ Kafka 发送前必须调 `normalize_record(row)`
- ✅ 批处理循环禁止宽泛 `except Exception:` 吞掉序列化错误
- ❌ 禁止：在 HTTP Handler 中直接写 Kafka（必须走 Worker）

---

## [EXAMPLE] 参考模式（来自 EP-098）
```python
# ✅ 完整 Ingestion Worker 骨架
async with JobExecutionScope(job_id, ctx) as scope:
    async for batch in source_adapter.read_batches():
        rows_sent = 0
        for row in batch:
            normalized = normalize_record(row)          # 归一化门
            buf = io.BytesIO()
            fastavro.writer(buf, parsed_schema, [normalized])  # container 格式
            await kafka_producer.send(topic, buf.getvalue())
            rows_sent += 1
        scope.set_metric("rows_processed", rows_sent)
```

---

## [OUTPUT] 输出格式
1. Worker 完整代码（含 JobExecutionScope + normalize_record 调用）
2. Avro schema JSON（如涉及新 schema）
3. 对应测试（mock kafka_producer + 验证 normalize_record 被调用）
