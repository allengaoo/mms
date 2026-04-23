# Active Decisions — 架构决策记录

> 记录关键架构决策，包含背景、决策内容、替代方案和影响。
> 格式：倒序，最新决策在最前面。ADR（Architecture Decision Record）风格。

---

## AD-008 · 知识索引三层架构（EP-099，2026-02-24）

**决策**：引入三层知识索引（global-constraints / Domain Manifests / Deep Knowledge），通过 `MASTER_INDEX.md` 路由。

**背景**：随着项目 EP 数量超过 99 个，每次新 EP 需要手工 @mention 10+ 个文件；约束分散导致模型跟随性差。

**替代方案**：
- A. 继续手工 @mention（维护成本高，效率低）
- B. 将所有规则合并为一个超大 `alwaysApply` 文件（token 消耗过高，失焦）
- **C（选择）**：分层索引，按需加载，`global-constraints.mdc` 仅保留 18 条红线约束

**影响**：后续所有 EP 需用新起手式（`@MASTER_INDEX + @SESSION_HANDOFF + @{domain}.md`）；历史 EP 不需要改动。

---

## AD-007 · NullSafeNormalizer 作为 Kafka 发送前强制门（EP-098，2026-02-24）

**决策**：在 `infrastructure/connector/normalizer.py` 中实现 `NullSafeNormalizer`，作为所有数据源到 Kafka 的唯一归一化层。

**背景**：PostgreSQL、MySQL、S3 等不同数据源的原生 Python 类型（`asyncpg.UUID`, `datetime.date`, `Decimal`）在 fastavro 序列化时静默失败。

**替代方案**：
- A. 在每个 source adapter 内部各自转换（分散，不一致）
- B. 在 Kafka Producer 内部转换（侵入 MQ 层）
- **C（选择）**：独立 normalizer 层，Worker 层调用，通过注册器支持扩展

**影响**：所有 Ingestion Worker 发 Kafka 前必须调 `normalize_record()`；新增数据源只需注册新类型处理器。

---

## AD-006 · JobExecutionScope 作为 Worker 唯一生命周期管理机制（EP-023/EP-096）

**决策**：所有 Worker 必须通过 `JobExecutionScope` 异步上下文管理器管理 Job 状态（pending→running→completed/failed）。

**背景**：早期 Worker 代码中散落大量 try/except 管理 `job.status`，导致异常路径状态不一致（Job 卡在 running 状态）。

**替代方案**：
- A. 每个 Worker 自行管理状态（已证明不可维护）
- **B（选择）**：`JobExecutionScope` 统一进入/退出，含自动状态翻转和错误捕获

**影响**：所有 Worker 代码结构必须是 `async with JobExecutionScope(...) as scope:`。

---

## AD-005 · SQLAlchemy 事务策略二选一（EP-087）

**决策**：后端写操作必须选且仅选 Strategy A（begin-first）或 Strategy B（autobegin + explicit commit），严禁混用。

**背景**：`AsyncSession` 默认 `autobegin=True`；在 `execute()` 后调 `session.begin()` 导致 `InvalidRequestError: A transaction is already begun`，在生产中造成 500 错误。

**规则**：
- Strategy A：读写混合 + 需要原子性 → `async with session.begin()` 包裹全部
- Strategy B：简单写入（已有 autobegin） → 在末尾显式 `await session.commit()`

---

## AD-004 · Kafka Avro + Schema Registry（EP-097）

**决策**：Kafka 消息统一使用 Avro 格式 + Confluent Schema Registry，替代原 JSON 格式。

**背景**：JSON 格式无 schema 约束，字段变更无法检测，导致消费者静默处理错误格式数据。

**替代方案**：
- A. 继续 JSON（无 schema 保证）
- B. Protobuf（更紧凑，但工具链复杂）
- **C（选择）**：Avro + Schema Registry（`fastavro` 成熟，与 Confluent 生态兼容）

**影响**：新增字段必须有 `default` 值；消费者需用 `fastavro.parse_schema` 解析 schema。

---

## AD-003 · 控制面 / 数据面严格分离（架构基线）

**决策**：`services/control`（MySQL）只管理元数据定义；写向量库/搜索引擎必须通过 Kafka 事件触发 Worker，不能在 HTTP 请求链路中直接写 Milvus/ES。

**背景**：HTTP 请求链路不适合长耗时写操作（超时风险）；向量索引失败不应影响元数据写入事务。

**影响**：向量索引写入是最终一致性（eventual consistency），API 返回 202 Accepted 或轮询。

---

## AD-002 · Row-Level Security 基于 tenant_id（架构基线）

**决策**：多租户隔离通过应用层 RLS 实现（所有查询加 `WHERE tenant_id = ctx.tenant_id`），不使用数据库级 RLS。

**背景**：MySQL 8.0 没有原生行级安全，实现复杂；应用层 RLS 更灵活，可在审计日志中记录 tenant 上下文。

**影响**：每个 Repository 方法必须过滤 `tenant_id`；如遗漏则构成 IDOR（越权访问）漏洞，这是安全红线。

---

## AD-001 · Modular Monolith 而非微服务（架构基线）

**决策**：采用 FastAPI Modular Monolith，模块间通过 Service 层调用，而非独立部署的微服务。

**背景**：团队规模 < 10 人；微服务的网络开销和运维复杂度在当前阶段是负担；未来可按域拆分。

**影响**：所有模块共享一个 FastAPI 实例和数据库连接池；横切关注点（认证、审计、缓存）通过 AOP/Middleware 实现。
