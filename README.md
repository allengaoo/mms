# MMS — MDP Memory System

> **AI Agent 驱动的结构化知识管理系统**
> 为复杂软件工程提供记忆积累、上下文注入、架构约束扫描与文档熵控能力。
> 纯文本推理，无向量数据库，零第三方运行时依赖，可嵌入任意 Python 项目。
>
> 最新版本：**EP-130**（AST-Ontology 双轨融合与离线冷启动）

---

## 设计目标


| 目标                            | 说明                                                         |
| ----------------------------- | ---------------------------------------------------------- |
| **Knowledge Accumulation**    | 将 EP 中的教训、决策、模式沉淀为结构化记忆，避免重复踩坑                            |
| **Context Engineering**       | 任务前自动注入最相关记忆片段，三级漏斗降低路径幻觉                                  |
| **Architectural Constraints** | 机械化扫描 6 条架构红线（AC-1 ~ AC-6），规范变为可执行检查                       |
| **Entropy Management**        | 文档漂移检测、孤立记忆扫描、LFU 热度 GC，防止知识库退化                            |
| **EP Lifecycle**              | `precheck → 修改代码 → postcheck → distill` 闭环，EP 质量门控        |
| **AIU Intent Decomposition**  | 任务原子化分解（28 种 AIU 类型），类比数据库查询优化器的算子化执行                      |
| **Query Feedback**            | 执行失败后三级回退策略（扩预算/插前置/分裂），类比 CBO Query Feedback             |
| **Cold Start**                | `mms bootstrap` 一键冷启动：AST 骨架化 + 种子包注入，0.4s，零 LLM 调用       |
| **AST-Ontology Dual Track**   | 双轨上下文路由：物理骨架（AST）+ 业务语义（Ontology）精准注入小模型，消除"注意力丢失"问题 |
| **Semantic Drift Prevention** | postcheck 自动检测接口契约变更（AST Diff），驱动 Ontology YAML 自动修补         |


---

## 模块分层架构

MMS 的代码分为 **5 个层次**，各层单向依赖（上层调用下层）：

```
┌──────────────────────────────────────────────────────────────────────────┐
│  L5 · 命令行与配置层  (cli.py · mms_config.py · router.py)                │
│  用户交互入口，统一命令分发与系统配置中枢                                  │
├──────────────────────────────────────────────────────────────────────────┤
│  L4 · 工作流编排层                                                        │
│  synthesizer.py  ep_wizard.py  ep_parser.py                              │
│  precheck.py  postcheck.py  unit_generate.py  unit_runner.py             │
│  unit_cmd.py  unit_context.py  unit_compare.py                           │
│  AIU 子系统：task_decomposer.py · aiu_types.py                            │
│             aiu_cost_estimator.py · aiu_feedback.py                      │
│  EP 全生命周期：意图合成 → DAG 生成 → 原子执行 → 后校验 → 知识蒸馏      │
├──────────────────────────────────────────────────────────────────────────┤
│  L3 · 推理与分析层                                                        │
│  intent_classifier.py   arch_resolver.py   graph_resolver.py             │
│  injector.py            task_matcher.py    dream.py                      │
│  [EP-130] ast_skeleton.py   repo_map.py   dep_sniffer.py                 │
│  本体化意图识别 → 双轨路由（AST+Ontology）→ 记忆检索 → 知识萃取           │
├──────────────────────────────────────────────────────────────────────────┤
│  L2 · 质量检查层                                                          │
│  arch_check.py   precheck.py（双重职责）   postcheck.py（双重职责）        │
│  atomicity_check.py   verify.py   validate.py   doc_drift.py             │
│  entropy_scan.py   fix_gen.py   sandbox.py   ci_hook.py                  │
│  [EP-130] ast_diff.py   ontology_syncer.py                               │
│  架构约束静态扫描 + AST 契约变更检测 + 文档健康 + 测试门控                │
├──────────────────────────────────────────────────────────────────────────┤
│  L1 · 基础设施层                                                          │
│  dag_model.py         ep_parser.py（双重职责）                            │
│  template_lib.py      codemap.py   funcmap.py                            │
│  model_tracker.py     private.py   file_applier.py                       │
│  [EP-130] seed_packs/                                                    │
│  core/  providers/  resilience/  observability/                          │
│  数据模型、LLM Provider 抽象、读写工具、韧性机制、种子包                   │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 模块关系图（关键调用链）

```
用户输入任务
    │
    ▼
cli.py ──────────────────────────────────────────────────────────┐
    │                                                             │
    ├─► synthesizer.py          EP 起手提示词生成                   │
    │       ├── task_matcher.py    (L1: 历史相似)                   │
    │       ├── intent_classifier.py → arch_resolver.py            │
    │       │       └── [EP-130] resolve_with_ast_skeleton()       │
    │       │               ├── repo_map.py  (AST 骨架 Token-Fit)  │
    │       │               └── Ontology 约束条款                   │
    │       └── injector.py       (L2: 记忆检索)                   │
    │                                                             │
    ├─► bootstrap [EP-130]      冷启动（零 LLM）                    │
    │       ├── dep_sniffer.py     技术栈嗅探                       │
    │       ├── seed_packs/        种子包注入（squads-cli 风格）     │
    │       ├── ast_skeleton.py    AST 骨架化                      │
    │       └── repo_map.py        入口点绑定                       │
    │                                                             │
    ├─► unit_generate.py        DAG 生成                           │
    │       └── dag_model.py      DagUnit 数据结构（含 aiu_steps）  │
    │                                                             │
    ├─► unit_runner.py          Unit 执行引擎                       │
    │       ├── task_decomposer.py ─► aiu_types.py                │
    │       │       ├── [RBO 规则 + LLM 兜底]                      │
    │       │       └── build_constrained_context()  动态 Token-Fit │
    │       ├── aiu_cost_estimator.py   代价估算                    │
    │       ├── aiu_feedback.py         反馈统计                    │
    │       ├── unit_context.py         上下文构建                  │
    │       └── sandbox.py              隔离执行                    │
    │                                                             │
    ├─► precheck.py / postcheck.py  质量门控                        │
    │       ├── arch_check.py          架构约束扫描                 │
    │       ├── [EP-130] ast_diff.py   AST 契约变更检测             │
    │       │       └── ontology_syncer.py  本体自动修补            │
    │       ├── atomicity_check.py     原子性检查                   │
    │       └── doc_drift.py           文档漂移检测                 │
    │                                                             │
    ├─► dream.py                autoDream 知识萃取                  │
    │       └── injector.py                                       │
    │                                                             │
    └─► providers/factory.py    LLM 路由层                          │
            ├── bailian.py      (主力：百炼 qwen3)                  │
            ├── ollama.py       (本地降级)                          │
            └── claude.py       (兜底)                             │
                                                                  │
共享底层：core/ · resilience/ · observability/ ◄──────────────────┘
```

---

## 各模块职责速查

### L5 — 命令行与配置层


| 模块              | 职责                              |
| --------------- | ------------------------------- |
| `cli.py`        | 统一命令行入口，解析子命令并路由到各功能模块          |
| `mms_config.py` | 系统配置中枢，所有阈值/参数的唯一权威来源（禁止各模块硬编码） |
| `router.py`     | 任务路由策略，决定某类任务走哪条 Provider 链     |


### L4 — 工作流编排层


| 模块                      | 职责                                                     |
| ----------------------- | ------------------------------------------------------ |
| `synthesizer.py`        | EP 起手提示词生成：三级漏斗检索（历史匹配 → 记忆检索 → 静态兜底）                  |
| `ep_wizard.py`          | EP 向导（新章节多行输入、确认流程）                                    |
| `ep_parser.py`          | EP Markdown 文件解析，提取 Unit 列表、Testing Plan、Scope 表格      |
| `unit_generate.py`      | DAG 生成：将 EP Scope 编译为 DagUnit 执行计划                     |
| `unit_runner.py`        | Unit 执行引擎：3-Strike 重试 + AIU Feedback 三级回退              |
| `unit_cmd.py`           | `mms unit` 子命令入口（next/done/run/run-next/run-all）       |
| `unit_context.py`       | 为单个 Unit 构建上下文（文件摘要 + 记忆注入 + 层边界契约）                    |
| `unit_compare.py`       | Unit 输出差异对比（Sonnet 生成 vs Gemini 裁判）                    |
| `task_decomposer.py`    | **[EP-129]** 任务 AIU 分解器：RBO 规则优先 + LLM 兜底，将任务拆分为原子步骤   |
| `aiu_types.py`          | **[EP-129]** AIU 数据结构定义：28 种类型（6 族）+ 错误分类规则表           |
| `aiu_cost_estimator.py` | **[EP-129]** AIU 代价估算器（CBO）：基于文件复杂度 + 历史成功率估算 token 预算 |
| `aiu_feedback.py`       | **[EP-129]** AIU 执行反馈统计：记录真实代价，驱动下次估算优化                |


### L3 — 推理与分析层


| 模块                     | 职责                                                               |
| ---------------------- | ---------------------------------------------------------------- |
| `intent_classifier.py` | 本体化意图分类器（MMS-OG v3.0），规则驱动 + LLM 兜底，输出层/操作/置信度                 |
| `arch_resolver.py`     | 意图 → 文件路径解析；**[EP-130]** 新增 `resolve_with_ast_skeleton()` 双轨路由 |
| `graph_resolver.py`    | 记忆图谱遍历，从 MEMORY_INDEX.json 组装上下文                               |
| `injector.py`          | 记忆注入引擎：多模式（default/dev/arch/debug/frontend）关键词检索 + 压缩          |
| `task_matcher.py`      | Jaccard + 时间衰减历史任务相似度匹配（synthesizer 第一级漏斗）                     |
| `dream.py`             | autoDream：EP 结束后自动萃取知识草稿（`mms dream --ep EP-NNN`）              |
| `ast_skeleton.py`      | **[EP-130]** AST 骨架化器：Python `ast` 标准库精确解析 + TS 正则粗粒度提取        |
| `repo_map.py`          | **[EP-130]** 局部引用子图 + 动态 Token-Fit（aider 启发），为小模型裁剪最优上下文      |
| `dep_sniffer.py`       | **[EP-130]** 技术栈嗅探器：扫描 requirements.txt / package.json / 目录特征 |


### L2 — 质量检查层


| 模块                    | 职责                                                                       |
| --------------------- | ------------------------------------------------------------------------ |
| `arch_check.py`       | 架构约束静态扫描（AC-1 ~ AC-6），可作为 CI 门控                                         |
| `atomicity_check.py`  | Unit 原子性检查：单文件变更、无业务逻辑跨层                                                |
| `verify.py`           | 全维度健康检查（schema / index / docs / frontend 四维）                            |
| `validate.py`         | 记忆文件 YAML front-matter Schema 校验                                        |
| `doc_drift.py`        | 文档漂移检测：代码变更后相关文档是否同步                                                   |
| `entropy_scan.py`     | 熵扫描：孤立记忆 / 幽灵引用 / 过期记忆 / 私有区膨胀                                         |
| `fix_gen.py`          | 架构违反 LLM 辅助补丁生成（为 arch_check 违规提供修复建议）                                 |
| `sandbox.py`          | 隔离执行沙箱：文件写入前 Scope 守卫，防止超出 Unit 边界                                     |
| `ci_hook.py`          | CI 集成辅助：GitHub Actions 钩子脚本                                            |
| `ast_diff.py`         | **[EP-130]** AST 契约变更检测：比对两份 ast_index 快照，识别新增/删除/签名变更（ChangeKind 枚举） |
| `ontology_syncer.py`  | **[EP-130]** 本体语义漂移修补器：自动修补 ObjectDef.properties，告警破坏性契约变更              |


### L1 — 基础设施层


| 模块                 | 职责                                                                  |
| ------------------ | ------------------------------------------------------------------- |
| `dag_model.py`     | DagUnit / DagState 数据模型；支持 AIU 子步骤（`aiu_steps`）与反馈日志                |
| `template_lib.py`  | EP/代码 Prompt 模板库（ep-backend-api / ep-frontend / ep-data-pipeline 等） |
| `codemap.py`       | 代码目录快照生成器，维护 `docs/memory/_system/codemap.md`                       |
| `funcmap.py`       | 函数签名 + docstring 索引生成器，维护 `docs/memory/_system/funcmap.md`          |
| `model_tracker.py` | LLM 调用用量追踪（token / 延迟 / 成功率），写 `model_usage.jsonl`                  |
| `private.py`       | 私有工作区管理（EP 私有文件的隔离存储）                                               |
| `file_applier.py`  | 将 Unit 输出的代码块应用到磁盘（原子写入）                                            |

#### `seed_packs/` — 冷启动种子包（EP-130）

squads-cli 风格，每个包为独立目录，通过 `shutil.copytree` 直接安装到目标项目：

| 种子包                  | 触发条件                             | 注入内容                            |
| -------------------- | -------------------------------- | ------------------------------- |
| `base/`              | 始终注入                             | 分层边界约束 + API 契约规范（通用工程基线）       |
| `fastapi_sqlmodel/`  | 检测到 `fastapi` + `sqlmodel`       | SQLAlchemy autobegin 陷阱 + RLS 基线 |
| `fastapi_kafka/`     | 检测到 `fastapi` + `aiokafka`       | Kafka 序列化规范 + Consumer 反模式     |
| `react_zustand/`     | 检测到 `react` + `zustand` / `antd` | 前端数据获取模式 + Store 架构规范           |
| `palantir_arch/`     | 检测到 Palantir 风格目录结构              | Control/Data Plane 分离 + CQRS 约束 |


#### `core/` — 底层工具


| 模块                | 职责                                           |
| ----------------- | -------------------------------------------- |
| `core/indexer.py` | MEMORY_INDEX.json 读写（层级记忆索引）                 |
| `core/reader.py`  | 记忆文件解析（YAML front-matter + Markdown 内容）      |
| `core/writer.py`  | 原子文件写入（`atomic_write` / `atomic_write_json`） |


#### `providers/` — LLM Provider 抽象


| 模块                     | 职责                                        |
| ---------------------- | ----------------------------------------- |
| `providers/base.py`    | LLMProvider / EmbedProvider 协议接口          |
| `providers/bailian.py` | 阿里云百炼适配器（OpenAI 兼容，纯 stdlib）              |
| `providers/ollama.py`  | Ollama 本地适配器（推理 + Embed）                  |
| `providers/claude.py`  | Claude / Cursor Sonnet（Pending Prompt 兜底） |
| `providers/factory.py` | Provider 工厂、任务路由、降级链管理                    |


#### `resilience/` — 韧性模块


| 模块                              | 职责                                |
| ------------------------------- | --------------------------------- |
| `resilience/retry.py`           | 指数退避重试装饰器                         |
| `resilience/circuit_breaker.py` | 熔断器（CLOSED / OPEN / HALF-OPEN 三态） |
| `resilience/checkpoint.py`      | 蒸馏断点保存 / 恢复                       |


#### `observability/` — 可观测性


| 模块                        | 职责                                |
| ------------------------- | --------------------------------- |
| `observability/audit.py`  | 操作审计日志（`audit.jsonl`，append-only） |
| `observability/tracer.py` | 操作耗时追踪（EP-127，4 级追踪深度）            |


---

## AIU 子系统（EP-129）

**AIU（Atomic Intent Unit）** 是代码生成的最小可执行语义单元，类比数据库查询优化器中的"算子"。

### 6 族 28 种 AIU 类型


| 族                 | 类型 ID | 说明                                 |
| ----------------- | ----- | ---------------------------------- |
| A: Schema         | A1-A6 | 字段/关系/Schema 定义操作                  |
| B: Control Flow   | B1-B5 | 条件/分支/循环/方法提取/守卫                   |
| C: Data Access    | C1-C5 | SELECT/Filter/INSERT/UPDATE/DELETE |
| D: Interface      | D1-D5 | API 端点/路由/前端组件/权限守卫/Store          |
| E: Infrastructure | E1-E4 | Kafka/Worker/Config/Migration      |
| F: Validation     | F1-F3 | 单元测试/集成测试/E2E 测试                   |


### AIU Feedback（Query Feedback 机制）

类比数据库优化器发现执行代价超预期后的回退重优化：


| 级别  | 触发条件                | 动作                    |
| --- | ------------------- | --------------------- |
| L1  | 上下文不足 / 语法错误 / 测试断言 | 扩充 token 预算，重试生成      |
| L2  | 缺少前置 Schema / 字段未定义 | 建议插入前置 AIU（如先加字段再写逻辑） |
| L3  | 逻辑冲突 / 任务过于复杂       | 建议将当前 AIU 拆分为两个子步骤    |


---

## 记忆存储结构

```
docs/memory/
├── MEMORY_INDEX.json       # 层级索引（推理检索入口）
├── MEMORY.md               # 人类可读记忆指针索引
├── _system/                # 系统级数据
│   ├── config.yaml         # MMS 全局配置
│   ├── codemap.md          # 代码目录快照（文件路径唯一可信来源）
│   ├── funcmap.md          # 函数签名索引
│   ├── ast_index.json      # [EP-130] AST 骨架索引（类/方法/签名/指纹）
│   ├── feedback_stats.jsonl  # AIU 执行反馈统计（append-only WAL）
│   ├── model_usage.jsonl   # LLM 调用用量记录
│   ├── dag/                # DAG 执行计划（EP 私有）
│   └── checkpoints/        # 蒸馏断点 + precheck-{EP}-ast.json
├── shared/                 # 共享知识库（L1~L5 + cross_cutting + BIZ）
│   ├── L1_platform/        # 安全/可观测/配置层记忆
│   ├── L2_infrastructure/  # DB/Kafka/Redis 层记忆
│   ├── L3_domain/          # 本体/数据管道/治理层记忆
│   ├── L4_application/     # Service/Worker/CQRS 层记忆
│   ├── L5_interface/       # API/前端/测试层记忆
│   └── cross_cutting/      # 架构决策 ADR
├── ontology/               # MMS 自身的本体定义（MMS-OG v3.0）
│   ├── arch_schema/        # layers.yaml · operations.yaml · intent_map.yaml
│   ├── actions/            # EP 工作流 ActionDef（含 unit_run / dream）
│   ├── functions/          # 计算属性 FunctionDef（含 fn_decompose_task / fn_estimate_aiu_cost）
│   └── objects/            # ObjectTypeDef（含 DagUnit / AIUStep）
├── private/                # EP 私有工作区（已 gitignore）
└── templates/              # 记忆文件 Prompt 模板

scripts/mms/seed_packs/     # [EP-130] 冷启动种子包（squads-cli 风格）
├── base/                   # 通用基础约束（始终注入）
├── fastapi_sqlmodel/       # FastAPI + SQLModel 栈专项记忆
├── fastapi_kafka/          # Kafka 消息队列栈专项记忆
├── react_zustand/          # React + Zustand 前端栈专项记忆
└── palantir_arch/          # Palantir 风格架构约束专项记忆
```

---

## 快速开始

### 前置要求

- Python 3.9+（无第三方运行时依赖）
- 阿里云百炼 API Key（推荐）或本地 Ollama

### 环境配置

```bash
# 1. 写入 API Key（.env.memory 已被 .gitignore 忽略）
cat >> .env.memory <<'EOF'
DASHSCOPE_API_KEY=sk-...
EOF

# 2. 配置 shell alias
alias mms="python3 $HOME/code/mdp-enterprise-version-build-with-cursor/scripts/mms/cli.py"

# 3. 验证
mms status
```

### 常用命令速查

```bash
# ── 基础操作 ──────────────────────────────────────────────────────────────────
mms status                          # 服务状态（Provider 可用性 / 记忆统计）
mms synthesize "新增对象类型 API"    # 意图合成 → 生成 EP 起手提示词
mms inject "修复 Kafka 序列化异常"   # 注入记忆上下文到 Prompt
mms precheck --ep EP-NNN            # EP 代码修改前门控检查
mms postcheck --ep EP-NNN           # EP 代码修改后校验（含 pytest + AST 同步）
mms distill --ep EP-NNN             # EP 知识蒸馏 → 写入共享记忆
mms search kafka avro               # 关键词检索记忆
mms list --tier hot                 # 列出热点记忆
mms validate                        # 记忆文件 Schema 校验
mms verify                          # 全维度健康检查
mms gc                              # GC（LFU 热度重算 + 索引更新）
mms codemap && mms funcmap          # 刷新代码路径快照
mms usage --since 7                 # 最近 7 天模型 token 消耗统计

# ── EP-130 新增命令 ───────────────────────────────────────────────────────────
mms bootstrap                       # 冷启动：AST骨架化 + 种子包注入（0.4s，零LLM）
mms bootstrap --dry-run             # 预览冷启动计划，不写文件
mms bootstrap --skip-ast            # 只注入种子包，跳过 AST 骨架化
mms ast-diff --ep EP-NNN            # 与 precheck 快照对比 AST 契约变更
mms ast-diff --before a.json --after b.json  # 比对任意两份 ast_index.json
```

---

## EP 工作流（7 步闭环）

```
① synthesize  →  ② 生成 EP 文档（用户确认）  →  ③ precheck
                                                      ↓
⑦ dream      ←  ⑥ distill  ←  ⑤ postcheck  ←  ④ 修改代码 + 生成测试
```

```bash
# ① 意图合成（三级漏斗：历史匹配 → 记忆检索 → 静态兜底）
mms synthesize "为对象类型新增批量导出 API" --template ep-backend-api

# 可用模板：ep-backend-api / ep-frontend / ep-ontology / ep-data-pipeline / ep-debug / ep-devops
mms synthesize --list-templates

# ② 将输出粘贴给 Cursor → 生成 EP 文件 → 用户确认（Go）

# ③ 代码修改前检查（建立架构基线）
mms precheck --ep EP-NNN

# ④ 按 EP Unit 修改代码 + 生成测试

# ⑤ 代码修改后校验
mms postcheck --ep EP-NNN
mms postcheck --ep EP-NNN --skip-tests   # 跳过 pytest（仅 arch_check + doc_drift）

# ⑥ 知识蒸馏（postcheck PASS 后）
mms distill --ep EP-NNN

# ⑦ autoDream 自动萃取知识草稿
mms dream --ep EP-NNN
mms dream --list        # 列出草稿
mms dream --promote     # 审核并提升为正式记忆
```

---

## 核心子系统

### 冷启动（`mms bootstrap`，EP-130）

在新项目或无记忆积累的空白环境中，一条命令完成初始化：

```
mms bootstrap（0.4s，零 LLM 调用）

  Step 1: dep_sniffer.scan()       → 识别技术栈（fastapi/sqlmodel/react/zustand…）
  Step 2: seed_packs.install()     → 复制种子记忆到 docs/memory/（分层架构约束 + 反模式）
  Step 3: ast_skeleton.build()     → 扫描 239 文件 → ast_index.json（类/方法/签名/指纹）
  Step 4: repo_map.bind()          → entry_files → ast_pointer 绑定
```

**效果**：全新项目立即获得：
- 通用架构约束基线（分层边界 + API 契约 + 安全 RLS）
- 技术栈专属反模式警告（autobegin 陷阱 / Kafka 序列化 / 前端 Store 模式）
- 完整代码骨架图（给小模型的"物理世界观"）

### AST-Ontology 双轨路由（EP-130）

单次 AIU 执行时，`arch_resolver.resolve_with_ast_skeleton()` 打包双轨上下文：

```
┌────────────────────────────────────────────────────┐
│  任务：新增 POST /export 路由                        │
│  token 预算：4000                                   │
├────────────────────────────────────────────────────┤
│  Track 1 · AST 骨架（物理层）                        │
│    backend/app/api/v1/endpoints/ontology.py:        │
│    ⋮...                                            │
│    │class OntologyRouter:                          │
│    │    @require_permission(...)                   │
│    │    async def list_objects(...) -> ...: ...    │
│    ⋮...                                            │
├────────────────────────────────────────────────────┤
│  Track 2 · Ontology 约束（语义层）                   │
│    [MEM-L-011] Avro 格式必须一致                     │
│    [AD-002] Service 首参必须是 SecurityContext       │
│    [AD-005] 事务策略：Strategy A 或 B               │
└────────────────────────────────────────────────────┘
                          ↓ Token-Fit 裁剪（二分搜索）
               送入 8b/fast 小模型执行
```

**设计参考**：aider 的 repo-map（AST + PageRank + 动态 Token-Fit）

### 语义漂移防护（`postcheck` Step 3，EP-130）

每次 `mms postcheck` 自动触发 AST Diff + Ontology 同步：

| 变更类型 | 处置策略 |
| ------ | ------ |
| 新增方法/字段 | ✅ 自动追加到 ObjectDef.properties |
| 方法签名变更 | ⚠️ 标记 `ast_pointer.drift=true`，输出告警 |
| 删除类/方法 | 🔴 标记 STALE，强制人工确认 |
| fingerprint 变化（无细节） | ✅ 自动更新 fingerprint |

### 意图合成：三级检索漏斗（`mms synthesize`）


| 级别  | 机制                          | 效果                      |
| --- | --------------------------- | ----------------------- |
| 第一级 | Jaccard 相似度 + 时间衰减，匹配历史任务   | 直接复用验证过的文件路径，**消除路径幻觉** |
| 第二级 | 关键词记忆检索（`injector.py` 增强版）  | 注入相关技术约束、反模式警告          |
| 第三级 | `task_quickmap.yaml` 静态映射兜底 | 毫秒级响应，**始终有输出**         |


### 本体化意图分类（`intent_classifier.py`）

基于 `docs/memory/ontology/arch_schema/intent_map.yaml` 中的规则集（优先级排序）：

- 规则匹配：关键词命中计数 × 权重，超过 `min_hit_ratio` 阈值触发
- LLM 兜底：规则低置信度时调用 LLM 辅助分类
- 路径解析：`arch_resolver.py` 将意图层 + 操作类型映射到真实文件路径，支持 codemap 精确匹配、目录展开、磁盘兜底

### 架构约束扫描（`arch_check.py`）


| 编号   | 红线                                                                  | 检测范围                            |
| ---- | ------------------------------------------------------------------- | ------------------------------- |
| AC-1 | `pymilvus` / `aiokafka` / `elasticsearch` 禁止在 `services/` 直接 import | `backend/app/services/`         |
| AC-2 | Service 公开方法首参必须是 `ctx: SecurityContext`                            | `backend/app/services/`         |
| AC-3 | WRITE 方法必须调 `AuditService.log()`                                    | `backend/app/services/control/` |
| AC-4 | API 返回必须是 `{"code":..,"data":..,"meta":..}` 信封格式                    | `backend/app/api/`              |
| AC-5 | 前端 Management 页面禁止使用 Amis JSON                                      | `frontend/src/pages/`           |
| AC-6 | Worker 必须使用 `JobExecutionScope`                                     | `backend/app/workers/`          |


```bash
python3 scripts/mms/arch_check.py --ci   # CI 模式，违反时 exit 2
python3 scripts/mms/fix_gen.py --file <path> --violation AC-2 --method <fn> --line <N>
```

### 诊断追踪（`observability/tracer.py`，EP-127）

```bash
mms trace enable EP-NNN --level 4    # 开启追踪（Level 4 = LLM 调用详情）
mms trace show EP-NNN                # 查看步骤耗时瀑布图 + LLM token 统计
mms trace summary EP-NNN             # 单行摘要（总耗时 / LLM calls / tokens）
mms trace show EP-NNN --format json  # 结构化 JSON 报告
```


| Level | 名称      | 记录内容                      |
| ----- | ------- | ------------------------- |
| 1     | Basic   | 步骤耗时、成功/失败                |
| 4     | LLM     | +LLM 模型/token/重试次数（推荐）    |
| 8     | FileOps | +文件变更路径/行数/Scope Guard 结果 |
| 12    | Full    | +LLM prompt/response 片段   |


---

## LLM Provider 配置

**路由策略：百炼（主力）→ Ollama（本地降级）→ Claude Pending（兜底）**

```
任务类型               主力 Provider                      降级链
distillation      →   bailian_plus (qwen3-32b)         → ollama_r1 → claude
context_compress  →   bailian_plus (qwen3-32b)         → ollama_r1 → claude
task_routing      →   bailian_plus (qwen3-32b)         → ollama_r1 → claude
code_review       →   bailian_plus (qwen3-32b)         → ollama_r1 → claude
code_gen_simple   →   bailian_coder (qwen3-coder-next) → ollama_coder → claude
complex_arch      →   claude (Cursor Sonnet)           — 人工介入
```

```bash
# .env.memory（已在 .gitignore 中）
DASHSCOPE_API_KEY=sk-...
DASHSCOPE_MODEL_REASONING=qwen3-32b          # 可改 qwen-plus / qwen-max
DASHSCOPE_MODEL_CODING=qwen3-coder-next      # 可改 qwen-coder-plus
```

```bash
ollama pull deepseek-r1:8b && ollama pull deepseek-coder-v2:16b
```

---

## mms_config.py — 配置中枢

所有可调参数通过 `mms_config.py` 统一管理，各模块从 `cfg` 对象读取，**禁止在模块内硬编码**。


| 配置键                               | 默认值   | 说明                    |
| --------------------------------- | ----- | --------------------- |
| `decomposer_confidence_threshold` | 0.6   | AIU 分解触发置信度阈值         |
| `decomposer_long_task_threshold`  | 80    | 触发分解的任务长度（字符）         |
| `decomposer_llm_max_tokens`       | 2000  | LLM 兜底分解 max_tokens   |
| `decomposer_auto_append_test`     | True  | 是否自动追加测试 AIU          |
| `cost_estimator_token_min`        | 1500  | AIU token 预算下界        |
| `cost_estimator_token_max`        | 16000 | AIU token 预算上界        |
| `cost_estimator_chars_per_token`  | 4     | 字符/token 换算比          |
| `fast_model_max_tokens`           | 4000  | fast 模型适用的最大 token 数  |
| `feedback_warn_success_threshold` | 0.5   | 低成功率警告阈值              |
| `feedback_suggest_min_samples`    | 3     | 给出建议所需的最少历史样本         |
| `ast_max_methods_per_class`       | 20    | **[EP-130]** 每类最多提取方法数 |
| `ast_max_files`                   | 2000  | **[EP-130]** AST 扫描最大文件数 |
| `ast_docstring_max_len`           | 100   | **[EP-130]** docstring 最大保留长度 |
| `repo_map_chars_per_token`        | 4     | **[EP-130]** Token 估算：字符/token |
| `repo_map_default_tokens`         | 1500  | **[EP-130]** Repo-Map 默认 token 预算 |
| `repo_map_bfs_depth`              | 2     | **[EP-130]** 引用图 BFS 跳数 |
| `repo_map_max_neighbors`          | 6     | **[EP-130]** 每文件最多邻居节点数 |


---

## 记忆文件格式

```markdown
---
id: MEM-L-050
layer: L4_application
module: service
dimension: D4
type: lesson
tier: hot
tags: [transaction, mysql, autobegin]
source_ep: EP-112
created_at: "2026-04-14"
last_accessed: "2026-04-14"
access_count: 0
---
# MEM-L-050 · 标题（WHAT）

## WHERE（适用场景）
## HOW（核心实现 / 正确做法）
## WHEN（触发条件 / 危险信号）
```


| 字段          | 枚举值                                                      | 说明            |
| ----------- | -------------------------------------------------------- | ------------- |
| `layer`     | `L1_platform` ~ `L5_interface` / `cross_cutting` / `BIZ` | 所属架构层         |
| `dimension` | `D1`（安全）~ `D10`（测试）                                      | 工程维度          |
| `type`      | `lesson` / `pattern` / `decision` / `constraint`         | 记忆类型          |
| `tier`      | `hot` / `warm` / `cold`                                  | LFU 热度（GC 依据） |


---

## Benchmark（三系统性能对比）

MMS 提供内置 benchmark，对比 **Markdown BM25**、**Hybrid RAG（ES+Milvus+RRF）**、**Ontology MMS** 三种记忆检索系统：

```bash
cd scripts/mms/benchmark
python run_benchmark.py                            # 运行全部系统（默认 queries.yaml）
python run_benchmark.py --dataset data/queries_v2.yaml --dataset-version v3  # 使用 v2 数据集
python run_benchmark.py --systems ontology markdown  # 只跑特定系统
python run_benchmark.py --report-only              # 重新生成报告（不重跑）
```

详见 `scripts/mms/benchmark/README.md`。

---

---

## 本体定义（MMS-OG v3.0）

MMS 用动态本体来组织自己的知识结构，核心对象如下：

| ObjectTypeDef    | 对应实现                    | 说明                          |
| ---------------- | ----------------------- | --------------------------- |
| `DagUnit`        | `dag_model.py::DagUnit` | EP 的文件级执行单元，含 aiu_steps      |
| `AIUStep`        | `aiu_types.py::AIUStep` | 最小语义执行单元（28 种类型，6 族）        |
| `DiagnosticEvent`| `trace/event.py`        | 可观测的最小工作流事件                 |

| ActionDef           | CLI 命令               | 说明                     |
| ------------------- | -------------------- | ---------------------- |
| `action_synthesize` | `mms synthesize`     | 意图合成→EP 提示词            |
| `action_precheck`   | `mms precheck`       | 前置检查，建立 AST 基线快照       |
| `action_postcheck`  | `mms postcheck`      | 后校验，含 AST 同步探针（EP-130） |
| `action_unit_run`   | `mms unit run`       | Unit 自动执行，触发 AST 同步     |
| `action_dream`      | `mms dream`          | autoDream 自动知识萃取        |

| FunctionDef              | 实现文件                      | 说明                        |
| ------------------------ | ------------------------- | ------------------------- |
| `fn_classify_intent`     | `intent_classifier.py`    | 三阶段意图识别（规则→LLM→AIU）       |
| `fn_decompose_task`      | `task_decomposer.py`      | 任务 AIU 分解（RBO + LLM 兜底）  |
| `fn_estimate_aiu_cost`   | `aiu_cost_estimator.py`   | 代价估算（CBO，预算 + 模型推荐）       |
| `fn_resolve_paths`       | `arch_resolver.py`        | 意图 → 文件路径（含双轨 AST 路由）     |
| `fn_rank_memories`       | `graph_resolver.py`       | 记忆优先级排序                   |

---

*EP-001 ~ EP-130 · Python 3.9+ · 零第三方运行时依赖 · 45 个模块 · 23 个测试文件*