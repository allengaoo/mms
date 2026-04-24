# MMS — Memory Management System

> **让端侧小模型写出大模型级别的代码**
>
> MMS 是一套面向复杂软件工程的 AI Agent 结构化记忆系统。它以纯文本、零向量数据库、零强制第三方运行时的方式，
> 将项目知识组织为动态本体（Dynamic Ontology），并在每次任务前向 AI Agent 精准注入上下文，
> 从而让资源受限的端侧小模型（8B/16B）持续产出符合架构约束的高质量代码。

[CI](https://github.com/allengaoo/mms/actions/workflows/ci.yml)
[Python 3.11+](https://www.python.org)
[Tests](#testing)
[License: MIT](LICENSE)

---

## 核心目标

### 为什么要让小模型执行？

大模型（GPT-4o、Claude 3.5）推理能力强，但有两个根本约束：

- **无法本地部署**：企业代码库涉及商业机密，不能上传云端
- **上下文成本高**：每次注入完整架构知识耗费大量 token 和费用

MMS 的核心假设是：**限制代码生成的主要因素不是模型能力，而是上下文质量。**

通过将任务分解为足够小的原子单元（≤4k tokens），并精准注入该单元所需的上下文，
一个 8B 参数的本地模型完全可以完成复杂的代码变更——而无需把整个代码库喂给大模型。

### 设计原则


| 原则         | 实现方式                                                     |
| ---------- | -------------------------------------------------------- |
| **端侧优先**   | 以 qwen3-32b（意图识别）+ qwen3-coder-next（代码生成）作为核心推理层，兼顾速度与成本 |
| **纯文本存储**  | 所有记忆、本体、执行计划均为 Markdown / YAML，无向量数据库依赖                  |
| **零强制运行时** | 核心功能仅依赖 `pyyaml` + `structlog`，无需启动任何服务                  |
| **动态本体驱动** | 用 ObjectType / LinkType / Action / Function 四层本体组织知识     |
| **原子化执行**  | 每个 AIU（Atomic Intent Unit）≤4k tokens，可由 8B 模型独立执行        |
| **记忆自进化**  | 每次任务完成后自动蒸馏经验，失败历史驱动代价模型优化                               |


---

## 项目现状

### 已实现的核心能力


| 模块                     | 状态   | 说明                                                       |
| ---------------------- | ---- | -------------------------------------------------------- |
| 动态本体（Ontology）         | ✅ 稳定 | 4 类本体定义 + AST 物理绑定 + 漂移检测                                |
| AIU 分解引擎               | ✅ 稳定 | 28 种原子意图类型，6 族，CBO 代价估算                                  |
| 3 级反馈回退                | ✅ 稳定 | 类 DB Query Feedback：扩预算→插前置→拆分                           |
| EP 工作流向导               | ✅ 稳定 | 7 步交互式引导，支持断点续跑                                          |
| 一键自动 Pipeline          | ✅ 稳定 | `mms ep run`：precheck→units→postcheck                    |
| 双模型对比执行                | ✅ 稳定 | Qwen vs Sonnet 机械 diff + qwen3-32b 语义评审                  |
| 诊断追踪（Trace）            | ✅ 稳定 | Oracle 10046 风格，4 级诊断级别                                  |
| 记忆检索注入                 | ✅ 稳定 | 3 级检索漏斗，< 4k tokens/任务                                   |
| 知识图谱                   | ✅ 稳定 | BFS 遍历 + 文件反查 + 影响传播分析                                   |
| autoDream 蒸馏           | ✅ 稳定 | git 历史 + EP Surprises → 知识草稿                             |
| 冷启动 Bootstrap          | ✅ 稳定 | AST 骨架化 + 种子包注入，< 1s，零 LLM                               |
| AST 契约变更检测             | ✅ 稳定 | precheck 快照 vs 当前状态 diff；语义哈希防止格式化引起的虚假漂移                |
| 代码模板库                  | ✅ 稳定 | 填空式骨架，降低小模型幻觉率                                           |
| **src/mms/ 分包重组**      | ✅ 稳定 | 48 个模块按职责整理为 8 个子包，对外仅暴露核心 API                           |
| **多语言 AST 骨架化**        | ✅ 稳定 | Python / Java / Go / TypeScript 四语言统一指纹提取                |
| **DB 迁移脚本门控**          | ✅ 稳定 | postcheck 强制验证 ORM 变更 ↔ up()/down() 迁移脚本对齐               |
| **脱敏屏障（SanitizeGate）** | ✅ 稳定 | 落盘前拦截 API Key / JWT / IP 等敏感凭证，自动替换为 `[REDACTED_*]`      |
| **Rule Absorber**      | ✅ 稳定 | `mms seed ingest <url>` 将 .cursorrules/.mdc 蒸馏为 MMS YAML |
| **双角色内部评审**            | ✅ 稳定 | Feature flag（默认关闭）：Coder 生成后由 Reviewer（qwen3-32b）合规审查    |
| 测试套件                   | ✅ 稳定 | **563** 测试用例，无需 LLM API 可全部通过                            |


### 技术栈

```
运行时    Python 3.11+  │  pyyaml · structlog（核心依赖）
LLM 集成  Alibaba Bailian · 意图识别 / 推理 / 评审  →  qwen3-32b
                        · 代码生成                   →  qwen3-coder-next
          Anthropic Claude（fallback / 人工介入）
存储      纯文本 Markdown + YAML + JSONL，无数据库
检索辅助  全文检索（章节匹配预筛，降低 LLM token 消耗）
安全      SanitizationGate 正则脱敏（类 gitleaks 轻量版）
测试      pytest 563+，全部可离线运行
```

---

## 核心架构

### 1. 动态本体（Dynamic Ontology）

MMS 用本体而非硬编码来描述和组织知识。本体定义存储在 `docs/memory/ontology/`，包含四类定义：

```
docs/memory/ontology/
├── objects/          # ObjectTypeDef — 数据对象定义（DagUnit、AIUStep、DiagnosticEvent）
├── actions/          # ActionDef      — 系统行为定义（unit_run、precheck、distill）
├── functions/        # FunctionDef    — 计算函数定义（fn_estimate_aiu_cost、fn_decompose_task）
└── arch_schema/      # 架构图谱       — 层定义、操作类型、意图映射、查询同义词
    ├── layers.yaml           # L1-L5 + CC 七层架构，每层包含路径前缀、关键词、热记忆
    ├── operations.yaml       # 操作类型（create / modify / debug / refactor）
    ├── intent_map.yaml       # 意图关键词 → 层 × 操作 的路由表
    └── query_synonyms.yaml   # 自然语言同义词扩展
```

**四类本体定义示例：**

```yaml
# ObjectTypeDef — 对象类型（objects/dag_unit.yaml）
id: DagUnit
type: object
description: "EP 中的文件级最小执行单元，由 capable model 规划、small model 执行"
properties:
  aiu_steps:  { type: list[AIUStep], description: "语义级子步骤列表" }
  aiu_feedback_log: { type: list, description: "3级回退记录" }
related_functions: [fn_compute_atomicity, fn_decompose_task]
related_actions:   [action_unit_run, action_postcheck]

# ActionDef — 系统行为（actions/unit_run.yaml）
id: action_unit_run
type: action
description: "驱动 UnitRunner 自动执行：上下文生成→AIU分解→LLM调用→测试→git commit"
calls_functions: [fn_decompose_task, fn_estimate_aiu_cost]
triggers_ast_sync: true

# FunctionDef — 计算函数（functions/fn_estimate_aiu_cost.yaml）
id: fn_estimate_aiu_cost
type: function
description: "CBO 风格代价估算：AIU基础代价 + 文件复杂度 + 层传播 + 历史成功率"
implementation: "aiu_cost_estimator.py :: AIUCostEstimator"

# 架构层（arch_schema/layers.yaml）
L3_ontology:
  keywords: [本体, 对象类型, 链接类型, ObjectTypeDef, ActionDef, FunctionDef]
  entry_files: [backend/app/models/ontology.py]
  hot_memories: [MEM-L-012, MEM-L-013, BIZ-001]
```

本体与代码之间通过 **AST 物理绑定**（`ast_pointer` 字段）保持同步：

```
mms bootstrap  →  扫描 AST  →  在本体 YAML 中填充 ast_pointer.fingerprint
mms postcheck  →  ast_diff  →  fingerprint 变更 → ontology_syncer 标记 drift=true
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

**AIU 28 种类型（6 族）：**


| 族                    | 类型                                                                                                                                                 | 执行顺序 |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| **A Schema**         | `SCHEMA_ADD_FIELD` · `SCHEMA_MODIFY_FIELD` · `SCHEMA_ADD_RELATION` · `CONTRACT_ADD_REQUEST` · `CONTRACT_ADD_RESPONSE` · `CONTRACT_MODIFY_RESPONSE` | 1    |
| **C Data Access**    | `QUERY_ADD_SELECT` · `QUERY_ADD_FILTER` · `MUTATION_ADD_INSERT` · `MUTATION_ADD_UPDATE` · `MUTATION_ADD_DELETE`                                    | 2    |
| **B Control Flow**   | `LOGIC_ADD_CONDITION` · `LOGIC_ADD_BRANCH` · `LOGIC_ADD_LOOP` · `LOGIC_EXTRACT_METHOD` · `LOGIC_ADD_GUARD`                                         | 3    |
| **E Infrastructure** | `EVENT_ADD_PRODUCER` · `EVENT_ADD_CONSUMER` · `CACHE_ADD_READ` · `CONFIG_MODIFY`                                                                   | 3    |
| **D Interface**      | `ROUTE_ADD_ENDPOINT` · `ROUTE_ADD_PERMISSION` · `FRONTEND_ADD_PAGE` · `FRONTEND_ADD_STORE` · `FRONTEND_BIND_API`                                   | 4–5  |
| **F Validation**     | `TEST_ADD_UNIT` · `TEST_ADD_INTEGRATION` · `DOC_SYNC`                                                                                              | 6–8  |


### 4. EP 工作流（7 步）

EP（Execution Plan，执行计划）是 MMS 的核心工作单元：

```
Step 1  mms synthesize "任务" --template ep-backend-api   意图合成 → Cursor 起手提示词
Step 2  Cursor 在 IDE 中生成 EP 文件 → 按 Enter 确认       EP Markdown 文件
Step 3  mms precheck --ep EP-NNN                           建立 arch_check 基线 + AST 快照
Step 4  mms unit generate --ep EP-NNN                      DAG 生成（qwen3-32b 编排）
Step 5  mms unit run → compare → apply  (每个 Unit 循环)    双模型执行 + 语义评审
Step 6  mms postcheck --ep EP-NNN                          质量门控（pytest + arch_check + doc_drift）
Step 7  mms distill / mms dream --ep EP-NNN                知识蒸馏 → 沉淀到记忆库
```

或一键全自动：

```bash
mms ep run EP-NNN --auto-confirm   # 自动执行全部 7 步（Phase 0~4）
```

### 5. 双模型对比执行（EP-120）

MMS 支持同一 Unit 由两个模型独立生成，再通过 qwen3-32b 语义评审选优：

```
qwen3-coder-next → qwen.txt  ─┐
                               ├─ mms unit compare → 机械 diff + qwen3-32b 语义评审报告
Cursor Sonnet    → sonnet.txt ─┘
                               └─ mms unit compare --apply qwen|sonnet  → 写入业务文件
```

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
# 推荐：交互式向导（7 步引导，支持断点续跑）
mms ep start EP-001

# 或一键全自动（CI/批量场景）
mms ep run EP-001 --auto-confirm

# 或分步手动执行
mms synthesize "新增对象类型批量导出 API" --template ep-backend-api
mms precheck --ep EP-001
mms unit generate --ep EP-001
mms unit run --ep EP-001 --unit U1 --save-output   # qwen 生成并存盘
mms unit sonnet-save --ep EP-001 --unit U1          # 粘贴 Sonnet 输出
mms unit compare --ep EP-001 --unit U1              # 对比 + qwen3-32b 评审
mms unit compare --apply qwen --ep EP-001 --unit U1 # 应用选定版本
mms postcheck --ep EP-001
mms distill --ep EP-001
```

---

## CLI 参考

### EP 工作流

```bash
mms ep start EP-NNN                    # 交互式 7 步向导
mms ep start EP-NNN --from-step 5     # 从第 5 步断点续跑
mms ep status EP-NNN                   # 查看向导进度
mms ep run EP-NNN                      # 全自动 Pipeline
mms ep run EP-NNN --from-unit U3       # 从 U3 续跑
mms ep run EP-NNN --only U1 U2         # 只执行指定 Unit
mms ep run EP-NNN --dry-run            # 模拟执行，不写文件
```

### Unit 双模型工作流

```bash
mms unit generate --ep EP-NNN                          # 生成 DAG（qwen3-32b 编排）
mms unit status --ep EP-NNN                            # 查看执行进度
mms unit run --ep EP-NNN --unit U1 --save-output       # qwen 生成并存盘
mms unit sonnet-save --ep EP-NNN --unit U1             # 保存 Sonnet 输出
mms unit compare --ep EP-NNN --unit U1                 # diff + qwen3-32b 语义评审
mms unit compare --apply qwen --ep EP-NNN --unit U1    # 应用 qwen 版本
mms unit compare --apply sonnet --ep EP-NNN --unit U1  # 应用 Sonnet 版本
mms unit done --ep EP-NNN --unit U1                    # 手动标记完成 + git commit
mms unit run-next --ep EP-NNN                          # 批量执行当前批次
mms unit run-all --ep EP-NNN                           # 执行全部剩余 Unit
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
mms status                            # Provider 健康 + 熔断器 + 记忆统计
mms usage --since 30                  # Token 用量报告（最近 30 天）
mms codemap --depth 3                 # 刷新代码目录快照
mms funcmap                           # 刷新函数签名索引
mms ast-diff --ep EP-NNN              # 检测 precheck 以来的契约变更
mms verify                            # 全面健康检查（schema/index/docs/frontend）
mms reset-circuit                     # 重置所有熔断器
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

### 近期（v2.x）

- **本体链接类型（LinkTypeDef）**：补充 `docs/memory/ontology/links/` 目录，定义对象间的关系类型（如 `DagUnit --contains--> AIUStep`、`EP --generates--> Memory`）
- **AIU 并行执行**：相同 `exec_order` 的 AIUStep 支持真正并发执行（当前为顺序执行）
- **记忆版本追踪**：记忆条目变更时自动生成 diff，支持查看历史版本
- **两阶段提交（2PC）**：引入 git worktree 影子工作区，EP 内所有 Unit 全部通过 postcheck 后才 Squash Commit 合并回主分支

### 中期（v3.x）

- **完全离线模式**：意图分类、代价估算、上下文压缩全部切换为规则/本地模型，实现零云端依赖
- **跨项目本体迁移**：提供 `mms export-ontology` 和 `mms import-ontology` 命令，支持在多个项目间共享领域知识
- **AI 自动记忆升级**：autoDream 草稿经本地小模型初步评估后，高置信度的自动提升为正式记忆，无需人工介入
- **VSCode / Cursor 插件**：将 `mms inject` 和 `mms status` 集成进 IDE 侧边栏，实现记忆注入的图形化操作
- **多智能体协作**：多个 UnitRunner 并行处理同一 EP 中无依赖关系的 Unit 批次

### 长期（v4.x）

- **自适应本体**：系统根据 AIU 执行历史、成功率统计，自动调整 28 种 AIU 类型的权重和拆分粒度
- **知识联邦**：团队成员的本地记忆库可选择性同步到共享库，实现团队级知识积累
- **代码基因组（Code Genome）**：为项目中每个核心类/函数维护"基因序列"（变更历史 + 依赖图 + 测试覆盖），辅助大规模重构
- **MMS-as-a-Service**：提供轻量级本地服务模式，让多个 IDE 会话共享同一个记忆实例

---

## 如何贡献

### 贡献方向


| 方向            | 难度    | 描述                                                                  |
| ------------- | ----- | ------------------------------------------------------------------- |
| 新增种子包         | ⭐ 低   | 为 Django、Vue、NestJS 等技术栈创建 `seed_packs/`（含 arch_schema/ontology/constraints 三层） |
| 扩充 EP 模板      | ⭐ 低   | 在 `docs/memory/templates/` 补充新任务类型的 EP 模板                            |
| 扩充 AIU 类型     | ⭐⭐ 中  | 在 `src/mms/dag/aiu_types.py` 中添加新的原子意图类型并配套测试                        |
| 新增 Provider   | ⭐⭐ 中  | 在 `src/mms/providers/` 中适配新的 LLM 服务（实现 `ProviderBase`）               |
| 本体链接类型        | ⭐⭐ 中  | 在 `docs/memory/ontology/links/` 补充 LinkTypeDef 定义                    |
| 扩充 Rule Absorber 噪声规则 | ⭐⭐ 中  | 改进 `src/mms/analysis/seed_absorber.py` 的噪声清洗正则，提升蒸馏准确率              |
| 并行 AIU 执行     | ⭐⭐⭐ 高 | 修改 `src/mms/execution/unit_runner.py` 支持相同 `exec_order` 的真并发          |


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