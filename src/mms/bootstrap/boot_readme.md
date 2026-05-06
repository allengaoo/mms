# MMS Bootstrap 模块 (src/mms/bootstrap)

> **最后更新**：2026-05-06 | Bootstrap v2.1（Schema v5.0）

## 1. 模块定位

`src/mms/bootstrap` 是 MMS 系统的**冷启动与初始化引擎（Cold Start Engine）**。它在一个全新的或现有的代码仓库中，通过零 LLM 调用的纯启发式方法，自动推断架构层级、提取代码特征，并生成初始记忆图谱（Memory Graph）。

**核心设计原则**：

- **零 LLM 依赖**：整个冷启动过程仅依赖 YAML 规则和 AST 分析，无 LLM 调用（< 5 秒）。
- **YAML 驱动**：推断规则完全由 `seed_packs/*/match_conditions.yaml` 和 `assets/ontology_schema/_config/inference_rules.yaml` 驱动，不硬编码业务逻辑。
- **六路信号融合 + Evaluation DAG**：三阶段推断（Stage 1 短路 → Stage 2 冲突检测 → Stage 3 六路加权融合）。
- **覆盖优先**：YAML Override Pass 在信号融合之前短路高置信度框架规则（confidence=1.0）。
- **Schema 演进反馈**：每次 Bootstrap 运行后自动生成 Schema 健康报告，驱动持续改进。

---

## 2. 文件结构

```text
src/mms/bootstrap/
├── __init__.py
├── ontology_populator.py   ★ 顶层编排器（CLI 主入口，七步流程 + GC + Schema演进）
├── signal_fusion.py        ★ Evaluation DAG + 六路信号融合推断
├── schema_evolution.py     ★ Schema 演进反馈回路（BootstrapRunStats + jsonl报告）
├── code_graph_builder.py   代码依赖图构建（depends_on / implements 边）
├── memory_seed_generator.py 初始记忆文件生成（MEM-BOOT-*.md，v5.0 通用层 ID）
└── seed_packs/             ★ 框架先验知识库（YAML 驱动）
    ├── __init__.py         SeedPackManager（懒加载 / 格式转换）
    └── {pack_name}/        各框架种子包
```

（注：项目根目录的 `seed_packs/` 是面向框架适配的独立资产包，供 Bootstrap 通过 `load_overrides()` 读取。）

---

## 3. 核心代码文件与方法

### `ontology_populator.py`（顶层编排器）

Bootstrap v2 的 CLI 主入口，按七步顺序协调所有子模块。

**核心数据结构**（`BootstrapV2Report`）：

```python
@dataclass
class BootstrapV2Report:
    project_root: str = ""
    elapsed_s: float = 0.0
    detected_stacks: List[str] = field(default_factory=list)
    stack_confidence: float = 0.0
    injected_seed_packs: List[str] = field(default_factory=list)

    # AST 统计
    files_scanned: int = 0
    classes_found: int = 0
    methods_found: int = 0

    # 代码图统计
    graph_nodes: int = 0
    graph_edges: int = 0
    cycle_count: int = 0

    # 推断统计
    classes_inferred: int = 0
    classes_skipped: int = 0
    layer_distribution: Dict[str, int] = field(default_factory=dict)

    # 记忆生成统计
    memories_generated: int = 0
    memories_per_layer: Dict[str, int] = field(default_factory=dict)
    memory_files: List[str] = field(default_factory=list)
    seed_memories_loaded: int = 0      # 注入的 seed pack 记忆数量
    weights_profile_used: str = ""     # 使用的权重 profile 名称

    dry_run: bool = False
    errors: List[str] = field(default_factory=list)
```

**核心方法**：

- `bootstrap_project(project_root, min_confidence, max_per_layer, dry_run, skip_*)`: 暴露给 CLI 的主入口，执行七步流程（含 GC + Schema 演进），返回 `BootstrapV2Report`。

---

### `signal_fusion.py`（架构推断大脑）

实现 OntologyRegistry 中的两个 Function：`fn_infer_layer` 和 `fn_detect_code_object_type`。

**核心数据结构**：

```python
@dataclass
class SignalBreakdown:
    path_score:        float  # 路径信号（base: 25%）
    name_score:        float  # 命名信号（base: 25%）
    annotation_score:  float  # 注解信号（base: 30%）
    inheritance_score: float  # 继承信号（base: 10%）
    import_score:      float  # 导入信号（base: 10%）
    signature_score:   float  # 方法签名信号（默认 0%，Go profile 激活）

    def total(self, weights) -> float:
        # 六路加权求和

@dataclass
class LayerInference:
    inferred_layer: str    # ADAPTER / APP / DOMAIN / PLATFORM / CC / UNKNOWN
    object_type: str       # Controller / Service / Repository / Entity / ...
    confidence:  float     # 0.0 ~ 1.0
    method:      str       # "shortcircuit" | "override" | "signal_fusion"
    breakdown:   SignalBreakdown
    all_scores:  Dict[str, float]  # 各层得分（含 _ambiguous 标记）
```

**Evaluation DAG（三阶段推断）**：

```
Stage 1: Short-circuit Rules（inference_rules.yaml）
  ├── Java: @RestController → ADAPTER(0.98)
  ├── Java: @Entity/@Table → DOMAIN(0.95)
  ├── Python: FastAPI @app.get → ADAPTER(0.90)
  ├── Go: *_handler.go → ADAPTER(0.88)
  ├── 测试类 → CC_testing(0.95)
  └── 工具类 → CC(0.85)

Stage 2: Conflict Detection
  ├── gap < 0.15（最高分与次高分差值）
  ├── 属于已知冲突对：ADAPTER-DOMAIN / APP-DOMAIN / ADAPTER-APP
  └── 路径信号 tiebreaker → 标记 _ambiguous = 1.0

Stage 3: Weighted Signal Fusion
  └── 六路加权 → 取最高分层级
```

**关键内置规则**：

```python
# 路径强信号（profile 动态加载）
_PATH_STRONG_PATTERNS = {
    "ADAPTER":  ["controller", "handler", "router", "endpoint", "rest"],
    "APP":      ["service", "usecase", "use_case", "application"],
    "DOMAIN":   ["entity", "aggregate", "domain", "repository", "model"],
    "PLATFORM": ["config", "configuration", "infrastructure", "infra", "middleware"],
    "CC":       ["util", "helper", "common", "shared"],
}

# 方法签名关键词（第 6 路信号）
_METHOD_SIGNATURE_PATTERNS = {
    "ADAPTER":  ["handle", "process_request", "on_message", "dispatch"],
    "APP":      ["execute", "run", "orchestrate", "coordinate"],
    "DOMAIN":   ["validate", "apply_rule", "calculate", "enforce"],
    "CC":       ["log", "trace", "encrypt", "hash", "serialize"],
}
```

**核心方法**：

- `load_overrides(project_root, detected_stacks)`: 从 `seed_packs/*/match_conditions.yaml` 加载 YAML 覆盖规则。
- `apply_override(cls_info, overrides)`: 三维匹配（`bases_contains` / `annotation_contains` / `name_suffix`），命中即返回 confidence=1.0。
- `infer_layer(file_path, class_info, ..., methods)`: 三阶段 Evaluation DAG → 返回 `LayerInference`。
- `detect_code_object_type(cls_info, layer)`: 在给定层推断具体 ObjectType。
- `infer_all(ast_index, project_root, detected_stacks, ...)`: 批量推断（Short-circuit → Override Pass → 六路融合）。

---

### `schema_evolution.py`（Schema 演进反馈）

Bootstrap v2.1 新增，每次 Bootstrap 结束后自动分析 Schema 健康度。

**核心数据结构**：

```python
@dataclass
class BootstrapRunStats:
    run_id: str                        # 唯一运行 ID（时间戳）
    project_root: str
    timestamp: str
    total_classes: int
    inferred_classes: int
    ambiguous_count: int               # _ambiguous 标记的类数量
    unknown_count: int                 # 推断为 UNKNOWN 的类数量
    null_rate_by_field: Dict[str, float]  # 各字段空值率
    unknown_classes: List[str]         # UNKNOWN 类名列表
    ambiguous_classes: List[str]       # 模糊推断类名列表
```

**核心函数**：

- `record_bootstrap_run(report, inferences)`: 分析 Bootstrap 结果，追加 JSONL 日志并生成 Markdown 报告。
- `generate_markdown_report(stats)`: 生成人可读的 Schema 演进报告（高空字段率/模糊推断/UNKNOWN 层统计）。

输出文件：

```
docs/memory/_system/schema_evolution_log.jsonl    ← 结构化历史日志
docs/memory/_system/schema_evolution_report.md    ← 人可读摘要
```

---

### `code_graph_builder.py`（代码依赖图）

构建项目内代码的静态依赖图。

**核心数据结构**：

```python
@dataclass
class CodeGraph:
    nodes: Dict[str, ClassInfo]      # class_fqn → ClassInfo
    edges: List[Tuple[str, str, str]] # (source, target, edge_type)
    in_degree: Dict[str, int]        # 入度索引（高入度 → 核心类）
```

**核心方法**：

- `fn_build_code_graph(project_root, ast_index)`: 基于 AST 索引中的 `bases`（继承关系）和 `imports`（导入依赖），构建有向依赖图，同时检测循环依赖。

---

### `memory_seed_generator.py`（初始记忆生成器）

将代码推断结果转化为标准 front-matter v5.0 格式的 Markdown 文件。

**v5.0 关键变更**：废弃 `_SCHEMA_LAYER_MAP`（旧的项目特化 ID 映射），改用 `_DDD_TO_UNIVERSAL_LAYER`（通用层 ID 直接写入）：

```python
_DDD_TO_UNIVERSAL_LAYER = {
    "ADAPTER":  "ADAPTER",   # 接口/适配层（直接使用通用 ID）
    "APP":      "APP",       # 应用服务层
    "DOMAIN":   "DOMAIN",    # 领域层
    "PLATFORM": "PLATFORM",  # 平台基础设施层
    "CC":       "CC",        # 横切关注点
    "UNKNOWN":  "CC",        # 未知 → 归入 CC
}
```

**核心方法**：

- `generate_seeds(inferences, project_root, max_per_layer, dry_run)`: 遍历推断结果，为置信度达标的类生成 `MEM-BOOT-NNN.md`，自动填充 `id`、`object_type`、`layer`（v5.0 通用 ID）、`tier`、`cites_files`、`ast_pointer`、`provenance` 等字段。

---

## 4. 业务流程（七步，v5.0）

```mermaid
graph TD
    A[CLI: mulan bootstrap] --> B(ontology_populator.bootstrap_project)

    subgraph Step1 ["Step 1 技术栈嗅探（dep_sniffer）"]
        B --> C[分析 requirements.txt / pom.xml / go.mod / package.json]
        C --> D[detected_stacks: spring_boot / fastapi / go_gin / nestjs 等]
    end

    subgraph Step1_5 ["Step 1.5 ★ 项目文档自动蒸馏"]
        D --> E[扫描 CONTRIBUTING.md / .cursorrules / ARCHITECTURE.md]
        E --> F[seed_absorber.absorb → CC/_absorb_draft/（待 promote）]
    end

    subgraph Step2 ["Step 2 种子包注入"]
        F --> G[匹配 seed_packs/{stack}/match_conditions.yaml]
        G --> H[注入预制 Markdown 记忆到 docs/memory/shared/CC/]
    end

    subgraph Step3 ["Step 3 AST 骨架化（build_ast_index）"]
        H --> I[多语言解析: Python / Java / Go / TypeScript]
        I --> J[ast_index.json: file_path → classes / methods / imports]
    end

    subgraph Step4 ["Step 4 代码依赖图（code_graph_builder）"]
        J --> K[构建 CodeGraph: depends_on / implements 边]
        K --> L[in_degree 索引 + 循环依赖检测]
    end

    subgraph Step5 ["Step 5 ★ Evaluation DAG — 六路信号推断"]
        L --> S1{Stage 1: Short-circuit<br/>inference_rules.yaml}
        S1 -- 命中 confidence=0.85~0.98 --> N[锁定 layer]
        S1 -- 未命中 --> S2{Stage 2: Override Pass<br/>seed_packs/*/match_conditions.yaml}
        S2 -- 命中 confidence=1.0 --> N
        S2 -- 未命中 --> S3[Stage 3: 六路信号加权融合]
        S3 --> P[path·name·annotation·inheritance·import·signature]
        P --> Q[confidence ≥ min_confidence?]
    end

    subgraph Step6 ["Step 6 增量记忆生成（memory_seed_generator）"]
        N --> R[生成 MEM-BOOT-NNN.md<br/>layer=v5.0 通用层 ID]
        Q -- YES --> R
        Q -- NO --> S[跳过，记录到 report.classes_skipped]
        R --> GC[Structural GC<br/>_run_structural_gc<br/>→ 软归档孤立节点]
    end

    subgraph Step7 ["Step 7 ★ Schema 演进反馈（schema_evolution）"]
        GC --> T[schema_evolution.record_bootstrap_run]
        T --> U[schema_evolution_log.jsonl<br/>schema_evolution_report.md]
        U --> V[BootstrapV2Report]
    end
```



### 信号权重详情（六路）


| 信号                               | 默认权重 | 典型示例                                                       |
| -------------------------------- | ---- | ---------------------------------------------------------- |
| 路径信号 (`_score_path`)             | 25%  | `controller/` → ADAPTER（强信号 1.0）；`service/` → APP（强信号 1.0） |
| 命名信号 (`_score_name`)             | 25%  | `*ServiceImpl` → APP；`*RepositoryImpl` → DOMAIN            |
| 注解信号 (`_score_annotation`)       | 30%  | `@RestController` → ADAPTER；`@Repository` → DOMAIN         |
| 继承信号 (`_score_inheritance`)      | 10%  | `JpaRepository` → DOMAIN(0.90)；`BaseSettings` → PLATFORM   |
| 导入信号 (`_score_import`)           | 10%  | 高入度 + 框架导入 → DOMAIN/PLATFORM                               |
| 方法签名 (`_score_method_signature`) | 0%*  | `handle/execute` → ADAPTER；`validate` → DOMAIN             |


*方法签名信号默认关闭；go_gin / go_ddd profile 激活为 0.05。

### YAML Override 规则示例（spring_boot）

```yaml
# seed_packs/spring_boot/match_conditions.yaml
ast_overrides:
  - bases_contains: "JpaRepository"
    force_layer: "DOMAIN"
    force_object_type: "Repository"
    confidence: 1.0

  - annotation_contains: "@RestController"
    force_layer: "ADAPTER"
    force_object_type: "Controller"
    confidence: 1.0

  - name_suffix: "ServiceImpl"
    force_layer: "APP"
    force_object_type: "Service"
    confidence: 1.0
```

---

## 5. 真实项目验证结果（4 个 stack 压测矩阵）


| 项目               | 语言/框架      | Fixture                                  | 关键验证                                                               |
| ---------------- | ---------- | ---------------------------------------- | ------------------------------------------------------------------ |
| Spring Boot Demo | Java       | `tests/fixtures/spring-boot-demo/`       | Controller→ADAPTER / Repository→DOMAIN / 幂等性                       |
| FastAPI Demo     | Python     | `tests/fixtures/python-fastapi-demo/`    | v5.0 universal layer ID 合规 / python_fastapi profile                |
| Go Gin Demo      | Go         | `tests/fixtures/go-gin-demo/`            | go_gin profile / path 信号主导 / signature 激活                          |
| NestJS Demo      | TypeScript | `tests/fixtures/typescript-nestjs-demo/` | ★ v5.0 新增 / @Controller→ADAPTER / @Injectable→APP / @Entity→DOMAIN |


---

## 6. 测试覆盖率（2026-05-06）


| 文件                         | 覆盖率  | 状态     |
| -------------------------- | ---- | ------ |
| `code_graph_builder.py`    | ~95% | ✅      |
| `memory_seed_generator.py` | ~99% | ✅      |
| `signal_fusion.py`         | ~92% | ✅      |
| `ontology_populator.py`    | ~86% | ✅      |
| `schema_evolution.py`      | —    | 新增，待补全 |
| `seed_packs/__init__.py`   | ~83% | ✅      |


**相关测试文件**：

- `tests/test_signal_fusion.py`：信号融合单元测试（含 Evaluation DAG）
- `tests/test_bootstrap_on_spring_boot.py`（15 个用例）：Spring Boot E2E + 幂等性
- `tests/test_bootstrap_on_python_fastapi.py`（18 个用例）：Python FastAPI E2E + v5.0 合规
- `tests/test_bootstrap_on_nestjs.py`：★ TypeScript/NestJS E2E（v5.0 新增）
- `tests/test_bootstrap_e2e.py`：综合 Bootstrap E2E
- `tests/test_bootstrap_incremental_e2e.py`（11 个用例）：增量 Bootstrap + Structural GC
- `tests/test_memory_seed_generator.py`：记忆生成器单元测试
- `tests/test_code_graph_builder.py`：依赖图构建测试
- `tests/test_bootstrap_populator.py`：顶层编排器测试
- `tests/test_ontology_principles.py`：★ 5 条本体设计原则 CI 合规检查

