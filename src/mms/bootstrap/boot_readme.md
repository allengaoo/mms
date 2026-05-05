# MMS Bootstrap 模块 (src/mms/bootstrap)

> **最后更新**：2026-05-05 | Bootstrap v2.0

## 1. 模块定位

`src/mms/bootstrap` 是 MMS 系统的**冷启动与初始化引擎（Cold Start Engine）**。它在一个全新的或现有的代码仓库中，通过零 LLM 调用的纯启发式方法，自动推断架构层级、提取代码特征，并生成初始记忆图谱（Memory Graph）。

**核心设计原则**：

- **零 LLM 依赖**：整个冷启动过程仅依赖 YAML 规则和 AST 分析，无 LLM 调用（< 5 秒）。
- **YAML 驱动**：推断规则完全由 `seed_packs/*/match_conditions.yaml` 驱动，不硬编码业务逻辑。
- **信号融合**：汇聚五路独立信号（路径 / 命名 / 注解 / 继承 / 导入），通过加权投票做最终推断。
- **覆盖优先**：YAML Override Pass 在五路信号融合之前短路高置信度框架规则（置信度=1.0）。

---

## 2. 文件结构

```text
src/mms/bootstrap/
├── __init__.py
├── ontology_populator.py   ★ 顶层编排器（CLI 主入口，六步流程）
├── signal_fusion.py        ★ YAML Override Pass + 五路信号融合推断
├── code_graph_builder.py   代码依赖图构建（depends_on / implements 边）
├── memory_seed_generator.py 初始记忆文件生成（MEM-BOOT-*.md）
└── seed_packs/             ★ 框架先验知识库（YAML 驱动）
    ├── __init__.py         SeedPackManager（懒加载 / 格式转换）
    └── {pack_name}/        各框架种子包
```

（注：项目根目录的 `seed_packs/` 是面向框架适配的独立资产包，供 Bootstrap 通过 `load_overrides()` 读取。）

---

## 3. 核心代码文件与方法

### `ontology_populator.py`（顶层编排器）

Bootstrap v2 的 CLI 主入口，按六步顺序协调所有子模块。

**核心数据结构**：

- `BootstrapV2Report`：完整的执行摘要（文件数、类数、推断分布、记忆生成数、耗时等）。

**核心方法**：

- `bootstrap_project(project_root, min_confidence, max_per_layer, dry_run, skip_*)`: 暴露给 CLI 的主入口，执行六步流程，返回 `BootstrapV2Report`。

---

### `signal_fusion.py`（架构推断大脑）

实现 OntologyRegistry 中的两个 Function：`fn_infer_layer` 和 `fn_detect_code_object_type`。

**核心数据结构**：

```python
@dataclass
class SignalBreakdown:
    path_score:        float  # 路径信号（25%）
    name_score:        float  # 命名信号（25%）
    annotation_score:  float  # 注解信号（30%）
    inheritance_score: float  # 继承信号（10%）
    import_score:      float  # 导入信号（10%）

@dataclass
class InferenceResult:
    layer:       str    # CC / PLATFORM / DOMAIN / APP / ADAPTER
    object_type: str    # Controller / Service / Repository / Entity / Config / ...
    confidence:  float  # 0.0 ~ 1.0
    method:      str    # "override" | "signal_fusion"
    breakdown:   SignalBreakdown
```

**关键内置规则表**：

```python
# 路径强信号（单路即可超过推断阈值）
_PATH_STRONG_PATTERNS = {
    "ADAPTER":  ["controller", "handler", "router", "endpoint"],
    "APP":      ["service", "usecase", "use_case"],
    "DOMAIN":   ["entity", "aggregate", "domain", "repository", "model"],
    "PLATFORM": ["config", "configuration", "infrastructure", "infra"],
}

# 类名后缀（含 Java Impl 系列）
_NAME_SUFFIXES = {
    "ADAPTER":  ["Controller", "Handler", "Router", "Endpoint", "Resource", "Filter"],
    "APP":      ["Service", "ServiceImpl", "UseCase", "UseCaseImpl", "Manager", "Orchestrator"],
    "DOMAIN":   ["Repository", "RepositoryImpl", "Entity", "Aggregate", "Dao", "DaoImpl"],
    "PLATFORM": ["Config", "Configuration", "Client", "Provider", "Factory"],
    ...
}
```

**核心方法**：

- `load_overrides(project_root, detected_stacks)`: 从 `seed_packs/*/match_conditions.yaml` 加载 YAML 覆盖规则。
- `apply_override(cls_info, overrides)`: 在三个维度（`bases_contains` / `annotation_contains` / `name_suffix`）匹配覆盖规则，命中即返回 `InferenceResult(confidence=1.0, method="override")`。
- `infer_layer(file_path, class_info, overrides, ...)`: 汇聚五路信号 → 加权投票 → 返回最优层。
- `detect_code_object_type(cls_info, layer)`: 在给定层推断具体 ObjectType。
- `infer_all(classes, project_root, detected_stacks, ...)`: 批量推断（Override Pass 优先，五路信号兜底）。

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

将代码推断结果转化为标准 front-matter v4.0 格式的 Markdown 文件。

**关键层名映射**（解决 Bootstrap 内部层名与 MemoryNode Schema 不符问题）：

```python
_SCHEMA_LAYER_MAP = {
    "ADAPTER":  "L5_interface",      # HTTP controller / gRPC handler
    "APP":      "L4_application",    # Application service / use case
    "DOMAIN":   "L3_domain",         # Domain entity / repository
    "PLATFORM": "L2_infrastructure", # Config / database client
    "CC":       "CC",
    "UNKNOWN":  "CC",
}
```

**核心方法**：

- `generate_seeds(inferences, project_root, max_per_layer, dry_run)`: 遍历推断结果，为置信度达标的类生成 `MEM-BOOT-NNN.md`，自动填充 `id`、`layer`、`tier`、`cites_files`、`ast_pointer`、`provenance` 等 front-matter 字段。

---

## 4. 业务流程（六步）

```mermaid
graph TD
    A[CLI: mulan bootstrap] --> B(ontology_populator.bootstrap_project)

    subgraph Step1 ["Step 1 技术栈嗅探（dep_sniffer）"]
        B --> C[分析 requirements.txt / pom.xml / go.mod]
        C --> D[detected_stacks: spring_boot / fastapi 等]
    end

    subgraph Step1_5 ["Step 1.5 ★ 项目文档自动蒸馏"]
        D --> E[扫描 CONTRIBUTING.md / .cursorrules / ARCHITECTURE.md]
        E --> F[seed_absorber.absorb → CC/_absorb_draft/（待 promote）]
    end

    subgraph Step2 ["Step 2 种子包注入"]
        F --> G[匹配 seed_packs/{stack}/match_conditions.yaml]
        G --> H[注入预制 Markdown 记忆到 docs/memory/seed_packs/]
    end

    subgraph Step3 ["Step 3 AST 骨架化（ast_skeleton）"]
        H --> I[多语言解析: Python / Java / Go / TypeScript]
        I --> J[ast_index.json: file_path → classes / methods / imports]
    end

    subgraph Step4 ["Step 4 代码依赖图（code_graph_builder）"]
        J --> K[构建 CodeGraph: depends_on / implements 边]
        K --> L[in_degree 索引 + 循环依赖检测]
    end

    subgraph Step5 ["Step 5 ★ YAML Override Pass → 五路信号融合"]
        L --> M{Pass 1: YAML Override}
        M -- 命中 confidence=1.0 --> N[锁定 layer + object_type]
        M -- 未命中 --> O[Pass 2: 五路信号加权投票]
        O --> P[路径 25% + 命名 25% + 注解 30% + 继承 10% + 导入 10%]
        P --> Q[confidence ≥ min_confidence?]
    end

    subgraph Step6 ["Step 6 生成初始记忆（memory_seed_generator）"]
        N --> R[生成 MEM-BOOT-NNN.md]
        Q -- YES --> R
        Q -- NO --> S[跳过，记录到 report.classes_skipped]
        R --> T[BootstrapV2Report]
    end
```

### 信号权重详情

| 信号 | 权重 | 典型示例 |
|------|------|---------|
| 路径信号 (`_score_path`) | 25% | `controller/` → ADAPTER（强信号 1.0）；`service/` → APP（强信号 1.0） |
| 命名信号 (`_score_name`) | 25% | `*ServiceImpl` → APP；`*RepositoryImpl` → DOMAIN |
| 注解信号 (`_score_annotation`) | 30% | `@RestController` → ADAPTER；`@Repository` → DOMAIN |
| 继承信号 (`_score_inheritance`) | 10% | `JpaRepository` → DOMAIN(0.90)；`BaseSettings` → PLATFORM |
| 导入信号 (`_score_import`) | 10% | 高入度 + 框架导入 → DOMAIN/PLATFORM |

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

## 5. 真实项目验证结果

| 项目 | 语言 | 文件数 | 识别类数 | 生成记忆数 | 耗时 |
|------|------|--------|---------|-----------|------|
| FastAPI-Template（Python） | Python | 47 | 31 | 9 | < 1s |
| Spring-Petclinic（Java） | Java | 42 | 52 | 4 | < 1s |
| Go-Clean-Template（Go） | Go | 98 | 101 | 14 | < 2s |
| MMS 项目自身 | Python | — | — | 73 | < 3s |

---

## 6. 测试覆盖率（2026-05-05）

| 文件 | 覆盖率 | 状态 |
|------|--------|------|
| `code_graph_builder.py` | 95% | ✅ |
| `memory_seed_generator.py` | 99% | ✅ |
| `signal_fusion.py` | 92% | ✅ |
| `ontology_populator.py` | 86% | ✅ |
| `seed_packs/__init__.py` | 83% | ✅ |

**相关测试文件**：

- `tests/test_signal_fusion.py`：信号融合单元测试
- `tests/test_bootstrap_on_spring_boot.py`（15 个用例）：Spring Boot E2E + 幂等性
- `tests/test_bootstrap_on_python_fastapi.py`（18 个用例）：Python FastAPI E2E + Schema 合规
- `tests/test_bootstrap_e2e.py`：综合 Bootstrap E2E
- `tests/test_memory_seed_generator.py`：记忆生成器单元测试
- `tests/test_code_graph_builder.py`：依赖图构建测试
- `tests/test_bootstrap_populator.py`：顶层编排器测试
