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
╔══════════════════════════════════════════════════════════════════════╗
║  第一层：任务工程层（Task Engineering）                                ║
║   synthesize → intent_classify → DAG 生成 → AIU 编排 → EP Pipeline   ║
║   模型：qwen3-32b（意图/推理/评审）                                    ║
╠══════════════════════════════════════════════════════════════════════╣
║  第二层：知识本体层（Knowledge Ontology）                 ← 本次重大升级 ║
║   Palantir 风格动态本体：ObjectType / LinkType / Function / Action     ║
║   OntologyRegistry + 五路信号推断 + Bootstrap v2（零 LLM 冷启动）      ║
║   记忆图谱：MemoryNode + ArchDecision + Pattern + Lesson               ║
║   图遍历：hybrid_search / typed_explore / find_by_concept              ║
╠══════════════════════════════════════════════════════════════════════╣
║  第三层：代码生成层（Code Generation）                                  ║
║   上下文注入（< 4k tokens）→ qwen3-coder-plus 生成 Diff               ║
║   代码模板骨架 + 双角色内部评审（feature flag，默认关闭）                ║
╠══════════════════════════════════════════════════════════════════════╣
║  第四层：安全验证层（Safety & Validation）                              ║
║   pytest + AST 契约检测 + DB 迁移门控 + 架构约束扫描                   ║
║   SanitizationGate（API Key / JWT / IP 脱敏）                         ║
║   MDR 诊断基础设施（alert_mulan.log + Incident Dump）                  ║
╠══════════════════════════════════════════════════════════════════════╣
║  第五层：自学习层（Self-Learning）                                      ║
║   distill/dream 知识蒸馏 → 写回记忆图谱                                ║
║   Rule Absorber：外部规范 URL → 种子包 YAML                            ║
╚══════════════════════════════════════════════════════════════════════╝
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
│   └── AD-001.md  AD-002.md  PAT-001.md
├── PLATFORM/    横切平台能力（认证/鉴权/配置）  0.2
│   └── MEM-L-005.md  MEM-L-012.md
├── DOMAIN/      业务领域核心（实体/聚合根/规则） 0.3
│   └── MEM-L-021.md  MEM-BOOT-001.md
├── APP/         应用用例编排（CQRS/Saga）     0.1
│   └── MEM-L-031.md  MEM-L-032.md
└── ADAPTER/     外部适配（REST/DB/MQ）        0.0  ← 最易淘汰
    └── MEM-L-045.md  MEM-BOOT-010.md

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

| 族 | 典型类型 | 执行顺序 | 亲和层级 |
|---|---|---|---|
| **A Schema** | `SCHEMA_ADD_FIELD` · `CONTRACT_ADD_REQUEST` | 1 | DOMAIN/ADAPTER |
| **C Data Access** | `QUERY_ADD_SELECT` · `MUTATION_ADD_INSERT` | 2 | ADAPTER |
| **B Control Flow** | `LOGIC_ADD_CONDITION` · `LOGIC_EXTRACT_METHOD` | 3 | DOMAIN/APP |
| **E Infrastructure** | `EVENT_ADD_PRODUCER` · `CACHE_ADD_READ` | 3 | ADAPTER |
| **D Interface** | `ROUTE_ADD_ENDPOINT` · `FRONTEND_ADD_PAGE` | 4–5 | ADAPTER |
| **F Validation** | `TEST_ADD_UNIT` · `DOC_SYNC` | 6–8 | APP/CC |
| **G Distributed** ★ | `SAGA_ADD_STEP` · `OUTBOX_ADD_MESSAGE` | 3–4 | APP/DOMAIN |
| **H Governance** ★ | `RBAC_ADD_PERMISSION` · `AUDIT_ADD_TRAIL` | 2–3 | PLATFORM/CC |
| **I Observability** ★ | `METRIC_ADD_COUNTER` · `TRACE_ADD_SPAN` | 3–5 | PLATFORM |

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
│   │   ├── distill.py             # EP 知识蒸馏（run_distill）
│   │   └── entropy_scan.py        # 孤儿/过时记忆检测
│   │
│   ├── analysis/                  # 代码静态分析
│   │   ├── ast_skeleton.py        # ★ AST 骨架化（Python/Java/Go/TS）
│   │   │                          #   修复：自动调用 _resolve_scan_dirs 检测扫描目录
│   │   ├── dep_sniffer.py         # 技术栈嗅探
│   │   ├── arch_check.py          # 架构约束扫描
│   │   ├── ast_diff.py            # AST diff（契约变更检测）
│   │   └── seed_absorber.py       # Rule Absorber（URL → YAML 种子包）
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
│   ├── shared/                    # 积累的共享记忆（5 层）
│   │   ├── CC/ PLATFORM/ DOMAIN/ APP/ ADAPTER/
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

| 任务 | 模型 |
|---|---|
| 意图合成 / DAG 生成 / 代码评审 / 知识蒸馏 | `qwen3-32b` |
| 代码生成 | `qwen3-coder-plus` |
| Fallback / 人工介入 | Claude（可选） |

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
