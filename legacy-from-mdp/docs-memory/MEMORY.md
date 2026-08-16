# MDP Memory Pointer Index
> **本文件是记忆指针索引，不是记忆存储。**
> 每行格式：`- [标题](相对路径) — 一行语义摘要`（≤120 字符）
> 机器可读完整索引：`MEMORY_INDEX.json` | Agent 完整工作流：`../../docs/context/WORKFLOW.md`
>
> 维护规则：
> - 新增记忆文件 → 同步添加一行指针（在对应 tier 区块内）
> - 记忆内容过时 → 删除或修改对应行
> - 行数上限：200 行；文件上限：25KB
> 最后更新：EP-116 · 2026-04-16

---

## 🔥 Hot — 高频约束（违反直接导致 Bug 或架构腐化）

### 事务与数据库

- [autobegin 后禁止再调 session.begin()](shared/L2_infrastructure/D9_database/MEM-DB-002.md) — session.execute() 触发 autobegin 后再调 begin() 报 InvalidRequestError，选 Strategy A 或 B
- [SQLAlchemy 事务策略二选一](shared/cross_cutting/decisions/AD-005.md) — Strategy A: begin-first；Strategy B: autobegin + explicit commit。同一方法禁止混用
- [Python or 不能用于数值型默认值](shared/L2_infrastructure/D4_resilience/MEM-L-001.md) — `0 or default` 返回 default（错误），数值字段必须用 `if x is None`

### 安全与多租户

- [RLS 基于 tenant_id（架构基线）](shared/cross_cutting/decisions/AD-002.md) — 所有 DB 查询必须 WHERE tenant_id = ctx.tenant_id，违反导致跨租户数据泄露
- [Modular Monolith 架构基线](shared/cross_cutting/decisions/AD-001.md) — 禁止拆微服务，内部调用走函数，外部边界走 Kafka

### 数据管道与 Kafka

- [Avro 序列化静默失败：必须过归一化门](shared/L2_infrastructure/D4_resilience/MEM-L-002.md) — Kafka 发送前必须调 normalize_record()，禁止发送含 date/Decimal/UUID 原生类型
- [Kafka Avro + Schema Registry（架构决策）](shared/cross_cutting/decisions/AD-004.md) — 所有 Kafka 消息用 Avro 序列化，Schema Registry 管理 schema 演化
- [Avro 格式必须一致：container 非 schemaless](shared/L2_infrastructure/D6_messaging/MEM-L-011.md) — 生产端用 fastavro.write，消费端必须用 fastavro.reader，混用导致解析错误
- [Schema Registry BACKWARD 兼容](shared/L2_infrastructure/D6_messaging/MEM-L-006.md) — 新字段必须有 default 值，否则旧 Consumer 反序列化失败
- [Kafka 单节点必须设 replication.factor=1](shared/L2_infrastructure/D6_messaging/MEM-L-010.md) — 本地/测试环境未设此项会导致 Topic 创建失败
- [NullSafeNormalizer 作为 Kafka 归一化强制门](shared/cross_cutting/decisions/AD-007.md) — 所有发送路径必须经过 normalizer，禁止绕过

### 架构边界

- [控制面/数据面严格分离（架构基线）](shared/cross_cutting/decisions/AD-003.md) — services/control 只写 MySQL；向量/搜索写入必须通过 services/dispatch 发 Kafka 事件
- [JobExecutionScope 作为 Worker 唯一状态管理](shared/cross_cutting/decisions/AD-006.md) — Worker 禁止散落 try/except 管理 Job 状态，必须用 JobExecutionScope
- [Duck-typing 处理第三方库类型](shared/L2_infrastructure/D4_resilience/MEM-L-003.md) — 用 hasattr+callable 探针处理 numpy/asyncpg 类型，避免硬依赖 import

### API 规范

- [API 响应必须用 Envelope 格式](shared/L5_interface/D8_api/MEM-L-020.md) — 返回 {"code": 200, "data": ..., "meta": ...}，禁止裸列表或裸字典
- [DomainException 必须映射 error_registry](shared/L5_interface/D8_api/MEM-L-022.md) — raise DomainException(code="E_MODULE_ID")，code 必须在 error_registry.md 中注册
- [大数据量列表 API 必须用 cursor 分页](shared/L5_interface/D8_api/MEM-L-021.md) — offset 分页在百万级数据退化严重，超过 10K 条必须改 cursor-based

### 前端

- [管理页面用 React + ProComponents](shared/L5_interface/frontend/MEM-L-023.md) — Amis JSON 只用于 Chat2App 模块，管理页面必须是 TypeScript React 组件
- [Zustand Store 按业务域划分](shared/L5_interface/frontend/MEM-L-024.md) — 禁止 God Store，每个域独立 Store，跨域用 selector，禁止直接修改其他域 Store
- [PermissionGate 细粒度权限控制](shared/L5_interface/frontend/MEM-L-025.md) — 按钮/字段级权限用 PermissionGate，禁止只做页面级路由守卫

### 本体（Ontology）

- [ObjectTypeDef 必须设 primary_key + unique_key](shared/L3_domain/ontology/MEM-L-012.md) — 缺少这两个字段会导致 Milvus 检索退化为全量扫描
- [Action 回写用 overlay 机制](shared/L3_domain/ontology/MEM-L-013.md) — Action 结果写入 sys_object_edits，不直接修改原始 Object 数据
- [SharedProperty 变更必须先做影响分析](shared/L3_domain/ontology/MEM-L-014.md) — 修改 SharedProperty 前必须查询所有引用方，级联影响所有使用该属性的 ObjectType
- [ObjectType 版本历史通过独立 API 暴露](shared/L3_domain/ontology/MEM-L-015.md) — 版本历史不应内联在 ObjectType 详情 API 中

### 治理

- [TenantQuota 计数必须用原子 INCR](shared/L3_domain/governance/MEM-L-018.md) — Redis 配额计数禁止 GET+SET（竞态），必须用 INCR/DECR 原子操作

### 测试

- [后端用 Polyfactory + dirty-equals](shared/L5_interface/D10_testing/MEM-L-026.md) — 测试数据用 Polyfactory 生成，断言用 dirty-equals 做模糊匹配，禁止手写大量 fixture
- [前端用 MSW + renderWithProviders](shared/L5_interface/D10_testing/MEM-L-027.md) — MSW 拦截 API，renderWithProviders 注入 Store 和 Router，禁止真实 HTTP 调用

### 运维与部署

- [双栈部署流量路由陷阱](shared/L4_application/workers/MEM-L-008.md) — Compose 和 K8s 并存时，K8s Service 和 Compose port-forward 可能路由到不同实例
- [kubectl logs 不可见：PYTHONUNBUFFERED](shared/L1_platform/D3_observability/MEM-L-009.md) — 未设 PYTHONUNBUFFERED=1 时 Python 日志缓冲，kubectl logs 看不到输出
- [kubectl set-image 必须先查容器名](shared/L4_application/workers/MEM-L-005.md) — 容器名不是 Deployment 名，必须先 kubectl describe 查 spec.containers[].name
- [Docker COPY 路径相对 build context](shared/L4_application/workers/MEM-L-004.md) — COPY 路径相对于 -f 指定的 build context 目录，而非 Dockerfile 所在目录
- [Iceberg 写入需要显式 commit](shared/L2_infrastructure/storage/MEM-L-007.md) — Iceberg 写入后必须显式 commit()，否则元数据不更新，数据不可见

### MMS 与知识系统

- [知识索引三层架构](shared/cross_cutting/decisions/AD-008.md) — MEMORY_INDEX.json（机器）+ MEMORY.md（Agent）+ task_quickmap.yaml（静态兜底）三层分工

### 业务流程（BIZ）

- [全域对象类型创建与修改流程](shared/BIZ/BIZ-001.md) — 全域 ObjectType 的完整生命周期：草稿→发布→影响分析→修改审批
- [数据同步管道创建与调度执行流程](shared/BIZ/BIZ-002.md) — SyncJob 从 Connector 配置到调度执行的完整流程
- [IngestionWorker 必须用 JobExecutionScope](shared/L3_domain/data_pipeline/MEM-L-016.md) — 数据载入 Worker 禁止散落 try/except，必须用 JobExecutionScope 管理 Job 状态

### 环境配置

- [K8s 生产模拟环境部署快照（OrbStack）](shared/L2_infrastructure/environment/ENV-001.md) — OrbStack K8s 集群的完整部署配置和连接方式

---

## 🌡 Warm — 中频（按需读取）

- [DataCatalog 列映射 auto 模式陷阱](shared/L3_domain/data_pipeline/MEM-L-017.md) — auto 模式下列名变更会静默断开映射，生产环境建议用 manual 模式
- [CR 审批流状态必须持久化到 MySQL](shared/L3_domain/governance/MEM-L-019.md) — Redis 只用于加速读，写操作必须先写 MySQL 再更新 Redis
- [多租户隔离与配额治理规则](shared/BIZ/BIZ-003.md) — 配额检查在 Service 层执行，Quota 超限返回 E_QUOTA_EXCEEDED
- [宿主机测试数据源配置](shared/L2_infrastructure/environment/ENV-002.md) — 宿主机跑集成测试时 MySQL/PostgreSQL 端口转发配置

---

## 🧊 Cold — 低频（全量检索时包含）

- [Connector 连接测试必须在独立超时内完成](shared/L3_domain/data_pipeline/MEM-L-015.md) — 连接测试禁止阻塞 API 主线程，必须设 timeout 并异步执行
- [影响分析 API 须扩展风险维度](shared/L3_domain/governance/MEM-L-016.md) — 影响分析需包含依赖计数和风险等级（high/medium/low）
- [EP 蒸馏必须绑定显式触发](shared/cross_cutting/decisions/AD-028.md) — distill 不自动触发，需在 postcheck PASS 后根据判断框架决定是否执行
