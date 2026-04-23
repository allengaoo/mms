# MDP 知识索引 · 主路由

> **每次开始新 EP 时 @mention 本文件**，然后根据 EP 类型加载对应 Manifest。
> 始终同时加载：`docs/context/SESSION_HANDOFF.md`（当前系统状态）

---

## EP 类型 → Manifest 路由表

> 「DB 迁移」「后端镜像」「前端镜像」列为**典型情况**，具体以 EP Plan 中的 [Runtime 声明](docs/context/ep_plan_template.md) 为准。

| EP 类型 | 何时使用 | 加载文件 | 🗄️ DB 迁移? | 🔧 后端镜像? | 🖥️ 前端镜像? |
|:---|:---|:---|:---|:---|:---|
| **后端 API** | 新增 Endpoint / Service / Model / Repository | `@docs/context/backend-api.md` | 可能（看模型） | ✅ 是 | ❌ 否 |
| **数据管道** | Ingestion Worker / Kafka / Iceberg / 连接器 | `@docs/context/data-pipeline.md` | 可能（看模型） | ✅ 是 | ❌ 否 |
| **前端** | 新增页面 / 组件 / 路由 / Zustand Store | `@docs/context/frontend.md` | ❌ 否 | ❌ 否 | ✅ 是 |
| **本体** | Object / Link / Action / Function / 画布 | `@docs/context/ontology.md` | 可能 | ✅ 是 | ✅ 是 |
| **权限/安全** | RBAC / ACL / 多租户 / 审计 | `@docs/context/rbac.md` | 可能 | ✅ 是 | 可能 |
| **运维/DevOps** | Docker / K8s / 镜像 / 端口转发 / CI | `@docs/context/devops.md` | 可能 | ✅ 是 | ✅ 是 |
| **故障排查** | Bug 诊断 / Hotfix / 性能问题 | `@docs/context/debug.md` | 可能 | 可能 | 可能 |
| **全栈** | 跨越多层的复合 EP | `@docs/context/fullstack.md` | 可能 | ✅ 是 | ✅ 是 |

---

## 加载协议

```
新 EP 标准起手式：

@docs/context/MASTER_INDEX.md
@docs/context/SESSION_HANDOFF.md
@docs/context/{对应域 Manifest}.md

EP 类型：[从上表选择]
需求描述：[一句话说清要做什么]
额外上下文（可选）：[特殊约束或背景]
```

**EP Plan 文件**：创建 `docs/execution_plans/EP-{NNN}_{Feature}.md` 时，以 `docs/context/ep_plan_template.md` 为模板。
Plan 阶段必须填写 **Runtime 声明节**（DB迁移 / 后端镜像 / 前端镜像 / 环境变量 / Kafka / 种子数据），提前暴露部署成本。

**File Reading Protocol（临时对话同样适用）**：
- 优先读接口定义（Abstract Base Class / Protocol），而非具体实现
- 先读 `docs/specs/` 再读代码，避免用实现猜意图

**文档变更时**：加载 `@.cursor/rules/doc_maintainer.mdc` 获取 e2e_traceability / frontend_page_map 同步规范

---

## Model 路由速查

| 任务类型 | 推荐模型 | 备注 |
|:---|:---|:---|
| 单文件 Bug 修复 / 简单字段追加 | **fast model** | MASTER_INDEX + SESSION_HANDOFF + 1 Manifest |
| 新增 Endpoint（有现成模板） | **fast model** | 同上 + backend-gen 关键段落 |
| 跨层故障诊断 | **capable（诊断）→ fast（执行）** | 诊断完 /compact，再切 fast model |
| 架构设计 / 全栈变更 / 新 EP 规划 | **capable model 全程** | 全量加载多 Manifest + skills |

---

## Strategic Compact 触发点

| 触发点 | 时机 |
|:---|:---|
| A · 诊断完成 | 故障根因已确定 → 开始执行修复前 → `/compact` |
| B · 大量读取后 | 读取文件超过 10 个 → 开始写代码前 → `/compact` |
| C · EP 切换 | 前一 EP 完成、记忆更新完毕 → 新建对话或 `/compact` 后重新 @起手文件 |

---

## EP 验收入口

EP 所有代码完成后执行：

```
@.cursor/rules/post-task.mdc
```

---

## 记忆层（深度上下文）

> **EP-107 起升级为 MMS v2**：Layer×Dimension 结构化记忆库，推理式检索（无向量，节省 65% token）

### MMS v2 检索协议（优先使用）
```
Step 1：读 docs/memory/MEMORY_INDEX.json（≈3K token，替代手工 @mention 10 文件）
Step 2：用任务关键词匹配 trigger_keywords → 定位 (layer, dimension) 节点
Step 3：读 top-3 hot 记忆（≈1.5K），总预算 ≤5K token
```

### 分层提示词模版（小模型 ≤50B 优化）

| 模版 | 适用场景 |
|:---|:---|
| `docs/memory/templates/L2-database-write.md` | DB 写操作 / Service |
| `docs/memory/templates/L2-kafka-producer.md` | Kafka / Ingestion Worker |
| `docs/memory/templates/L4-control-service.md` | Control Service |
| `docs/memory/templates/L5-api-endpoint.md` | REST API Endpoint |
| `docs/memory/templates/L5-frontend-page.md` | 前端页面/组件 |
| `docs/memory/templates/L3-ontology.md` | 本体领域操作 |
| `docs/memory/templates/debug-single-file.md` | 单文件 Bug 修复 |

### 旧版记忆文件（仍可查阅，已被 MMS v2 结构化替代）

| 文件 | 内容 | 何时加载 |
|:---|:---|:---|
| `docs/context/LESSONS_LEARNED.md` | 跨 EP 经验教训 | 快速查阅（已迁移到 MMS v2） |
| `docs/context/ACTIVE_DECISIONS.md` | 架构决策记录 | 快速查阅（已迁移到 MMS v2） |
| `docs/context/EP_REGISTRY.md` | 历史 EP 索引 | 需引用历史 EP 时 |

---

## 深度知识层（按需）

| 场景 | 加载文件 |
|:---|:---|
| 影响范围分析 | `docs/architecture/e2e_traceability.md` |
| 前端页面/API 对应关系 | `docs/architecture/frontend_page_map.md` |
| 本体 / 调度 / 治理核心概念 | `.cursor/skills/{ontology,scheduler,governance}/SKILL.md` |
| 已知故障模式 | `docs/hotfix/ISSUE-REGISTRY.md` |
| 数据模型定义 | `docs/models/*.json` |
| 业务规约 | `docs/specs/*.md` |

---

## 当前状态快照

> 详见 `docs/context/SESSION_HANDOFF.md`

- **最新完成 EP**：EP-105（2026-02-24）
- **后端镜像版本**：`mdp-backend:ep105`，前端：`mdp-frontend:ep105`（Docker Compose，`localhost:8000/3000`）
- **Alembic Head（Compose）**：`ep104_object_ver_dataset`
- **遗留问题**：K8s MySQL 仍在 ep096，需手动同步 ep103+ep104 迁移；Schema Registry Avro 向后兼容策略未全量测试
