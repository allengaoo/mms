# MMS — 端侧 AI 代码工程工具链

> **将复杂软件任务分解、执行、验证、学习——全程在端侧完成，不上传代码**
>
> MMS（Memory-driven Multi-step System）是一套**端侧 AI 代码工程工具链**。  
> 它以任务分解引擎（AIU/DAG）为驱动核心，以动态知识图谱为记忆后端，以多层安全门控为工程保障，  
> 让本地 32B 参数模型完成过去需要云端大模型才能胜任的复杂代码工程任务。

[CI](https://github.com/allengaoo/mms/actions/workflows/ci.yml)
[Python 3.11+](https://www.python.org)
[Tests](#testing)
[License: MIT](LICENSE)

---

## 它能做什么？

MMS 的定位不是一个 AI 聊天工具，而是一个**工程化的代码任务执行系统**。一次完整的 MMS 工作循环如下：

```
① 任务输入       mms synthesize "新增批量导出 API"
      │
      ▼
② 智能分解       qwen3-32b 生成 DAG（有序 AIU 单元图）
      │           每个 AIU ≤ 4k tokens，含 precheck/postcheck 挂载点
      ▼
③ 上下文注入     从记忆图谱中 hybrid_search 相关架构决策、经验教训、代码模式
      │           精准注入，不超出 4k tokens 预算
      ▼
④ 代码生成       qwen3-coder-next 生成 Diff，受模板骨架约束
      │
      ├─ 可选：双角色内部评审（qwen3-32b 作 Reviewer 检查合规性）
      │
      ▼
⑤ 自动验证       postcheck：pytest 验证 + AST 契约检查 + DB 迁移对齐 + 记忆新鲜度检测
      │           3 级 Feedback 回退（扩预算 → 插前置 → 拆分）
      ▼
⑥ 知识回流       distill/dream：从执行历史萃取经验 → 写回记忆图谱（自动 auto-link）
      │           SanitizationGate：脱敏后才落盘
      ▼
⑦ 下次任务更好   记忆图谱越来越丰富，下一次 AIU 的上下文质量越来越高
```

整个过程可以无人值守（`mms ep run EP-NNN --auto-confirm`），也可以在关键决策点暂停确认。

---

## 为什么是端侧？

### 云端大模型的根本限制

| 限制 | 具体问题 |
|------|---------|
| **安全合规** | 企业核心代码库不能上传到云端（SOC2 / ISO27001 要求） |
| **上下文成本** | 把完整代码库注入大模型，每次任务消耗数万 token |
| **黑盒推理** | 大模型为什么这样写？无法追溯，无法调试，无法改进 |
| **无状态** | 大模型不记得上次任务发生了什么，每次都从零开始 |

### MMS 的解法

**MMS 的核心假设：限制代码生成质量的主要因素不是模型能力，而是上下文质量和任务粒度。**

通过将任务分解为足够细的原子单元（AIU，≤4k tokens），并为每个单元精准注入最相关的历史知识，  
一个 32B 参数的本地模型完全可以完成过去需要 GPT-4 级别模型才能处理的复杂代码变更。

### 设计原则

| 原则 | 实现方式 |
|------|---------|
| **端侧优先** | qwen3-32b（意图 / 推理 / 评审）+ qwen3-coder-next（代码生成），兼顾速度与成本 |
| **工程化执行** | DAG 任务图 + AIU 原子单元 + precheck/postcheck 门控，不是一次性提示词 |
| **记忆驱动** | 动态知识图谱积累跨任务经验，越用越聪明，解决大模型无状态问题 |
| **纯文本存储** | 所有记忆、本体、执行计划均为 Markdown / YAML，无向量数据库依赖 |
| **零强制运行时** | 核心功能仅依赖 `pyyaml` + `structlog`，无需启动任何服务 |
| **企业级安全** | SanitizationGate 脱敏 + 架构约束检查 + DB 迁移门控 + 审计日志 |
| **可观测** | Oracle 10046 风格诊断追踪，每次 LLM 调用、文件操作均有完整记录 |

---

## 工具链五层架构

```
┌─────────────────────────────────────────────────────────────┐
│ 第一层：任务工程层（Task Engineering）                         │
│  mms synthesize → DAG 生成 → AIU 编排 → EP 工作流           │
│  角色：qwen3-32b 意图分解 + DAG 编排                         │
├─────────────────────────────────────────────────────────────┤
│ 第二层：知识记忆层（Knowledge Memory）                         │
│  动态本体图谱：MemoryNode / ArchDecision / Pattern / Lesson   │
│  图遍历：hybrid_search / typed_explore / find_by_concept     │
│  Auto-Link 自动建边 + 记忆新鲜度追踪                          │
├─────────────────────────────────────────────────────────────┤
│ 第三层：代码生成层（Code Generation）                          │
│  上下文注入（< 4k tokens）→ qwen3-coder-next 生成 Diff        │
│  代码模板骨架 + 双角色内部评审（可选）                          │
├─────────────────────────────────────────────────────────────┤
│ 第四层：安全验证层（Safety & Validation）                      │
│  pytest 验证 + AST 契约检测 + DB 迁移门控 + 架构约束扫描        │
│  SanitizationGate（API Key / JWT / IP 脱敏）                 │
│  3 级 Feedback 回退机制                                       │
├─────────────────────────────────────────────────────────────┤
│ 第五层：自学习层（Self-Learning）                              │
│  distill/dream 知识蒸馏 → 写回记忆图谱                        │
│  失败历史 → 代价模型优化 → 下次 AIU 预算更准确                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 项目现状

### 各层已实现能力

**第一层：任务工程**

| 模块 | 状态 | 说明 |
|------|------|------|
| AIU 分解引擎 | ✅ 稳定 | 28 种原子意图类型，6 族，CBO 代价估算 |
| DAG 编排 | ✅ 稳定 | qwen3-32b 生成有序任务图，支持并行 / 串行批次 |
| EP 全自动 Pipeline | ✅ 稳定 | `mms ep run`：precheck → units → postcheck，支持无人值守 |
| 3 级反馈回退 | ✅ 稳定 | 类 DB Query Feedback：扩预算 → 插前置 → 拆分 |
| AIU Registry YAML 扩展 | ✅ 稳定 | 新增 AIU 类型无需修改 Python 源码 |

**第二层：知识记忆**

| 模块 | 状态 | 说明 |
|------|------|------|
| 动态本体（Ontology v4） | ✅ 稳定 | 四层分离架构 + 5 种 ObjectType + 5 种 LinkType |
| 语义图遍历 | ✅ 稳定 | `hybrid_search` / `typed_explore` / `find_by_concept`，O(1) 概念级检索 |
| Auto-Link 自动建边 | ✅ 稳定 | dream 写入记忆时自动提取文件路径和领域概念 |
| 记忆新鲜度追踪 | ✅ 稳定 | `freshness_checker`：代码变更 → cites 边反查 → drift 传播 |
| 图健康监控 | ✅ 稳定 | `mms status` 实时显示节点分布、边覆盖率、孤立率、图密度 |
| 冷启动 Bootstrap | ✅ 稳定 | AST 骨架化 + 种子包注入，< 1s，零 LLM 调用 |

**第三层：代码生成**

| 模块 | 状态 | 说明 |
|------|------|------|
| 上下文精准注入 | ✅ 稳定 | 3 级检索漏斗，< 4k tokens/任务，不稀释模型注意力 |
| 代码模板库 | ✅ 稳定 | 填空式骨架（Service / API / Worker / React Page），降低幻觉率 |
| 双模型对比执行 | ✅ 稳定 | Qwen vs Sonnet 机械 diff + qwen3-32b 语义评审（可选高级模式） |
| 双角色内部评审 | ✅ 稳定 | Feature flag（默认关闭）：Coder 生成后由 Reviewer 检查合规 |

**第四层：安全验证**

| 模块 | 状态 | 说明 |
|------|------|------|
| AST 契约变更检测 | ✅ 稳定 | precheck 快照 vs postcheck diff；语义哈希防格式化引起的虚假漂移 |
| DB 迁移脚本门控 | ✅ 稳定 | postcheck 强制验证 ORM 变更 ↔ up()/down() 迁移脚本对齐 |
| 脱敏屏障（SanitizeGate） | ✅ 稳定 | 落盘前拦截 API Key / JWT / IP，自动替换为 `[REDACTED_*]` |
| 架构约束扫描 | ✅ 稳定 | 6 条硬性规则（AC-1~AC-6），可通过 seed_packs 自定义扩展 |
| 多语言 AST 骨架化 | ✅ 稳定 | Python / Java / Go / TypeScript 四语言统一指纹提取 |
| 诊断追踪（Trace） | ✅ 稳定 | Oracle 10046 风格，4 级诊断级别，完整 LLM 调用审计 |

**第五层：自学习**

| 模块 | 状态 | 说明 |
|------|------|------|
| EP 知识蒸馏（distill） | ✅ 稳定 | 任务完成后自动提炼经验 → MEM-*.md |
| autoDream 蒸馏 | ✅ 稳定 | git 历史 + EP Surprises → 知识草稿（需人工审核升级） |
| Rule Absorber | ✅ 稳定 | `mms seed ingest <url>` 将 .cursorrules/.mdc 蒸馏为 MMS YAML 种子 |
| 代价模型自优化 | ✅ 稳定 | 历史成功率驱动 CBO 预算估算，失败记录影响下次任务拆分 |

**工程基础设施**

| 模块 | 状态 | 说明 |
|------|------|------|
| src/mms/ 分包重组 | ✅ 稳定 | 48 个模块按职责整理为 8 个子包，对外仅暴露核心 API |
| 测试套件 | ✅ 稳定 | **563** 测试用例，无需 LLM API 可全部通过 |

### 技术栈

```
运行时    Python 3.11+  │  pyyaml · structlog（核心依赖，无其他强制依赖）
LLM 集成  Alibaba Bailian · 意图识别 / 推理 / 评审  →  qwen3-32b
                        · 代码生成                   →  qwen3-coder-next
          Anthropic Claude（fallback / 人工介入）
存储      纯文本 Markdown + YAML + JSONL，无数据库，无向量存储
检索      动态知识图谱（hybrid_search）+ 全文预筛（章节匹配，降低 token 消耗）
安全      SanitizationGate 正则脱敏（类 gitleaks 轻量版）+ Append-only 审计日志
测试      pytest 563+，全部可离线运行，mock 掉所有 LLM 调用
```

---

## 核心架构

### 1. 动态本体（Dynamic Ontology）— 四层分离架构

MMS v4.0 采用严格的四层分离架构，将代码结构模型、记忆知识图谱和执行机械彻底隔离：

```
Layer 0: 物理代码库           .py / .java / .ts / git history
    │  AST扫描 bootstrap/postcheck
    ▼
Layer 1: 代码结构模型          ast_index.json / _system/routing/layers.yaml
    │  auto-link 创建 cites/about 边
    ▼
Layer 2: 记忆本体图（核心）    ObjectType + LinkType + Function + Action
    │  inject 注入上下文
    ▼
Layer 3: 执行机械              DAG / AIU / UnitRunner / Trace
    │  distill/dream 生产新记忆
    └─────────────────────────▶ Layer 2（知识回流）
```

**Layer 2（记忆本体图）的 5 种 ObjectType：**

| ObjectType | 说明 | ID 前缀 | 默认 Tier |
|-----------|------|---------|---------|
| `MemoryNode` | 核心知识节点（所有记忆的基类型） | `MEM-L-` | warm |
| `ArchDecision` | 架构决策记录（ADR，最高优先级） | `AD-` | hot |
| `Lesson` | 从 EP 执行中提炼的经验教训 | `MEM-L-` | warm |
| `Pattern` | 可复用的架构/代码模式 | `PAT-` | hot |
| `DomainConcept` | 领域概念锚点（图谱索引节点） | `[layer-id]` | — |

**Layer 2 的 5 种 LinkType（图边）：**

| LinkType | 含义 | 基数 | 自动建边 |
|---------|------|-----|---------|
| `cites` | MemoryNode → CodeFile（引用代码文件） | M:N | ✅ `_auto_link()` 正则提取 |
| `about` | MemoryNode → DomainConcept（描述领域概念） | M:N | ✅ `layers.yaml` 关键词匹配 |
| `impacts` | MemoryNode → MemoryNode（影响关系） | M:N | 可选（`enable_auto_impacts`） |
| `contradicts` | MemoryNode → MemoryNode（矛盾关系） | M:N | 手动 |
| `derived_from` | MemoryNode → MemoryNode（提炼来源） | N:M | 手动 |

**记忆图索引示例（front-matter v4.0）：**

```yaml
---
id: MEM-L-021
layer: L3_domain
tier: hot
tags: [grpc, service-layer, dto]
cites_files:                          # auto-link 自动填充
  - backend/app/services/user_service.py
about_concepts:                       # auto-link 关键词匹配填充
  - l3-domain
  - l2-infrastructure
impacts: [MEM-L-024]                  # 变更时需同步检查的记忆
derived_from: [AD-002]                # 从 ArchDecision 提炼而来
---
# gRPC 服务层 DTO 校验规范
...
```

本体定义存储在 `docs/memory/ontology/`（Layer 2 定义）和 `docs/memory/_system/`（Layer 3 系统对象）：

```
docs/memory/ontology/
├── objects/              # Layer 2 ObjectType 定义
│   ├── memory_node.yaml  # MemoryNode（核心节点类型）
│   ├── arch_decision.yaml
│   ├── lesson.yaml
│   ├── pattern.yaml
│   └── domain_concept.yaml
├── links/                # 5 种 LinkType 定义（YAML 驱动）
│   ├── cites.yaml / about.yaml / impacts.yaml
│   ├── contradicts.yaml / derived_from.yaml
├── _config/
│   └── traversal_paths.yaml   # 图遍历路径配置（新增路径不改代码）
├── actions/              # Layer 2 Action 定义（distill, dream）
└── functions/            # Layer 2 Function 定义（fn_rank_memories 等）

docs/memory/_system/
├── routing/              # 路由配置（原 arch_schema/）
│   ├── layers.yaml       # L1-L5 七层 + 关键词 + 路径前缀
│   └── intent_map.yaml / operations.yaml / query_synonyms.yaml
└── schemas/              # Layer 3 系统对象（执行机械内部对象）
    ├── dag_unit.yaml / aiu_step.yaml / diagnostic_event.yaml
    └── aiu_types_extended.yaml   # AIU 类型 YAML 扩展（新增类型不改 Python）
```

本体与代码之间通过 **AST 物理绑定**（`ast_pointer` 字段）保持同步：

```
mms bootstrap  →  扫描 AST  →  在本体 YAML 中填充 ast_pointer.fingerprint
mms postcheck  →  ast_diff  →  fingerprint 变更 → ontology_syncer 标记 drift=true
               →  freshness  →  cites 边反查记忆 → 标记 drift_suspected
```

### 2. 记忆层级（Memory Layers L1–L5）

记忆以 Markdown front-matter 格式存储，按架构层 + 热度分级管理：

```
docs/memory/shared/
├── L1_platform/         # 安全、认证、多租户（SecurityContext、RLS、RBAC）
├── L2_infrastructure/   # 数据库、Kafka、Redis、对象存储
├── L3_domain/           # 业务领域（本体、数据管道、治理）
├── L4_application/      # 应用服务、Worker 调度
├── L5_interface/        # API、前端页面、测试
└── cross_cutting/       # ADR 架构决策、全链路追踪文档
```

每条记忆包含 v3 图关系字段，支持知识图谱遍历：

```yaml
---
id: MEM-L-021
layer: L3_domain
tier: hot            # hot / warm / cold / archive（驱动 GC 和检索优先级）
tags: [ontology, ObjectTypeDef, primary-key]
related_to:
  - id: AD-002
    reason: "API 必须含 tenant_id 过滤，直接依赖 RLS 基线"
cites_files:
  - backend/app/models/ontology.py
impacts: [MEM-L-024]
ast_pointer:
  file_path: backend/app/models/ontology.py
  class_name: ObjectTypeDef
  fingerprint: "sha256:abc123ef45"
---
# ObjectTypeDef 主键与索引规范
...
```

**章节入口的全文检索预筛：**

记忆检索的核心策略是 Jaccard 关键词匹配 + 知识图谱遍历（无向量数据库）。但在用户输入一个章节路径或章节标题时，系统会额外触发一次轻量全文检索（倒排索引扫描），快速判断是否存在与该章节高度匹配的已有记忆条目。这一步在 LLM 介入之前完成，命中则直接返回匹配章节，从而避免了不必要的 LLM 调用、降低 token 消耗。全文检索不是记忆系统的核心通道，仅作为"入口预筛"使用。

### 3. AIU 执行引擎

```
用户任务描述
    │
    ▼ intent_classifier.py（3级漏斗）
[Level 1] RBO 规则分类（~0ms，零 LLM）
    │ confidence < 0.85
    ▼
[Level 2] 本体关键词匹配（~5ms）
    │ confidence < 0.60
    ▼
[Level 3] LLM 意图分类（~500ms，Bailian fallback）
    │
    ▼ task_decomposer.py
AIU 分解 → 28种类型 × 6族 → AIUStep 列表
    │
    ▼ aiu_cost_estimator.py（CBO 代价估算）
token_budget + model_hint（fast/capable）
    │
    ▼ unit_runner.py（3-Strike 重试循环）
LLM 生成代码 → Scope Guard → 语法验证 → 应用文件
    │                                        │
    │   PASS                           FAIL (retry ≤3)
    ▼                                        ▼
arch_check + pytest                  aiu_feedback.py（3级回退）
    │                                  Level 1: 扩 token_budget × 1.5
    ▼                                  Level 2: 插入前置 AIUStep
git commit + mark_done                 Level 3: 拆分为子 AIUStep
```

**AIU 类型（内置 28 种 + YAML 扩展）：**

| 族                    | 内置类型（节选）                                                                                                                                      | 执行顺序 |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| **A Schema**         | `SCHEMA_ADD_FIELD` · `SCHEMA_MODIFY_FIELD` · `SCHEMA_ADD_RELATION` · `CONTRACT_ADD_REQUEST` · `CONTRACT_ADD_RESPONSE` · `CONTRACT_MODIFY_RESPONSE` | 1    |
| **C Data Access**    | `QUERY_ADD_SELECT` · `QUERY_ADD_FILTER` · `MUTATION_ADD_INSERT` · `MUTATION_ADD_UPDATE` · `MUTATION_ADD_DELETE`                                    | 2    |
| **B Control Flow**   | `LOGIC_ADD_CONDITION` · `LOGIC_ADD_BRANCH` · `LOGIC_ADD_LOOP` · `LOGIC_EXTRACT_METHOD` · `LOGIC_ADD_GUARD`                                         | 3    |
| **E Infrastructure** | `EVENT_ADD_PRODUCER` · `EVENT_ADD_CONSUMER` · `CACHE_ADD_READ` · `CONFIG_MODIFY`                                                                   | 3    |
| **D Interface**      | `ROUTE_ADD_ENDPOINT` · `ROUTE_ADD_PERMISSION` · `FRONTEND_ADD_PAGE` · `FRONTEND_ADD_STORE` · `FRONTEND_BIND_API`                                   | 4–5  |
| **F Validation**     | `TEST_ADD_UNIT` · `TEST_ADD_INTEGRATION` · `DOC_SYNC`                                                                                              | 6–8  |

> **扩展 AIU 类型**：在 `docs/memory/_system/schemas/aiu_types_extended.yaml` 新增条目，无需修改 `aiu_types.py` 源码。AIURegistry 在运行时自动合并 Enum 内置与 YAML 扩展。

### 3.5. 记忆图索引检索（Memory Graph Search）

记忆系统的检索分为三个层次，图检索是核心，全文检索仅作预筛：

```
检索请求（任务描述/关键词）
    │
    ▼ hybrid_search()
[图检索] find_by_concept(keywords)              ← 零 LLM，O(1) DomainConcept 定位
    │   └── _concept_to_ids 反向索引 → MemoryNode
    │   图结果 < 阈值（默认 3）时
    ▼ fallback
[关键词] _keyword_fallback(keywords)            ← 标题 + tags 关键词匹配
    │
    ▼ typed_explore(path_intent)                ← 沿 LinkType 边有向遍历
[图遍历] concept_lookup  : about + related_to   ← 概念级知识查询
         code_change_impact: cites + impacts    ← 代码变更影响分析
         knowledge_expand   : related_to + derived_from ← 知识扩展
```

> **遍历路径可配置**：修改 `docs/memory/ontology/_config/traversal_paths.yaml` 新增路径，无需修改 `graph_resolver.py` 源码。

### 4. EP 工作流（全自动 Pipeline）

EP（Execution Plan，执行计划）是 MMS 的核心工作单元。**默认形态是全自动 Pipeline**：

```bash
# 标准启动方式（推荐）
mms synthesize "新增对象类型批量导出 API" --template ep-backend-api
# → 生成起手提示词，在 Cursor 中生成 EP 文件后执行：
mms ep run EP-NNN --auto-confirm
```

`mms ep run` 自动完成以下阶段，无需人工逐步确认：

```
Phase 0  mms synthesize            意图合成 → 章节提示词
Phase 1  mms precheck              arch_check 基线 + AST 快照 + 记忆注入
Phase 2  mms unit generate         qwen3-32b 编排 DAG，生成 Unit 列表
Phase 3  mms unit run-all          qwen3-coder-next 逐批执行（3-Strike + 沙箱回滚）
Phase 4  mms postcheck             pytest + arch_check + MigrationGate 质量门控
Phase 5  mms distill / mms dream   知识蒸馏 → 自动沉淀到记忆库
```

常用执行选项：

```bash
mms ep run EP-NNN                      # 自动执行，遇到关键决策点暂停确认
mms ep run EP-NNN --auto-confirm       # 完全无人值守（CI / 批量场景）
mms ep run EP-NNN --from-unit U3       # 从指定 Unit 续跑
mms ep run EP-NNN --only U1 U2         # 只执行指定 Unit
mms ep run EP-NNN --dry-run            # 模拟执行，不写文件，不提交 git
```

### 5. 双模型对比执行（可选高级模式）

默认流程由 `qwen3-coder-next` 独立完成代码生成。若需要与 Cursor Sonnet 进行对比选优，可启用双模型工作流（非默认行为）：

```
qwen3-coder-next → qwen.txt  ─┐
                               ├─ mms unit compare → 机械 diff + qwen3-32b 语义评审报告
Cursor Sonnet    → sonnet.txt ─┘
                               └─ mms unit compare --apply qwen|sonnet  → 写入业务文件
```

启用方式：在执行 Unit 时加 `--save-output` 标志，存盘后手动触发对比。

### 6. 诊断追踪（Oracle 10046 风格）

4 级诊断级别，类比 Oracle 10046 Trace：

```
Level 1  Basic    — 步骤耗时、成功/失败、Unit 状态变更
Level 4  LLM      — + 模型名、token 消耗、重试次数、结果
Level 8  FileOps  — + 文件写入路径、行数、Scope Guard 结果
Level 12 Full     — + LLM prompt/response 片段（前 N 字符）
```

### 7. 文件结构

项目采用标准 `src/mms/` 分包结构，对外仅通过 `src/mms/__init__.py` 暴露核心 API：

```
mms/
├── cli.py                       # 统一 CLI 入口（mms <command>）
├── pyproject.toml               # 项目配置（setuptools / pytest）
│
├── src/mms/                     # 核心包（pip install -e . 后可 import mms）
│   │
│   ├── workflow/                # EP 工作流编排
│   │   ├── synthesizer.py       # 意图合成（任务 → Cursor 起手提示词）
│   │   ├── ep_parser.py         # EP Markdown → DagState
│   │   ├── ep_runner.py         # 自动 Pipeline（mms ep run）
│   │   ├── ep_wizard.py         # 交互式向导（mms ep start）
│   │   ├── precheck.py          # 前置基线检查（arch_check + AST 快照）
│   │   ├── postcheck.py         # 后置质量门（pytest + arch_check + MigrationGate）
│   │   └── migration_gate.py    # DB 迁移脚本门控（ORM 变更 ↔ up/down 对齐验证）
│   │
│   ├── dag/                     # DAG & AIU 引擎
│   │   ├── dag_model.py         # DagUnit / DagState 数据模型
│   │   ├── aiu_types.py         # 28 种原子意图类型（6 族）枚举 + AIUStep
│   │   ├── aiu_cost_estimator.py # CBO 风格代价估算（token_budget + model_hint）
│   │   ├── aiu_feedback.py      # 3 级回退反馈（类 DB Query Feedback）
│   │   ├── task_decomposer.py   # AIU 分解器（RBO 规则 + LLM fallback）
│   │   └── atomicity_check.py   # Unit 原子化评分
│   │
│   ├── execution/               # Unit 执行层
│   │   ├── unit_generate.py     # DAG 生成（从 EP 文件生成 Unit 列表）
│   │   ├── unit_runner.py       # Unit 自动执行（3-Strike + SandboxRollback）
│   │   ├── internal_reviewer.py # 双角色内部评审（feature flag，默认关闭）
│   │   ├── unit_compare.py      # 双模型对比 + qwen3-32b 语义评审
│   │   ├── unit_context.py      # 单 Unit 压缩上下文生成器
│   │   ├── unit_cmd.py          # unit 子命令（status/next/done/reset）
│   │   ├── file_applier.py      # 解析并应用 LLM BEGIN/END-CHANGES 块
│   │   ├── sandbox.py           # GitSandbox（文件操作隔离 + 自动回滚）
│   │   └── fix_gen.py           # 自动生成修复建议
│   │
│   ├── memory/                  # 记忆检索与注入
│   │   ├── injector.py          # 记忆注入（检索 + 压缩 → Cursor 上下文前缀）
│   │   ├── intent_classifier.py # 3 级意图漏斗（RBO → 本体匹配 → LLM）
│   │   ├── task_matcher.py      # 任务-记忆相关度匹配
│   │   ├── dream.py             # autoDream（git 历史 + EP → 知识草稿）
│   │   ├── entropy_scan.py      # 孤儿/过时记忆检测
│   │   ├── repo_map.py          # PageRank 风格文件重要性排序
│   │   ├── graph_resolver.py    # 知识图谱（BFS 遍历 + 影响传播）
│   │   ├── codemap.py           # 代码目录快照生成
│   │   ├── funcmap.py           # 函数签名索引生成
│   │   ├── template_lib.py      # 填空式代码骨架模板
│   │   └── private.py           # EP 私有工作区（草稿笔记）
│   │
│   ├── analysis/                # 代码静态分析
│   │   ├── arch_check.py        # 架构约束扫描（6 条规则 AC-1~AC-6）
│   │   ├── arch_resolver.py     # 层 → 文件路径解析器
│   │   ├── ast_skeleton.py      # AST 骨架化（Python/Java/Go/TS 四语言，语义哈希）
│   │   ├── ast_diff.py          # AST diff（检测接口契约变更）
│   │   ├── ontology_syncer.py   # 本体 YAML ↔ AST 同步
│   │   ├── dep_sniffer.py       # 技术栈嗅探（pip/npm/pom.xml/gradle/go.mod）
│   │   ├── doc_drift.py         # 文档漂移检测
│   │   └── seed_absorber.py     # Rule Absorber（URL → 噪声清洗 → YAML 蒸馏）
│   │
│   ├── core/                    # 基础 I/O 工具
│   │   ├── reader.py            # 编码自适应文件读取
│   │   ├── writer.py            # 安全文件写入（集成 SanitizationGate）
│   │   ├── sanitize.py          # 脱敏屏障（API Key / JWT / IP 自动 REDACT）
│   │   └── indexer.py           # 记忆索引构建器
│   │
│   ├── providers/               # LLM Provider 适配器
│   │   ├── factory.py           # 任务 → Provider 路由（支持运行时覆盖）
│   │   ├── bailian.py           # 阿里云百炼（qwen3-32b / qwen3-coder-next）
│   │   └── claude.py            # Anthropic Claude（fallback / 人工介入）
│   │
│   ├── trace/                   # 诊断追踪（Oracle 10046 风格）
│   │   ├── tracer.py            # EPTracer：记录 LLM 调用、文件操作、事件
│   │   ├── collector.py         # Trace 数据采集
│   │   ├── reporter.py          # 报告生成（text / json / html）
│   │   └── event.py             # 事件类型 + 4 级诊断级别
│   │
│   ├── observability/           # 可观测性
│   │   ├── audit.py             # Append-only JSONL 审计日志
│   │   └── tracer.py            # Trace ID 生成器
│   │
│   ├── resilience/              # 可靠性原语
│   │   ├── retry.py             # 指数退避重试装饰器
│   │   ├── circuit_breaker.py   # 熔断器（防止 LLM API 级联故障）
│   │   └── checkpoint.py        # 断点保存/恢复（长时间任务续跑）
│   │
│   └── utils/                   # 工具集
│       ├── mms_config.py        # 配置加载（config.yaml）
│       ├── model_tracker.py     # LLM 用量追踪
│       ├── router.py            # 任务 → Provider 路由
│       ├── validate.py          # Schema 校验
│       ├── verify.py            # 系统健康检查
│       ├── ci_hook.py           # CI 集成 hook
│       └── _paths.py            # 项目路径解析
│
├── seed_packs/                  # 冷启动种子知识包（6 个）
│   ├── base/                    # 通用架构模式（安全、事务）
│   ├── fastapi_sqlmodel/        # FastAPI + SQLModel 后端模式
│   ├── react_zustand/           # React + Zustand 前端模式
│   ├── palantir_arch/           # 本体/元数据平台模式
│   ├── spring_boot/             # Java Spring Boot（Maven/Gradle）模式
│   └── go_gin/                  # Go + Gin Web 框架模式
│       └── {arch_schema/ ontology/ constraints/}  # 每包含三层结构
│
├── docs/memory/                 # 知识库（由 mms 命令自动维护）
│   ├── _system/                 # 系统文件（config.yaml、ast_index、feedback_stats）
│   ├── shared/                  # 积累的记忆（L1–L5 + cross_cutting）
│   ├── ontology/                # 动态本体（objects / actions / functions / arch_schema）
│   ├── private/                 # EP 私有草稿工作区 + trace 数据
│   └── templates/               # EP 任务模板（7 种类型）
│
├── benchmark/                   # 检索质量与代码生成质量基准测试
└── tests/                       # 测试套件（563 测试用例）
```

---

## 快速开始

### 安装

```bash
# 核心依赖（大部分功能不需要 LLM）
pip install pyyaml structlog

# 百炼（阿里云）LLM 支持
pip install openai dashscope

# 克隆并加入 PATH
git clone https://github.com/allengaoo/mms.git
cd mms
export PATH="$PATH:$(pwd)"
```

### 冷启动新项目

```bash
# 在你的项目根目录执行（< 1 秒，零 LLM 调用）
mms bootstrap --root /path/to/your/project

# 执行内容：
# 1. 技术栈嗅探（requirements.txt / package.json）
# 2. 匹配并注入种子知识包到 docs/memory/shared/
# 3. AST 骨架化扫描 → docs/memory/_system/ast_index.json
# 4. 架构层入口点绑定 → ast_pointer 写入本体 YAML
```

可用种子包：


| 种子包                | 触发条件                                  | 注入内容                    |
| ------------------ | ------------------------------------- | ----------------------- |
| `base`             | 任意项目                                  | 安全、事务、通用架构模式            |
| `fastapi_sqlmodel` | requirements 中有 fastapi + sqlmodel    | FastAPI 后端 API 模式       |
| `react_zustand`    | package.json 中有 react + zustand       | 前端页面模式                  |
| `palantir_arch`    | 含本体/元数据关键词                            | 领域建模模式                  |
| `spring_boot`      | pom.xml / build.gradle 中含 spring-boot | Java 分层架构 + DTO + 迁移规则  |
| `go_gin`           | go.mod 中含 gin                         | Go 接口分层 + GORM + 错误包裹规则 |


每个种子包均含三层结构：

- `arch_schema/layers.yaml` — 覆盖默认层级定义（如 Java 的 Controller/Service/Repository）
- `ontology/core_objects.yaml` — 预置业务概念（如 JpaEntity、GormModel）
- `constraints/hard_rules.yaml` — 可被 `arch_check.py` 拦截的硬性红线规则

通过 `mms seed ingest` 可从 GitHub 吸收外部规范自动生成新种子包（见 [Rule Absorber](#rule-absorber)）。

### 配置 LLM Provider

```bash
# 创建配置文件
cat > .env.memory << 'EOF'
DASHSCOPE_API_KEY=sk-your-key-here
DASHSCOPE_MODEL_REASONING=qwen3-32b
DASHSCOPE_MODEL_CODING=qwen3-coder-next
EOF
```

LLM 路由策略：


| 任务     | 默认 Provider     | 模型                 |
| ------ | --------------- | ------------------ |
| 意图合成   | `bailian_plus`  | `qwen3-32b`        |
| DAG 生成 | `bailian_plus`  | `qwen3-32b`        |
| 代码生成   | `bailian_coder` | `qwen3-coder-next` |
| 代码评审   | `bailian_plus`  | `qwen3-32b`        |
| 知识蒸馏   | `bailian_plus`  | `qwen3-32b`        |


```bash
# 运行时覆盖
MMS_TASK_MODEL_OVERRIDE="code_generation:bailian_coder" mms unit run --ep EP-001 --unit U1
```

### 开始第一个任务

```bash
# 第一步：生成 Cursor 起手提示词（在 IDE 中生成 EP 文件）
mms synthesize "新增对象类型批量导出 API" --template ep-backend-api

# 第二步：全自动执行（推荐，无人值守）
mms ep run EP-001 --auto-confirm

# 或保留关键决策点的确认（默认）
mms ep run EP-001

# 需要从中间某个 Unit 续跑时
mms ep run EP-001 --from-unit U3

# 先预览再执行
mms ep run EP-001 --dry-run
```

---

## CLI 参考

### EP 工作流（自动执行）

```bash
mms synthesize "任务描述" --template ep-backend-api    # 生成 Cursor 起手提示词
mms ep run EP-NNN --auto-confirm                       # 全自动执行（无人值守）
mms ep run EP-NNN                                      # 自动执行，关键节点暂停确认
mms ep run EP-NNN --from-unit U3                       # 从 U3 续跑
mms ep run EP-NNN --only U1 U2                         # 只执行指定 Unit
mms ep run EP-NNN --dry-run                            # 模拟执行，不写文件
mms ep status EP-NNN                                   # 查看执行进度
```

### Unit 执行

```bash
mms unit generate --ep EP-NNN               # 生成 DAG（qwen3-32b 编排）
mms unit status --ep EP-NNN                 # 查看各 Unit 执行状态
mms unit run --ep EP-NNN --unit U1          # 单独执行指定 Unit
mms unit run-next --ep EP-NNN              # 执行当前批次全部 Unit
mms unit run-all --ep EP-NNN               # 执行全部剩余 Unit
mms unit done --ep EP-NNN --unit U1         # 手动标记完成 + git commit
mms unit reset --ep EP-NNN --unit U1        # 重置 Unit 状态
```

### Unit 双模型对比（可选高级模式）

```bash
mms unit run --ep EP-NNN --unit U1 --save-output       # qwen 仅生成存盘，不写业务文件
mms unit sonnet-save --ep EP-NNN --unit U1             # 保存 Cursor Sonnet 输出
mms unit compare --ep EP-NNN --unit U1                 # 生成机械 diff + qwen3-32b 语义评审报告
mms unit compare --apply qwen --ep EP-NNN --unit U1    # 应用 qwen 版本到业务文件
mms unit compare --apply sonnet --ep EP-NNN --unit U1  # 应用 Sonnet 版本到业务文件
```

### 记忆管理

```bash
mms search kafka replication           # 关键词检索（Jaccard，无向量）；章节入口预匹配亦可触发全文检索以降低 token 消耗
mms search kafka --preview             # 检索并预览最高匹配内容
mms inject "新增对象类型 API"           # 生成 Cursor 上下文前缀
mms inject "修复 RLS 问题" --mode debug # 调试模式注入
mms list --tier hot                    # 列出热记忆
mms list --layer L3                    # 按层过滤
mms graph stats                        # 知识图谱统计
mms graph explore AD-002               # 从 AD-002 出发 BFS 遍历
mms graph file backend/api/routes.py   # 反查引用该文件的记忆
mms graph impacts AD-002               # 影响传播分析
mms gc                                 # 垃圾回收（LFU 淘汰 + 索引重建）
mms validate --changed-only            # Schema 校验（仅 git diff 范围）
```

### 代码模板

```bash
mms template list                                          # 列出所有模板
mms template info service-method                           # 查看模板变量说明
mms template use service-method --var entity=ObjectType    # 渲染模板
```


| 模板名               | 生成内容                                              |
| ----------------- | ------------------------------------------------- |
| `service-method`  | Service 层方法（SecurityContext + AuditService + RLS） |
| `api-endpoint`    | FastAPI Endpoint + Schema（信封格式 + 权限守卫）            |
| `react-list-page` | ProTable 列表页（useQuery + PermissionGate + Zustand） |
| `worker-job`      | Worker Job（JobExecutionScope + structlog）         |


### 知识蒸馏

```bash
mms distill --ep EP-NNN               # EP 知识蒸馏 → MEM-*.md
mms distill --ep EP-NNN --dry-run     # 预览模式
mms dream --ep EP-NNN                 # autoDream：从 git 历史萃取知识草稿
mms dream --promote                   # 交互式审核 → 升级为正式记忆
mms dream --list                      # 列出所有待处理草稿
mms private init EP-NNN               # 初始化 EP 私有工作区
mms private note EP-NNN "发现一个坑"  # 添加临时笔记
mms private promote EP-NNN note.md L3_domain MEM-L-028  # 升级为公有记忆
```

### 诊断追踪

```bash
mms trace enable EP-NNN --level 4     # 开启追踪（Level 4 = LLM 详情）
mms trace enable EP-NNN --level 12    # 开启全量追踪（含 prompt/response 片段）
mms trace show EP-NNN                 # 查看诊断报告（类 tkprof 输出）
mms trace show EP-NNN --format json   # JSON 格式报告
mms trace summary EP-NNN             # 一行摘要（LLM 次数/总耗时/token）
mms trace list                        # 列出所有有追踪记录的 EP
mms trace clean EP-NNN                # 清除追踪数据
```

### 种子包管理（Rule Absorber）{#rule-absorber}

```bash
mms seed list                                          # 列出所有已安装种子包
mms seed ingest https://raw.github.com/.../rules.mdc   # 从 URL 吸收规范蒸馏为 YAML
mms seed ingest ./local-rules.md --seed-name my_stack  # 从本地文件吸收
mms seed ingest <url> --dry-run                        # 预览蒸馏结果，不写文件
mms seed ingest <url> --force                          # 覆盖已有同名种子包
```

Rule Absorber 工作流：URL 获取 → 噪声清洗（去除 UI 说明性文字）→ 提取规则段落 → `qwen3-32b` 蒸馏 → 写入 `seed_packs/<name>/{arch_schema,ontology,constraints}/`。

### 系统维护

```bash
mms status                            # Provider 健康 + 熔断器 + 记忆统计 + 记忆图健康
mms usage --since 30                  # Token 用量报告（最近 30 天）
mms codemap --depth 3                 # 刷新代码目录快照
mms funcmap                           # 刷新函数签名索引
mms ast-diff --ep EP-NNN              # 检测 precheck 以来的契约变更
mms verify                            # 全面健康检查（schema/index/docs/frontend）
mms reset-circuit                     # 重置所有熔断器
```

`mms status` 包含记忆图健康报告输出示例：

```
【记忆图健康（Memory Graph Health）】
记忆图健康：
  节点总数：142  热节点：38  温节点：84  冷节点：20  归档：0
  有 cites 边：89/142 (63%)       ← 代码变更追踪覆盖率
  有 about 边：61/142 (43%)       ← 概念级检索覆盖率
  有 impacts 边：32/142
  孤立节点（无任何边）：12         ← >20% 时标红，提示需要补充图关系
  平均邻居数：3.2
  图密度：0.022
  ✅ 质量良好：
    - cites 边覆盖率 63%，代码变更追踪能力良好
    - 孤立节点比例 8%，图连通性良好
```
mms hook install                      # 安装 git pre-commit hook
mms incomplete                        # 列出未完成的蒸馏断点
```

---

## 基准测试

基准测试的目的是为了验证基于动态本体的记忆系统在代码生成的准确性等方面要比目前其他的方式更好。如果不需要进行基准测试，不需要部署向量数据库和ES。

```bash
# 检索质量基准（支持 PageIndex / HybridRAG / Ontology 三种系统对比）
python3 benchmark/run_benchmark.py --systems pageindex hybrid_rag ontology

# 代码生成质量基准（20 个 MDP 后端任务，需要百炼 API）
python3 benchmark/run_codegen.py --systems pageindex ontology --full-eval

# 离线预览（不调用 LLM，仅检查结构）
python3 benchmark/run_codegen.py --dry-run
```

### 评估指标

**记忆检索质量：**


| 指标             | 公式                           | 衡量维度         |
| -------------- | ---------------------------- | ------------ |
| Layer Accuracy | `hits / queries`             | L1–L5 层识别正确率 |
| Recall@5       | `relevant in top-5 / total`  | 相关记忆覆盖率      |
| MRR            | `Σ(1/rank_i) / N`            | 平均倒数排名       |
| Path Validity  | `valid_paths / total_paths`  | 文件路径可用率      |
| Context Tokens | `mean(token_count)`          | 上下文 token 效率 |
| Info Density   | `Recall@5 / (tokens / 1000)` | 单 token 信息密度 |
| AIU Precision  | `correct_AIUs / predicted`   | 分解准确率        |


**代码生成质量（主要指标）：**


| 指标                  | 含义                                            |
| ------------------- | --------------------------------------------- |
| **Pass@1**          | 首次执行即通过 pytest 的概率（核心指标，直接衡量生成质量）             |
| **Resolve Rate**    | 在 3 级 Feedback 回退机制下的最终修复率（衡量系统鲁棒性）           |
| Avg Feedback Rounds | 平均 Feedback 轮数（越低越好，目标 < 1.5 轮）               |
| [Legacy] Score      | 原公式评分 `0.1×syntax + 0.3×contract + ...`（仅供参考） |


---

## 配置说明

配置文件位于 `docs/memory/_system/config.yaml`（由 `mms bootstrap` 自动创建）：

```yaml
runner:
  timeout_llm: 180              # LLM 调用超时（秒）
  max_retries: 2                # 3-Strike 重试上限（首次 + 最多重试 2 次）
  enable_internal_review: false # 双角色内部评审（feature flag，默认关闭）
                                # 也可通过环境变量 MMS_ENABLE_INTERNAL_REVIEW=true 开启
  max_tokens:
    code_generation: 4096
    code_review: 4096
    dag_orchestration: 8192

intent:
  confidence_threshold: 0.85   # 低于此值 → LLM fallback
  grey_zone_low: 0.60

dag:
  annotate_threshold_high: 0.85
  report_threshold: 0.75

cost_estimator:
  token_min: 1500              # AIU token 预算下限
  token_max: 16000             # AIU token 预算上限
  default_success_rate: 0.8   # 无历史数据时的乐观估计
  chars_per_token: 4           # 字符/token 估算比

trace:
  default_level: 4             # 默认诊断级别
  max_events: 10000            # 单 EP 最大事件数
```

**双角色内部评审开启方式：**

```bash
# 方式一：环境变量（推荐，无需修改配置文件）
MMS_ENABLE_INTERNAL_REVIEW=true mms unit run --ep EP-123

# 方式二：config.yaml
# runner:
#   enable_internal_review: true
```

开启后，`qwen3-coder-next` 生成的代码 Diff 会先交由 `qwen3-32b`（Reviewer 角色）根据注入的 Ontology 和 AC 规则审查；若发现架构违规（如缺少 DTO 转换、Controller 直接操作数据库），直接生成修改建议打回 Coder 重写，最多 2 轮。

---

## 测试

```bash
# 运行全部测试（无需 LLM API）
pytest tests/ -v

# 仅运行非慢速测试
pytest tests/ -m "not slow and not integration"

# 生成覆盖率报告
pytest tests/ --cov=src/mms --cov-report=html
```

测试结果：**563 通过**，1 个跳过，2 个预期失败（xfail）

---

## Roadmap

### 已完成（v4.x）

**任务工程层**
- ✅ **AIU Registry YAML 扩展**：新增 AIU 类型无需修改 `aiu_types.py`
- ✅ **EP 全自动 Pipeline**：`mms ep run --auto-confirm` 无人值守端到端执行
- ✅ **3 级 Feedback 回退机制**：类 DB Query Feedback 的自适应任务重试策略

**知识记忆层**
- ✅ **四层本体架构分离**：Layer 0-3 职责明确，Layer 2 成为独立的记忆知识图谱
- ✅ **LinkType Registry**：5 种 LinkType（cites/about/impacts/contradicts/derived_from）YAML 驱动
- ✅ **语义图遍历**：`typed_explore` / `find_by_concept` / `hybrid_search`，O(1) 概念级检索
- ✅ **Auto-Link 自动建边**：`dream.py` 写入记忆时自动提取文件路径和领域概念
- ✅ **记忆新鲜度检测**：`freshness_checker.py` 集成 postcheck，代码变更→记忆 drift 传播
- ✅ **图健康监控**：`mms status` 实时显示节点分布、边覆盖率、孤立率、图密度

**安全验证层**
- ✅ **AST 语义哈希**：剔除注释/空白，防格式化工具引起的虚假 drift
- ✅ **DB 迁移脚本门控**：postcheck 强制验证 ORM ↔ up()/down() 对齐
- ✅ **脱敏屏障（SanitizeGate）**：API Key / JWT / IP 写入前强制 REDACT
- ✅ **多语言 AST**：Python / Java / Go / TypeScript 四语言统一骨架化

**自学习层**
- ✅ **Rule Absorber**：`mms seed ingest <url>` 将外部规范蒸馏为 MMS 种子包
- ✅ **双角色内部评审**：Feature flag，Coder 生成后由 Reviewer 检查合规性

### 中期目标（v4.5）

**增强工程化执行能力**
- **多 Agent 并行执行**：多个 UnitRunner 并行处理同一 EP 中无依赖关系的 Unit 批次
- **两阶段提交（2PC）**：引入 git worktree shadow workspace，所有 AIU 通过后才 squash merge 回主分支
- **矛盾检测自动化**：LLM 辅助识别 `contradicts` 边候选（同 DomainConcept 下结论相反的记忆对）

**增强端侧独立性**
- **完全离线模式**：意图分类、代价估算、上下文压缩全部切换为规则/本地模型，实现零云端依赖
- **VSCode / Cursor 插件**：将 `mms inject` 和 `mms status` 集成进 IDE 侧边栏，图形化操作

**增强知识共享**
- **跨项目本体迁移**：`mms export-ontology` 和 `mms import-ontology`，支持在多个项目间共享领域知识

### 长期目标（v5.x）

- **自适应 AIU 引擎**：系统根据执行历史和成功率统计，自动调整 AIU 类型权重和拆分粒度
- **团队知识联邦**：多开发者本地记忆库可选择性同步，实现团队级经验积累
- **代码基因组（Code Genome）**：为项目中每个核心模块维护"基因序列"（变更历史 + 依赖图 + 测试覆盖 + 架构决策链），支持大规模重构的风险评估
- **端侧 Agent 网络**：多个 MMS 实例分布在不同机器，协同完成跨服务的代码工程任务

---

## 如何贡献

MMS 的设计目标之一是让贡献尽可能低门槛——大多数扩展通过 **YAML 文件**完成，无需修改 Python 源码。

### 贡献方向

**YAML 驱动的扩展（无需改 Python 源码）：**

| 方向 | 难度 | 入口文件 |
|------|------|---------|
| 新增种子包 | ⭐ 低 | `seed_packs/<name>/{arch_schema,ontology,constraints}/` |
| 扩充 EP 任务模板 | ⭐ 低 | `docs/memory/templates/` |
| 扩充 AIU 类型 | ⭐ 低 | `docs/memory/_system/schemas/aiu_types_extended.yaml` |
| 新增记忆图遍历路径 | ⭐ 低 | `docs/memory/ontology/_config/traversal_paths.yaml` |
| 新增 LinkType（图边类型） | ⭐⭐ 中 | `docs/memory/ontology/links/<name>.yaml`（`LinkTypeRegistry` 自动加载） |

**Python 代码级扩展：**

| 方向 | 难度 | 描述 |
|------|------|------|
| 新增 LLM Provider | ⭐⭐ 中 | 在 `src/mms/providers/` 实现 `ProviderBase`，注册到 `factory.py` |
| 扩充 Rule Absorber 噪声规则 | ⭐⭐ 中 | 改进 `src/mms/analysis/seed_absorber.py` 噪声清洗正则，提升蒸馏准确率 |
| 新增 postcheck 验证步骤 | ⭐⭐ 中 | 在 `src/mms/workflow/postcheck.py` 添加新的验证门控 |
| 新增安全脱敏规则 | ⭐⭐ 中 | 在 `src/mms/core/sanitize.py` 扩充敏感凭证正则模式 |


### 贡献流程

```bash
# 1. Fork 并克隆
git clone https://github.com/your-username/mms.git
cd mms

# 2. 创建特性分支
git checkout -b feature/my-feature

# 3. 开发前安装开发依赖
pip install pyyaml structlog pytest pytest-cov

# 4. 开发并写测试（测试覆盖率要求 ≥ 80%）
# 所有测试必须可离线运行（mock 掉 LLM API 调用）

# 5. 本地验证
pytest tests/ -v                                  # 全部测试通过
python3 src/mms/analysis/arch_check.py --ci       # 架构约束检查
mms validate --changed-only                        # 记忆文件 Schema 校验（如有修改）

# 6. 提交并推送
git commit -m "feat: add support for Django seed pack"
git push origin feature/my-feature

# 7. 创建 Pull Request
```

### 代码规范

- **新增模块**：放入 `src/mms/` 对应子包，并在 `docs/memory/ontology/` 创建对应 ObjectTypeDef / ActionDef / FunctionDef 本体定义文件
- **新增 AIU 类型**：同步更新 `src/mms/dag/aiu_types.py`、`src/mms/dag/aiu_cost_estimator.py`（`AIU_BASE_COST`）、`docs/memory/ontology/objects/aiu_step.yaml`
- **新增 CLI 命令**：同步更新 `_COMMAND_DOCS` 字典（用于 `mms help`）和本文件的 CLI 参考章节
- **测试要求**：新功能必须包含单元测试，LLM 调用必须通过 mock 处理，确保离线可运行
- **记忆文件**：修改 `docs/memory/shared/` 中的记忆时，遵循 `memory_schema.yaml` v3.0 字段规范
- **架构检查**：`python3 src/mms/analysis/arch_check.py --ci` 代替旧路径 `python3 arch_check.py --ci`

### 本地开发建议

```bash
# 验证 LLM 环境
mms status                            # 检查百炼 API + 记忆系统状态

# 开启诊断追踪调试新功能
mms trace enable EP-DEV --level 8
# ... 运行你的功能 ...
mms trace show EP-DEV

# 运行基准测试验证检索质量
python3 benchmark/run_codegen.py --dry-run   # 离线结构验证
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.