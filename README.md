# 木兰（Mulan）— 端侧 AI 编码工具

> 唧唧复唧唧，木兰当户织。
>
> 织布，是最古老的工程：经线定骨架，纬线填逻辑，梭来梭往积累出完整的布匹。  
> 写代码也是这样，**木兰工具**将复杂的软件任务分解为原子工序（AIU），  
> 以积累的架构知识为经、以精准生成的代码为纬，一梭一线织出符合企业约束的高质量工程产物——  
> 全程在端侧完成，不上传一行代码。

[CI](https://github.com/allengaoo/mms/actions/workflows/ci.yml)
[Python 3.11+](https://www.python.org)
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
③ 穿梭（上下文注入）  从记忆本体图谱中 hybrid_search 相关架构决策、经验教训、代码模式
      │               精准注入，不超出 4k tokens 预算
      ▼
④ 织造（代码生成）    qwen3-coder-plus 生成 Diff，受模板骨架约束
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

---

## 工具链五层架构总览

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║  第一层：任务工程层（Task Engineering）                                        ║
║  功能：意图分解 → DAG 编排 → AIU 原子执行 → EP 全自动 Pipeline                  ║
║  模型：qwen3-32b（意图/推理/评审）                                              ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  代码包：src/mms/workflow/     EP 生命周期（synthesize/precheck/postcheck）     ║
║          src/mms/dag/          AIU 类型/代价估算/分解/反馈                      ║
║          src/mms/execution/    Unit 执行/沙箱/对比/文件应用                     ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  第二层：知识本体层（Knowledge Ontology）                        ← v5.0 重大升级 ║
║  功能：Palantir 动态本体 + 记忆图谱 + 图遍历检索 + Bootstrap 冷启动             ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  代码包：src/mms/ontology/     OntologyRegistry（ObjectType/Fn/Action）        ║
║          src/mms/bootstrap/    Bootstrap v2（五路信号推断 + 初始记忆生成）       ║
║          src/mms/memory/       记忆图谱（检索/注入/图遍历/新鲜度/蒸馏）          ║
║  数据层：docs/memory/ontology/ YAML 本体定义（ObjectType/LinkType/Fn/Action）  ║
║          docs/memory/shared/   积累的记忆文件（5 层 × MEM-*.md）               ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  第三层：代码生成层（Code Generation）                                          ║
║  功能：记忆注入上下文 → LLM 生成 Diff → 模板骨架约束 → 双角色评审               ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  代码包：src/mms/execution/    unit_runner / unit_context / internal_reviewer ║
║          src/mms/providers/    LLM 适配器（bailian/claude/gemini/ollama）      ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  第四层：安全验证层（Safety & Validation）                                      ║
║  功能：AST 契约检测 + 架构约束 + DB 迁移门控 + 脱敏屏障 + MDR 诊断              ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  代码包：src/mms/analysis/     arch_check / ast_diff / dep_sniffer / ast_skel ║
║          src/mms/core/         sanitize / writer / reader / indexer           ║
║          src/mms/observability/ alert_logger / incident / audit               ║
║          src/mms/resilience/   circuit_breaker / retry / checkpoint           ║
║          src/mms/trace/        EPTracer（Oracle 10046 风格，4 级）             ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  第五层：自学习层（Self-Learning）                                              ║
║  功能：EP 知识蒸馏 + Rule Absorber + autoDream + 种子包管理                    ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  代码包：src/mms/memory/       dream / entropy_scan（distill ⬜ v6.0 待开发）  ║
║          src/mms/analysis/     seed_absorber（外部规范 → YAML 种子包）         ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  横切关注点（Cross-Cutting）                                                   ║
║  src/mms/utils/   配置/校验/路由/路径/CI钩子/Token追踪                         ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

---

## 各层详细模块图

> 以下每层展示完整的 Python 模块、关键类、对外接口和模块间依赖。  
> 模块边界是模块粒度开发的基本单元（见[模块化开发指南](#模块化开发指南)）。

---

### Layer 1：任务工程层

```
src/mms/workflow/                        EP 生命周期编排
├── synthesizer.py       850L           意图合成器
│   └── Synthesizer                     synthesize(task) → CursorPrompt
│       依赖: intent_classifier, memory.injector, providers
│
├── ep_parser.py         316L           EP Markdown 解析
│   └── ParsedEP, ScopeUnit             parse_ep_file(path) → DagState
│
├── ep_runner.py         840L           全自动 Pipeline 编排
│   └── EpRunResult, EpRunState         run_ep(ep_id, auto_confirm) → EpRunResult
│       依赖: precheck, unit_generate, unit_runner, postcheck, distill
│
├── ep_wizard.py         642L           交互式向导（mulan ep start）
│   └── WizardState
│
├── precheck.py          348L           前置基线检查
│   └── run_precheck(ep)               arch_check 基线 + AST 快照 + 记忆注入
│
├── postcheck.py         599L           后置质量门
│   └── run_postcheck(ep)              pytest + arch_check + MigrationGate
│
└── migration_gate.py    203L           DB 迁移脚本门控
    └── check_migration_alignment()

src/mms/dag/                             AIU 引擎
├── aiu_types.py         589L           AIU 类型体系（43 种 / 9 族）
│   └── AIUType(Enum), AIUStep, AIUPlan
│
├── dag_model.py         342L           DAG 数据模型
│   └── DagUnit, DagState
│
├── task_decomposer.py   825L           AIU 分解器
│   └── TaskDecomposer                  decompose(task) → AIUPlan
│       依赖: intent_classifier, aiu_registry, providers(qwen3-32b)
│
├── aiu_registry.py      335L           Schema-Driven 动态注册表
│   └── AIURegistry                     get_input_schema / get_validation_rules
│       数据: docs/memory/_system/schemas/aius/*.yaml
│
├── aiu_cost_estimator.py 337L          CBO 代价估算
│   └── AIUCostEstimator                estimate(aiu_type) → {token_budget, model_hint}
│
├── aiu_feedback.py      437L           3 级反馈回退
│   └── AIUFeedbackStore                record / compute_next_level
│
└── atomicity_check.py   347L           Unit 原子化评分
    └── check_atomicity(unit) → CheckResult

src/mms/execution/                       Unit 执行层（11 个模块）
├── unit_generate.py     628L           DAG 生成（EP → Unit 列表）
│   └── generate_units(ep) → List[DagUnit]
│       依赖: task_decomposer, providers(qwen3-32b)
│
├── unit_runner.py      1297L           Unit 自动执行（核心）
│   └── RunResult, AttemptLog           run_unit(unit) → RunResult
│       3-Strike 重试 + SandboxRollback + aiu_feedback
│
├── unit_context.py      425L           单 Unit 压缩上下文生成
│   └── build_context(unit) → str       memory.injector + 代码片段
│
├── sandboxed_runner.py  172L           Sandbox 化执行包装器
│   └── SandboxedCodeRunner
│
├── sandbox.py           257L           GitSandbox（文件操作隔离）
│   └── GitSandbox                      commit / rollback
│
├── file_applier.py      454L           解析并应用 LLM BEGIN/END-CHANGES 块
│   └── ApplyResult, FileChange         apply_changes(diff_text, files)
│
├── unit_compare.py      629L           双模型对比 + 语义评审
│   └── compare_outputs(qwen, sonnet) → CompareReport
│
├── internal_reviewer.py 180L           双角色内部评审（feature flag）
│   └── review(code) → ReviewResult
│
├── unit_cmd.py          370L           unit 子命令（status/next/done/reset）
├── fix_gen.py           219L           自动生成修复建议
└── (依赖图)
    unit_runner → file_applier, sandbox, aiu_feedback, trace, providers
    unit_context → memory.injector, memory.graph_resolver
```

---

### Layer 2：知识本体层

```
src/mms/ontology/                        动态本体注册表
└── registry.py          707L
    ├── ObjectTypeRegistry               加载 objects/*.yaml，validate(type_id, inst)
    ├── FunctionRegistry                 加载 functions/*.yaml，call(fn_id, **kwargs)
    ├── ActionRegistry                   加载 actions/*.yaml，check_submission_criteria
    ├── RuleEngine                       按 ActionDef.rules 顺序执行，路由 fn/validate
    └── OntologyRegistry                 统一入口，validate_completeness()

src/mms/bootstrap/                       Bootstrap v2（五路信号推断）
├── signal_fusion.py     497L           fn_infer_layer + fn_detect_code_object_type
│   ├── infer_layer()                   路径/命名/注解/继承/导入 五路加权
│   ├── detect_code_object_type()       Controller/Service/Repository/Entity/Config
│   └── infer_all()                     批量推断（供 Bootstrap 使用）
│
├── code_graph_builder.py 281L          fn_build_code_graph
│   └── build_code_graph()             depends_on/implements 有向图 + in_degree 索引
│
├── memory_seed_generator.py 309L       初始记忆生成器
│   └── generate_seed_memories()       → docs/memory/shared/{LAYER}/MEM-BOOT-*.md
│
└── ontology_populator.py 300L          action_bootstrap 6步编排器（CLI 主入口）
    └── bootstrap_project()             调用以上三模块 + dep_sniffer + ast_skeleton

src/mms/memory/                          记忆图谱（17 个模块）
│
├── ─── 检索与注入 ──────────────────────────────────────────
│   graph_resolver.py    997L           知识图谱（核心）
│   └── MemoryGraph, MemoryNode         hybrid_search / typed_explore / find_by_concept
│       依赖: link_registry, core.reader, intent_classifier
│
│   injector.py          510L           记忆注入
│   └── MemoryInjector                  inject(task) → InjectionResult（Cursor 前缀）
│       依赖: graph_resolver, memory_functions
│
│   intent_classifier.py 465L           3 级意图漏斗
│   └── IntentClassifier                classify(text) → IntentResult
│       Level1:RBO → Level2:本体匹配 → Level3:LLM
│
│   task_matcher.py      337L           任务-记忆相关度匹配
│   └── TaskMatcher                     match(task, candidates) → MatchResult
│
├── ─── 图谱管理 ──────────────────────────────────────────
│   memory_functions.py  285L           纯函数层（无副作用，可测试）
│   └── MemoryInsight, MemoryQualityScore  compute_quality / extract_provenance
│
│   memory_actions.py    480L           有状态动作层（写入 / 矛盾检测）
│   └── ActionResult                    write_memory / detect_contradictions / archive
│
│   link_registry.py     267L           LinkType YAML 注册表
│   └── LinkTypeRegistry                加载 ontology/links/*.yaml
│
│   freshness_checker.py 229L           记忆新鲜度检测（fn_detect_drift 实现）
│   └── FreshnessChecker                check(memory_id, ast_index) → FreshnessReport
│
│   graph_health.py      245L           图健康监控
│   └── HealthReport                    compute_health() → 节点分布/边覆盖/孤立率
│
│   entropy_scan.py      675L           孤儿/过时记忆检测 + 边衰减
│
├── ─── 蒸馏与生产 ──────────────────────────────────────────
│   dream.py             767L           autoDream（git 历史 → 知识草稿 + auto-link）
│   private.py           247L           EP 私有工作区（草稿笔记）
│
├── ─── 辅助工具 ──────────────────────────────────────────
│   codemap.py           236L           代码目录快照生成
│   funcmap.py           296L           函数签名索引生成
│   repo_map.py          371L           PageRank 风格文件重要性排序
│   template_lib.py      322L           填空式代码骨架模板

docs/memory/ontology/                    YAML 本体定义（无代码修改可扩展）
├── objects/  (8 个 ObjectType YAML)
├── links/    (8 个 LinkType YAML)
├── functions/(9 个 Function YAML)
├── actions/  (5 个 Action YAML)
└── _config/traversal_paths.yaml        图遍历路径（新增路径不改代码）
```

---

### Layer 3：代码生成层

```
src/mms/providers/                       LLM Provider 适配器（策略模式）
├── base.py               63L           ProviderBase 抽象基类
│   └── complete(prompt) / embed(text)
│
├── factory.py           210L           任务 → Provider 路由
│   └── get_provider(task_type)         code_gen → bailian_coder
│                                       reasoning → bailian_plus
│
├── bailian.py           376L           阿里云百炼（主力 Provider）
│   ├── BailianProvider                 qwen3-32b（推理/评审）
│   └── BailianEmbedProvider            text-embedding-v3（可选）
│       配置: DASHSCOPE_API_KEY / .env.memory
│
├── claude.py             80L           Anthropic Claude（Fallback）
│   └── ClaudeProvider                  ANTHROPIC_API_KEY
│
├── gemini.py            276L           Google Gemini（备用）
└── ollama.py            191L           Ollama 本地模型（备用）

LLM 任务路由：
  code_generation  → bailian_coder  → qwen3-coder-plus
  dag_generation   → bailian_plus   → qwen3-32b
  code_review      → bailian_plus   → qwen3-32b
  intent_classify  → bailian_plus   → qwen3-32b（Level3 fallback）
  knowledge_distil → bailian_plus   → qwen3-32b

src/mms/execution/（与 Layer 1 共享）
  unit_context.py  → 上下文精准注入（< 4k tokens）
  unit_runner.py   → LLM 调用 + 3-Strike 重试
  internal_reviewer.py → 双角色评审（feature flag）
  unit_compare.py  → 双模型对比（Qwen vs Sonnet）
```

---

### Layer 4：安全验证层

```
src/mms/analysis/                        代码静态分析（14 个模块）
│
├── ─── AST 解析子系统 ──────────────────────────────────────
│   ast_skeleton.py      837L           多语言 AST 骨架化（核心）
│   └── AstSkeletonBuilder              build() → ast_index.json
│       MethodSkeleton, ClassSkeleton, FileSkeleton
│       支持: Python(ast模块) / Java / Go / TypeScript(正则)
│       可选: Tree-sitter Sidecar 升级
│
│   parsers/                            AST 解析器适配层
│   ├── protocol.py        35L          ASTParserProtocol（接口）
│   ├── factory.py         74L          get_parser()：自动路由+降级
│   ├── regex_parser.py    35L          RegexFallbackParser（零依赖）
│   └── tree_sitter_parser.py 202L     TreeSitterParser（可选强化）
│
│   ast_diff.py           322L          AST diff（接口契约变更检测）
│   └── AstDiffResult, ContractChange   diff(before, after) → changes[]
│
├── ─── 架构约束子系统 ──────────────────────────────────────
│   arch_check.py         308L          架构约束扫描（6 条硬规则）
│   └── run_arch_check()               可被 seed_packs/constraints.yaml 扩展
│
│   arch_resolver.py      435L          层 → 文件路径解析器
│   └── ArchResolver                    resolve_layer(layer) → [file_paths]
│
├── ─── 依赖与同步子系统 ──────────────────────────────────────
│   dep_sniffer.py        498L          技术栈嗅探
│   └── DependencySniffer               sniff(root) → StackProfile
│       requirements.txt / pom.xml / go.mod / package.json
│
│   ontology_syncer.py    357L          本体 YAML ↔ AST 同步
│   └── OntologySyncer                  sync() → SyncReport
│
│   doc_drift.py          244L          文档漂移检测
│
│   signal_fusion.py      459L          分析层信号融合（Layer 4 独立副本）
│   └── LayerInference, SignalBreakdown 同 bootstrap/signal_fusion，供架构约束分析调用
│
│   seed_absorber.py      750L          Rule Absorber（URL → YAML 种子包）
│   └── absorb(url) → SeedPack         用于 Layer 5，此处归 analysis

src/mms/core/                            基础 I/O（安全写入）
├── sanitize.py          120L           SanitizationGate（脱敏屏障）
│   └── sanitize(text) → str            API Key / JWT / IP → [REDACTED_*]
│
├── writer.py             81L           安全文件写入（集成脱敏）
│   └── safe_write(path, content)
│
├── reader.py            180L           编码自适应文件读取（含 TTL 缓存）
│   └── MemoryReader                    read_memory(id) → MemoryNode
│
└── indexer.py           198L           记忆索引构建器
    └── IncrementalIndexer              build_index(dir) → MEMORY_INDEX.json

src/mms/observability/                   MDR 诊断基础设施
├── logger.py            158L           全局告警日志
│   └── alert_info/alert_warn/alert_fatal/alert_circuit
│       写入: docs/memory/private/mdr/alert/alert_mulan.log（按天轮转）
│
├── incident.py          232L           Incident Dump 黑匣子
│   └── setup_incident_handler()        sys.excepthook 全局接管
│       输出: call_stack.dmp / prompt_context.txt / incident_manifest.json
│
├── audit.py             154L           Append-only JSONL 操作审计
│   └── AuditLogger
│
└── tracer.py             28L           轻量 Trace ID 生成器

src/mms/resilience/                      可靠性原语
├── circuit_breaker.py   186L           熔断器（三态机）
│   └── CircuitBreaker                  CLOSED → OPEN → HALF_OPEN → CLOSED
│       状态转移 → alert_mulan.log
│
├── retry.py              83L           指数退避重试装饰器
│   └── @retry(max_attempts=3)
│
└── checkpoint.py        137L           断点保存/恢复（长任务续跑）
    └── Checkpoint                      save(state) / restore() → CheckpointState

src/mms/trace/                           EP 级诊断追踪（Oracle 10046 风格）
├── event.py             223L           TraceEvent（4 级诊断级别）
│   └── Level1/4/8/12
│
├── tracer.py            459L           EPTracer 生命周期管理
│   └── EPTracer                        start_ep / end_ep / record_event
│
├── collector.py         112L           进程级 Tracer 注册表（懒加载，线程安全）
└── reporter.py          541L           tkprof 风格报告生成（text/json/html）
    └── TraceSummary                    generate_report(ep_id) → str
```

---

### Layer 5：自学习层

```
src/mms/memory/（与 Layer 2 共享包，以下为 Layer 5 专属模块）
│
├── dream.py             767L           autoDream（核心自学习引擎）
│   └── 触发: git 历史 + EP 执行日志
│       输出: docs/memory/private/drafts/（待审核草稿）
│       auto_link: 正则提取 cites_files + about_concepts
│       promote: 审核通过 → docs/memory/shared/{LAYER}/
│
└── entropy_scan.py      675L           熵扫描（孤儿/过时记忆检测）
    └── scan(threshold) → [candidates]  驱动 mulan gc

⬜ distill.py（待开发）                EP 执行 → 结构化记忆蒸馏（独立模块，v6.0 规划）

src/mms/analysis/seed_absorber.py       Rule Absorber
    └── absorb(url/file) → SeedPack
        噪声清洗 v2 → 规则段落提取 → qwen3-32b 蒸馏
        → docs/memory/seed_packs/{name}/
           ├── meta.yaml
           ├── constraints.yaml
           └── memories/AC-*.md

横切：src/mms/utils/                     工具集（8 个模块）
├── _paths.py             72L           项目路径常量（_PROJECT_ROOT 等）
├── mms_config.py        431L           配置加载（config.yaml + 环境变量）
│   └── MmsConfig                       load() → {runner, dag, cost_estimator, gc, …}
├── validate.py          272L           Schema 校验（front-matter v4.0）
│   └── validate_memory_file(path)
├── verify.py            317L           系统健康检查（mulan verify）
├── model_tracker.py     352L           LLM 用量追踪
├── router.py             77L           任务 → Provider 路由
├── ci_hook.py           105L           git pre-commit hook 管理
└── _paths.py             72L           路径解析
```

---

## 模块化开发指南

> 系统已有 **13 个子包 / 95+ 个 Python 模块**，以"模块"为粒度开发是最可行的迭代策略。

### 模块边界原则

```
每个开发任务应对应一个清晰的"模块单元"：
  1. 同一 src/mms/{子包}/ 目录内的 1~3 个 .py 文件
  2. 对应的 docs/memory/ontology/ YAML 定义（如有）
  3. 对应的 tests/test_{模块名}.py 或 tests/integration/{模块名}_tests.py
  4. 对应的 CLI 命令（cli.py 中 1~2 个子命令）

禁止跨层大改：改 Layer 2 记忆图谱 不应同时改 Layer 1 执行引擎。
```

### 当前模块清单（按开发优先级）

```
状态图例：✅ 稳定  🔧 可改进  ⬜ 待开发  🆕 v5.0 新增

Layer 2 知识本体层（核心，优先投入）
─────────────────────────────────────────────────────────────────
模块名                  包路径                           状态   下一步
OntologyRegistry        ontology/registry.py            🆕✅   增加 LinkTypeRegistry 集成
SignalFusion            bootstrap/signal_fusion.py      🆕✅   Go 注解信号增强
CodeGraphBuilder        bootstrap/code_graph_builder.py 🆕✅   跨文件符号解析
MemorySeedGenerator     bootstrap/memory_seed_generator.py 🆕✅ 支持 ArchDecision 生成
OntologyPopulator       bootstrap/ontology_populator.py 🆕✅   distill 集成（Stage 6→）
MemoryGraph             memory/graph_resolver.py        ✅     typed_explore 路径扩展
MemoryInjector          memory/injector.py              ✅     Token 预算自适应
FreshnessChecker        memory/freshness_checker.py     ✅     批量漂移检测优化
GraphHealth             memory/graph_health.py          ✅     趋势图（时间序列）

Layer 1 任务工程层
─────────────────────────────────────────────────────────────────
EpRunner                workflow/ep_runner.py           ✅     并行批次执行优化
UnitRunner              execution/unit_runner.py        ✅     Streaming 响应支持
TaskDecomposer          dag/task_decomposer.py          ✅     AIU 类型权重自适应
AiuRegistry             dag/aiu_registry.py             ✅     Layer 2 本体集成
Synthesizer             workflow/synthesizer.py         ✅     多模板并行对比

Layer 3 代码生成层
─────────────────────────────────────────────────────────────────
BailianProvider         providers/bailian.py            ✅     Streaming 模式
UnitContext             execution/unit_context.py       🔧     Token 精确计数优化
InternalReviewer        execution/internal_reviewer.py  🔧     开启默认值讨论

Layer 4 安全验证层
─────────────────────────────────────────────────────────────────
AstSkeleton             analysis/ast_skeleton.py        ✅     Rust 语言支持
DepSniffer              analysis/dep_sniffer.py         ✅     Gradle KTS 支持
OntologySyncer          analysis/ontology_syncer.py     🔧     双向同步完善
Observability           observability/                  ✅     结构化日志升级
CircuitBreaker          resilience/circuit_breaker.py   ✅     分 Provider 独立熔断

Layer 5 自学习层
─────────────────────────────────────────────────────────────────
Dream                   memory/dream.py                 🔧     LLM 蒸馏质量评分
SeedAbsorber            analysis/seed_absorber.py       ✅     批量并发吸收
EntropyScanner          memory/entropy_scan.py          🔧     边衰减自动触发

待开发模块（⬜ v6.0）
─────────────────────────────────────────────────────────────────
distill.py              memory/                         ⬜     EP→记忆自动蒸馏（独立模块）
code_genome.py          analysis/                       ⬜     代码基因组（变更历史+依赖链）
federation.py           ontology/                       ⬜     多项目本体联邦
adaptive_aiu.py         dag/                            ⬜     AIU 权重自适应引擎
```

### 新增一个模块的标准步骤

```bash
# 以新增 "CodeGenome 代码基因组" 模块为例：

# Step 1: 在对应子包创建 Python 文件
touch src/mms/analysis/code_genome.py

# Step 2: 创建本体 YAML 定义（如是新 ObjectType/Function）
cat > docs/memory/ontology/functions/fn_build_genome.yaml << 'EOF'
id: fn_build_genome
label: "代码基因组构建"
type: function
...
EOF

# Step 3: 创建对应测试文件
touch tests/test_code_genome.py        # 单元测试（mock LLM）
touch tests/integration/genome_tests.py  # 集成测试（真实 CLI）

# Step 4: 在 cli.py 注册 CLI 命令（如需要）
# 在 cli.py 的 sub.add_parser 区域添加子命令

# Step 5: 验证模块边界（不引入跨层依赖）
python3 -c "from mms.analysis.code_genome import CodeGenome; print('OK')"

# Step 6: 运行模块级测试
pytest tests/test_code_genome.py -v
```

### 模块间依赖规则

```
允许的依赖方向（单向，不得反转）：
  Layer 1（workflow/dag/execution）
      → Layer 2（memory/ontology/bootstrap）  ✅
      → Layer 3（providers）                  ✅
      → Layer 4（analysis/core/resilience）   ✅

  Layer 2（memory/ontology）
      → Layer 4（core/analysis）              ✅
      → Layer 3（providers，仅 dream/distill） ✅

  Layer 4（analysis/core）
      → utils                                 ✅
      → 禁止依赖 Layer 1/2/3                  ❌

  横切（resilience/trace/observability）
      → 任何层均可依赖它们                     ✅
      → 它们不依赖任何业务层                   规则

检查跨层依赖：
  python3 -c "
  import ast, sys
  from pathlib import Path
  # 检查 analysis/ 是否意外导入了 workflow/
  for f in Path('src/mms/analysis').glob('*.py'):
      src = f.read_text()
      if 'from mms.workflow' in src or 'from mms.execution' in src:
          print(f'⚠️  跨层依赖: {f}')
  print('检查完成')
  "
```

---

## 知识本体层（核心架构）

> 这是木兰系统的核心，参考 Palantir Ontology Manager 设计，v5.0 全面升级。

### 1. 四层代码 → 记忆转化链

```
Layer 0: 物理代码库
  .py / .java / .go / .ts / git history
       │
       │  ① Bootstrap v2 扫描（零 LLM）
       │     dep_sniffer → 技术栈嗅探
       │     ast_skeleton → 多语言 AST 骨架化
       ▼
Layer 1: 代码结构模型（CodeFile / CodeClass / CodeModule）
  ast_index.json   ← 存储每个文件/类的骨架 + 语义哈希指纹
       │
       │  ② 五路信号融合推断（signal_fusion.py）
       │     路径信号 25% + 命名信号 25% + 注解信号 30%
       │     + 继承信号 10% + 导入依赖图信号 10%
       │     Framework Override Pass（SQLModel/JpaRepository 等直接覆盖）
       ▼
Layer 2: 记忆本体图谱（核心）
  ObjectType × 8  +  LinkType × 8  +  Function × 9  +  Action × 5
  OntologyRegistry 统一管理，完整性自动校验
       │
       │  ③ 语义注入（injector.py）
       │     hybrid_search → 精准检索 → 压缩 → 上下文前缀
       ▼
Layer 3: 执行机械
  DAG / AIU / UnitRunner / Trace
       │
       │  ④ 知识回流（distill/dream）
       └─────────────────────────────▶ Layer 2（新记忆沉淀）
```

---

### 2. ObjectType 全景图（8 种）

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Layer 1：代码结构对象                              │
│                                                                     │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────────────┐          │
│  │  CodeFile   │   │  CodeClass   │   │   CodeModule    │          │
│  │─────────────│   │──────────────│   │─────────────────│          │
│  │ file_path   │   │ class_fqn    │   │ module_path     │          │
│  │ lang        │   │ name         │   │ package_name    │          │
│  │ fingerprint │   │ kind         │   │ lang            │          │
│  │ inferred_   │   │ file_path    │   │ file_count      │          │
│  │   layer     │   │ bases        │   │ class_count     │          │
│  │ object_type │   │ annotations  │   │ inferred_layer  │          │
│  │   _hint     │   │ methods[]    │   │ object_type_    │          │
│  └─────────────┘   │ inferred_    │   │   hint          │          │
│                    │   layer      │   └─────────────────┘          │
│                    │ confidence   │                                 │
│                    │ code_object_ │                                 │
│                    │   type       │                                 │
│                    └──────────────┘                                 │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ auto-link（Bootstrap v2）
┌─────────────────────────────────────────────────────────────────────┐
│                    Layer 2：记忆图谱对象                              │
│                                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────┐  ┌────────────┐  │
│  │ MemoryNode  │  │ArchDecision  │  │  Lesson  │  │  Pattern   │  │
│  │─────────────│  │──────────────│  │──────────│  │────────────│  │
│  │ id (MEM-*)  │  │ id (AD-*)    │  │ ep_id    │  │ id (PAT-*) │  │
│  │ layer       │  │ status       │  │ outcome  │  │ reusable   │  │
│  │ tier        │  │ alternatives │  │ root_    │  │ example    │  │
│  │ tags[]      │  │ consequences │  │   cause  │  │ _code      │  │
│  │ cites_files │  │ tier: hot    │  │ tier:    │  │ tier: hot  │  │
│  │ about_      │  └──────────────┘  │   warm   │  └────────────┘  │
│  │  concepts   │                    └──────────┘                   │
│  │ impacts[]   │  ┌───────────────────────────────────┐            │
│  │ derived_    │  │          DomainConcept             │            │
│  │   from[]    │  │──────────────────────────────────  │            │
│  │ ast_pointer │  │ concept_id  description  layer     │            │
│  │ provenance  │  │ keywords[]  related_to[]           │            │
│  └─────────────┘  │（图谱索引锚点，O(1) 概念级检索）     │            │
│                   └───────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────────────┘
```

---

### 3. LinkType 关系图（8 种边）

```
┌──────────────────────────────────────────────────────────────────────┐
│                       LinkType 关系全景                               │
│                                                                      │
│   Layer 1 边（代码结构关系）：                                         │
│                                                                      │
│   CodeModule ──[contains 1:N]──▶ CodeFile                           │
│   CodeFile   ──[contains 1:N]──▶ CodeClass                          │
│   CodeClass  ──[depends_on M:N]─▶ CodeClass  （import/use 依赖）     │
│   CodeClass  ──[implements M:N]─▶ CodeClass  （继承/接口实现）        │
│                                                                      │
│   Layer 2 边（记忆图谱关系）：                                         │
│                                                                      │
│   MemoryNode ──[cites M:N]──────▶ CodeFile       （引用代码文件）     │
│                                   ↑ auto-link 正则自动建边            │
│   MemoryNode ──[about M:N]──────▶ DomainConcept  （描述领域概念）     │
│                                   ↑ layers.yaml 关键词自动匹配        │
│   MemoryNode ──[impacts M:N]────▶ MemoryNode     （影响关系）         │
│   MemoryNode ──[contradicts M:N]▶ MemoryNode     （矛盾关系）         │
│   MemoryNode ──[derived_from N:M]▶ MemoryNode    （提炼来源）         │
│                                                                      │
│   自动建边触发时机：                                                    │
│   dream.py 写入记忆 → _auto_link() → 正则提取 cites + 关键词匹配 about │
└──────────────────────────────────────────────────────────────────────┘
```

---

### 4. Function 定义图（9 个）

```
┌─────────────────────────────────────────────────────────────────────┐
│                  FunctionRegistry（9 个纯函数）                       │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ fn_infer_layer           五路信号融合推断架构层               │   │
│  │   输入: file_path + class_name + annotations + bases         │   │
│  │         + in_degree + out_degree_by_layer                    │   │
│  │   输出: LayerInference{layer, confidence, signal_breakdown}  │   │
│  │   Python实现: signal_fusion.infer_layer()                    │   │
│  ├──────────────────────────────────────────────────────────────┤   │
│  │ fn_detect_code_object_type   推断代码对象语义类型            │   │
│  │   输入: class_name + annotations + methods + layer_inference │   │
│  │   输出: ObjectTypeMapping{code_type, mem_type, tier, layer}  │   │
│  │   Python实现: signal_fusion.detect_code_object_type()        │   │
│  ├──────────────────────────────────────────────────────────────┤   │
│  │ fn_build_code_graph      构建代码依赖图                      │   │
│  │   输入: ast_index + project_root                             │   │
│  │   输出: CodeGraph{nodes, edges, in_degree, stats}            │   │
│  │   Python实现: code_graph_builder.build_code_graph()          │   │
│  ├──────────────────────────────────────────────────────────────┤   │
│  │ fn_detect_drift          记忆新鲜度检测                      │   │
│  │   输入: memory_node + ast_index                              │   │
│  │   输出: drift_suspected, drifted_files[]                     │   │
│  ├──────────────────────────────────────────────────────────────┤   │
│  │ fn_find_contradictions   图谱矛盾检测                        │   │
│  │   输入: memory_id + graph                                    │   │
│  │   输出: contradiction_pairs[]                                │   │
│  ├──────────────────────────────────────────────────────────────┤   │
│  │ fn_rank_memories / fn_compute_quality_score                  │   │
│  │ fn_build_context_window / fn_extract_provenance              │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

### 5. Action 定义图（5 个）

```
┌─────────────────────────────────────────────────────────────────────┐
│                  ActionRegistry（5 个有状态动作）                      │
│                                                                     │
│  action_bootstrap    ← 本次核心重构，完整 9 条 Rule                   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ Rule 01  dep_sniffer 技术栈嗅探（requirements/pom/go.mod）   │   │
│  │ Rule 02  install_packs 种子包注入（v3.1 格式优先）            │   │
│  │ Rule 03  ast_skeleton 骨架化（CodeFile+CodeClass 实例生成）   │   │
│  │ Rule 04  build_code_graph（depends_on/implements 边构建）    │   │
│  │ Rule 05  fn_infer_layer 批量推断（五路信号）                  │   │
│  │ Rule 06  fn_detect_code_object_type 语义类型标注              │   │
│  │ Rule 07  generate_seed_memories（MEM-BOOT-*.md 生成）        │   │
│  │ Rule 08  build_link_graph（cites/about 初始边建立）           │   │
│  │ Rule 09  update_index（MEMORY_INDEX.json 更新）               │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  action_distill      EP 完成 → MEM-*.md 知识蒸馏                    │
│  action_dream        git 历史 → 知识草稿（待人工审核）                │
│  action_retire_memory 记忆降级归档（切断入边）                        │
│  action_promote_draft 草稿升级为正式共享记忆                         │
└─────────────────────────────────────────────────────────────────────┘
```

---

### 6. OntologyRegistry 架构图

```
┌────────────────────────────────────────────────────────────────────┐
│                       OntologyRegistry                             │
│              src/mms/ontology/registry.py                          │
│                                                                    │
│  ┌──────────────────────┐   ┌──────────────────────────────────┐  │
│  │  ObjectTypeRegistry  │   │       FunctionRegistry           │  │
│  │  ──────────────────  │   │  ──────────────────────────────  │  │
│  │  加载 objects/*.yaml │   │  加载 functions/*.yaml            │  │
│  │  get(type_id)        │   │  get(fn_id)                      │  │
│  │  validate(id,inst)   │   │  register_implementation(fn,py)  │  │
│  │  layer_1_types()     │   │  call(fn_id, **kwargs)           │  │
│  │  layer_2_types()     │   │  get_signal_rules(fn_id)         │  │
│  └──────────────────────┘   └──────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────┐   ┌──────────────────────────────────┐  │
│  │   ActionRegistry     │   │          RuleEngine              │  │
│  │  ──────────────────  │   │  ──────────────────────────────  │  │
│  │  加载 actions/*.yaml │   │  按 ActionDef.rules 顺序执行     │  │
│  │  get(action_id)      │   │  处理 skip_if / condition        │  │
│  │  check_submission_   │   │  路由 function_rule → FunctionReg│  │
│  │    criteria(id,ctx)  │   │  路由 validation_rule → 校验     │  │
│  └──────────────────────┘   └──────────────────────────────────┘  │
│                                                                    │
│  validate_completeness()  ← 启动时校验所有引用是否可解析            │
│  summary()                ← 打印已加载的 ObjectType/Fn/Action 数量 │
└────────────────────────────────────────────────────────────────────┘

加载路径：
  docs/memory/ontology/objects/*.yaml   → ObjectTypeRegistry
  docs/memory/ontology/functions/*.yaml → FunctionRegistry
  docs/memory/ontology/actions/*.yaml   → ActionRegistry
  docs/memory/ontology/links/*.yaml     → LinkTypeRegistry（memory/link_registry.py）
```

---

### 7. Bootstrap v2 执行流程图

```
mulan bootstrap [--root PATH] [--min-confidence 0.5] [--max-per-layer 10]
                [--skip-ast] [--skip-seeds] [--skip-memory-gen]
       │
       ▼ src/mms/bootstrap/ontology_populator.py
┌─────────────────────────────────────────────────────────────────────┐
│  Step 1/6  技术栈嗅探（dep_sniffer）                                  │
│    requirements.txt / pom.xml / go.mod / package.json               │
│    → detected_stacks: ["python_fastapi"] confidence: 0.92           │
├─────────────────────────────────────────────────────────────────────┤
│  Step 2/6  种子包注入（seed_packs）                                   │
│    → docs/memory/seed_packs/{stack}/memories/AC-*.md                │
├─────────────────────────────────────────────────────────────────────┤
│  Step 3/6  AST 骨架化（ast_skeleton.py，多语言）                      │
│    Python → ast 模块精确解析                                          │
│    Java / Go / TypeScript → 正则骨架提取（可选 Tree-sitter 升级）      │
│    → ast_index.json（file_path → {classes, methods, imports}）       │
├─────────────────────────────────────────────────────────────────────┤
│  Step 4/6  代码依赖图（code_graph_builder.py）                        │
│    从 ast_index 的 imports 字段提取项目内部依赖                        │
│    → CodeGraph{depends_on 边, implements 边, in_degree 索引}         │
│    → docs/memory/_system/code_graph.json（缓存）                     │
├─────────────────────────────────────────────────────────────────────┤
│  Step 5/6  五路信号融合推断（signal_fusion.py）                       │
│                                                                     │
│    对每个 CodeClass 执行 infer_layer()：                             │
│    ┌────────────┬────────┬─────────────────────────────────────┐   │
│    │ 信号       │ 权重   │ 示例                                 │   │
│    ├────────────┼────────┼─────────────────────────────────────┤   │
│    │ 路径信号   │ 25%    │ controller/ → ADAPTER               │   │
│    │ 命名信号   │ 25%    │ *Service → APP                      │   │
│    │ 注解信号   │ 30%    │ @Repository → DOMAIN                │   │
│    │ 继承信号   │ 10%    │ JpaRepository → DOMAIN(0.90)        │   │
│    │ 导入信号   │ 10%    │ 高入度 → DOMAIN/PLATFORM            │   │
│    └────────────┴────────┴─────────────────────────────────────┘   │
│    Framework Override Pass：                                        │
│      SQLModel → DOMAIN(0.80)  BaseSettings → PLATFORM(0.90)        │
│      JpaRepository → DOMAIN(0.90)                                   │
│    → fn_detect_code_object_type → Controller/Service/Repository/…  │
├─────────────────────────────────────────────────────────────────────┤
│  Step 6/6  生成初始记忆（memory_seed_generator.py）                  │
│    置信度 ≥ min_confidence 且非 skip 类型（Util/Test）               │
│    → docs/memory/shared/{LAYER}/MEM-BOOT-NNN.md                    │
│    记忆包含：tags / cites_files / ast_pointer / provenance          │
└─────────────────────────────────────────────────────────────────────┘

真实项目验证结果（零 LLM 调用）：
  FastAPI-Template（Python）：47 文件 / 31 类 → 9 条记忆（Settings→PLATFORM 0.90）
  Go-Clean-Template（Go）  ：98 文件 / 101 类 → 14 条记忆（TranslationController→ADAPTER）
  Spring-Petclinic（Java） ：42 文件 / 52 类 → 4 条记忆（JpaRepository子类 0.90）
```

---

### 8. 记忆图谱检索架构

```
检索请求（任务描述 / 关键词 / 文件路径）
       │
       ▼ hybrid_search()  ← graph_resolver.py
       │
       ├─[优先] find_by_concept(keywords)
       │         _concept_to_ids 反向索引 → O(1) DomainConcept 定位
       │         ↓ 结果 < 阈值（默认 3 条）时
       │
       ├─[Fallback] _keyword_fallback(keywords)
       │             标题 + tags Jaccard 匹配
       │
       └─[扩展] typed_explore(path_intent)
                 沿 LinkType 有向边遍历，路径可配置：

   路径名               边序列                    用途
   ──────────────────────────────────────────────────
   concept_lookup       about → related_to       概念级知识查询
   code_change_impact   cites → impacts          代码变更影响分析
   knowledge_expand     related_to → derived_from 知识图谱扩展
   drift_propagation    cites_reverse → about     新鲜度漂移传播

遍历路径可配置：docs/memory/ontology/_config/traversal_paths.yaml
（新增路径不改 graph_resolver.py 代码）

检索结果排序（fn_rank_memories）：
  score = tier_weight × access_freq × recency_decay × layer_affinity_bonus
  tier: hot(1.0) > warm(0.7) > cold(0.3)
```

---

### 9. 五层记忆空间（v3.0 通用 5 层）

```
docs/memory/shared/                      保护系数（GC 淘汰难度）
├── CC/          架构约束（ADR/反模式/红线）    0.5  ← 最难淘汰
│   └── AD-SEED-001.md  AD-SEED-002.md        ← 当前已有；更多 AD-*.md 运行后自动生成
├── PLATFORM/    横切平台能力（认证/鉴权/配置）  0.2
│   └── （Bootstrap v2 / EP 蒸馏后自动生成）
├── DOMAIN/      业务领域核心（实体/聚合根/规则） 0.3
│   └── （MEM-BOOT-*.md 置信度≥0.5 的 DOMAIN 类记忆）
├── APP/         应用用例编排（CQRS/Saga）     0.1
│   └── （EP 完成后 distill 写入）
└── ADAPTER/     外部适配（REST/DB/MQ）        0.0  ← 最易淘汰
    └── （MEM-BOOT-*.md 置信度≥0.5 的 ADAPTER 类记忆）

Bootstrap v2 生成的记忆文件名：MEM-BOOT-NNN.md
EP 蒸馏生成的记忆文件名：      MEM-L-NNN.md
ArchDecision 记忆文件名：       AD-NNN.md
Pattern 记忆文件名：            PAT-NNN.md

记忆 front-matter 标准格式（v4.0）：
─────────────────────────────────────────
---
id: MEM-L-021
type: pattern                    # pattern / decision / lesson / fact
layer: DOMAIN                    # CC / PLATFORM / DOMAIN / APP / ADAPTER
tier: warm                       # hot / warm / cold
tags: [grpc, dto, service-layer]
cites_files:
  - backend/app/services/user_service.py   # auto-link 自动填充
about_concepts:
  - grpc                                   # auto-link 关键词匹配
  - dto-validation
impacts: [MEM-L-024]
derived_from: [AD-002]
ast_pointer:                     # Bootstrap v2 新增
  file_path: backend/app/services/user_service.py
  class_name: UserService
  fingerprint: sha256:abc123
  drift: false
provenance:
  ep_id: EP-021                  # 或 trigger_type: bootstrap_v2
  trigger_type: ep_postcheck_passed
  generated_at: 2026-04-30
  layer_confidence: 0.85         # Bootstrap v2 推断置信度
version: 1
created_at: 2026-04-30
---
# gRPC 服务层 DTO 校验规范
```

---

## 核心架构（其他模块）

### AIU 执行引擎

```
用户任务描述
       │
       ▼ intent_classifier.py（3 级漏斗）
[Level 1] RBO 规则分类（~0ms，零 LLM）
       │ confidence < 0.85
       ▼
[Level 2] 本体关键词匹配（~5ms）
       │ confidence < 0.60
       ▼
[Level 3] LLM 意图分类（~500ms，qwen3-32b）
       │
       ▼ task_decomposer.py
AIU 分解 → 43 种类型 × 9 族 → AIUStep 列表
       │
       ▼ aiu_cost_estimator.py（CBO 代价估算）
token_budget + model_hint（fast/capable）
       │
       ▼ unit_runner.py（3-Strike 重试循环）
LLM 生成代码 → Scope Guard → 语法验证 → 应用文件
       │                                         │
       │  PASS                             FAIL (retry ≤3)
       ▼                                         ▼
arch_check + pytest                   aiu_feedback.py（3 级回退）
       │                                Level 1: 扩 token_budget × 1.5
       ▼                                Level 2: 插入前置 AIUStep
git commit + mark_done                  Level 3: 拆分为子 AIUStep
```

**AIU 类型体系（43 种，9 大族）：**


| 族                     | 典型类型                                           | 执行顺序 | 亲和层级           |
| --------------------- | ---------------------------------------------- | ---- | -------------- |
| **A Schema**          | `SCHEMA_ADD_FIELD` · `CONTRACT_ADD_REQUEST`    | 1    | DOMAIN/ADAPTER |
| **C Data Access**     | `QUERY_ADD_SELECT` · `MUTATION_ADD_INSERT`     | 2    | ADAPTER        |
| **B Control Flow**    | `LOGIC_ADD_CONDITION` · `LOGIC_EXTRACT_METHOD` | 3    | DOMAIN/APP     |
| **E Infrastructure**  | `EVENT_ADD_PRODUCER` · `CACHE_ADD_READ`        | 3    | ADAPTER        |
| **D Interface**       | `ROUTE_ADD_ENDPOINT` · `FRONTEND_ADD_PAGE`     | 4–5  | ADAPTER        |
| **F Validation**      | `TEST_ADD_UNIT` · `DOC_SYNC`                   | 6–8  | APP/CC         |
| **G Distributed** ★   | `SAGA_ADD_STEP` · `OUTBOX_ADD_MESSAGE`         | 3–4  | APP/DOMAIN     |
| **H Governance** ★    | `RBAC_ADD_PERMISSION` · `AUDIT_ADD_TRAIL`      | 2–3  | PLATFORM/CC    |
| **I Observability** ★ | `METRIC_ADD_COUNTER` · `TRACE_ADD_SPAN`        | 3–5  | PLATFORM       |


> 扩展方式：`docs/memory/_system/schemas/aiu_types_extended.yaml` 新增条目即生效，无需改代码。

---

### EP 全自动 Pipeline

```
Phase 0  mulan synthesize       意图合成 → Cursor 起手提示词
Phase 1  mulan precheck         arch_check 基线 + AST 快照 + 记忆注入
Phase 2  mulan unit generate    qwen3-32b 编排 DAG，生成 Unit 列表
Phase 3  mulan unit run-all     qwen3-coder-plus 逐批执行（3-Strike + SandboxRollback）
Phase 4  mulan postcheck        pytest + arch_check + MigrationGate 质量门控
Phase 5  mulan distill/dream    知识蒸馏 → 自动沉淀到 Layer 2 记忆图谱
```

---

### MDR 诊断基础设施（Oracle ADR 风格）

```
┌─────────────────────────────────────────────────────────────────────┐
│                 MDR（Mulan Diagnostic Repository）                   │
│                                                                     │
│  全局告警日志（alert_mulan.log）                                      │
│    写入: docs/memory/private/mdr/alert/                             │
│    按天轮转，保留 30 天                                               │
│    触发事件: 启动/关闭/熔断/崩溃                                       │
│    查看: mulan diag status  /  tail -f alert_mulan.log              │
│                                                                     │
│  熔断器告警集成（circuit_breaker.py）                                 │
│    CLOSED → OPEN    ：alert_fatal（算力掉线）                        │
│    OPEN → HALF_OPEN ：alert_warn（恢复探测）                         │
│    HALF_OPEN→CLOSED ：alert_info（正常恢复）                         │
│                                                                     │
│  Incident Dump 黑匣子（incident.py）                                 │
│    触发: sys.excepthook 全局接管致命崩溃                              │
│    保全: call_stack.dmp / prompt_context.txt / incident_manifest    │
│    查看: mulan diag list  /  mulan diag pack <id>                   │
│                                                                     │
│  EP 级诊断追踪（Oracle 10046 风格）                                   │
│    Level 1  Basic   — 步骤耗时、成功/失败                            │
│    Level 4  LLM     — + 模型名、token、重试次数                      │
│    Level 8  FileOps — + 文件写入路径、Scope Guard                    │
│    Level 12 Full    — + LLM prompt/response 片段                    │
│    查看: mulan trace show EP-NNN                                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 文件结构

```
mms/
├── cli.py                         # 统一 CLI 入口（mulan <command>）
├── pyproject.toml                 # 项目配置（setuptools / pytest）
├── .env.memory                    # LLM API 密钥（gitignore，不提交）
│
├── src/mms/                       # 核心包
│   │
│   ├── ontology/                  # ★ 动态本体注册表（v5.0 新增）
│   │   ├── __init__.py
│   │   └── registry.py            # OntologyRegistry（ObjectType/Fn/Action 统一入口）
│   │
│   ├── bootstrap/                 # ★ Bootstrap v2（v5.0 新增）
│   │   ├── __init__.py
│   │   ├── signal_fusion.py       # fn_infer_layer / fn_detect_code_object_type 实现
│   │   │                          #   五路信号（路径/命名/注解/继承/导入）+ Framework Override
│   │   ├── code_graph_builder.py  # fn_build_code_graph 实现（depends_on/implements 图）
│   │   ├── memory_seed_generator.py # MEM-BOOT-*.md 初始记忆生成器
│   │   └── ontology_populator.py  # action_bootstrap 6步编排器（Bootstrap v2 主入口）
│   │
│   ├── workflow/                  # EP 工作流编排
│   │   ├── synthesizer.py         # 意图合成
│   │   ├── ep_parser.py           # EP Markdown → DagState
│   │   ├── ep_runner.py           # 全自动 Pipeline
│   │   ├── ep_wizard.py           # 交互式向导
│   │   ├── precheck.py            # 前置基线检查
│   │   ├── postcheck.py           # 后置质量门
│   │   └── migration_gate.py      # DB 迁移脚本门控
│   │
│   ├── dag/                       # DAG & AIU 引擎
│   │   ├── aiu_types.py           # AIU 枚举（9 族 / 43 种）
│   │   ├── aiu_cost_estimator.py  # CBO 代价估算
│   │   ├── aiu_feedback.py        # 3 级回退
│   │   ├── aiu_registry.py        # Schema-Driven 动态注册表
│   │   ├── task_decomposer.py     # AIU 分解器
│   │   └── dag_model.py           # DagUnit / DagState 数据模型
│   │
│   ├── execution/                 # Unit 执行层
│   │   ├── unit_runner.py         # Unit 自动执行（3-Strike + SandboxRollback）
│   │   ├── unit_generate.py       # DAG 生成
│   │   ├── internal_reviewer.py   # 双角色内部评审（feature flag）
│   │   ├── unit_compare.py        # 双模型对比 + 语义评审
│   │   ├── file_applier.py        # 解析应用 LLM BEGIN/END-CHANGES 块
│   │   └── sandbox.py             # GitSandbox（隔离 + 自动回滚）
│   │
│   ├── memory/                    # 记忆检索与注入
│   │   ├── injector.py            # 记忆注入（检索→压缩→Cursor 上下文前缀）
│   │   ├── graph_resolver.py      # 知识图谱（hybrid_search / typed_explore）
│   │   ├── intent_classifier.py   # 3 级意图漏斗
│   │   ├── memory_functions.py    # 纯函数层（无副作用，可测试）
│   │   ├── memory_actions.py      # 有状态动作层（写入 / 矛盾检测）
│   │   ├── link_registry.py       # LinkType YAML 注册表
│   │   ├── freshness_checker.py   # 新鲜度检测（fn_detect_drift 实现）
│   │   ├── graph_health.py        # 图健康监控
│   │   ├── dream.py               # autoDream（git 历史→知识草稿+auto-link）
│   │   ├── entropy_scan.py        # 孤儿/过时记忆检测
│   │   ├── codemap.py / funcmap.py / repo_map.py / template_lib.py / private.py / task_matcher.py
│   │   └── (distill.py — ⬜ v6.0 待开发，EP→记忆自动蒸馏独立模块)
│   │
│   ├── analysis/                  # 代码静态分析
│   │   ├── ast_skeleton.py        # ★ AST 骨架化（Python/Java/Go/TS）
│   │   │                          #   修复：自动调用 _resolve_scan_dirs 检测扫描目录
│   │   ├── dep_sniffer.py         # 技术栈嗅探
│   │   ├── arch_check.py          # 架构约束扫描
│   │   ├── arch_resolver.py       # 层 → 文件路径解析
│   │   ├── ast_diff.py            # AST diff（契约变更检测）
│   │   ├── doc_drift.py           # 文档漂移检测
│   │   ├── ontology_syncer.py     # 本体 YAML ↔ AST 同步
│   │   ├── signal_fusion.py       # ★ 信号融合（Layer 4 副本，供架构分析调用）
│   │   ├── seed_absorber.py       # Rule Absorber（URL → YAML 种子包）
│   │   └── parsers/               # AST 解析器适配层（protocol/factory/regex/tree_sitter）
│   │
│   ├── providers/                 # LLM Provider 适配器
│   │   ├── bailian.py             # 阿里云百炼（qwen3-32b / qwen3-coder-plus）[主力]
│   │   ├── claude.py              # Anthropic Claude（fallback）
│   │   └── factory.py             # 任务 → Provider 路由
│   │
│   ├── observability/             # MDR 诊断基础设施
│   │   ├── logger.py              # 全局告警日志（alert_mulan.log）
│   │   ├── incident.py            # Incident Dump 黑匣子
│   │   └── audit.py               # Append-only JSONL 审计日志
│   │
│   ├── resilience/                # 可靠性原语
│   │   ├── circuit_breaker.py     # 熔断器（三态机，状态转移写 alert 日志）
│   │   ├── retry.py               # 指数退避重试
│   │   └── checkpoint.py          # 断点保存/恢复
│   │
│   ├── core/                      # 基础 I/O
│   │   ├── sanitize.py            # SanitizationGate（API Key / JWT / IP 脱敏）
│   │   ├── writer.py              # 安全文件写入（集成脱敏屏障）
│   │   └── indexer.py             # 记忆索引构建器
│   │
│   └── utils/                     # 工具集
│       ├── mms_config.py          # 配置加载（config.yaml + 环境变量）
│       ├── validate.py            # Schema 校验
│       ├── verify.py              # 系统健康检查
│       └── _paths.py              # 项目路径常量
│
├── docs/memory/                   # 知识库（mulan 命令自动维护）
│   │
│   ├── ontology/                  # ★ 动态本体 YAML 定义（v5.0 全面补全）
│   │   ├── memory_schema.yaml     # 记忆节点通用 JSON Schema（front-matter v4.0 校验基准）
│   │   ├── objects/               # ObjectType 定义（8 种）
│   │   │   ├── code_file.yaml     # Layer1：CodeFile
│   │   │   ├── code_class.yaml    # Layer1：CodeClass（含五路信号推断字段）
│   │   │   ├── code_module.yaml   # Layer1：CodeModule
│   │   │   ├── memory_node.yaml   # Layer2：MemoryNode（核心）
│   │   │   ├── arch_decision.yaml # Layer2：ArchDecision
│   │   │   ├── lesson.yaml        # Layer2：Lesson
│   │   │   ├── pattern.yaml       # Layer2：Pattern
│   │   │   └── domain_concept.yaml# Layer2：DomainConcept（索引锚点）
│   │   ├── links/                 # LinkType 定义（8 种）
│   │   │   ├── depends_on.yaml    # Layer1：代码依赖（import/use）
│   │   │   ├── implements.yaml    # Layer1：继承/接口实现
│   │   │   ├── contains.yaml      # Layer1：包含（Module→File→Class）
│   │   │   ├── cites.yaml         # Layer2：MemoryNode → CodeFile
│   │   │   ├── about.yaml         # Layer2：MemoryNode → DomainConcept
│   │   │   ├── impacts.yaml       # Layer2：影响关系
│   │   │   ├── contradicts.yaml   # Layer2：矛盾关系
│   │   │   └── derived_from.yaml  # Layer2：提炼来源
│   │   ├── functions/             # Function 定义（9 个）
│   │   │   ├── fn_infer_layer.yaml           # 五路信号融合推断
│   │   │   ├── fn_detect_code_object_type.yaml# 语义类型检测
│   │   │   ├── fn_build_code_graph.yaml      # 依赖图构建
│   │   │   ├── fn_detect_drift.yaml          # 记忆新鲜度检测
│   │   │   ├── fn_find_contradictions.yaml   # 图谱矛盾检测
│   │   │   └── fn_rank_memories.yaml / …（4 个）
│   │   ├── actions/               # Action 定义（5 个）
│   │   │   ├── bootstrap.yaml     # action_bootstrap（9 条 Rule）
│   │   │   ├── retire_memory.yaml # 记忆降级归档
│   │   │   ├── promote_draft.yaml # 草稿升级为正式记忆
│   │   │   └── distill.yaml / dream.yaml
│   │   └── _config/
│   │       └── traversal_paths.yaml  # 图遍历路径配置
│   │
│   ├── shared/                    # 积累的共享记忆（5 层目录，随项目运行自动填充）
│   │   ├── CC/                    # 当前已有: AD-SEED-001.md / AD-SEED-002.md
│   │   ├── PLATFORM/ DOMAIN/ APP/ ADAPTER/  # Bootstrap v2 / EP 蒸馏后自动生成
│   │   └── （MEM-L-*.md / MEM-BOOT-*.md / AD-*.md / PAT-*.md）
│   │
│   ├── seed_packs/                # 种子记忆（66+ 条，8 个包）
│   │   ├── python_fastapi/        # AC-PY-01~10
│   │   ├── java_spring_boot/      # AC-JAV-01~12
│   │   ├── go_microservice/       # AC-GO-01~10
│   │   ├── typescript_nestjs/     # AC-TS-01~10
│   │   ├── cross_cutting/         # AC-ARCH-01~08
│   │   ├── python_sqlalchemy/     # AC-SQLALCH-01~06
│   │   ├── infrastructure_redis/  # AC-REDIS-01~05
│   │   └── infrastructure_devops/ # AC-DEVOPS-01~05
│   │
│   ├── _system/                   # 系统运行时文件
│   │   ├── config.yaml            # 记忆系统配置
│   │   ├── ast_index.json         # AST 骨架化索引缓存
│   │   ├── code_graph.json        # 代码依赖图缓存（Bootstrap v2 生成）
│   │   ├── MEMORY_INDEX.json      # 记忆节点索引
│   │   ├── bootstrap_v2_test_report.md  # Bootstrap v2 验证报告
│   │   ├── routing/               # 路由配置
│   │   │   ├── layers.yaml        # 通用 5 层定义
│   │   │   └── intent_map.yaml / operations.yaml
│   │   └── schemas/               # 系统对象 Schema
│   │       ├── aiu_types_extended.yaml
│   │       └── aius/              # Schema-Driven AIU 合约
│   │
│   ├── private/                   # EP 私有工作区 + 诊断数据
│   │   ├── EP-NNN/                # EP 私有草稿
│   │   ├── trace/                 # EP 诊断 trace 数据
│   │   └── mdr/                   # MDR 诊断仓库
│   │       ├── alert/             # alert_mulan.log
│   │       └── incident/          # Incident Dump 现场
│   │
│   └── templates/                 # EP 任务模板（9 种）
│       └── code/                  # 填空式代码骨架
│
├── seed_packs/                    # 项目级种子包（for mulan bootstrap）
│   ├── base/ fastapi_sqlmodel/ react_zustand/
│   ├── palantir_arch/ spring_boot/ go_gin/
│   └── {arch_schema/ ontology/ constraints/ match_conditions.yaml}
│
├── benchmark/                     # Benchmark v2（三层模块化）
│   ├── v2/                        # 评测框架
│   │   ├── layer1_swebench/       # SWE-bench 信用锚
│   │   ├── layer2_memory/         # 记忆质量评测
│   │   └── layer3_safety/         # 安全门控评测
│   └── run_benchmark_v2.py
│
└── tests/                         # 测试套件（完全离线可运行）
    ├── integration/               # 集成测试（真实 CLI 调用）
    │   ├── seed_ingest_tests.py
    │   ├── health_check_tests.py
    │   ├── diag_trace_tests.py
    │   ├── codemap_tests.py
    │   ├── memory_query_tests.py
    │   └── coldstart_tests.py
    └── test_*.py                  # 各核心模块单元测试
```

---

## 快速开始

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/allengaoo/mms.git ~/code/mms

# 2. 安装核心依赖
pip install pyyaml structlog

# 3. 安装 LLM 支持（阿里云百炼）
pip install openai

# 4. 注册 mulan 命令
echo 'alias mulan="python3 $HOME/code/mms/cli.py"' >> ~/.zshrc
source ~/.zshrc

# 验证
mulan --help
```

### 配置 LLM Provider

```bash
# .env.memory（已加入 .gitignore，不提交）
DASHSCOPE_API_KEY=sk-your-key-here
DASHSCOPE_MODEL_REASONING=qwen3-32b          # 推理/评审（非流式调用需 enable_thinking=false）
DASHSCOPE_MODEL_CODING=qwen3-coder-plus      # 代码生成
```


| 任务                          | 模型                 |
| --------------------------- | ------------------ |
| 意图合成 / DAG 生成 / 代码评审 / 知识蒸馏 | `qwen3-32b`        |
| 代码生成                        | `qwen3-coder-plus` |
| Fallback / 人工介入             | Claude（可选）         |


### 冷启动新项目（Bootstrap v2）

```bash
# 在目标项目根目录执行（零 LLM 调用，< 5 秒）
mulan bootstrap --root /path/to/your/project

# 控制参数
mulan bootstrap --min-confidence 0.5    # 层推断最低置信度（低于此值不生成记忆）
mulan bootstrap --max-per-layer 10      # 每层最多生成的初始记忆数
mulan bootstrap --skip-memory-gen       # 只做结构分析，不生成记忆文件
mulan bootstrap --dry-run               # 预览模式，不写文件

# 执行流程（6 步，零 LLM）：
# 1. 技术栈嗅探 → 2. 种子包注入 → 3. AST 骨架化
# 4. 代码依赖图 → 5. 五路信号推断 → 6. 生成 MEM-BOOT-*.md
```

### 开始第一个任务

```bash
mulan synthesize "新增对象类型批量导出 API" --template ep-backend-api
mulan ep run EP-001 --auto-confirm    # 全自动无人值守
mulan ep run EP-001                   # 关键节点暂停确认
```

---

## CLI 参考

### EP 工作流

```bash
mulan synthesize "描述" --template ep-backend-api   # 生成起手提示词
mulan ep run EP-NNN --auto-confirm                   # 全自动执行
mulan ep run EP-NNN --from-unit U3                   # 从 U3 续跑
mulan ep run EP-NNN --dry-run                        # 模拟执行
mulan ep status EP-NNN                               # 查看进度
```

### 记忆管理

```bash
mulan search kafka replication          # 关键词检索（图遍历 + Jaccard）
mulan inject "新增 API"                 # 生成 Cursor 上下文前缀
mulan list --tier hot                   # 列出热记忆
mulan list --layer DOMAIN               # 按通用层过滤
mulan graph stats                       # 知识图谱统计
mulan graph explore AD-002              # BFS 图遍历
mulan graph file backend/api/routes.py  # 反查引用该文件的记忆
mulan gc                                # GC（LFU 淘汰 + 索引重建）
mulan validate --changed-only           # Schema 校验
```

### 种子包管理

```bash
mulan seed list                          # 列出已安装种子包
mulan seed ingest <url>                  # 从 URL 吸收规范蒸馏为 YAML
mulan seed ingest <url> --dry-run        # 预览，不写文件
mulan seed ingest-batch <url1> <url2>    # 批量吸收
```

### 诊断追踪

```bash
mulan trace enable EP-NNN --level 4      # 开启 LLM 详情追踪
mulan trace show EP-NNN                  # 查看 tkprof 风格报告
mulan trace summary EP-NNN              # 一行摘要
mulan diag status                        # 读取 alert_mulan.log 尾部
mulan diag list                          # 列出所有 Incident
mulan diag pack <incident_id>            # 打包 Incident 供 Bug Report
```

### 系统维护

```bash
mulan status        # Provider 健康 + 熔断器 + 记忆统计 + 图健康
mulan verify        # 全面健康检查
mulan hook install  # 安装 git pre-commit hook
mulan codemap       # 刷新代码目录快照
mulan funcmap       # 刷新函数签名索引
mulan ast-diff      # 检测 precheck 以来的契约变更
```

---

## 测试

```bash
pytest tests/ -v                                      # 全量（无需 LLM API）
pytest tests/ -m "not slow and not integration"       # 快速单元测试
pytest tests/integration/ -m integration              # 集成测试（真实 CLI）
pytest tests/ --cov=src/mms --cov-report=html         # 覆盖率报告
```

---

## 配置说明（docs/memory/_system/config.yaml）

```yaml
runner:
  timeout_llm: 180
  max_retries: 2
  enable_internal_review: false

cost_estimator:
  token_min: 1500
  token_max: 16000

graph:
  confidence_threshold: 3     # auto-link 置信度阈值

gc:
  edge_decay_factor: 0.8
  edge_prune_threshold: 0.2
  eviction_weights:
    alpha: 0.3                # 时间衰减权重
    beta:  0.4                # 访问频率权重（LFU）
    gamma: 0.3                # 图结构重要性（in-degree）

analysis:
  use_tree_sitter: false      # true 需先: pip install "mulan[tree_sitter]"
```

---

## Roadmap

### 已完成（v5.0）— Bootstrap v2 + Palantir 动态本体

- ✅ **Palantir 风格动态本体**：ObjectType × 8 / LinkType × 8 / Function × 9 / Action × 5，全部 YAML 定义
- ✅ **OntologyRegistry**：ObjectTypeRegistry + FunctionRegistry + ActionRegistry + RuleEngine 统一管理，启动时完整性自动校验
- ✅ **Bootstrap v2（五路信号融合）**：零 LLM，路径/命名/注解/继承/导入五路信号加权推断架构层 + Framework Override Pass
- ✅ **CodeGraph 构建**：fn_build_code_graph，从 ast_index 提取 depends_on / implements 有向图
- ✅ **初始记忆自动生成**：MEM-BOOT-*.md，含 ast_pointer / layer_confidence / tags 字段
- ✅ **ast_skeleton 扫描目录修复**：_resolve_scan_dirs 自动检测，修复 Go/FastAPI 项目被错误扫描的 Bug
- ✅ **真实项目验证**：FastAPI（Python）/ Go-Clean（Go）/ Spring-Petclinic（Java）三项目零 LLM 验证通过

### 已完成（v4.x）

- ✅ AIU Registry YAML 扩展 / EP 全自动 Pipeline / 3 级 Feedback 回退
- ✅ 四层本体架构分离 / LinkType Registry / 语义图遍历 / Auto-Link / 记忆新鲜度检测
- ✅ Benchmark v2 三层框架 / 企业靶机（mall / halo）

### 已完成（v3.x）

- ✅ MDR 诊断基础设施（alert_mulan.log + Incident Dump + mulan diag）
- ✅ Rule Absorber v2 / 三大技术栈种子包（SQLAlchemy / Redis / DevOps）
- ✅ Schema-Driven AIU（开闭原则重构）/ 图谱矛盾检测自动化

### 待完成（v6.x）

- **自适应 AIU 引擎**：根据执行历史自动调整 AIU 类型权重
- **代码基因组（Code Genome）**：为核心模块维护变更历史 + 依赖图 + 架构决策链
- **多项目本体联邦**：跨项目共享 ObjectType 定义，统一 DomainConcept 命名空间

---

## License

MIT License — 见 [LICENSE](LICENSE)