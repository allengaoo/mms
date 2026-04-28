# 木兰（Mulan）— 端侧 AI 编码工具

> 唧唧复唧唧，木兰当户织。
>
> 织布，是最古老的工程：经线定骨架，纬线填逻辑，梭来梭往积累出完整的布匹。  
> 写代码也是这样，**木兰工具**将复杂的软件任务分解为原子工序（AIU），  
> 以积累的架构知识为经、以精准生成的代码为纬，一梭一线织出符合企业约束的高质量工程产物——  
> 全程在端侧完成，不上传一行代码。

[CI](https://github.com/allengaoo/mms/actions/workflows/ci.yml)
[Python 3.11+](https://www.python.org)
[Tests: 847 passed](#测试)
[License: MIT](LICENSE)

---

## 它能做什么？

木兰的定位不是一个 AI 聊天工具，而是一个**工程化的代码任务执行系统**。  
一次完整的织造循环（工作流）如下：

```
① 立经（任务输入）    mulan synthesize "新增批量导出 API"
      │
      ▼
② 理纬（智能分解）    qwen3-32b 生成 DAG（有序 AIU 单元图）
      │               每个 AIU ≤ 4k tokens，含 precheck/postcheck 挂载点
      ▼
③ 穿梭（上下文注入）  从记忆图谱中 hybrid_search 相关架构决策、经验教训、代码模式
      │               精准注入，不超出 4k tokens 预算
      ▼
④ 织造（代码生成）    qwen3-coder-next 生成 Diff，受模板骨架约束
      │
      │
      ▼
⑤ 验布（自动验证）    postcheck：pytest + AST 契约检查 + DB 迁移对齐 + 记忆新鲜度检测
      │               3 级 Feedback 回退（扩预算 → 插前置 → 拆分）
      ▼
⑥ 积纹（知识回流）    distill/dream：从执行历史萃取经验 → 写回记忆图谱（自动 auto-link）
      │               SanitizationGate：脱敏后才落盘
      ▼
⑦ 炉火纯青           记忆图谱越来越丰富，下一次 AIU 的上下文质量越来越高
```

整个过程可以无人值守（`mulan ep run EP-NNN --auto-confirm`），也可以在关键决策点暂停确认。

---

## 为什么是端侧？

### 云端大模型的根本限制


| 限制        | 具体问题                               |
| --------- | ---------------------------------- |
| **安全合规**  | 企业核心代码库不能上传到云端（SOC2 / ISO27001 要求） |
| **上下文成本** | 把完整代码库注入大模型，每次任务消耗数万 token         |
| **黑盒推理**  | 大模型为什么这样写？无法追溯，无法调试，无法改进           |
| **无状态**   | 大模型不记得上次任务发生了什么，每次都从零开始            |




**核心假设：限制代码生成质量的主要因素不是模型能力，而是上下文质量和任务粒度。**

将任务分解为足够细的原子工序（AIU，≤4k tokens），并为每道工序精准注入最相关的历史知识。

### 设计原则


| 原则         | 实现方式                                                |
| ---------- | --------------------------------------------------- |
| **端侧优先**   | qwen3-32b（意图/推理/评审）+ qwen3-coder-next（代码生成），兼顾速度与成本 |
| **工序化执行**  | DAG 任务图 + AIU 原子工序 + precheck/postcheck 门控，不是一次性提示词 |
| **记忆积累**   | 动态知识图谱积累跨任务经验，越用越聪明，解决大模型无状态问题                      |
| **纯文本存储**  | 所有记忆、本体、执行计划均为 Markdown / YAML，无向量数据库依赖             |
| **零强制运行时** | 核心功能仅依赖 `pyyaml` + `structlog`，无需启动任何服务             |
| **企业级安全**  | SanitizationGate 脱敏 + 架构约束检查 + DB 迁移门控 + 审计日志       |
| **可观测**    | Oracle 10046 风格诊断追踪，每次 LLM 调用、文件操作均有完整记录            |


---

## 工具链五层架构

```
┌─────────────────────────────────────────────────────────────┐
│ 第一层：任务工程层（Task Engineering）                          │
│  synthesize → DAG 生成 → AIU 编排 → EP 全自动 Pipeline        │
│  角色：qwen3-32b 意图分解 + DAG 编排                           │
├─────────────────────────────────────────────────────────────┤
│ 第二层：知识记忆层（Knowledge Memory）                          │
│  动态本体图谱：MemoryNode / ArchDecision / Pattern / Lesson    │
│  图遍历：hybrid_search / typed_explore / find_by_concept      │
│  Auto-Link 自动建边 + 记忆新鲜度追踪                            │
├─────────────────────────────────────────────────────────────┤
│ 第三层：代码生成层（Code Generation）                           │
│  上下文注入（< 4k tokens）→ qwen3-coder-next 生成 Diff         │
│  代码模板骨架 + 双角色内部评审（feature flag，默认关闭）            │
├─────────────────────────────────────────────────────────────┤
│ 第四层：安全验证层（Safety & Validation）                       │
│  pytest + AST 契约检测 + DB 迁移门控 + 架构约束扫描              │
│  SanitizationGate（API Key / JWT / IP 脱敏）                  │
│  3 级 Feedback 回退机制                                        │
├─────────────────────────────────────────────────────────────┤
│ 第五层：自学习层（Self-Learning）                               │
│  distill/dream 知识蒸馏 → 写回记忆图谱                         │
│  失败历史 → 代价模型优化 → 下次 AIU 预算更准确                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 项目现状

### 各层已实现能力

**第一层：任务工程**


| 模块                   | 状态   | 说明                                               |
| -------------------- | ---- | ------------------------------------------------ |
| AIU 分解引擎             | ✅ 稳定 | 28 种原子意图类型，6 族，CBO 代价估算                          |
| DAG 编排               | ✅ 稳定 | qwen3-32b 生成有序任务图，支持并行 / 串行批次                    |
| EP 全自动 Pipeline      | ✅ 稳定 | `mulan ep run`：precheck → units → postcheck，无人值守 |
| 3 级反馈回退              | ✅ 稳定 | 类 DB Query Feedback：扩预算 → 插前置 → 拆分               |
| AIU Registry YAML 扩展 | ✅ 稳定 | 新增 AIU 类型无需修改 `aiu_types.py` 源码                  |


**第二层：知识记忆**


| 模块                | 状态   | 说明                                                               |
| ----------------- | ---- | ---------------------------------------------------------------- |
| 动态本体（Ontology v4） | ✅ 稳定 | 四层分离架构 + 5 种 ObjectType + 5 种 LinkType                           |
| 语义图遍历             | ✅ 稳定 | `hybrid_search` / `typed_explore` / `find_by_concept`，O(1) 概念级检索 |
| Auto-Link 自动建边    | ✅ 稳定 | dream 写入记忆时自动提取文件路径和领域概念，自动建立 cites / about 边                    |
| 记忆新鲜度追踪           | ✅ 稳定 | `freshness_checker`：代码变更 → cites 边反查 → drift 传播                  |
| 图健康监控             | ✅ 稳定 | `mulan status` 实时显示节点分布、边覆盖率、孤立率、图密度                             |
| 冷启动 Bootstrap     | ✅ 稳定 | AST 骨架化 + 种子包注入，< 1s，零 LLM 调用                                    |


**第三层：代码生成**


| 模块      | 状态   | 说明                                               |
| ------- | ---- | ------------------------------------------------ |
| 上下文精准注入 | ✅ 稳定 | 3 级检索漏斗，< 4k tokens/任务，不稀释模型注意力                  |
| 代码模板库   | ✅ 稳定 | 填空式骨架（Service / API / Worker / React Page），降低幻觉率 |
| 双模型对比执行 | ✅ 稳定 | Qwen vs Sonnet 机械 diff + qwen3-32b 语义评审（可选高级模式）  |
| 双角色内部评审 | ✅ 稳定 | Feature flag（默认关闭）：Coder 生成后由 Reviewer 检查合规      |


**第四层：安全验证**


| 模块                 | 状态   | 说明                                                |
| ------------------ | ---- | ------------------------------------------------- |
| AST 契约变更检测         | ✅ 稳定 | precheck 快照 vs postcheck diff；语义哈希防虚假漂移           |
| DB 迁移脚本门控          | ✅ 稳定 | postcheck 强制验证 ORM 变更 ↔ up()/down() 迁移脚本对齐        |
| 脱敏屏障（SanitizeGate） | ✅ 稳定 | 落盘前拦截 API Key / JWT / IP，自动替换为 `[REDACTED_*]`     |
| 架构约束扫描             | ✅ 稳定 | 6 条硬性规则（AC-1~AC-6），可通过 seed_packs 自定义扩展           |
| 多语言 AST 骨架化        | ✅ 稳定 | Python / Java / Go / TypeScript 四语言统一指纹提取         |
| 诊断追踪（Trace）        | ✅ 稳定 | Oracle 10046 风格，4 级诊断级别，完整 LLM 调用审计               |
| 全局告警日志（alert）      | ✅ 稳定 | `alert_mulan.log` 系统心电图，熔断/崩溃事件自动写入，按天轮转          |
| 崩溃现场保全（Incident）   | ✅ 稳定 | sys.excepthook 接管，自动保全 call_stack.dmp + LLM 有毒提示词 |


**第五层：自学习**


| 模块               | 状态   | 说明                                                            |
| ---------------- | ---- | ------------------------------------------------------------- |
| EP 知识蒸馏（distill） | ✅ 稳定 | 任务完成后自动提炼经验 → MEM-*.md                                        |
| autoDream 蒸馏     | ✅ 稳定 | git 历史 + EP Surprises → 知识草稿（需人工审核升级）                         |
| Rule Absorber    | ✅ 稳定 | `mulan seed ingest <url>` 将 .cursorrules/.mdc 蒸馏为 MMS YAML 种子 |
| 代价模型自优化          | ✅ 稳定 | 历史成功率驱动 CBO 预算估算，失败记录影响下次任务拆分                                 |


**工程基础设施**


| 模块            | 状态   | 说明                                                               |
| ------------- | ---- | ---------------------------------------------------------------- |
| src/mms/ 分包重组 | ✅ 稳定 | 48 个模块按职责整理为 8 个子包，对外仅通过 `__init__.py` 暴露                        |
| Benchmark v2  | ✅ 稳定 | 三层模块化评测框架，完全离线可运行（见 [基准测试](#基准测试)）                               |
| 测试套件          | ✅ 稳定 | **847** 测试用例，无需 LLM API 可全部通过                                    |
| MDR 诊断基础设施    | ✅ 稳定 | Oracle ADR 风格：alert_mulan.log + Incident Dump + `mulan diag` CLI |


### 技术栈

```
运行时    Python 3.11+  │  pyyaml · structlog（核心依赖，无其他强制依赖）
LLM 集成  Alibaba Bailian · 意图识别 / 推理 / 评审  →  qwen3-32b
                        · 代码生成                   →  qwen3-coder-next
          Anthropic Claude（fallback / 人工介入）
存储      纯文本 Markdown + YAML + JSONL，无数据库，无向量存储
检索      动态知识图谱（hybrid_search）+ 全文预筛（章节匹配，降低 token 消耗）
安全      SanitizationGate 正则脱敏（类 gitleaks 轻量版）+ Append-only 审计日志
测试      pytest 757+，全部可离线运行，mock 掉所有 LLM 调用
Benchmark 三层评测框架（安全门控 / 记忆质量 / SWE-bench），YAML 驱动可扩展
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


| ObjectType      | 说明                | ID 前缀        | 默认 Tier |
| --------------- | ----------------- | ------------ | ------- |
| `MemoryNode`    | 核心知识节点（所有记忆的基类型）  | `MEM-L-`     | warm    |
| `ArchDecision`  | 架构决策记录（ADR，最高优先级） | `AD-`        | hot     |
| `Lesson`        | 从 EP 执行中提炼的经验教训   | `MEM-L-`     | warm    |
| `Pattern`       | 可复用的架构/代码模式       | `PAT-`       | hot     |
| `DomainConcept` | 领域概念锚点（图谱索引节点）    | `[layer-id]` | —       |


**Layer 2 的 5 种 LinkType（图边）：**


| LinkType       | 含义                                 | 基数  | 自动建边                      |
| -------------- | ---------------------------------- | --- | ------------------------- |
| `cites`        | MemoryNode → CodeFile（引用代码文件）      | M:N | ✅ `_auto_link()` 正则提取     |
| `about`        | MemoryNode → DomainConcept（描述领域概念） | M:N | ✅ `layers.yaml` 关键词匹配     |
| `impacts`      | MemoryNode → MemoryNode（影响关系）      | M:N | 可选（`enable_auto_impacts`） |
| `contradicts`  | MemoryNode → MemoryNode（矛盾关系）      | M:N | 手动                        |
| `derived_from` | MemoryNode → MemoryNode（提炼来源）      | N:M | 手动                        |


**记忆图索引示例（front-matter v4.0）：**

```yaml
---
id: MEM-L-021
layer: DOMAIN                         # 通用 5 层：CC/PLATFORM/DOMAIN/APP/ADAPTER
tier: hot
tags: [grpc, service-layer, dto]
cites_files:                          # auto-link 自动填充
  - backend/app/services/user_service.py
about_concepts:                       # auto-link 关键词匹配填充
  - grpc
  - dto-validation
impacts: [MEM-L-024]                  # 变更时需同步检查的记忆
derived_from: [AD-002]                # 从 ArchDecision 提炼而来
provenance:                           # v3.0 新增：来源追踪
  ep_id: EP-021
  trigger_type: ep_postcheck_passed
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
│   ├── layers.yaml       # 通用 5 层 + 关键词 + 路径前缀（v3.0 已更新）
│   └── intent_map.yaml / operations.yaml / query_synonyms.yaml
└── schemas/              # Layer 3 系统对象（执行机械内部对象）
    ├── dag_unit.yaml / aiu_step.yaml / diagnostic_event.yaml
    └── aiu_types_extended.yaml   # AIU 类型 YAML 扩展（新增类型不改 Python）
```

### 2. 记忆层级（通用 5 层，v3.0）

记忆以 Markdown front-matter 格式存储，按**通用 5 层架构**分类（不绑定具体技术框架），热度分级管理：

```
docs/memory/shared/
├── CC/          # 架构决策与约束（ADR、反模式、红线）   [保护系数 0.5，最难淘汰]
├── PLATFORM/    # 横切平台能力（认证/鉴权/配置/可观测）  [保护系数 0.2]
├── DOMAIN/      # 业务领域核心（实体/聚合根/领域规则）   [保护系数 0.3]
├── APP/         # 应用用例编排（CQRS Handler/Saga/工作流）[保护系数 0.1]
└── ADAPTER/     # 外部适配（REST/DB/MQ/Cache/UI 组件）  [保护系数 0.0，最易淘汰]
```

新记忆文件自动写入新路径；`dream.py` 保留对旧路径格式的向后兼容读取。

**章节入口的全文检索预筛：**

记忆检索的核心策略是 Jaccard 关键词匹配 + 知识图谱遍历（无向量数据库）。在用户输入章节路径或标题时，系统会触发一次轻量全文检索（倒排索引扫描），快速判断是否存在与该章节高度匹配的已有记忆。此步骤在 LLM 介入之前完成，命中则直接返回，降低 token 消耗。全文检索不是核心通道，仅作"入口预筛"使用。

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

**AIU 类型（内置 43 种，9 大族，v3.0 扩展）：**


| 族                     | 内置类型（节选）                                                            | 执行顺序 | 亲和层级           |
| --------------------- | ------------------------------------------------------------------- | ---- | -------------- |
| **A Schema**          | `SCHEMA_ADD_FIELD` · `SCHEMA_MODIFY_FIELD` · `CONTRACT_ADD_REQUEST` | 1    | DOMAIN/ADAPTER |
| **C Data Access**     | `QUERY_ADD_SELECT` · `MUTATION_ADD_INSERT` · `MUTATION_ADD_UPDATE`  | 2    | ADAPTER        |
| **B Control Flow**    | `LOGIC_ADD_CONDITION` · `LOGIC_ADD_BRANCH` · `LOGIC_EXTRACT_METHOD` | 3    | DOMAIN/APP     |
| **E Infrastructure**  | `EVENT_ADD_PRODUCER` · `EVENT_ADD_CONSUMER` · `CACHE_ADD_READ`      | 3    | ADAPTER        |
| **D Interface**       | `ROUTE_ADD_ENDPOINT` · `ROUTE_ADD_PERMISSION` · `FRONTEND_ADD_PAGE` | 4–5  | ADAPTER        |
| **F Validation**      | `TEST_ADD_UNIT` · `TEST_ADD_INTEGRATION` · `DOC_SYNC`               | 6–8  | APP/CC         |
| **G Distributed** ★   | `SAGA_ADD_STEP` · `SAGA_ADD_COMPENSATOR` · `OUTBOX_ADD_MESSAGE`     | 3–4  | APP/DOMAIN     |
| **H Governance** ★    | `RBAC_ADD_PERMISSION` · `RBAC_ADD_ROLE` · `AUDIT_ADD_TRAIL`         | 2–3  | PLATFORM/CC    |
| **I Observability** ★ | `METRIC_ADD_COUNTER` · `TRACE_ADD_SPAN` · `ALERT_ADD_RULE`          | 3–5  | PLATFORM       |


★ v3.0 新增：面向企业级分布式、合规治理和可观测性场景（语言无关，Java/Go/Python 通用）

每种 AIU 类型携带 `layer_affinity` 属性，自动指导 `hybrid_search` 提升对应层记忆的检索权重。

> **扩展 AIU 类型**：在 `docs/memory/_system/schemas/aiu_types_extended.yaml` 新增条目，无需修改 `aiu_types.py` 源码。`AIURegistry` 运行时自动合并 Enum 内置与 YAML 扩展。

### 4. 记忆图检索（Memory Graph Search）

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

### 5. EP 工作流（全自动 Pipeline）

EP（Episode）是木兰的核心工作单元。**默认形态是全自动 Pipeline**：

```bash
# 标准启动方式（推荐）
mulan synthesize "新增对象类型批量导出 API" --template ep-backend-api
# 为一个章节生成执行计划并自动运行
mulan ep run EP-NNN --auto-confirm
```

`mulan ep run` 自动完成以下阶段，无需人工逐步确认：

```
Phase 0  mulan synthesize            意图合成 → 章节执行计划（提示词）
Phase 1  mulan precheck              arch_check 基线 + AST 快照 + 记忆注入
Phase 2  mulan unit generate         qwen3-32b 编排 DAG，生成 Unit 列表
Phase 3  mulan unit run-all          qwen3-coder-next 逐批执行（3-Strike + 沙箱回滚）
Phase 4  mulan postcheck             pytest + arch_check + MigrationGate 质量门控
Phase 5  mulan distill / mulan dream 知识蒸馏 → 自动沉淀到记忆库
```

常用执行选项：

```bash
mulan ep run EP-NNN                      # 自动执行，遇关键决策点暂停确认
mulan ep run EP-NNN --auto-confirm       # 完全无人值守（CI / 批量场景）
mulan ep run EP-NNN --from-unit U3       # 从指定 Unit 续跑
mulan ep run EP-NNN --only U1 U2         # 只执行指定 Unit
mulan ep run EP-NNN --dry-run            # 模拟执行，不写文件，不提交 git
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

### 8. 文件结构

```
mms/
├── cli.py                       # 统一 CLI 入口（mulan <command>，含 diag 子命令）
├── pyproject.toml               # 项目配置（setuptools / pytest）
├── conftest.py                  # pytest 全局 fixtures
│
├── src/mms/                     # 核心包（pip install -e . 后可 import mms）
│   ├── workflow/                # EP 工作流编排
│   │   ├── synthesizer.py       # 意图合成（任务 → Cursor 起手提示词）
│   │   ├── ep_parser.py         # EP Markdown → DagState
│   │   ├── ep_runner.py         # 自动 Pipeline（mulan ep run）
│   │   ├── ep_wizard.py         # 交互式向导（mulan ep start）
│   │   ├── precheck.py          # 前置基线检查（arch_check + AST 快照）
│   │   ├── postcheck.py         # 后置质量门（pytest + arch_check + MigrationGate）
│   │   └── migration_gate.py    # DB 迁移脚本门控
│   │
│   ├── dag/                     # DAG & AIU 引擎
│   │   ├── dag_model.py         # DagUnit / DagState 数据模型
│   │   ├── aiu_types.py         # AIU 原子意图类型枚举（9 族 / 43 种基础类型）
│   │   ├── aiu_cost_estimator.py # CBO 风格代价估算
│   │   ├── aiu_feedback.py      # 3 级回退反馈
│   │   ├── aiu_registry.py      # Schema-Driven 动态注册表（YAML 优先 / Enum 兜底）
│   │   ├── task_decomposer.py   # AIU 分解器
│   │   └── atomicity_check.py   # Unit 原子化评分
│   │
│   ├── execution/               # Unit 执行层
│   │   ├── unit_generate.py     # DAG 生成（EP → Unit 列表）
│   │   ├── unit_runner.py       # Unit 自动执行（3-Strike + SandboxRollback）
│   │   ├── internal_reviewer.py # 双角色内部评审（feature flag）
│   │   ├── unit_compare.py      # 双模型对比 + qwen3-32b 语义评审
│   │   ├── unit_context.py      # 单 Unit 压缩上下文生成器
│   │   ├── unit_cmd.py          # unit 子命令（status/next/done/reset）
│   │   ├── file_applier.py      # 解析并应用 LLM BEGIN/END-CHANGES 块
│   │   ├── sandbox.py           # GitSandbox（文件操作隔离 + 自动回滚）
│   │   ├── sandboxed_runner.py  # Sandbox 化 Unit 执行包装器
│   │   └── fix_gen.py           # 自动生成修复建议
│   │
│   ├── memory/                  # 记忆检索与注入
│   │   ├── injector.py          # 记忆注入（检索 + 压缩 → Cursor 上下文前缀）
│   │   ├── intent_classifier.py # 3 级意图漏斗（RBO → 本体匹配 → LLM）
│   │   ├── graph_resolver.py    # 知识图谱（hybrid_search / typed_explore / contradicts）
│   │   ├── memory_functions.py  # 纯函数层（无副作用，可测试）
│   │   ├── memory_actions.py    # 有状态动作层（写入 / 矛盾检测 / Provenance）
│   │   ├── link_registry.py     # LinkType YAML 注册表
│   │   ├── freshness_checker.py # 记忆新鲜度检测（cites 边反查 + drift 传播）
│   │   ├── graph_health.py      # 图健康监控（节点分布 / 边覆盖率 / 孤立率）
│   │   ├── dream.py             # autoDream（git 历史 + EP → 知识草稿 + auto-link）
│   │   ├── entropy_scan.py      # 孤儿/过时记忆检测 + 边衰减（mulan gc --edge-decay）
│   │   ├── repo_map.py          # PageRank 风格文件重要性排序
│   │   ├── codemap.py           # 代码目录快照生成
│   │   ├── funcmap.py           # 函数签名索引生成
│   │   ├── template_lib.py      # 填空式代码骨架模板
│   │   ├── task_matcher.py      # 任务-记忆相关度匹配
│   │   └── private.py           # EP 私有工作区（草稿笔记）
│   │
│   ├── analysis/                # 代码静态分析
│   │   ├── arch_check.py        # 架构约束扫描（规则可由 seed_packs 扩展）
│   │   ├── arch_resolver.py     # 层 → 文件路径解析器
│   │   ├── ast_skeleton.py      # AST 骨架化（Python/Java/Go/TS，语义哈希）
│   │   ├── ast_diff.py          # AST diff（接口契约变更检测）
│   │   ├── ontology_syncer.py   # 本体 YAML ↔ AST 同步
│   │   ├── dep_sniffer.py       # 技术栈嗅探（pip/npm/pom.xml/gradle/go.mod）
│   │   ├── doc_drift.py         # 文档漂移检测
│   │   ├── seed_absorber.py     # Rule Absorber（URL → YAML 蒸馏）
│   │   └── parsers/             # AST 解析器适配层（Adapter Pattern）
│   │       ├── protocol.py      # ASTParserProtocol 接口
│   │       ├── regex_parser.py  # 正则解析器（默认，零依赖）
│   │       ├── tree_sitter_parser.py  # Tree-sitter Sidecar（可选）
│   │       └── factory.py       # get_parser()：自动路由 + 降级
│   │
│   ├── core/                    # 基础 I/O 工具
│   │   ├── reader.py            # 编码自适应文件读取
│   │   ├── writer.py            # 安全文件写入（集成 SanitizationGate）
│   │   ├── sanitize.py          # 脱敏屏障（API Key / JWT / IP 自动 REDACT）
│   │   └── indexer.py           # 记忆索引构建器
│   │
│   ├── providers/               # LLM Provider 适配器
│   │   ├── base.py              # ProviderBase 抽象基类
│   │   ├── factory.py           # 任务 → Provider 路由
│   │   ├── bailian.py           # 阿里云百炼（qwen3-32b / qwen3-coder-next）[主力]
│   │   ├── claude.py            # Anthropic Claude（fallback / 人工介入）
│   │   ├── gemini.py            # Google Gemini（备用，默认不启用）
│   │   └── ollama.py            # Ollama 本地模型（备用，默认不启用）
│   │
│   ├── trace/                   # EP 级诊断追踪（Oracle 10046 风格）
│   │   ├── event.py             # TraceEvent 数据结构 + 4 级诊断级别（1/4/8/12）
│   │   ├── tracer.py            # EPTracer：生命周期管理、线程安全写入
│   │   ├── collector.py         # 进程级 Tracer 注册表（懒加载，线程安全）
│   │   └── reporter.py          # tkprof 风格报告生成（text / json / html）
│   │
│   ├── observability/           # 系统级可观测性（MDR 诊断基础设施）
│   │   ├── audit.py             # Append-only JSONL 操作审计日志
│   │   ├── logger.py            # 全局告警日志（alert_mulan.log，按天轮转）[v3.2]
│   │   ├── incident.py          # 崩溃现场保全（sys.excepthook + Incident Dump）[v3.2]
│   │   └── tracer.py            # 轻量 Trace ID 生成器（observability 内部使用）
│   │
│   ├── resilience/              # 可靠性原语
│   │   ├── retry.py             # 指数退避重试装饰器
│   │   ├── circuit_breaker.py   # 熔断器（三态机，状态转移写入 alert_mulan.log）
│   │   └── checkpoint.py        # 断点保存/恢复（长时间任务续跑）
│   │
│   └── utils/                   # 工具集
│       ├── mms_config.py        # 配置加载（config.yaml + 环境变量）
│       ├── model_tracker.py     # LLM 用量追踪
│       ├── router.py            # 任务 → Provider 路由
│       ├── validate.py          # Schema 校验
│       ├── verify.py            # 系统健康检查
│       └── _paths.py            # 项目路径解析（_PROJECT_ROOT 等常量）
│
├── seed_packs/                  # 冷启动种子知识包（技术栈级，6 个）
│   ├── base/                    # 通用架构模式（安全、事务）
│   ├── fastapi_sqlmodel/        # FastAPI + SQLModel 后端模式
│   ├── react_zustand/           # React + Zustand 前端模式
│   ├── palantir_arch/           # 本体/元数据平台模式
│   ├── spring_boot/             # Java Spring Boot（Maven/Gradle）模式
│   └── go_gin/                  # Go + Gin Web 框架模式
│       └── {arch_schema/ ontology/ constraints/ match_conditions.yaml}
│
├── benchmark/                   # 三层模块化 Benchmark v2
│   ├── run_benchmark_v2.py      # 独立运行入口
│   ├── v2/                      # v2 评测框架（见 benchmark/v2/README.md）
│   │   ├── schema.py            # 共享数据结构
│   │   ├── runner.py            # 主调度器 + 注册表
│   │   ├── config.yaml          # 评测配置（模型/阈值/报告格式）
│   │   ├── layer1_swebench/     # SWE-bench 信用锚（Pass@1 / Resolve Rate）
│   │   ├── layer2_memory/       # 记忆质量评测（Info Density / Funnel / Drift）
│   │   └── layer3_safety/       # 安全门控评测（arch / sanitize / migration）
│   └── src/                     # v1 检索质量基准（保留向后兼容）
│
├── docs/memory/                 # 知识库（由 mulan 命令自动维护）
│   ├── _system/                 # 系统运行时文件
│   │   ├── config.yaml          # 记忆系统配置（路由 / 淘汰 / 熔断阈值）
│   │   ├── schemas/             # 系统对象 Schema 定义
│   │   │   ├── dag_unit.yaml / aiu_step.yaml / diagnostic_event.yaml
│   │   │   ├── aiu_types_extended.yaml   # 轻量 AIU 扩展（新类型不改 Python 源码）
│   │   │   └── aius/            # Schema-Driven AIU 合约（input_schema + validation_rules）
│   │   │       ├── family_A_schema.yaml  # Schema/Contract 族（6 种 AIU）
│   │   │       ├── family_D_interface.yaml # Interface/Route 族（5 种 AIU）
│   │   │       ├── family_G_distributed.yaml # Distributed 族（4 种 AIU）
│   │   │       └── custom/      # 用户自定义 AIU（放入即生效，无需改代码）
│   │   └── routing/             # 路由配置
│   │       ├── layers.yaml      # 通用 5 层架构 + 关键词 + 路径前缀
│   │       └── intent_map.yaml / operations.yaml / query_synonyms.yaml
│   │
│   ├── shared/                  # 积累的共享记忆（5 层架构）
│   │   ├── CC/                  # 架构约束（ADR / 反模式 / 红线）[保护系数 0.5]
│   │   ├── PLATFORM/            # 横切平台能力（认证/鉴权/配置）[保护系数 0.2]
│   │   ├── DOMAIN/              # 业务领域核心（实体/聚合根/规则）[保护系数 0.3]
│   │   ├── APP/                 # 应用用例编排（Handler/Saga/工作流）[保护系数 0.1]
│   │   └── ADAPTER/             # 外部适配（REST/DB/MQ/Cache）[保护系数 0.0]
│   │
│   ├── seed_packs/              # 工业级种子记忆（语言/框架级，50 条）[v3.1]
│   │   ├── python_fastapi/      # Python × 10 条（AC-PY-01~10）
│   │   │   ├── meta.yaml        # 种子包元数据（语言 / arch_paradigm / layer_affinity）
│   │   │   ├── constraints.yaml # arch_check 可扫描的静态约束规则
│   │   │   └── memories/        # AC-PY-01.md … AC-PY-10.md（含代码示例）
│   │   ├── java_spring_boot/    # Java × 12 条（AC-JAV-01~12）
│   │   ├── go_microservice/     # Go × 10 条（AC-GO-01~10）
│   │   ├── typescript_nestjs/   # TypeScript × 10 条（AC-TS-01~10）
│   │   └── cross_cutting/       # 通用架构 × 8 条（AC-ARCH-01~08）
│   │
│   ├── ontology/                # 动态本体定义
│   │   ├── objects/             # 5 种 ObjectType（memory_node / arch_decision / …）
│   │   ├── links/               # 5 种 LinkType（cites / about / contradicts / …）
│   │   ├── actions/             # distill / dream 等 Action 定义
│   │   └── _config/
│   │       └── traversal_paths.yaml   # 图遍历路径配置（新增路径不改代码）
│   │
│   ├── private/                 # EP 私有工作区 + 诊断数据（不进入共享记忆）
│   │   ├── EP-NNN/              # EP 私有草稿笔记（mulan private）
│   │   ├── trace/               # EP 级诊断 trace 数据（mulan trace enable）
│   │   │   └── EP-NNN/          # mms.trace.jsonl + trace_config.json + report/
│   │   └── mdr/                 # MDR 诊断仓库（类 Oracle ADR）[v3.2]
│   │       ├── alert/           # alert_mulan.log（系统心电图，按天轮转）
│   │       └── incident/        # 致命崩溃现场（call_stack.dmp / prompt_context.txt）
│   │
│   └── templates/               # EP 任务模板（9 种类型）
│       ├── ep-backend-api.md / ep-frontend.md / ep-debug.md / …
│       └── code/                # 填空式代码骨架（api-endpoint / service-method / …）
│
└── tests/                       # 测试套件（847 测试用例，完全离线可运行）
    ├── benchmark/               # Benchmark v2 单元测试（layer1/2/3 + Phase 4 Pass@1）
    ├── test_alert_logger.py     # 全局告警日志测试（v3.2）
    ├── test_incident.py         # 崩溃现场保全测试（v3.2）
    ├── test_aiu_registry.py     # AIU 注册表基础测试
    ├── test_aiu_registry_v2.py  # Schema-Driven AIU 新接口测试（v3.1）
    ├── test_contradiction_detection.py  # 图谱矛盾检测测试（v3.1）
    ├── test_trace_*.py          # 诊断追踪模块测试（tracer/event/collector/reporter）
    └── test_*.py                # 各核心模块测试（dag / memory / analysis / execution …）
```

---

## 快速开始

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/allengaoo/mms.git ~/code/mms

# 2. 安装核心依赖（大部分功能不需要 LLM）
pip install pyyaml structlog

# 3. 安装百炼（阿里云）LLM 支持
pip install openai dashscope

# 4. 注册 mulan 命令（添加到 ~/.zshrc 或 ~/.bashrc）
echo 'export MULAN_HOME="$HOME/code/mms"' >> ~/.zshrc
echo 'alias mulan="python3 $MULAN_HOME/cli.py"' >> ~/.zshrc
source ~/.zshrc

# 验证安装
mulan --help
```

### 冷启动新项目

```bash
# 在你的项目根目录执行（< 1 秒，零 LLM 调用）
mulan bootstrap --root /path/to/your/project

# 执行内容：
# 1. 技术栈嗅探（requirements.txt / package.json / pom.xml / go.mod）
# 2. 匹配并注入种子知识包到 docs/memory/shared/
# 3. AST 骨架化扫描 → docs/memory/_system/ast_index.json
# 4. 架构层入口点绑定 → ast_pointer 写入本体 YAML
```

通过 `mulan seed ingest` 可从 GitHub 吸收外部规范自动生成新种子包（见 [Rule Absorber](#种子包管理rule-absorber)）。

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


### 开始第一个任务

```bash
# 第一步：生成 Cursor 起手提示词（在 IDE 中生成 EP 文件）
mulan synthesize "新增对象类型批量导出 API" --template ep-backend-api

# 第二步：全自动执行（推荐，无人值守）
mulan ep run EP-001 --auto-confirm

# 或保留关键决策点的确认（默认）
mulan ep run EP-001

# 需要从中间某个 Unit 续跑时
mulan ep run EP-001 --from-unit U3

# 先预览再执行
mulan ep run EP-001 --dry-run
```

---

## CLI 参考

### EP 工作流（自动执行）

```bash
mulan synthesize "任务描述" --template ep-backend-api    # 生成 Cursor 起手提示词
mulan ep run EP-NNN --auto-confirm                       # 全自动执行（无人值守）
mulan ep run EP-NNN                                      # 自动执行，关键节点暂停确认
mulan ep run EP-NNN --from-unit U3                       # 从 U3 续跑
mulan ep run EP-NNN --only U1 U2                         # 只执行指定 Unit
mulan ep run EP-NNN --dry-run                            # 模拟执行，不写文件
mulan ep status EP-NNN                                   # 查看执行进度
```

### Unit 执行

```bash
mulan unit generate --ep EP-NNN               # 生成 DAG（qwen3-32b 编排）
mulan unit status --ep EP-NNN                 # 查看各 Unit 执行状态
mulan unit run --ep EP-NNN --unit U1          # 单独执行指定 Unit
mulan unit run-next --ep EP-NNN               # 执行当前批次全部 Unit
mulan unit run-all --ep EP-NNN                # 执行全部剩余 Unit
mulan unit done --ep EP-NNN --unit U1         # 手动标记完成 + git commit
mulan unit reset --ep EP-NNN --unit U1        # 重置 Unit 状态
```

### Unit 双模型对比（可选高级模式）

```bash
mulan unit run --ep EP-NNN --unit U1 --save-output       # qwen 仅生成存盘，不写业务文件
mulan unit sonnet-save --ep EP-NNN --unit U1             # 保存 Cursor Sonnet 输出
mulan unit compare --ep EP-NNN --unit U1                 # 生成机械 diff + 语义评审报告
mulan unit compare --apply qwen --ep EP-NNN --unit U1    # 应用 qwen 版本到业务文件
mulan unit compare --apply sonnet --ep EP-NNN --unit U1  # 应用 Sonnet 版本到业务文件
```

### 记忆管理

```bash
mulan search kafka replication           # 关键词检索（Jaccard + 图遍历，无向量）
mulan search kafka --preview             # 检索并预览最高匹配内容
mulan inject "新增对象类型 API"           # 生成 Cursor 上下文前缀
mulan list --tier hot                    # 列出热记忆
mulan list --layer DOMAIN                # 按通用层过滤（CC/PLATFORM/DOMAIN/APP/ADAPTER）
mulan graph stats                        # 知识图谱统计
mulan graph explore AD-002               # 从 AD-002 出发 BFS 遍历
mulan graph file backend/api/routes.py   # 反查引用该文件的记忆
mulan graph impacts AD-002               # 影响传播分析
mulan gc                                 # 垃圾回收（LFU 淘汰 + 索引重建）
mulan validate --changed-only            # Schema 校验（仅 git diff 范围）
```

### 代码模板

```bash
mulan template list                                          # 列出所有模板
mulan template info service-method                           # 查看模板变量说明
mulan template use service-method --var entity=ObjectType    # 渲染模板
```


| 模板名               | 生成内容                                              |
| ----------------- | ------------------------------------------------- |
| `service-method`  | Service 层方法（SecurityContext + AuditService + RLS） |
| `api-endpoint`    | FastAPI Endpoint + Schema（信封格式 + 权限守卫）            |
| `react-list-page` | ProTable 列表页（useQuery + PermissionGate + Zustand） |
| `worker-job`      | Worker Job（JobExecutionScope + structlog）         |


### 知识蒸馏

```bash
mulan distill --ep EP-NNN               # EP 知识蒸馏 → MEM-*.md
mulan distill --ep EP-NNN --dry-run     # 预览模式
mulan dream --ep EP-NNN                 # autoDream：从 git 历史萃取知识草稿
mulan dream --promote                   # 交互式审核 → 升级为正式记忆
mulan dream --list                      # 列出所有待处理草稿
mulan private init EP-NNN               # 初始化 EP 私有工作区
mulan private note EP-NNN "发现一个坑"  # 添加临时笔记
mulan private promote EP-NNN note.md DOMAIN MEM-L-028     # 升级为公有记忆（通用 5 层路径）
```

### 诊断追踪

```bash
mulan trace enable EP-NNN --level 4     # 开启追踪（Level 4 = LLM 详情）
mulan trace enable EP-NNN --level 12    # 开启全量追踪（含 prompt/response 片段）
mulan trace show EP-NNN                 # 查看诊断报告（类 tkprof 输出）
mulan trace show EP-NNN --format json   # JSON 格式报告
mulan trace summary EP-NNN             # 一行摘要（LLM 次数/总耗时/token）
mulan trace list                        # 列出所有有追踪记录的 EP
mulan trace clean EP-NNN                # 清除追踪数据
```

### 种子包管理（Rule Absorber）

```bash
mulan seed list                                          # 列出所有已安装种子包
mulan seed ingest https://raw.github.com/.../rules.mdc   # 从 URL 吸收规范蒸馏为 YAML
mulan seed ingest ./local-rules.md --seed-name my_stack  # 从本地文件吸收
mulan seed ingest <url> --dry-run                        # 预览蒸馏结果，不写文件
mulan seed ingest <url> --force                          # 覆盖已有同名种子包
```

Rule Absorber 工作流：URL 获取 → 噪声清洗 → 提取规则段落 → `qwen3-32b` 蒸馏 → 写入 `seed_packs/<name>/{arch_schema,ontology,constraints}/`。

### Benchmark 评测

```bash
mulan benchmark                                    # 离线模式（仅安全门控，< 1s）
mulan benchmark --level fast                       # + 记忆质量评测（需 LLM）
mulan benchmark --level full --llm                 # 全量三层（需 LLM + Docker）
mulan benchmark --layer 3                          # 仅运行安全门控层
mulan benchmark --layer 3 --verbose                # 详细输出每条测试结果
mulan benchmark --output markdown --output-path reports/bench.md  # 生成报告
mulan benchmark --max-tasks 5                      # 限制任务数（调试用）

# 或直接运行独立入口
python3 benchmark/run_benchmark_v2.py --level offline
```

### 系统维护

```bash
mulan status                            # Provider 健康 + 熔断器 + 记忆统计 + 图健康
mulan usage --since 30                  # Token 用量报告（最近 30 天）
mulan codemap --depth 3                 # 刷新代码目录快照
mulan funcmap                           # 刷新函数签名索引
mulan ast-diff --ep EP-NNN              # 检测 precheck 以来的契约变更
mulan verify                            # 全面健康检查（schema/index/docs）
mulan reset-circuit                     # 重置所有熔断器
mulan hook install                      # 安装 git pre-commit hook
mulan incomplete                        # 列出未完成的蒸馏断点
```

`mulan status` 包含记忆图健康报告：

```
【记忆图健康（Memory Graph Health）】
  节点总数：142  热节点：38  温节点：84  冷节点：20  归档：0
  有 cites 边：89/142 (63%)       ← 代码变更追踪覆盖率
  有 about 边：61/142 (43%)       ← 概念级检索覆盖率
  有 impacts 边：32/142
  孤立节点（无任何边）：12         ← >20% 时标红，提示需要补充图关系
  平均邻居数：3.2  图密度：0.022
  ✅ 质量良好：cites 边覆盖率 63%，孤立节点比例 8%
```

---

## 基准测试

木兰内置三层模块化 Benchmark v2，用于验证记忆系统和安全门控的有效性。  
详细设计文档见 [benchmark/v2/README.md](benchmark/v2/README.md)。

### 快速运行

```bash
# 离线模式（推荐，< 1 秒，无需 LLM API）
mulan benchmark

# 或
python3 benchmark/run_benchmark_v2.py
```

### 三层概览


| 层   | 名称            | 运行条件     | 核心指标                             |
| --- | ------------- | -------- | -------------------------------- |
| L3  | 安全门控（Safety）  | 完全离线     | 凭证检出率 / 阻断精度 / 架构规则覆盖率           |
| L2  | 记忆质量（Memory）  | D1/D4 离线 | Recall@K / MRR / ΔPass@1 / 漂移检出率 |
| L1  | SWE-bench 信用锚 | 离线格式验证   | Pass@1 / Resolve Rate（在线填充）      |


**v3.0 新增测试集：**


| 测试集                       | 类型                     | 说明                             |
| ------------------------- | ---------------------- | ------------------------------ |
| `funnel_retrieval.yaml`   | 漏斗有效性                  | FUNNEL-A/B/C/D 四类，验证三阶段漏斗各自贡献度 |
| `mall_order_cases.yaml`   | 企业项目（Java Spring Boot） | 基于 macrozheng/mall 订单服务真实代码结构  |
| `halo_content_cases.yaml` | 企业项目（Java Spring Boot） | 基于 halo-dev/halo CMS 内容管理模块    |


### 当前运行结果（离线 fast 模式）

```
Layer 3: 安全门控评测     94.7%（46 个测试，43 通过）
  sanitize.detection_rate:      0.9444
  sanitize.false_positive_rate: 0.0000
  migration.block_accuracy:     1.0000
  arch.detection_rate:          0.8333

Layer 2: 记忆质量评测     45.0%（D4 漂移检测 100%，D1/D2 需真实记忆库+LLM）
  d4.drift_detection_rate:      1.0000
  d1.recall_pass_rate:          0.0000  # 需填充 relevant_ids
  d2.injection_pass_rate:       0.0000  # 需 LLM API
  funnel.total_cases:           9       # FUNNEL-A/B/C/D 基准（v3.0 新增）
  enterprise.mall_cases:        4       # mall 订单服务企业基准
  enterprise.halo_cases:        2       # halo CMS 内容管理基准

综合得分: 69.9%
```

> **防过拟合说明**：Layer 2 离线得分偏低是设计行为——D1/D2 指标必须依赖真实记忆库数据，
> 而非合成数据。这样可避免 benchmark 得分虚高，确保对真实检索质量的公正评估。

---

## 配置说明

配置文件位于 `docs/memory/_system/config.yaml`（由 `mulan bootstrap` 自动创建）：

```yaml
runner:
  timeout_llm: 180              # LLM 调用超时（秒）
  max_retries: 2                # 3-Strike 重试上限
  enable_internal_review: false # 双角色内部评审（feature flag，默认关闭）
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
  default_success_rate: 0.8
  chars_per_token: 4

trace:
  default_level: 4             # 默认诊断级别
  max_events: 10000            # 单 EP 最大事件数

graph:
  confidence_threshold: 3      # auto-link 置信度阈值

runner_enable_auto_impacts: false

# Tree-sitter Sidecar（可选，默认关闭）
analysis:
  use_tree_sitter: false        # true 需先安装: pip install "mulan[tree_sitter]"
  tree_sitter_languages: [java, go]

# 记忆图谱边衰减（mulan gc --edge-decay）
gc:
  edge_decay_factor: 0.8        # 衰减系数（每次 GC 未命中边的权重 × 0.8）
  edge_prune_threshold: 0.2     # 低于此值的边将被物理删除
  edge_decay_window_eps: 20     # 超过 N 个 EP 未访问的边才触发衰减

  # 三维度淘汰评分权重（v3.0 新增）
  eviction_weights:
    alpha: 0.3                  # 时间衰减权重
    beta:  0.4                  # 访问频率权重（LFU）
    gamma: 0.3                  # 图结构重要性权重（in-degree）
  # 层级保护系数由 layers.protection_bonus 字段定义（CC=0.5 > DOMAIN=0.3 > PLATFORM=0.2 > APP=0.1 > ADAPTER=0）

# 项目类型自动检测（v3.0 新增，由 dep_sniffer 运行时写入）
project_type:
  detected: "generic"           # python_fastapi | java_spring | go_microservice | generic
  seed_pack: null               # 对应的 seed_pack 目录（null = 使用通用 5 层）
  scan_dirs: []                 # 由 dep_sniffer 动态填充，覆盖 ast_skeleton.py 的默认扫描目录
```

**双角色内部评审开启方式：**

```bash
# 方式一：环境变量（推荐）
MMS_ENABLE_INTERNAL_REVIEW=true mulan unit run --ep EP-123

# 方式二：config.yaml
# runner:
#   enable_internal_review: true
```

---

## 测试

```bash
# 运行全部测试（无需 LLM API）
pytest tests/ -v

# 仅运行非慢速测试
pytest tests/ -m "not slow and not integration"

# 仅运行 Benchmark 测试
pytest tests/benchmark/ -v

# 生成覆盖率报告
pytest tests/ --cov=src/mms --cov-report=html
```

测试结果：**823 通过**，1 个跳过，2 个预期失败（xfail）

新增单元测试（v3.0）：

- `tests/test_memory_functions.py`：纯函数层（质量评分、重复检测、Provenance 构建）
- `tests/test_eviction_score.py`：三维度淘汰评分验证
- `tests/test_aiu_expansion.py`：G/H/I 三族 AIU 扩展验证（43 种类型完整覆盖）

新增单元测试（v3.1）：

- `tests/test_aiu_registry_v2.py`：AIU 注册表 v2.0（Schema-Driven OCP，input_schema / validation_rules 接口）
- `tests/test_contradiction_detection.py`：图谱矛盾检测（爆炸半径控制、关键词级检测、降级操作）

---

## Roadmap

### 已完成（v4.x）

**任务工程层**

- ✅ **AIU Registry YAML 扩展**：新增 AIU 类型无需修改 `aiu_types.py`
- ✅ **EP 全自动 Pipeline**：`mulan ep run --auto-confirm` 无人值守端到端执行
- ✅ **3 级 Feedback 回退机制**：类 DB Query Feedback 的自适应任务重试策略

**知识记忆层**

- ✅ **四层本体架构分离**：Layer 0-3 职责明确，Layer 2 成为独立的记忆知识图谱
- ✅ **LinkType Registry**：5 种 LinkType YAML 驱动，新增边类型不改 Python 代码
- ✅ **语义图遍历**：`typed_explore` / `find_by_concept` / `hybrid_search`
- ✅ **Auto-Link 自动建边**：dream.py 写入记忆时自动提取文件路径和领域概念
- ✅ **记忆新鲜度检测**：`freshness_checker.py`，代码变更→记忆 drift 传播
- ✅ **图健康监控**：`mulan status` 实时显示边覆盖率、孤立率、图密度

**安全验证层**

- ✅ **AST 语义哈希**：剔除注释/空白，防格式化工具引起的虚假 drift
- ✅ **DB 迁移脚本门控**：postcheck 强制验证 ORM ↔ up()/down() 对齐
- ✅ **脱敏屏障（SanitizeGate）**：API Key / JWT / IP 写入前强制 REDACT
- ✅ **多语言 AST**：Python / Java / Go / TypeScript 四语言统一骨架化

**自学习层**

- ✅ **Rule Absorber**：`mulan seed ingest <url>` 将外部规范蒸馏为种子包
- ✅ **双角色内部评审**：Feature flag，Coder 生成后由 Reviewer 检查合规性

**评测体系**

- ✅ **Benchmark v2 三层框架**：安全门控（完全离线）/ 记忆质量 / SWE-bench 信用锚
- ✅ **YAML 驱动扩展**：新增测试 case 无需修改评测器代码

### 已完成（v3.1）

**Benchmark 优化**

- ✅ **Benchmark README 重构**：删除 ES/Milvus 描述，明确"动态本体路由 vs BM25"核心命题
- ✅ **L2 核心指标**：新增 Info Density 公式（ΔPass@1 / avg_injection_tokens × 1000），比传统 Recall@K 更适合小模型
- ✅ **企业靶机说明**：mall（80k⭐）/ halo（35k⭐）来源和工业复杂度说明

**种子记忆（Seed Genes）**

- ✅ **seed_packs 目录结构**：`docs/memory/seed_packs/` 含 5 个种子包（Python/Java/Go/TypeScript/CC）
- ✅ **50 条工业级种子记忆**：Python×10 + Java×12 + Go×10 + TypeScript×10 + 通用×8，每条含代码示例和原因分析
- ✅ **constraints.yaml**：每个种子包同时提供可被 `arch_check.py` 静态扫描的约束定义（双格式）

**Schema-Driven AIU（开闭原则重构）**

- ✅ **AIU 合约 Schema**：`docs/memory/_system/schemas/aius/` 含 input_schema（DAG 编排规范）+ validation_rules（AST 验证规则）
- ✅ **动态注册表增强**：`aiu_registry.py` v2.0 支持 `get_input_schema()` / `get_validation_rules()` / `get_layer_affinity()` 新接口
- ✅ **custom/ 子目录支持**：用户自定义 AIU（如 K8S_ADD_SIDECAR）只需放入 YAML 文件，无需改代码

**图谱矛盾检测自动化**

- ✅ **detect_contradictions()**：两阶段检测（关键词级离线 + LLM 语义在线），爆炸半径控制（同层 + hot/warm + max 20 候选）
- ✅ **apply_contradiction_resolution()**：自动建立 contradicts 边 + archive_node 降级（切断入边，hybrid_search 永久忽略）
- ✅ **graph_resolver 扩展**：`get_candidates_for_contradiction_check()` / `add_contradicts_edge()` / `archive_node()` 新方法

### 已完成（v3.2）

**MDR 诊断基础设施**

- ✅ **全局告警日志 `alert_mulan.log`**：`src/mms/observability/logger.py` 新建，写入路径 `docs/memory/private/mdr/alert/`，按天轮转（保留 30 天），仅记录系统级重大事件（启动/关闭/熔断/崩溃），对外暴露 `alert_info/alert_warn/alert_fatal/alert_circuit` 四个模块级函数，运维人员只需 `tail -f alert_mulan.log` 实时监控系统存活状态
- ✅ **熔断器状态转移告警**：`circuit_breaker.py` 集成告警日志，三个状态转移节点均触发：`CLOSED→OPEN`（FATAL 级，算力掉线）/ `OPEN→HALF_OPEN`（WARN 级，恢复探测）/ `HALF_OPEN→CLOSED`（INFO 级，正常恢复）；通过安全 import（try/except）设计，避免循环依赖
- ✅ **Incident Dump 黑匣子**：`src/mms/observability/incident.py` 新建，通过 `sys.excepthook` 全局接管致命崩溃现场，自动保全三份文件：`call_stack.dmp`（完整 traceback + 最深崩溃帧的局部变量快照）/ `prompt_context.txt`（LLM 有毒提示词，供开发者直接复现幻觉行为）/ `incident_manifest.json`（结构化元数据），处理器自身有双重 try/except 保护，不会因诊断代码 bug 导致二次崩溃
- ✅ **ContextVars 上下文捕获**：`set_last_llm_context(prompt, response)` 通过 Python 原生 `contextvars.ContextVar` 存储最后一次 LLM 调用输入输出，asyncio / 多线程场景下各 EP 互不干扰，崩溃时自动写入 `prompt_context.txt`
- ✅ `**mulan diag` CLI**：`cli.py` 新增三个子命令：`diag status`（读取 `alert_mulan.log` 尾部，统计 FATAL/WARN 告警，存在未处理 FATAL 时退出码为 1）/ `diag list`（列出所有 Incident 记录）/ `diag pack <incident_id>`（打包 Incident 目录 + 相关 EP trace + ast_index.json 为 ZIP，供附到 GitHub Issue）


### 待完成（v5.x）

- **自适应 AIU 引擎**：根据执行历史自动调整 AIU 类型权重和拆分粒度
- **代码基因组（Code Genome）**：为每个核心模块维护变更历史 + 依赖图 + 架构决策链

---

### 代码规范

- **新增模块**：放入 `src/mms/` 对应子包，并在 `docs/memory/ontology/` 创建对应本体定义文件
- **新增 AIU 类型**：同步更新 `src/mms/dag/aiu_types.py` 和 `aiu_cost_estimator.py`（`AIU_BASE_COST`）
- **新增 CLI 命令**：同步更新 `_COMMAND_DOCS` 字典（用于 `mulan help`）和本文件 CLI 参考章节
- **测试要求**：新功能必须包含单元测试，LLM 调用必须通过 mock 处理，确保离线可运行
- **记忆文件**：修改 `docs/memory/shared/` 时，遵循 `memory_schema.yaml` v3.0 字段规范

---

## License

MIT License — 见 [LICENSE](LICENSE)