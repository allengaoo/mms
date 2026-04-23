# Lessons Learned — 跨 EP 经验积累

> 每次 EP 结束后追加新发现。格式：倒序，最新经验在最前面。
> 与 `docs/hotfix/` 的区别：hotfix 记录"已知故障 + 修复步骤"；此处记录"设计教训 + 为何这样决策"。
>
> **剪枝策略**：条目超过 25 条时，将 6 个月前且在近 5 个 EP 中未被引用的条目移入 `docs/context/LESSONS_LEARNED_ARCHIVE.md`。
> **格式要求**：每条必须包含「触发条件 + 动作/结论 + 禁止项 + 来源 EP」四要素，便于小模型高效解析。

---

## EP-101 经验（2026-03-06）

### L-010 · Kafka 单节点必须显式设置 offsets.topic.replication.factor=1

**背景**：`GroupCoordinatorNotAvailableError` 是 K8s 单 broker Kafka 最常见的陷阱。默认 `replication.factor=3` 使 `__consumer_offsets` 无法满足 ISR → Consumer Group 无法协调。

**根因**：`AIOKafkaConsumer.start()` 内部无限重试 FindCoordinator，**不向外抛出异常**，导致整个协程挂死。

**修复**：
1. Kafka StatefulSet 加 3 个 env：`KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1`、`KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1`、`KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1`
2. `consumer.start()` 用 `asyncio.wait_for(..., timeout=kafka_connect_timeout_seconds)` 包裹（二次保险）

**K8s patch 命令**（无需修改 StatefulSet yaml，避免 resourceVersion 冲突）：
```bash
kubectl patch statefulset kafka -n mdp --type=json -p='[
  {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR","value":"1"}},
  {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR","value":"1"}},
  {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"KAFKA_TRANSACTION_STATE_LOG_MIN_ISR","value":"1"}}
]'
```

---

### L-011 · Kafka 生产/消费 Avro 格式必须一致：schemaless vs container

**背景**：`kafka_producer.py` 用 `fastavro.schemaless_writer`（无头部），`lake_writer.py` 用 `fastavro.reader`（期望完整容器格式含 Avro 头部）。两者不兼容导致所有消息解码失败，lake_writer 超时 SKIPPED。

**规范**：
- **Producer**：使用 `fastavro.writer(buf, schema, [record])` 写入完整 Avro 容器
- **Consumer**：使用 `fastavro.reader(buf)` 读取（可自动推断 schema）
- 不允许混用 schemaless 与 container 格式

---

## EP-100 经验（2026-03-06）

### L-008 · 双栈运行陷阱：Docker Compose + K8s 共存时流量路由不透明

**背景**：EP-100 发现项目同时运行 Docker Compose 栈（`mdp-backend:v21` 绑定 `0.0.0.0:8000`）和 K8s 栈（`mdp-backend:ep098`）。所有 `localhost:8000` 请求走 Docker Compose 旧版，EP-098 的代码修复对用户完全无效。

**教训**：**每次重建镜像后必须同步更新 Docker Compose 容器**，不能只更新 K8s 镜像。验收时必须用 `docker ps` 确认当前监听 8000 端口的是哪个容器及其镜像版本。

**检测命令**：
```bash
lsof -nP -i TCP:8000          # 确认监听进程
docker ps | grep "8000->8000"  # 确认 Docker Compose 绑定容器
docker inspect <container> | grep Image  # 确认实际镜像
```

**规范**：EP 执行计划中的"镜像重建"步骤必须同时包含 `docker compose up -d` 步骤，或明确说明只更新 K8s 镜像（不影响 Compose 栈）。

---

### L-009 · kubectl logs 日志不可见的根因是 PYTHONUNBUFFERED 未设置

**背景**：EP-100 调查时发现 K8s 后端 Pod 触发 ingestion 任务后完全没有日志输出，导致排查困难。根因是容器未设置 `PYTHONUNBUFFERED=1`，Python stdout 为块缓冲模式。

**教训**：K8s 容器 Dockerfile 或 Deployment 必须设置 `ENV PYTHONUNBUFFERED=1` 以确保日志实时流到 `kubectl logs`。

```dockerfile
ENV PYTHONUNBUFFERED=1
```

---

## EP-098/097 经验（2026-02-24）

### L-001 · Python `or` 不能用于数值型默认值

**背景**：EP-098 Unit 1 发现 `base.py` 中 `scope.rows_affected = job.rows_affected or 0`，当 `job.rows_affected = 0`（合法值）时，`0 or 0` 返回 `0`，表面无误，但 `0 or 5 = 5`（旧值覆盖新值）。

**教训**：**Python 的 `or` 是布尔短路，不是"None 检查"**。数值型字段的默认值必须用 `if x is None else x`。

```python
# 错误
rows_affected = job.rows_affected or 0

# 正确
rows_affected = job.rows_affected if job.rows_affected is not None else 0
```

**适用范围**：任何数值、列表、字典字段的默认值赋值。

---

### L-002 · Avro 序列化静默失败的根因模式

**背景**：EP-098 诊断出 `rows_affected` 为 0 的另一个根因：原始 PostgreSQL 数据（含 `asyncpg.pgproto.UUID`、`datetime.date`、`Decimal`）在送入 `fastavro` 前未归一化，导致序列化失败被静默吞掉，整条消息丢失。

**教训**：`fastavro` 对类型极其严格；任何不在 Avro schema 原生类型集合内的 Python 对象都会导致 `ValueError`，**但这个 ValueError 在批处理循环中很容易被宽泛的 except 吃掉**。

**设计决策**：在 Kafka Producer 层之上增加 `normalize_record()` 归一化门；未来所有新数据源（MySQL/S3/FTP/Kafka）都必须经过此门。

---

### L-003 · Duck-typing 处理第三方库类型优于显式 import

**背景**：EP-098 设计 `NullSafeNormalizer` 时，需要处理 NumPy scalar（`.item()`）和 `asyncpg.pgproto.UUID`（`.isoformat()`），但不想在 normalizer 中 `import numpy` 或 `import asyncpg`（增加耦合）。

**教训**：用 `getattr(value, "item", None)` 探针替代直接 import，实现零依赖的第三方类型处理。模式可推广到所有"需要处理但不想依赖"的外部类型。

---

### L-004 · Docker 镜像构建的上下文陷阱

**背景**：EP-098 部署时，在项目根目录执行 `docker build -f backend/Dockerfile .` 导致 `requirements.txt` 路径找不到（COPY 路径相对于 build context）。

**教训**：**`COPY requirements.txt .` 中的 `requirements.txt` 相对于 build context，不是 Dockerfile 所在目录**。解决方案：在 `backend/` 目录下执行 `docker build .`，使 context = Dockerfile 所在目录。

---

### L-005 · `kubectl set-image` 必须查容器名

**背景**：EP-098 部署时执行 `kubectl set image deployment/mdp-backend mdp-backend=...` 报 `unable to find container named "mdp-backend"`，实际容器名是 `api`。

**教训**：K8s Deployment 的容器名由 `spec.template.spec.containers[].name` 决定，**与 Deployment 名字无关**。每次 `set-image` 前必须先查：`kubectl get deployment xxx -n mdp -o jsonpath='{.spec.template.spec.containers[*].name}'`

---

## EP-096/097 经验（参考）

### L-006 · Schema Registry BACKWARD 兼容策略

**背景**：EP-097 引入 Confluent Schema Registry 后，向已有 Avro schema 新增字段时，若无 `"default": null`，BACKWARD 检查会失败导致发布拒绝。

**教训**：新增字段必须有默认值（`"default": null` 或具体值）。删除字段比新增字段破坏性更强，需要 FULL 兼容模式。

---

### L-007 · Iceberg 写入需要显式 commit

**背景**：EP-096 中 PyIceberg 写入数据后未调 `table.transaction().commit_transaction()`，数据在 S3 但元数据未更新，查询返回空。

**教训**：PyIceberg 写入是事务性的，必须显式 commit；Iceberg Table 的元数据（manifest files）和数据文件是分离的。
