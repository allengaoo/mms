# 木兰（Mulan）— 端侧 AI 编码工具链

> **为什么叫木兰？**  
> 木兰诗里的织布隐喻恰好对应这个工具的核心机制：将一个复杂任务拆成原子工序（AIU），以积累的架构知识为经、以 LLM 生成的代码为纬，一梭一线织出完整的工程产物。名字取自这个意象，没有更深的含义。

**定位**：面向工程团队的端侧 AI 编码工具链。它不是聊天 IDE 插件，而是一个结构化的任务执行系统——将自然语言描述的编码任务，经过意图分解、知识检索、代码生成、质量验证、知识回流五个环节，生成可直接应用的代码变更，且全程不上传业务代码。

**核心价值**：

- **知识复用**：将历次 EP 执行产生的架构决策、教训和模式沉淀为可检索的记忆图谱，新任务执行时精准注入，减少重复错误
- **框架感知**：Bootstrap v2 通过 YAML 驱动的多信号融合，自动理解项目的分层架构（无需人工标注）
- **双轨执行**：Track A（UnitRunner 串行流水线）适合小模型；Track B（Autonomous ReAct 循环）适合有 Tool-Calling 能力的大模型，共享同一套工具层

[CI](https://github.com/allengaoo/mms/actions/workflows/ci.yml)
[Python 3.11+](https://www.python.org)
[License: MIT](LICENSE)

---

## 工具链架构总览

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║  第一层：任务工程层（Task Engineering）                                        ║
║  意图分解 → DAG 编排 → AIU 原子执行 → EP 全自动 Pipeline                      ║
║  Track A: workflow/ + dag/ + execution/unit_runner （UnitRunner 串行）         ║
║  Track B: execution/autonomous_runner （ReAct 循环，大模型自治）               ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  第二层：知识本体层（Knowledge Ontology）                                      ║
║  Palantir 动态本体 + 记忆图谱 + 图遍历检索 + Bootstrap 冷启动                  ║
║  ontology/ + bootstrap/ + memory/                                             ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  第三层：代码生成层（Code Generation）                                          ║
║  记忆上下文注入 → LLM 生成 Diff → 双角色评审                                   ║
║  providers/（bailian/claude/gemini/ollama）+ execution/unit_context           ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  第四层：安全验证层（Safety & Validation）                                      ║
║  AST 契约检测 + 架构约束 + DB 迁移门控 + 脱敏 + MDR 诊断                       ║
║  analysis/ + core/ + observability/ + resilience/ + trace/                   ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  第五层：自学习层（Self-Learning）                                              ║
║  EP 蒸馏 + Rule Absorber + autoDream + 种子包管理                             ║
║  memory/dream + memory/entropy_scan + analysis/seed_absorber                 ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  横切关注点（Cross-Cutting）                                                   ║
║  agent_tools/（Tool 抽象层）+ utils/ + resilience/ + trace/                  ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

---

## EP 执行流程

```
mulan synthesize "任务描述"
       │
       ▼ 意图合成 → Cursor 起手提示词
       │
       ▼ mulan ep run EP-NNN
       │
       ├─[Capability Router]──────────────────────────────────────────┐
       │                                                              │
       ▼ Track A（默认）                               Track B（大模型）│
 UnitRunner 串行 Pipeline                      Autonomous ReAct 循环   │
   precheck → unit generate                    System Prompt 初始化    │
   → unit run-all → postcheck                  → Action（调 Tool）     │
   → distill/dream                             → Observation           │
                                               → 循环（≤10 轮）        │
                                               → tool_finish 退出      │
       │                                              │               │
       └──────────────────────────────────────────────┘               │
                              │                                        │
       ┌──────────────────────▼────────────────────────────────────┐  │
       │          Tool Abstraction Layer（agent_tools/）            │◄─┘
       │  tool_query_ontology → memory/graph_resolver              │
       │  tool_get_ast        → docs/memory/_system/ast_index.json │
       │  tool_dry_run_diff   → execution/sandbox + arch_check     │
       │  tool_run_pytest     → subprocess pytest                  │
       └───────────────────────────────────────────────────────────┘
```

---

## 各层详细模块图

### Layer 1：任务工程层

```
src/mms/workflow/
├── synthesizer.py         意图合成器（synthesize → CursorPrompt）
├── ep_parser.py           EP Markdown → DagState
├── ep_runner.py           全自动 Pipeline 编排（含 Capability Router）
│   └── _resolve_execution_track()  读 config.yaml → pipeline | autonomous
├── ep_wizard.py           交互式向导
├── precheck.py            前置基线检查（arch_check + AST 快照 + 记忆注入）
├── postcheck.py           后置质量门（pytest + arch_check + MigrationGate）
└── migration_gate.py      DB 迁移脚本门控

src/mms/dag/
├── aiu_types.py           AIU 类型体系（43 种 / 9 族）
├── dag_model.py           DagUnit / DagState 数据模型
├── task_decomposer.py     AIU 分解器（qwen3-32b）
├── aiu_registry.py        Schema-Driven 动态注册表（aius/*.yaml）
├── aiu_cost_estimator.py  CBO 代价估算
├── aiu_feedback.py        3 级回退（扩预算 → 插前置 → 拆分）
└── atomicity_check.py     Unit 原子化评分

src/mms/execution/
├── unit_runner.py         Unit 自动执行（3-Strike + SandboxRollback）
├── unit_generate.py       DAG 生成（EP → Unit 列表）
├── unit_context.py        单 Unit 压缩上下文生成（< 4k tokens）
├── file_applier.py        解析并应用 LLM BEGIN/END-CHANGES 块
├── sandbox.py             GitSandbox（隔离 + 自动回滚）
├── sandboxed_runner.py    Sandbox 化执行包装器
├── unit_compare.py        双模型对比 + 语义评审
├── internal_reviewer.py   双角色内部评审（feature flag）
├── autonomous_runner.py   ★ Track B ReAct 循环（max_turns=10，MaxTurnsExceededError）
├── unit_cmd.py            unit 子命令
└── fix_gen.py             自动生成修复建议
```

---

### Layer 2：知识本体层

```
src/mms/ontology/
└── registry.py            OntologyRegistry（ObjectType/Fn/Action 统一管理）
    ├── ObjectTypeRegistry 加载 objects/*.yaml，validate(type_id, inst)
    ├── FunctionRegistry   加载 functions/*.yaml，call(fn_id, **kwargs)
    ├── ActionRegistry     加载 actions/*.yaml，check_submission_criteria
    ├── RuleEngine         按 ActionDef.rules 顺序执行
    └── OntologyRegistry   统一入口，validate_completeness()

src/mms/bootstrap/                         Bootstrap v2（六步，零 LLM）
├── ontology_populator.py  action_bootstrap 编排器（CLI 主入口）
│   Step 1    dep_sniffer 技术栈嗅探
│   Step 1.5  ★ 项目文档扫描（CONTRIBUTING.md/.cursorrules → seed_absorber）
│   Step 2    种子包注入
│   Step 3    AST 骨架化（多语言：Python/Java/Go/TypeScript）
│   Step 4    代码依赖图（depends_on / implements 边）
│   Step 5    ★ 六路信号推断（Evaluation DAG：短路→冲突检测→加权融合）
│   Step 6    生成 MEM-BOOT-*.md 初始记忆（v5.0 通用层 ID）
│   Step 7    Bootstrap 结构性 GC + Schema 演进反馈报告
│
├── signal_fusion.py       ★ Evaluation DAG + 六路信号融合
│   ├── Stage 1            短路规则（inference_rules.yaml，confidence=0.85~0.98）
│   ├── Stage 2            冲突检测（gap < 0.15 → 路径 tiebreaker）
│   └── Stage 3            六路加权：path·name·annotation·inheritance·import·signature
│
├── schema_evolution.py    ★ Schema 演进反馈回路（jsonl + markdown 报告）
├── code_graph_builder.py  fn_build_code_graph（depends_on/implements 图）
└── memory_seed_generator.py MEM-BOOT-*.md 初始记忆生成器

src/mms/memory/            记忆图谱（16 个模块）
├── graph_resolver.py      知识图谱核心（hybrid_search / typed_explore）
├── injector.py            记忆注入（检索 → 压缩 → Cursor 上下文前缀）
├── intent_classifier.py   3 级意图漏斗（RBO → 本体匹配 → LLM）
├── memory_functions.py    纯函数层（quality_score / provenance）
├── memory_actions.py      有状态动作（write / 矛盾检测 / archive）
├── link_registry.py       LinkType YAML 注册表
├── freshness_checker.py   记忆新鲜度检测（fn_detect_drift）
├── graph_health.py        图健康监控
├── dream.py               autoDream（git 历史 → 知识草稿 + auto-link）
├── entropy_scan.py        孤儿/过时记忆检测（驱动 mulan gc）
├── codemap.py / funcmap.py / repo_map.py / template_lib.py
├── task_matcher.py        任务-记忆相关度匹配
└── private.py             EP 私有工作区

assets/ontology_schema/    YAML 本体定义（无代码修改可扩展）[Schema v5.0]
├── memory_schema.yaml     记忆节点通用 JSON Schema（兼容 v4.0/v5.0）
├── objects/   (10 个 ObjectType YAML，含 v5.0 新增 Pattern/Decision/AntiPattern/BusinessFlow)
│   └── _memory_base.yaml  ★ 共享基础 Schema（模拟 Palantir Interface）
├── links/     (9 个 LinkType YAML)
├── functions/ (9 个 Function YAML)
├── actions/   (5 个 Action YAML)
├── rules/     ★ 独立 Rule 定义（rule_bootstrap_pipeline / rule_memory_quality / rule_post_apply_incremental）
└── _config/   ★ universal_layers.yaml / ontology_design_principles.yaml / inference_rules.yaml

seed_packs/                框架种子包（YAML 驱动，含 ast_overrides）
├── base/                  通用约束（always_inject=true）
├── spring_boot/           ★ 13 条 ast_overrides（@RestController/JpaRepository 等）
├── fastapi_sqlmodel/      ★ 9 条 ast_overrides（SQLModel/BaseSettings 等）
├── python_django/         ★ 13 条 ast_overrides（models.Model/APIView 等）
├── go_gin/
├── palantir_arch/
└── react_zustand/
```

---

### Layer 3：代码生成层

```
src/mms/providers/         LLM Provider 适配器（策略模式）
├── bailian.py             阿里云百炼（主力 Provider）
│   ├── BailianProvider           complete / complete_messages
│   ├── complete_with_tools()  ★  Tool-Calling 接口（tools 参数格式）
│   └── BailianEmbedProvider      text-embedding-v3
├── claude.py              Anthropic Claude（Fallback）
├── gemini.py              Google Gemini（备用）
├── ollama.py              Ollama 本地模型（备用）
└── factory.py             任务 → Provider 路由

LLM 任务路由：
  code_generation  → qwen3-coder-plus
  dag_generation   → qwen3-32b
  code_review      → qwen3-32b
  intent_classify  → qwen3-32b（Level3 fallback）
  tool_calling     → 需支持 tools 参数的模型（配置于 autonomous_models）
```

---

### Layer 4：安全验证层

```
src/mms/analysis/          代码静态分析（14 个模块）
├── ast_skeleton.py        多语言 AST 骨架化（Python/Java/Go/TS）
├── dep_sniffer.py         技术栈嗅探（pom.xml / go.mod / requirements.txt）
├── arch_check.py          架构约束扫描（6 条硬规则）
├── arch_resolver.py       层 → 文件路径解析
├── ast_diff.py            AST diff（接口契约变更检测）
├── doc_drift.py           文档漂移检测
├── ontology_syncer.py     本体 YAML ↔ AST 同步
├── signal_fusion.py       信号融合（Layer 4 副本，供架构分析调用）
├── seed_absorber.py       Rule Absorber（URL/文件 → YAML 种子包）
└── parsers/               AST 解析器适配层（protocol/factory/regex/tree_sitter）

src/mms/diagnostics/       ★ 记忆图谱诊断工具（Layer 4 新增）
├── memory_viz.py          数据收集器（扫描 docs/memory/ → NodeData/EdgeData/AstMapping）
└── html_renderer.py       HTML 渲染器（3 Tab 自包含页面：图谱/AST 树/映射表）

src/mms/core/              基础 I/O（安全写入）
├── sanitize.py            SanitizationGate（API Key / JWT / IP 脱敏，支持 MMS_SANITIZE_EXTRA 自定义正则）
├── writer.py              安全文件写入（集成脱敏屏障）
├── reader.py              编码自适应读取（TTL 缓存）
└── indexer.py             记忆索引构建器（MEMORY_INDEX.json）

src/mms/observability/     MDR 诊断基础设施
├── logger.py              全局告警日志（alert_mulan.log，按天轮转）
├── incident.py            Incident Dump 黑匣子（sys.excepthook 接管）
├── audit.py               Append-only JSONL 操作审计
└── tracer.py              轻量 Trace ID 生成器

src/mms/resilience/        可靠性原语
├── circuit_breaker.py     熔断器（三态机：CLOSED → OPEN → HALF_OPEN）
├── retry.py               指数退避重试装饰器
└── checkpoint.py          断点保存/恢复（长任务续跑）

src/mms/trace/             EP 级诊断追踪（Oracle 10046 风格）
├── event.py               TraceEvent（4 级：1/4/8/12）
├── tracer.py              EPTracer 生命周期管理
├── collector.py           进程级 Tracer 注册表（懒加载，线程安全）
└── reporter.py            tkprof 风格报告生成（text/json/html）
```

---

### Layer 5：自学习层

```
src/mms/memory/
├── dream.py               autoDream（git 历史 + EP 日志 → 知识草稿 → CC/_absorb_draft/）
└── entropy_scan.py        熵扫描（孤儿/过时记忆检测，驱动 mulan gc）

src/mms/analysis/seed_absorber.py   Rule Absorber
  absorb(url_or_file) → SeedPack
  噪声清洗 → 规则提取 → qwen3-32b 蒸馏
  → docs/memory/seed_packs/{name}/{meta.yaml / constraints.yaml / AC-*.md}
```

---

### 横切：Tool Abstraction Layer

```
src/mms/agent_tools/                 ★ 工具抽象层（Sprint 2 新增）
├── __init__.py            get_tool_registry() 入口
├── registry.py            ToolRegistry（JSON Schema 注册 + 统一 call 接口）
│   ├── register(ToolDef)  装饰器注册
│   ├── call(name, **kw)   统一调用（捕获异常 → ToolResult）
│   ├── get_schemas()      → OpenAI / 百炼 tools 格式描述
│   └── get_system_prompt_section()  生成 System Prompt 工具说明段
└── tools.py               4 个内置工具实现
    ├── tool_query_ontology  → memory/graph_resolver.hybrid_search
    ├── tool_get_ast         → docs/memory/_system/ast_index.json 查询
    ├── tool_dry_run_diff    → 语法 + 架构约束 + 安全扫描
    └── tool_run_pytest      → subprocess pytest（结构化结果）
```

---

## 核心架构详图

### Bootstrap v2 执行流程

```
mulan bootstrap [--root PATH] [--min-confidence 0.5] [--max-per-layer 10]
                [--skip-ast] [--skip-seeds] [--skip-memory-gen] [--skip-doc-absorb]
       │
       ▼ src/mms/bootstrap/ontology_populator.py
┌─────────────────────────────────────────────────────────────────────┐
│  Step 1   技术栈嗅探（dep_sniffer）                                  │
│    requirements.txt / pom.xml / go.mod / package.json              │
│    → detected_stacks: ["spring_boot"] confidence: 0.92             │
├─────────────────────────────────────────────────────────────────────┤
│  Step 1.5 ★ 项目文档自动扫描                                         │
│    扫描: CONTRIBUTING.md / .cursorrules / ARCHITECTURE.md 等         │
│    调用 seed_absorber.absorb(file) → CC/_absorb_draft/（待 promote） │
│    无 API Key 时静默跳过（不阻断主流程）                               │
├─────────────────────────────────────────────────────────────────────┤
│  Step 2   种子包注入（seed_packs/{stack}/）                           │
│    → docs/memory/seed_packs/{stack}/memories/AC-*.md               │
├─────────────────────────────────────────────────────────────────────┤
│  Step 3   AST 骨架化（ast_skeleton.py）                              │
│    Python(ast 模块) / Java / Go / TypeScript（正则）                 │
│    → ast_index.json（file_path → {classes, methods, imports}）      │
├─────────────────────────────────────────────────────────────────────┤
│  Step 4   代码依赖图（code_graph_builder.py）                         │
│    → CodeGraph{depends_on, implements, in_degree 索引}              │
├─────────────────────────────────────────────────────────────────────┤
│  Step 5   ★ Evaluation DAG — 六路信号推断（v5.0）                    │
│                                                                     │
│  Stage 1: Short-circuit Rules（inference_rules.yaml）                │
│    命中即停止（confidence=0.85~0.98），覆盖主流框架明确类型            │
│    示例：@RestController → ADAPTER(0.98) / @Entity → DOMAIN(0.95)   │
│                                                                     │
│  Stage 2: YAML Override Pass（seed_packs/*/match_conditions.yaml）  │
│    bases_contains / annotation_contains / name_suffix               │
│    命中 → 直接锁定 layer + object_type（confidence=1.0）              │
│    示例：bases_contains: "JpaRepository" → DOMAIN(1.0)              │
│                                                                     │
│  Stage 3: 六路信号加权融合（未命中上述的类）                           │
│    ┌────────────┬────────┬─────────────────────────────────────┐    │
│    │ 信号       │ 权重   │ 示例                                 │    │
│    ├────────────┼────────┼─────────────────────────────────────┤    │
│    │ 路径信号   │ 25%    │ controller/ → ADAPTER               │    │
│    │ 命名信号   │ 25%    │ *Service → APP                      │    │
│    │ 注解信号   │ 30%    │ @Repository → DOMAIN                │    │
│    │ 继承信号   │ 10%    │ JpaRepository → DOMAIN(0.90)        │    │
│    │ 导入信号   │ 10%    │ 高入度 → DOMAIN/PLATFORM            │    │
│    │ 方法签名   │  0%*   │ handle/execute → ADAPTER            │    │
│    └────────────┴────────┴─────────────────────────────────────┘    │
│    * 默认关闭；Go 项目 profile 可激活（0.05）                        │
├─────────────────────────────────────────────────────────────────────┤
│  Step 6   生成初始记忆（memory_seed_generator.py）                   │
│    置信度 ≥ min_confidence → MEM-BOOT-NNN.md                        │
│    layer 字段直接写入 v5.0 通用层 ID（ADAPTER/APP/DOMAIN/PLATFORM/CC）│
├─────────────────────────────────────────────────────────────────────┤
│  Step 7   Bootstrap 结构性 GC + Schema 演进反馈                      │
│    _run_structural_gc()：软归档已删除类的孤立 MEM-BOOT-*.md          │
│    schema_evolution.py：生成高空字段率/模糊推断/UNKNOWN 统计报告      │
└─────────────────────────────────────────────────────────────────────┘

验证结果（零 LLM 调用，4 个 stack 压测矩阵）：
  FastAPI-Demo（Python）     ：v5.0 universal layer ID 合规
  Spring-Boot-Demo（Java）   ：Controller→ADAPTER / Repository→DOMAIN / 幂等
  Go-Gin-Demo（Go）          ：go_gin profile / path 信号主导
  NestJS-Demo（TypeScript）  ：★ v5.0 新增 / @Controller→ADAPTER / @Entity→DOMAIN
```

---

### Autonomous Runner（Track B）执行流程

```
mulan ep run EP-NNN  （config.yaml: execution_mode=autonomous）
       │
       ▼ ep_runner._resolve_execution_track()
       │  读取 agent.execution_mode / agent.autonomous_models
       │
       ▼ execution/autonomous_runner.run_autonomous()
┌─────────────────────────────────────────────────────────────────────┐
│  初始化                                                              │
│  ├── 读取 config: max_turns=10 / token_budget=80000 / timeout=600s  │
│  ├── get_tool_registry() → 4 个工具 + tool_finish                   │
│  └── BailianProvider.complete_with_tools() 可用性检查               │
├─────────────────────────────────────────────────────────────────────┤
│  System Prompt 注入                                                  │
│  ├── 任务描述（EP 文件首行标题）                                      │
│  ├── ToolRegistry.get_system_prompt_section()（4 个工具使用说明）    │
│  └── 安全约束（必须经过 tool_dry_run_diff 验证）                     │
├─────────────────────────────────────────────────────────────────────┤
│  ReAct 循环（Turn 1 ~ max_turns）                                    │
│                                                                     │
│    LLM complete_with_tools(messages, tools)                         │
│           │                                                         │
│    response.tool_calls?                                             │
│      ├─ YES → tool_registry.call(name, **args) → Observation        │
│      │         messages.append(tool_result)                         │
│      │         特殊：tool_finish → 退出循环                          │
│      └─ NO  → text_content → 追加 "请继续" 提示                    │
│                                                                     │
│  三重安全边界：                                                      │
│    elapsed > timeout_s  → finish_reason="timeout"                  │
│    turn > max_turns     → finish_reason="max_turns"                 │
│                            （raise_on_max_turns=True 时抛出         │
│                              MaxTurnsExceededError，供测试断言）    │
│    LLM 调用异常         → finish_reason="error"（不抛出）           │
└─────────────────────────────────────────────────────────────────────┘
```

---

### ObjectType 全景图（v5.0，10 种）

```
代码结构对象（4 种）
┌─────────────┐   ┌──────────────┐   ┌─────────────────┐   ┌──────────────────┐
│  CodeFile   │   │  CodeClass   │   │   CodeModule    │   │  DomainConcept   │
│  file_path  │   │  class_fqn   │   │  module_path    │   │  concept_id      │
│  lang       │   │  bases[]     │   │  lang           │   │  keywords[]      │
│  fingerprint│   │  annotations │   │  file_count     │   │  related_to[]    │
│  inferred_  │   │  methods[]   │   │  inferred_layer │   │  is_auto_gen     │
│    layer    │   │  signal_     │   │  dominant_obj_  │   └──────────────────┘
└─────────────┘   │  breakdown   │   │    type         │
                  └──────────────┘   └─────────────────┘

记忆图谱对象（v5.0，共享 _memory_base.yaml）
┌─────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│  Pattern    │  │  Decision    │  │  AntiPattern │  │  BusinessFlow    │
│ PAT-* 前缀  │  │  AD-* 前缀   │  │  ANTI-* 前缀 │  │  BIZ-* 前缀      │
│ category    │  │  status      │  │  symptoms    │  │  steps_summary   │
│ applicab-   │  │  context     │  │  causes      │  │  involves_layers │
│   ility     │  │  decision    │  │  consequen-  │  │  actors          │
│ code_example│  │  consequen-  │  │    ces       │  └──────────────────┘
│ anti_pattern│  │    ces       │  │  refactoring │
│    _risk    │  │  alternatives│  │    _path     │
└─────────────┘  └──────────────┘  └──────────────┘

向后兼容（保留）
┌─────────────┐  ┌──────────────┐
│ MemoryNode  │  │ ArchDecision │
│ MEM-* 前缀  │  │  AD-* 前缀   │
│ (通用节点)  │  │  (旧版ADR)   │
└─────────────┘  └──────────────┘
```

---

### OntologyRegistry 架构图

```
┌────────────────────────────────────────────────────────────────────┐
│                       OntologyRegistry                             │
│              src/mms/ontology/registry.py                          │
│                                                                    │
│  ┌──────────────────────┐   ┌──────────────────────────────────┐  │
│  │  ObjectTypeRegistry  │   │       FunctionRegistry           │  │
│  │  objects/*.yaml      │   │  functions/*.yaml                │  │
│  │  get(type_id)        │   │  register_implementation(fn, py) │  │
│  │  validate(id, inst)  │   │  call(fn_id, **kwargs)           │  │
│  └──────────────────────┘   └──────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────┐   ┌──────────────────────────────────┐  │
│  │   ActionRegistry     │   │          RuleEngine              │  │
│  │  actions/*.yaml      │   │  按 ActionDef.rules 顺序执行     │  │
│  │  check_submission_   │   │  skip_if / condition 处理        │  │
│  │    criteria(id, ctx) │   │  路由 function_rule / validation  │  │
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

### 记忆图谱检索架构

```
检索请求（任务描述 / 关键词 / 文件路径）
       │
       ▼ hybrid_search(keywords)  ← graph_resolver.py
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
```

---

### 五层记忆空间

```
docs/memory/shared/                      保护系数（GC 淘汰难度）
├── CC/          架构约束（ADR/反模式/红线）    0.5  ← 最难淘汰
│   └── AD-SEED-001.md / AD-SEED-002.md
│       _absorb_draft/（Rule Absorber 草稿，待人工 promote）
├── PLATFORM/    横切平台能力（认证/鉴权/配置）  0.2
├── DOMAIN/      业务领域核心（实体/聚合根/规则） 0.3
├── APP/         应用用例编排（CQRS/Saga）     0.1
└── ADAPTER/     外部适配（REST/DB/MQ）        0.0  ← 最易淘汰
    （各目录随 Bootstrap v2 / EP 蒸馏自动填充）

记忆 front-matter 标准格式（v5.0）：
---
id: PAT-001                  # Pattern:PAT-* / Decision:AD-* / AntiPattern:ANTI-* / BizFlow:BIZ-*
object_type: pattern         # pattern / decision / anti-pattern / business-flow
layer: DOMAIN                # v5.0 通用层：ADAPTER/APP/DOMAIN/PLATFORM/CC/CC_testing...
tier: warm                   # hot / warm / cold / archive
tags: [ddd, repository]
cites_files:
  - backend/domain/user_repository.py
about_concepts:
  - repository
ast_pointer:
  file_path: backend/domain/user_repository.py
  class_name: UserRepository
  fingerprint: sha256:abc123
  drift: false
provenance:
  trigger_type: bootstrap_v2 | ep_postcheck_passed
  generated_at: 2026-05-06
  layer_confidence: 0.92
version: 1
created_at: 2026-05-06
---
```

---

### MDR 诊断基础设施

```
┌─────────────────────────────────────────────────────────────────────┐
│                 MDR（Mulan Diagnostic Repository）                   │
│                                                                     │
│  全局告警日志（alert_mulan.log）                                      │
│    写入: docs/memory/private/mdr/alert/（按天轮转，保留 30 天）       │
│    触发: 启动 / 关闭 / 熔断 / 崩溃                                   │
│                                                                     │
│  Incident Dump 黑匣子（incident.py）                                 │
│    触发: sys.excepthook 全局接管致命崩溃                              │
│    保全: call_stack.dmp / prompt_context.txt / incident_manifest    │
│                                                                     │
│  EP 级诊断追踪（Oracle 10046 风格）                                   │
│    Level 1  Basic   — 步骤耗时、成功/失败                            │
│    Level 4  LLM     — + 模型名、token、重试次数                      │
│    Level 8  FileOps — + 文件写入路径、Scope Guard                    │
│    Level 12 Full    — + LLM prompt/response 片段                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 文件结构

```
mms/
├── cli.py                         CLI 入口（mulan <command>）
├── pyproject.toml
├── .env.memory                    LLM API 密钥（gitignore）
│
├── src/mms/
│   ├── agent_tools/               ★ Tool 抽象层（Sprint 2）
│   │   ├── registry.py            ToolRegistry（JSON Schema + 统一 call）
│   │   └── tools.py               4 个内置工具实现
│   │
│   ├── ontology/                  动态本体注册表
│   │   └── registry.py            OntologyRegistry
│   │
│   ├── bootstrap/                 Bootstrap v2
│   │   ├── signal_fusion.py       ★ YAML Override Pass + 五路信号融合
│   │   ├── ontology_populator.py  ★ 6 步编排（含 Step 1.5 文档扫描）
│   │   ├── code_graph_builder.py  依赖图构建
│   │   └── memory_seed_generator.py 初始记忆生成
│   │
│   ├── workflow/                  EP 工作流编排
│   │   ├── ep_runner.py           ★ Capability Router（Track A/B 路由）
│   │   ├── synthesizer.py         意图合成
│   │   ├── ep_parser.py / ep_wizard.py
│   │   ├── precheck.py / postcheck.py
│   │   └── migration_gate.py
│   │
│   ├── dag/                       DAG & AIU 引擎
│   │   ├── aiu_types.py           AIU 枚举（9 族 / 43 种）
│   │   ├── aiu_cost_estimator.py  CBO 代价估算
│   │   ├── aiu_feedback.py        3 级回退
│   │   ├── aiu_registry.py        Schema-Driven 动态注册表
│   │   ├── task_decomposer.py     AIU 分解器
│   │   └── dag_model.py
│   │
│   ├── execution/                 Unit 执行层
│   │   ├── unit_runner.py         Unit 自动执行（3-Strike + SandboxRollback）
│   │   ├── autonomous_runner.py   ★ Track B ReAct 循环
│   │   ├── unit_generate.py / unit_context.py / unit_compare.py
│   │   ├── file_applier.py / sandbox.py / sandboxed_runner.py
│   │   └── internal_reviewer.py / unit_cmd.py / fix_gen.py
│   │
│   ├── memory/                    记忆图谱
│   │   ├── graph_resolver.py      知识图谱（hybrid_search / typed_explore）
│   │   ├── injector.py            记忆注入
│   │   ├── intent_classifier.py   3 级意图漏斗
│   │   ├── memory_functions.py / memory_actions.py
│   │   ├── link_registry.py / freshness_checker.py / graph_health.py
│   │   ├── dream.py / entropy_scan.py
│   │   └── codemap.py / funcmap.py / repo_map.py / template_lib.py / ...
│   │
│   ├── analysis/                  代码静态分析
│   │   ├── ast_skeleton.py        多语言 AST 骨架化
│   │   ├── dep_sniffer.py / arch_check.py / arch_resolver.py
│   │   ├── ast_diff.py / doc_drift.py / ontology_syncer.py
│   │   ├── signal_fusion.py / seed_absorber.py
│   │   └── parsers/（protocol / factory / regex / tree_sitter）
│   │
│   ├── providers/                 LLM 适配器
│   │   ├── bailian.py             ★ 含 complete_with_tools()
│   │   ├── claude.py / gemini.py / ollama.py
│   │   └── factory.py / base.py
│   │
│   ├── diagnostics/               ★ 记忆图谱诊断工具
│   │   ├── memory_viz.py          数据收集器
│   │   └── html_renderer.py       HTML 渲染器
│   │
│   ├── observability/             MDR 诊断基础设施
│   │   ├── logger.py / incident.py / audit.py / tracer.py
│   │
│   ├── resilience/                可靠性原语
│   │   ├── circuit_breaker.py / retry.py / checkpoint.py
│   │
│   ├── trace/                     EP 级诊断追踪
│   │   ├── event.py / tracer.py / collector.py / reporter.py
│   │
│   ├── core/                      基础 I/O
│   │   ├── sanitize.py / writer.py / reader.py / indexer.py
│   │
│   └── utils/                     工具集
│       ├── mms_config.py / validate.py / verify.py
│       ├── _paths.py / ci_hook.py / model_tracker.py / router.py
│
├── docs/memory/
│   ├── ontology/                  YAML 本体定义
│   │   ├── memory_schema.yaml     front-matter v4.0 JSON Schema
│   │   ├── objects/ links/ functions/ actions/ _config/
│   │
│   ├── shared/                    积累的共享记忆（5 层目录）
│   │   └── CC/ PLATFORM/ DOMAIN/ APP/ ADAPTER/
│   │       （Bootstrap / EP 蒸馏后自动填充）
│   │
│   ├── seed_packs/                种子记忆（66+ 条，8 个包）
│   │   └── python_fastapi / java_spring_boot / go_microservice /
│   │       typescript_nestjs / cross_cutting / python_sqlalchemy /
│   │       infrastructure_redis / infrastructure_devops
│   │
│   ├── _system/                   系统运行时文件
│   │   ├── config.yaml            ★ 含 agent 配置块（execution_mode 等）
│   │   ├── ast_index.json / code_graph.json / MEMORY_INDEX.json
│   │   ├── routing/               意图路由元数据
│   │   │   ├── layers.yaml        层定义（CC_testing / CC_governance / BIZ / Tooling_mms）
│   │   │   ├── intent_map.yaml    意图规则（知识查询 / 静态分析 / 重构 等新操作类型）
│   │   │   └── operations.yaml    操作类型定义（含 knowledge_query / analyze / refactor）
│   │   └── schemas/（aiu_types_extended.yaml / aius/）
│   │
│   ├── private/                   EP 私有工作区 + 诊断数据
│   │   ├── EP-NNN/                私有草稿
│   │   ├── trace/                 诊断 trace 数据
│   │   └── mdr/alert/ mdr/incident/
│   │
│   └── templates/                 EP 任务模板（9 种）
│
├── seed_packs/                    框架种子包（YAML 驱动）
│   ├── base/ spring_boot/ fastapi_sqlmodel/ python_django/
│   ├── go_gin/ palantir_arch/ react_zustand/
│   └── {match_conditions.yaml（含 ast_overrides）/ constraints/ ontology/}
│
├── benchmark/
│   ├── run_benchmark.py           ★ 主入口（原 run_benchmark_v2.py）
│   ├── v2/                        Benchmark v2（三层模块化，活跃维护）
│   │   ├── layer1_swebench/       ★ L1：ΔPass@1（DualRailRunner 双轨对比）
│   │   ├── layer2_memory/         L2：记忆质量（D1~D4 维度）
│   │   └── layer3_safety/         L3：安全门控（离线，< 1s）
│   └── v1_legacy/                 ★ 已废弃（原 benchmark/src/，仅历史参考）
│
└── tests/
    ├── conftest.py                ★ 全局 fixture（isolated_spring_boot / vcr_config）
    ├── fixtures/spring-boot-demo/ ★ Java Spring Boot 靶机（7 个 Java 文件）
    ├── cassettes/                 VCR cassette 存储（pytest-recording）
    ├── integration/               集成测试（真实 CLI 调用）
    ├── benchmark/                 Benchmark v2 单元测试
    ├── fixtures/go-gin-demo/      ★ Go Gin 靶机
├── fixtures/python-fastapi-demo/ ★ Python FastAPI 靶机
├── fixtures/typescript-nestjs-demo/ ★ TypeScript NestJS 靶机（v5.0 新增）
└── test_*.py                  单元测试
```

---

## 快速开始

### 安装

```bash
git clone https://github.com/allengaoo/mms.git ~/code/mms
pip install pyyaml structlog openai
echo 'alias mulan="python3 $HOME/code/mms/cli.py"' >> ~/.zshrc && source ~/.zshrc
mulan --help
```

### 配置 LLM Provider

```bash
# .env.memory（gitignore，不提交）
DASHSCOPE_API_KEY=sk-your-key-here
DASHSCOPE_MODEL_REASONING=qwen3-32b
DASHSCOPE_MODEL_CODING=qwen3-coder-plus
```


| 任务                          | 模型                 |
| --------------------------- | ------------------ |
| 意图合成 / DAG 生成 / 代码评审 / 知识蒸馏 | `qwen3-32b`        |
| 代码生成                        | `qwen3-coder-plus` |
| Tool-Calling（Track B）       | 需支持 tools 参数的模型    |


### 冷启动新项目（Bootstrap v2，零 LLM）

```bash
# 在目标项目根目录执行（< 5 秒）
mulan bootstrap --root /path/to/your/project

# 控制参数
mulan bootstrap --min-confidence 0.5    # 层推断最低置信度
mulan bootstrap --max-per-layer 10      # 每层最多生成记忆数
mulan bootstrap --skip-memory-gen       # 只做结构分析
mulan bootstrap --skip-doc-absorb       # 跳过项目文档自动蒸馏
mulan bootstrap --dry-run               # 预览，不写文件
```

### 开始第一个任务

```bash
mulan synthesize "新增批量导出 API" --template ep-backend-api
mulan ep run EP-001 --auto-confirm      # 全自动 Track A Pipeline
```

### 切换到 Autonomous 模式（Track B）

```bash
# docs/memory/_system/config.yaml
agent:
  execution_mode: "autonomous"      # 或 "auto"
  autonomous_models: ["claude-opus-4"]
  max_autonomous_turns: 10
  autonomous_token_budget: 80000

mulan ep run EP-001                 # 自动走 Track B ReAct 循环
```

---

## Benchmark v2

三层模块化评测框架，用于量化 Mulan 的核心价值主张。


| 层                | 指标                                     | 运行模式                 | 说明                                           |
| ---------------- | -------------------------------------- | -------------------- | -------------------------------------------- |
| **L1 SWE-bench** | ΔPass@1、Info Density                   | 离线/在线双模式             | Mulan-Enhanced vs Baseline 双轨对比              |
| **L2 记忆质量**      | D1 精准检索 / D2 注入提升 / D3 跨任务留存 / D4 漂移检测 | D1/D4 离线，D2/D3 需 LLM | 四维记忆质量评分                                     |
| **L3 安全门控**      | 检出率 / 漏报 / 误报                          | 完全离线（< 1s）           | SanitizationGate + MigrationGate + ArchCheck |


```bash
# 快速离线运行（当前得分 L3: 94.7%）
python benchmark/run_benchmark.py

# 在线模式（需配置 LLM API + Docker）
python benchmark/run_benchmark.py --level online --layers l1 l2
```

> **旧版 Benchmark**（检索质量对比 BM25 vs Hybrid RAG vs Ontology）已归档至 `benchmark/v1_legacy/`，不再维护。

---

## CLI 参考

### EP 工作流

```bash
mulan synthesize "描述" --template ep-backend-api
mulan ep run EP-NNN --auto-confirm
mulan ep run EP-NNN --from-unit U3
mulan ep run EP-NNN --dry-run
mulan ep status EP-NNN
```

### 记忆管理

```bash
mulan search kafka replication
mulan inject "新增 API"
mulan list --tier hot
mulan list --layer DOMAIN
mulan graph stats
mulan graph explore AD-002
mulan graph file backend/api/routes.py
mulan gc
mulan validate --changed-only
```

### 种子包管理

```bash
mulan seed list
mulan seed ingest <url>             # URL 或本地文件
mulan seed ingest <url> --dry-run
mulan seed ingest-batch <url1> <url2>
```

### 诊断追踪

```bash
mulan trace enable EP-NNN --level 4
mulan trace show EP-NNN
mulan diag status
mulan diag list
mulan diag pack <incident_id>
```

### 记忆图谱可视化诊断

```bash
# 生成记忆图谱 HTML 诊断页（3 Tab 交互式页面）
python3 scripts/visualize_memory.py --open

# 指定参数
python3 scripts/visualize_memory.py -o /tmp/viz.html --project MyApp
python3 scripts/visualize_memory.py --memory-root docs/memory --open
```

### 系统维护

```bash
mulan status
mulan verify
mulan hook install
mulan bootstrap --root /path/to/project
mulan codemap / mulan funcmap
mulan ast-diff
```

---

## 测试

```bash
pytest tests/ -v --ignore=tests/benchmark --ignore=tests/dag --ignore=tests/integration --ignore=tests/execution --ignore=tests/eval  # 全量
pytest tests/ -m "not slow and not integration"       # 快速单元测试
pytest tests/integration/ -m integration              # 集成测试（真实 CLI）
pytest tests/ --cov=src/mms --cov-report=html
```

**当前覆盖率（2026-05-06）**：全项目整体 **~63%**，Layer 2（Bootstrap 86~99% / Ontology 83% / Memory 63% / Diagnostics 87~99%）。

### TDD 覆盖层（7 阶段 + Layer 2 专项）

| 阶段              | 测试文件                                                        | 覆盖点                                                                    |
| --------------- | ----------------------------------------------------------- | ---------------------------------------------------------------------- |
| 1 物理沙箱          | `tests/conftest.py`、`tests/fixtures/spring-boot-demo/`      | 全局 fixture（Spring Boot 靶机、Python 项目、VCR 配置）                           |
| 2 纯函数           | `test_ast_skeleton.py`（+9）、`test_sanitize.py`（34）           | 语义哈希稳定性（格式化不漂移）、SanitizationGate 全模式                                  |
| 3 VCR 控制流       | `test_autonomous_runner_control.py`（12）                     | max_turns 阻断、tool_finish 退出、`MaxTurnsExceededError`                    |
| 4 Bootstrap 宏观  | `test_bootstrap_on_spring_boot.py`（15）                      | Spring Boot fixture 端到端、幂等性、dry_run、detected_stacks                   |
| 5 安全门控          | `test_arch_check.py`（15）                                    | AC-1~AC-4 阳性 + 阴性（tmp_path 注入，完全离线）                                   |
| 6 图演化           | `test_edge_decay.py`（+4）、`test_seed_absorber.py`（18）        | GC 物理剪枝、dry_run 不写磁盘、seed_absorber 噪声过滤                                |
| 7 E2E Pass@1    | `test_layer1_swebench.py`（+9）                               | DualRailRunner 双轨对比、ΔPass@1、在线模式 mock 验证                              |
| L2 Memory 单元   | `test_memory_engine_unit.py`（81）                            | TaskMatcher/IntentClassifier/MemoryGraph/Injector/memory_actions       |
| L2 Memory 集成   | `test_memory_engine_integration.py`（21）                     | Bootstrap→Graph→Injector→Matcher 端到端联动                                |
| L2 E2E         | `test_layer2_e2e.py`（24）+`test_layer2_e2e_extended.py`（32） | 全链路 Prompt 组装 / 跨语言一致性 / Schema↔Memory 一致性                           |
| L2 诊断模块        | `test_diagnostics.py`（41）                                   | frontmatter 解析 / 数据收集器 / HTML 渲染器 / CLI E2E                           |


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
  confidence_threshold: 3

gc:
  edge_decay_factor: 0.8
  edge_prune_threshold: 0.2
  eviction_weights:
    alpha: 0.3     # 时间衰减
    beta:  0.4     # 访问频率（LFU）
    gamma: 0.3     # 图结构重要性（in-degree）

analysis:
  use_tree_sitter: false

# ★ 弹性工具链配置（Sprint 2）
agent:
  execution_mode: "pipeline"        # pipeline | autonomous | auto
  autonomous_models: []             # 支持 Tool-Calling 的模型名
  max_autonomous_turns: 10
  autonomous_token_budget: 80000
  autonomous_timeout: 600
```

---

## License

MIT License — 见 [LICENSE](LICENSE)