# EP 类型模板：数据管道

> 适用场景：Connector（连接器）/ SyncJob（同步任务）/ IngestionWorker / DataCatalog / Kafka

---

## 必读文件（Cursor @mention 列表）

```
@docs/context/MASTER_INDEX.md
@docs/context/SESSION_HANDOFF.md
@docs/context/data-pipeline.md
@docs/architecture/e2e_traceability.md
```

---

## 关键约束摘要

1. **流式 I/O**：读 S3/File/DB Cursor 必须用 `yield` 生成器，禁止 `read()` / `fetchall()`
2. **Kafka Normalize**：发送前必须调 `normalize_record(row)` 处理原生 PG/date/Decimal 类型
3. **JobExecutionScope**：所有 Worker 必须使用 `JobExecutionScope`，禁止散落 try/except 管理状态
4. **Schema Registry**：Kafka 消息必须用 Avro 序列化（Schema Registry）
5. **架构边界**：`aiokafka` / `pymilvus` 禁止在 Service 层直接 import，只走 `infrastructure/` 适配器
6. **同步策略显性化**：属性必须明确标注"实时 / 批量 / 按需"同步模式

---

## EP 类型声明

**数据管道**

---

## 自定义要求

<!--
在此填写您的特殊需求、约束或背景信息。
示例：
  - 数据源为本地 PostgreSQL（宿主机 5432，非 K8s 内部）
  - 需要支持增量同步（基于 updated_at 字段）
  - Kafka Topic 名称需遵循现有命名规范 mdp.{tenant}.{table}
-->



---

## Surprises & Discoveries
<!-- 实施过程中的意外发现（完成后填写）
格式：
- 现象：...
  证据：...（命令输出 / 错误信息片段）
-->

---

## Decision Log
<!-- 每个关键决策（完成后填写）
格式：
- Decision: [做了什么决定]
  Rationale: [为什么；有哪些备选方案被排除]
  Date: YYYY-MM-DD
-->

---

## Outcomes & Retrospective
<!-- EP 完成后填写
- 达成了什么（与 Purpose 对照）
- 偏差（未完成的 Unit 或范围变更）
- 给下一个 Agent 的教训
-->

---

## DAG Sketch（跨层变更时填写，单层可省略）
<!-- 描述 Unit 间依赖关系，供小模型执行时参考执行顺序
示例：
U1(model) → U2(service) → U3(endpoint) → U4(frontend)
             ↘ U5(test, 与 U2 同时)
注：同层 Unit 可并行；跨层 Unit 必须串行（见 layer_contracts.md §DAG 层依赖规则）
-->

---

## Scope

> ⚠️ **此节为必填项**，mms precheck 解析此表格以建立基线。节名必须为 `## Scope`。

| Unit | 操作描述 | 涉及文件 |
|------|---------|---------|
| U1   | （填写第一个原子操作） | `路径/文件.py` |
| U2   | （填写第二个原子操作） | `路径/文件.py` |

---

## Testing Plan

> ⚠️ **此节为必填项**，mms precheck 解析此列表以建立测试基线。节名必须为 `## Testing Plan`。

- `tests/unit/.../test_xxx.py` — 说明验证内容
