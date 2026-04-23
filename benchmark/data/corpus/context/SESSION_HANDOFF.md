# Session Handoff — 系统状态快照

> 每次 EP 结束后更新本文件。新 EP 开始时 @mention 本文件获取当前状态。
> **格式**：倒序，最新状态在最前面。

---

## 当前状态（更新于 2026-04-14，EP-114 完成后）

### EP-114 · 全流程增强（MMS 工作流升级）

| 组件 | 状态 | 说明 |
|:---|:---|:---|
| `scripts/mms/synthesizer.py` | ✅ 新增 | LLM 意图合成器（qwen-plus），结合记忆+模板生成结构化 Cursor 起手提示词 |
| `scripts/mms/precheck.py` | ✅ 新增 | 代码修改前检查门控：arch_check 基线 + Scope 解析 + 影响范围分析 |
| `scripts/mms/postcheck.py` | ✅ 新增 | 代码修改后校验：pytest（精准）+ arch_check diff + doc_drift |
| `scripts/mms/cli.py` | ✅ 更新 | 新增 synthesize / precheck / postcheck 三个子命令 |
| `docs/memory/templates/ep-*.md` | ✅ 新增 | 5 个 EP 类型提示词模板（含自定义要求区，可编辑） |
| `AGENTS.md` | ✅ 更新 | 工作流升级为 6 步闭环，新增 mms 命令参考 |
| `scripts/mms/providers/bailian.py` | ✅ 更新 | 新增 `complete_messages()` 支持 system+user 多角色消息 |

**新工作流 6 步**：`mms synthesize` → Cursor 生成 EP → `mms precheck` → 修改代码 → `mms postcheck` → `mms distill`

---

## 历史状态（EP-113 完成时，2026-04-14）

### EP-113 · 本体影响分析与版本历史（OrbStack K8s 验证）

| 组件 | 状态 | 说明 |
|:---|:---|:---|
| `GET /api/v1/objects/:id/impact` | ✅ 增强 | 包含 Scenario/SyncJob/风险等级 |
| `GET /api/v1/objects/:id/versions` | ✅ 新增 | 版本历史 + 属性数量统计 |
| 后端镜像 | ✅ `mdp-backend:ep113` | 已部署到 OrbStack K8s |
| 端口转发 | `8001:8000`（后端）`3001:80`（前端） | 与本地服务区分 |
| `docs/memory/shared/L2_infrastructure/environment/` | ✅ ENV-001/ENV-002 | OrbStack K8s 环境 + 宿主机数据源记忆 |

---

## 历史状态（更新于 2026-04-11，EP-107 完成后）

### MMS v2 记忆系统（EP-107 新增）

| 组件 | 状态 | 说明 |
|:---|:---|:---|
| `docs/memory/` | ✅ 初始化完成 | 19 条结构化记忆，Layer×Dimension 双轴组织 |
| `docs/memory/MEMORY_INDEX.json` | ✅ 已创建 | 推理式检索根索引（无向量） |
| `scripts/memory_gc.py` | ✅ 已创建 | 纯规则 LFU 淘汰脚本 |
| `scripts/memory_distill.py` | ✅ 已创建 | Gemini API 驱动蒸馏（key 在 .env.memory） |
| `docs/memory/templates/` | ✅ 已创建 | 7 个分层提示词模版（小模型 ≤50B 优化） |
| `.env.memory` | ✅ 本地（不提交） | Gemini API Key 存储 |

---

## 历史状态（EP-106 完成时，2026-02-24）

### 运行时状态

| 组件 | 状态 | 镜像版本 | Alembic Head | 备注 |
|:---|:---|:---|:---|:---|
| **Docker Compose 后端** | ✅ Running | `mdp-backend:ep105` | `ep104_object_ver_dataset` | EP-103 is_paused + EP-104 default_connector_id/table 均已应用 |
| **Docker Compose 前端** | ✅ Running | `mdp-frontend:ep105` | — | `localhost:3000`；含 EP-105 全部 Bug 修复 |
| **K8s 后端** | ✅ Running | `ep101`（K8s pod） | `ep096_lake_fields` | ⚠️ EP-103/104 迁移**未应用**到 K8s MySQL；需手动同步 |
| **MySQL（Compose）** | ✅ Running | mysql:3306 | `ep104_object_ver_dataset` | 含 logistics_carriers 测试数据 |
| **MySQL（K8s）** | ✅ Running | mysql.mdp.svc | `ep096_lake_fields` | 宿主机连接需 port-forward 3307 |
| **Kafka** | ✅ Running | K8s Kafka | — | EP-101 修复：`REPLICATION_FACTOR=1`，Compose 通过 `192.168.139.2:32092` 访问 |
| **Redis** | ✅ Running | — | — | 用于缓存 + Leader Election |
| **Iceberg (MinIO)** | ✅ SUCCESS | — | — | EP-101 验证：`tenant_001.logistics_carriers` 写入 2 行 |

> ⚠️ **重要架构说明**：前端/API 流量实际走 Docker Compose 栈（`localhost:8000/3000`）；K8s 栈（mdp-backend pod）只作为辅助，不接受外部流量。
>
> 📋 **Alembic Head 说明**：每次执行含模型变更的 EP 后，需同步更新上表中两个 MySQL 的 Alembic Head 列。验证命令：`docker exec mdp-backend sh -c 'cd /app && python -m alembic current'`

### 默认账号
- **管理员**：`admin@mdp.com` / 密码见 README 「Default Test Users」

---

## 活跃 EP（当前进行中）

| EP | 负责人 | 域 | 状态 | 冻结文件（请勿并行修改） |
|:---|:---|:---|:---|:---|
| EP-106 | — | 运维部署 / CI | ✅ 完成 | — |

> **使用规范**：开始新 EP 前在此登记（状态：🔄 执行中）；完成后改为 ✅ 并清除冻结文件，同时在「已完成 EP 摘要」追加条目。
> **协作原则**：冻结文件期间，其他人修改前需先沟通，避免 Session 快照冲突。

---

## 遗留问题与待续工作

### 🟡 中优先级

| 问题 | 背景 |
|:---|:---|
| Schema Registry AVRO 模式兼容性 | EP-097 建立 Schema Registry，但向后兼容策略未全量测试 |
| 连接器 host 配置规范化 | 现有测试连接器 host=127.0.0.1 依赖 MDP_DATA_SOURCE_HOST_ALIAS 替换，生产环境需配置正确 K8s 服务名 |

---

## 已完成 EP 摘要（近期）

| EP | 主要成果 | 状态 |
|:---|:---|:---|
| **EP-106** | CI/CD 测试基础设施全面升级：修复 e2e-rbac.yml（test-results 假报错 + MySQL native_password）；ci.yml 换用 ruff 代替 py_compile（修复 7 个真实 lint 问题）；删除重复的 performance-tests.yml；ruff 自动修复 833 处可自动修复问题 | ✅ 完成（2026-02-24） |
| **EP-105** | 7 处 Bug 全修复：/sync-jobs 500（ep103 迁移）、表级计划空、DataSet tab 联动、共享属性 tab 重构（改为存储属性选择器）、主键标识修复（local_api_name vs primary_key_prop）、Usage 属性列、N:M 关系属性乱码（dict 格式解析）；重建并部署 ep105 前后端镜像 | ✅ 完成（2026-02-24） |
| **EP-103** | SyncJob 暂停/恢复：SyncJobStatus.PAUSED、SyncJob.is_paused、POST /sync-jobs/:id/pause|resume、trigger 拒绝已暂停任务、Scheduler 排除 is_paused、单元测试 5 条 | ✅ 完成（2026-03-07） |
| **EP-102** | 知识体系优化：移除 3 个 alwaysApply（-4,000t/次）、global-constraints +3条、MASTER_INDEX 增强、PR 模板、8 Manifest 维护者声明等 | ✅ 完成（2026-03-07） |
| **EP-101** | 诊断并修复 Iceberg 写入卡死 RUNNING：三根因（Kafka replication.factor、consumer.start()无超时、Avro格式不匹配），全链路 lake_status=SUCCESS 验证通过 | ✅ 完成（2026-03-06） |
| **EP-100** | 诊断并修复 `rows_affected=0` + `关联表计划`为空：根因为 Docker Compose 运行旧镜像 v21，重建部署 ep100 | ✅ 完成（2026-03-06） |
| **EP-099** | 知识索引系统：global-constraints + 路由 + 8 Manifest + 记忆层 + 工作流接入 | ✅ 完成（2026-02-24） |
| **EP-098** | Avro normalizer 重构（NullSafeNormalizer）+ base.py or-Bug 修复 + SyncJobDetail UI 重构 | ✅ 完成（EP-100 验收） |
| **EP-097** | Schema Registry 集成 + rows_affected 计数逻辑 + Pipeline UI 修复 | ✅ 完成 |
| **EP-096** | 数据管道完整闭环：Iceberg + Kafka + Connector Sync | ✅ 完成 |
| **EP-095** | Kafka 共享属性 + MN Link 修复 | ✅ 完成 |
| **EP-094** | 本体 UI + Kafka 集成 | ✅ 完成 |

---

## 架构关键路径

```
数据流：Source DB → IngestionWorker → normalize_record() → KafkaDataProducer
                  → Kafka Topic → Iceberg Sink → Query Service

本体流：ObjectTypeDef → ObjectInstance → Action(WriteBack) → Control Service
                     → Kafka Event → Index Worker → Milvus/ES
```

---

## 下次 EP 建议起手文件

```
@docs/context/MASTER_INDEX.md
@docs/context/SESSION_HANDOFF.md
@docs/context/{域 Manifest}.md
```

---

## 历史快照归档

### 状态快照 v1（EP-098 完成前，2026-02-24）

- 后端：`mdp-backend:ep097`（EP-096~097 的管道完整闭环版本）
- 已知问题：`rows_affected=0`、`关联表计划` 为空
- 前端：SyncJobDetail 组件展示逻辑待重构
