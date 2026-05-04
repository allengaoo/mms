# DAG 层 (Directed Acyclic Graph)

> **最后更新**：2026-05-04（测试覆盖完成：168 tests / 168 passed，DAG 层全模块 TDD 套件建立）

## 1. 架构定位

DAG 层是木兰 (Mulan) 任务工程层 (Layer 1) 的核心数据结构与任务拆解模块。它负责将高层级的执行计划 (EP) 转化为机器可读的、带有依赖关系的原子任务图 (DAG)，并为执行层提供代价估算和执行反馈统计。

**设计哲学**：类比数据库优化器的 CBO/RBO 双轨策略。

- **RBO（Rule-Based Optimizer）**：关键词匹配 AIU 类型，零延迟，100% 确定性，覆盖约 70% 常见任务。规则从 `schemas/aius/*.yaml` 动态加载（OCP 设计：新增类型无需修改 Python 代码）。
- **LLM 兜底**：RBO miss 时调用 LLM 分解，按 `exec_order` 统一排序，`depends_on` 始终清空（执行顺序由 `exec_order` 唯一表达）。

**与 Execution 层的边界**：DAG 层只负责"拆解计划"（WHAT to do & in what order），不负责"执行"（HOW to run）。`DagUnit` 是 Execution 层调度的最小粒度单元；`AIUStep` 是比 `DagUnit` 更细的"执行提示（Hint）"，向 LLM 传递逻辑分解意图，不参与实际调度。

---

## 2. 核心文件结构与主要函数

### 2.1 状态与模型定义 (`dag_model.py`)

定义了 DAG 的核心数据结构和状态流转逻辑，是整个执行过程的状态机持久化载体。

#### `class DagUnit`

代表 DAG 图中的单个执行节点（Execution 层调度的最小原子单元）。


| 字段                 | 类型           | 说明                                       |
| ------------------ | ------------ | ---------------------------------------- |
| `id`               | `str`        | 节点 ID，如 `"U1"`, `"U2"`                   |
| `title`            | `str`        | 一句话描述                                    |
| `layer`            | `str`        | 所属架构层（如 `"L4_application"`）              |
| `files`            | `List[str]`  | 涉及文件路径列表                                 |
| `depends_on`       | `List[str]`  | 前置 Unit ID 列表（DAG 边）                     |
| `order`            | `int`        | 执行批次（同 order 可并行）                        |
| `status`           | `str`        | `pending / in_progress / done / skipped` |
| `model_hint`       | `str`        | 建议执行模型（`8b / 16b / capable`）             |
| `atomicity_score`  | `float`      | 原子化评分（0.0–1.0）                           |
| `aiu_steps`        | `List[dict]` | AIUStep 的序列化列表（执行提示层，非调度状态）              |
| `aiu_feedback_log` | `List[dict]` | Feedback 回退记录（历史溯源用）                     |


**核心方法**：

- `is_executable(done_ids: List[str]) -> bool`：判断前置依赖是否全部完成，驱动 DAG 拓扑调度。
- `is_atomic_for_model(model: str) -> bool`：根据 `atomicity_score` 和模型类型判断是否满足执行阈值。
- `has_aiu_plan() -> bool`：判断是否已生成 AIUStep 计划。
- `get_aiu_plan() -> Optional[AIUPlan]`：反序列化 `aiu_steps` → `AIUPlan` 对象。
- `set_aiu_plan(plan: AIUPlan)`：将 `AIUPlan` 序列化存储到 `aiu_steps`。
- `to_dict() / from_dict()`：JSON 序列化/反序列化（带向后兼容处理）。

#### `class DagState`

代表整个 EP 的 DAG 执行状态机图，持久化到 `docs/memory/_system/dag/{EP-NNN}.json`。

**核心查询方法**：

- `done_ids() -> List[str]`：获取所有 `done` 状态的 Unit ID。
- `pending_units() / in_progress_units() -> List[DagUnit]`：获取各状态 Unit 列表。
- `executable_units() -> List[DagUnit]`：返回依赖已满足的待执行 Unit（按 `order` 排序）。
- `next_executable(model) -> Optional[DagUnit]`：获取下一个可执行 Unit，优先返回满足模型原子化阈值的。
- `get_batch_groups() -> List[List[DagUnit]]`：按 `order` 分组（同组可并行执行）。
- `progress() -> Tuple[int, int]`：返回 `(done_count, total_count)`。

**状态变更方法**：

- `mark_in_progress(unit_id) / mark_done(unit_id, commit_hash) / mark_skipped(unit_id) / reset_unit(unit_id)`

**持久化 (已实现全局路径解耦)**：

- `save(project_root) -> Path`：动态写入 `{project_root}/docs/memory/_system/dag/{EP}.json`。
- `DagState.load(ep_id, project_root) / DagState.exists(ep_id, project_root)`：基于 `project_root` 从磁盘加载/检测存在。

#### `make_dag_state(ep_id, units_data, orchestrator_model) -> DagState`

工厂函数，将 dict 列表转化为强类型 `DagState`，自动推导 `order`（从 `LAYER_ORDER` 映射）。

---

### 2.2 任务拆解引擎 (`task_decomposer.py`)

将自然语言任务描述拆解为有序的 AIUStep 序列（AIUPlan），供 `DagUnit.aiu_steps` 存储。

**v2.1 重要变更（OCP 重构 + 依赖简化）**：

- 删除了硬编码的 `RBO_RULES` 常量，改由 `AIURegistry.get_rbo_rules()` 从 YAML 动态加载。
- `_assign_ids_and_order()` 移除了 `preserve_llm_deps` 参数和 BSP 同步屏障逻辑，统一按 `exec_order` 排序并清空 `depends_on`。

#### `class TaskDecomposer`

**初始化（动态加载 RBO 规则）**：

```python
def __init__(self):
    # OCP：从 AIURegistry 动态加载（YAML 驱动）
    # 新增 RBO 类型：在 schemas/aius/*.yaml 添加 rbo_triggers 块，无需修改此文件
    self._rbo_rules = get_registry().get_rbo_rules()
```

**入口方法**：

```
decompose(task, dag_unit_id, layer, operation, confidence, files_hint) -> AIUPlan
```

- Phase 1：RBO 规则匹配（`_rbo_decompose`）→ 命中则直接返回，零 LLM 调用。
- Phase 2：LLM 兜底（`_llm_decompose`）→ RBO miss 时调用。
- Fallback：返回单步骤 Plan（等同于不分解）。

**关键静态方法**：

```python
_assign_ids_and_order(steps: List[AIUStep]) -> List[AIUStep]
```

按 `exec_order` 排序后分配顺序 `aiu_id`（如 `aiu_1`, `aiu_2`...）。

> **最新变更 (2026-05)**：恢复了稀疏依赖 (`depends_on`) 的保留与映射。在分配新的 `aiu_id` 时，会同步更新 `depends_on` 中的 ID 引用。同时加入了**循环依赖检测**机制，若发现循环则清空依赖，确保 DAG 的合法性。这为未来的细粒度并发调度保留了拓扑信息。

**执行顺序的表达方式**：


| 机制           | 用途                                 |
| ------------ | ---------------------------------- |
| `exec_order` | **主要排序依据**（数字越小越先执行）               |
| `depends_on` | **稀疏依赖**（保留 LLM 声明的拓扑关系，供未来并发调度使用） |


**RBO 规则加载**：

RBO 规则通过 `AIURegistry.get_rbo_rules()` 从 YAML 文件动态加载，覆盖 12 种核心 AIU 类型：


| YAML 文件                        | 覆盖的 RBO 触发类型                                                      |
| ------------------------------ | ----------------------------------------------------------------- |
| `family_A_schema.yaml`         | `SCHEMA_ADD_FIELD`、`CONTRACT_ADD_REQUEST`、`CONTRACT_ADD_RESPONSE` |
| `family_B_control_flow.yaml`   | `LOGIC_ADD_GUARD`                                                 |
| `family_C_data_access.yaml`    | `MUTATION_ADD_INSERT`、`MUTATION_ADD_UPDATE`、`QUERY_ADD_SELECT`    |
| `family_D_interface.yaml`      | `ROUTE_ADD_ENDPOINT`、`ROUTE_ADD_PERMISSION`                       |
| `family_E_infrastructure.yaml` | `CONFIG_MODIFY`                                                   |
| `family_F_validation.yaml`     | `TEST_ADD_UNIT`、`DOC_SYNC`                                        |
| `schemas/aius/custom/*.yaml`   | 自定义扩展（可随时添加，零代码修改）                                                |


**辅助方法**：

```python
should_decompose(task, confidence) -> bool    # 判断是否需要触发分解（使用 registry 加载规则）
_rbo_decompose(task, files_hint) -> (steps, confidence)
_llm_decompose(task, layer, operation, confidence) -> (steps, confidence)
_parse_llm_response(raw) -> (steps, confidence)  # 解析 LLM JSON，depends_on 始终清空
_match_files(dag_files, hint_prefixes) -> List[str]
```

**模块级函数**：

```python
build_constrained_context(task_description, aiu_step, intent_result, memory_context, token_budget) -> str
```

EP-130 动态 Token-Fit 上下文打包，将 AST 骨架 + Ontology 约束 + 记忆上下文按优先级裁剪至 `token_budget`。

---

### 2.3 原子意图单元定义 (`aiu_types.py`)

定义 AIU 类型体系和数据结构，是整个 DAG 层的类型元数据中心。

#### `class AIUType(str, Enum)`

43 种 AIU 类型，分 9 族：

- 族 A（6 种）：结构定义类（Schema Operators），如 `SCHEMA_ADD_FIELD`
- 族 B（5 种）：逻辑流控制类，如 `LOGIC_ADD_CONDITION`
- 族 C（5 种）：数据读写类，如 `MUTATION_ADD_INSERT`
- 族 D（5 种）：接口与路由类，如 `ROUTE_ADD_ENDPOINT`
- 族 E（4 种）：事件与基础设施类，如 `EVENT_ADD_PRODUCER`
- 族 F（3 种）：质量保障类，如 `TEST_ADD_UNIT`
- 族 G（4 种）：分布式协调类，如 `SAGA_ADD_STEP` *(v3.0 新增)*
- 族 H（4 种）：治理与合规类，如 `RBAC_ADD_PERMISSION` *(v3.0 新增)*
- 族 I（3 种）：可观测性类，如 `METRIC_ADD_COUNTER` *(v3.0 新增)*

**配套静态映射**：

- `AIU_EXEC_ORDER: Dict[AIUType, int]`：执行顺序（1=结构定义最先，8=文档同步最后）
- `AIU_LAYER_MAP: Dict[AIUType, str]`：主影响层（如 `DOMAIN / ADAPTER / APP / PLATFORM`）
- `AIU_LAYER_AFFINITY: Dict[AIUType, List[str]]`：多层亲和性（用于 synthesizer 提权搜索）
- `AIU_FAMILY: Dict[str, List[AIUType]]`：族分组
- `AIU_TO_FAMILY: Dict[AIUType, str]`：反向索引

#### `class AIUStep`（半保留策略 v2.0）

**当前定位**：执行提示层（Execution Hint），向 LLM 传递"这个 Unit 的逻辑分解是步骤1→2→3"，不参与运行时调度状态管理。

**当前字段（9 个，移除了 7 个状态机字段）**：


| 字段             | 类型          | 说明                                  |
| -------------- | ----------- | ----------------------------------- |
| `aiu_id`       | `str`       | 步骤 ID，如 `"aiu_1"`                   |
| `aiu_type`     | `str`       | AIUType 字符串值                        |
| `description`  | `str`       | 自然语言描述                              |
| `layer`        | `str`       | 所属架构层                               |
| `target_files` | `List[str]` | 涉及文件（DagUnit.files 的子集）             |
| `depends_on`   | `List[str]` | **始终为 `[]*`*（执行顺序由 `exec_order` 表达） |
| `exec_order`   | `int`       | 执行顺序（唯一排序依据）                        |
| `token_budget` | `int`       | Token 预算                            |
| `model_hint`   | `str`       | 推荐执行模型                              |


> **已移除**（v1.0 遗留的伪状态机字段，从未被 `unit_runner.py` 读写）：`status`, `retry_count`, `feedback_level`, `split_from`, `error_pattern`, `actual_tokens`, `completed_at`，以及 `can_be_split()` 方法。

**实例方法**：

- `aiu_type_enum -> Optional[AIUType]`：字符串转枚举。
- `family -> Optional[str]`：返回所属族名。
- `is_schema_type() -> bool`：是否为族 A（结构定义类）。
- `to_dict() / from_dict(d)`：序列化/反序列化（向后兼容，忽略旧 JSON 中的未知字段）。

#### `class AIUPlan`

一个 `DagUnit` 的完整 AIU 分解计划，由 `task_decomposer.py` 生成，存储于 `DagUnit.aiu_steps`。

**字段**：`dag_unit_id`, `steps: List[AIUStep]`, `decomposed_by` (`"rbo"/"llm"/"fallback"`), `confidence`, `original_task`

**方法**：

- `get_step(aiu_id) -> Optional[AIUStep]`
- `insert_before(target_aiu_id, new_step)`：在指定 AIU 前插入步骤（Level 2 回退预留钩子）。
- `replace_with_split(target_aiu_id, part_a, part_b)`：将指定 AIU 分裂为两个（Level 3 回退预留钩子）。
- `to_dict() / from_dict(d)`

> **已移除**（v2.0）：`pending_steps`, `done_steps`, `failed_steps`, `get_executable_steps`（均依赖已删除的 `status` 字段）。

#### 错误分类（错误处理用）

- `class AIUErrorPattern(str, Enum)`：9 种错误模式（`IMPORT_ERROR`, `MISSING_FIELD`, `SYNTAX_ERROR` 等）
- `ERROR_TO_FEEDBACK_LEVEL: Dict[AIUErrorPattern, int]`：错误模式 → 建议 Feedback 级别映射
- `classify_error(error_msg: str) -> AIUErrorPattern`：从错误文本推断错误模式（供 `unit_runner._aiu_feedback_analysis` 使用）

---

### 2.4 AIU 类型注册表 (`aiu_registry.py`)

全局 AIU 类型注册表，提供 Schema-Driven 的类型元数据查询能力（v2.1，新增 RBO OCP 扩展）。

**三层加载优先级**（低到高）：

1. `AIUType` Enum 内置（43 种，兜底层）
2. `schemas/aiu_types_extended.yaml`（轻量扩展，向后兼容）
3. `schemas/aius/*.yaml` 合约文件（含 `input_schema` + `validation_rules` + `rbo_triggers`，最高优先级）

#### `class AIUTypeDef`（v2.1 新增 `rbo_triggers` 字段）

```python
@dataclass
class AIUTypeDef:
    id: str                   # AIU 类型 ID
    family: str               # 所属族（如 "A_schema"）
    layer: str                # 主架构层
    layer_affinity: List[str] # 多层亲和性
    exec_order: int           # 执行顺序
    base_cost: int            # 基础 Token 成本
    description: str
    input_schema: Dict        # DAG 编排 LLM 输入规范
    validation_rules: Dict    # arch_check AST 验证规则
    rbo_triggers: Dict        # RBO 触发器（v2.1 新增，OCP 扩展点）
    is_builtin: bool
```

`rbo_triggers` 格式（在 YAML 中声明）：

```yaml
rbo_triggers:
  keywords: ["新增字段", "add field", ...]
  description_template: "在 {model} 模型新增字段"
  token_budget: 3000
  model_hint: "fast"
  files_hint: ["backend/app/domain/"]
```

#### `class AIURegistry`

**公共 API**：

```python
registry.get(type_id)                    # -> Optional[AIUTypeDef]
registry.get_family(type_id)             # -> str，如 "A_schema"
registry.get_layer(type_id)              # -> str，如 "ADAPTER"
registry.get_base_cost(type_id)          # -> int（基础 Token 成本）
registry.get_exec_order(type_id)         # -> int
registry.get_input_schema(type_id)       # -> Dict（DAG 编排时 LLM 遵守的输入规范）
registry.get_validation_rules(type_id)   # -> Dict（arch_check AST 验证规则）
registry.get_layer_affinity(type_id)     # -> List[str]
registry.get_rbo_rules()                 # -> List[Dict]，供 TaskDecomposer 动态加载（v2.1 新增）
registry.all_types()                     # -> List[str]，所有已注册类型
registry.types_with_contracts()          # -> List[str]，已定义 input_schema 的类型
registry.types_without_contracts()       # -> List[str]，待完善合约的类型
```

`**get_rbo_rules()` 返回格式**（与 TaskDecomposer 内部格式兼容）：

```python
[{
    "id": "rbo_schema_add_field",
    "aiu_type": AIUType.SCHEMA_ADD_FIELD,   # AIUType Enum
    "keywords": ["新增字段", "add field", ...],
    "description_template": "...",
    "token_budget": 3000,
    "model_hint": "fast",
    "files_hint": ["backend/app/domain/"],
}, ...]
```

**便捷函数**：`get_registry() -> AIURegistry`（模块级单例，懒加载）

---

### 2.5 原子性验证器 (`atomicity_check.py`)

验证一个 `DagUnit` 是否满足小模型（8B/16B）可执行的 4 条原子化标准。阈值来源于 `docs/memory/_system/config.yaml`。

**4 条原子化标准**（A3 已升级为图谱连通性检查）：


| 标准          | 说明                                    | 权重  | 违反行为        |
| ----------- | ------------------------------------- | --- | ----------- |
| A1 文件数量     | `≤ max_files_per_unit`（默认 2）          | 0.3 | 硬性阻断        |
| A2 Token 估算 | `≤` 模型对应阈值（8b: 4000, 16b: 8000）       | 0.3 | 硬性阻断        |
| **A3 内聚性**  | **双轨策略**：代码图谱连通性（优先）或架构层一致性（Fallback） | 0.1 | **仅警告**，不阻断 |
| A4 可验证性     | 有 pytest 路径 OR arch_check 覆盖          | 0.3 | 硬性阻断        |


#### A3 双轨检查策略（v2.1 升级）

```
Track A（优先，code_graph.json 存在时）：
  _build_file_graph()    → 从 code_graph.json 构建文件级无向邻接表
  _are_files_connected() → BFS 检查所有文件是否属于同一连通分量
  ├── 全连通 → passed=True, "代码图谱连通（N 个文件属同一连通分量）"
  └── 有孤立 → passed=False, is_warning=True, "代码图谱不连通，孤立文件：xxx.py"

Track B（Fallback，文件不在图中时）：
  infer_layer(file_path) → 从路径推断架构层
  所有业务层文件属于同一层 → passed=True
  层不一致 → passed=False, is_warning=True（架构层 fallback）
```

**辅助函数**：

```python
_build_file_graph(code_graph_path) -> Dict[str, Set[str]]
    # 从 code_graph.json 构建文件级无向图（code_graph 路径：PROJECT_ROOT/docs/memory/_system/code_graph.json）

_normalize_path(file_path) -> str
    # 规范化为相对路径（去除项目根前缀）

_are_files_connected(files, graph) -> (bool, List[str])
    # BFS 连通性检查，返回 (is_connected, isolated_files)
```

**主要函数**：

```python
validate_unit(files, model, test_files, max_files, token_thresholds, verbose)
    -> (is_atomic: bool, score: float, results: List[CheckResult])

check_a1_file_count(files, max_files) -> CheckResult
check_a2_token_budget(files, model, thresholds) -> CheckResult
check_a3_layer_consistency(files, code_graph_path=None) -> CheckResult  # 双轨策略，is_warning=True
check_a4_verifiability(files, test_files) -> CheckResult
compute_atomicity_score(results) -> float     # 加权综合分 0.0-1.0
infer_layer(file_path) -> str                 # 从路径推断架构层（Track B fallback）
estimate_tokens(file_paths) -> int            # 粗略 token 估算
```

**CLI 用法**：

```bash
python3 atomicity_check.py --files f1.py f2.py --model 8b
python3 atomicity_check.py --unit U3 --ep EP-117 --model 16b
```

---

### 2.6 代价估算器 (`aiu_cost_estimator.py`)

为 AIUPlan 中的每个 AIUStep 估算执行代价（Token 预算、推荐模型、文件优先级），类比 CBO。

> **CBO 解耦升级 (2026-05)**：移除了对 `AIUFeedbackStore` 的硬编码依赖。现在 `estimate_step` 和 `estimate_plan` 接受一个可选的 `success_rate_provider` 回调函数。这使得代价估算器完全脱离了底层文件 I/O，极大地提升了可测试性和模块独立性。

**代价模型（4 维）**：


| 维度    | 说明                                                                                  |
| ----- | ----------------------------------------------------------------------------------- |
| 基准代价  | `AIU_BASE_COST[aiu_type]`，每种 AIU 类型的经验基准 Token 数                                    |
| 文件复杂度 | `estimate_token_for_file()` 估算目标文件的 Token 成本（含 ratio=0.3 摘要系数）                      |
| 层传播系数 | `LAYER_PROPAGATION_COST`，如 L3_domain 修改代价系数 1.3                                     |
| 历史调整  | `history_factor = min(1.0 + (1.0 - success_rate) * 0.1, 1.1)`，**上限 +10%**（已修复毒性正反馈） |


> **v2.0 修复**：原公式 `1.0 + (1-rate) * 0.5` 会在低成功率时分配过多 Token，导致 LLM 上下文过长、注意力分散，进而成功率进一步下降（毒性正反馈）。新公式将增幅上限从 +50% 收窄至 +10%，低成功率情况改由 `suggest()` 切换 capable 模型解决。

**主要类与函数**：

```python
class AIUCostEstimator:
    estimate_step(step, all_unit_files) -> AIUStep  # 原地更新 token_budget 和 model_hint
    estimate_plan(steps, all_unit_files) -> List[AIUStep]  # 批量估算并按复杂度排序文件
    get_total_budget(steps) -> int               # 串行上界（所有步骤之和）

# 辅助函数
estimate_file_complexity(file_path) -> Dict  # 行数、函数数、import 数、复杂度分
estimate_token_for_file(file_path, ratio) -> int
get_historical_success_rate(aiu_type) -> float  # 委托 AIUFeedbackStore 查询（O(1)，v2.0）
```

> **v2.1 变更**：已删除 `get_critical_path_budget(steps)` 方法。该方法依赖 `AIUStep.depends_on` 构建依赖图并通过动态规划计算最长路径，但由于 `depends_on` 在 v2.1 中始终为 `[]`，此方法输出退化为与 `get_total_budget()` 相同的结果，故删除。

---

### 2.7 执行反馈系统 (`aiu_feedback.py`)

收集 AIU 执行结果并建立统计闭环，为代价估算器提供真实数据。v2.1 完全确定 filelock 依赖。

**v2.1 改进**（在 v2.0 基础上）：

1. **filelock 升为必选依赖**（`requirements.txt: filelock>=3.12`）：移除 `threading.Lock` 降级分支，直接 `from filelock import FileLock`。保证 CI/CD 多进程场景的跨进程写入安全，避免 `feedback_stats.jsonl` 数据竞争损坏。

**v2.0 已有改进**：

1. **内存态缓存**：`Dict[str, deque(maxlen=N)]` 按 AIU 类型缓存最近 N 条记录，`query()` 不再触发磁盘 I/O
2. **滑动窗口衰减**：每种 AIU 类型默认保留最近 50 条（`feedback_decay_window`），自动淘汰旧版本积累的幽灵记忆
3. **统一 Feedback 入口**：`record_unit_feedback()` 和 `get_max_feedback_level()` 替代 `unit_runner` 中的直接文件读写

#### `class AIUStats`

从滑动窗口记录中计算的统计对象（按需计算，不积累全局状态）：


| 属性                       | 说明                   |
| ------------------------ | -------------------- |
| `total_runs`             | 窗口内总执行次数             |
| `success_rate`           | 成功率（无数据时默认 0.8）      |
| `avg_attempts`           | 平均重试次数               |
| `avg_actual_tokens`      | 平均实际 Token 消耗        |
| `token_estimation_error` | Token 预估偏差率（>0 表示低估） |
| `avg_latency_ms`         | 平均执行延迟               |


#### `class AIUFeedbackStore`

```python
store.record(ep_id, unit_id, aiu_id, aiu_type, success,
             attempts, actual_tokens, estimated_tokens, latency_ms,
             feedback_level, error_pattern)
    # 同步更新内存缓存 + FileLock 追加写磁盘（WAL，跨进程安全）

store.query(aiu_type=None) -> Dict[str, AIUStats]
    # 从内存缓存读取（O(1)），不触发磁盘 I/O

store.suggest(aiu_type, estimated_tokens) -> Dict
    # 返回推荐 token_budget / model / confidence / warning

store.summary(top_n) -> str
    # 统计摘要报告（类比 EXPLAIN ANALYZE）

store.record_unit_feedback(ep_id, unit_id, level, success, error_preview)
    # 记录 Unit 级 Feedback 回退事件（type=aiu_feedback）

store.get_max_feedback_level(ep_id, unit_id) -> int
    # 查询 Unit 已达到的最高 Feedback 级别（供三级回退决策）
```

**数据存储**：`docs/memory/_system/feedback_stats.jsonl`（append-only WAL）

- `type=aiu_execution`：AIU 执行统计记录（进入内存缓存）
- `type=aiu_feedback`：Unit 级 Feedback 回退事件（直接写磁盘）

**便捷函数**：

```python
get_feedback_store() -> AIUFeedbackStore   # 全局单例
record_aiu_execution(ep_id, unit_id, aiu_id, aiu_type, success, **kwargs)
query_aiu_suggestion(aiu_type, estimated_tokens) -> Dict
print_feedback_summary()
```

**与 `unit_runner.py` 的集成**：Unit 执行成功后自动调用 `record()`，3-Strike 全失败后记录失败反馈。`_record_aiu_feedback()` 和 `_get_aiu_feedback_history_level()` 均委托给 `AIUFeedbackStore`，消除了 `unit_runner` 中的重复文件操作。

---

## 3. 模块间调用关系与数据流

### 3.1 数据流转 (Data Flow)

```
ep_parser.py (EP Markdown)
    │
    │ EpDocument (Scope Table: Unit ID / Title / Files / Depends)
    ▼
ep_runner.py (调用 DAG 层)
    │
    ├─ dag_model.make_dag_state(units_data) ──→ DagState（持久化到 JSON）
    │
    └─ task_decomposer.decompose(task, dag_unit_id, ...)
           │
           ├─ __init__: get_registry().get_rbo_rules() → self._rbo_rules（YAML 驱动）
           │
           ├─ RBO: _rbo_decompose() ──→ AIUPlan
           │       └─ _assign_ids_and_order(steps)  # 按 exec_order 排序，depends_on=[]
           │
           ├─ LLM: _llm_decompose() ──→ AIUPlan
           │       └─ _assign_ids_and_order(steps)  # 同上，LLM 声明的依赖也被清空
           │
           └─ Fallback: 单步骤 Plan
               │
               ▼
           AIUPlan.steps → DagUnit.set_aiu_plan() → DagState.save()
               │
               │（可选，供 LLM 上下文构建使用）
               ▼
           build_constrained_context(task, aiu_step, ...)
               │
               └─ AIUCostEstimator.estimate_plan() ──→ token_budget / model_hint 更新
                       └─ get_historical_success_rate(aiu_type)
                               └─ AIUFeedbackStore.query()（内存缓存，O(1)）

unit_runner.py（执行完成后）
    └─ AIUFeedbackStore.record(success/failure) ──→ 反馈闭环
           └─ FileLock 保护写入（跨进程安全，filelock 必选依赖）
```

### 3.2 内部调用关系图

```mermaid
graph TD
    subgraph DAG层
        Decomposer(task_decomposer.py<br/>TaskDecomposer)
        DagModel(dag_model.py<br/>DagState / DagUnit)
        Types(aiu_types.py<br/>AIUType / AIUStep / AIUPlan)
        Registry(aiu_registry.py<br/>AIURegistry)
        AtomCheck(atomicity_check.py<br/>validate_unit)
        CostEst(aiu_cost_estimator.py<br/>AIUCostEstimator)
        Feedback(aiu_feedback.py<br/>AIUFeedbackStore)
        CodeGraph[(code_graph.json<br/>文件级依赖图)]
    end

    Workflow[ep_runner.py<br/>Workflow层] -->|1. make_dag_state| DagModel
    Workflow -->|2. decompose| Decomposer

    Registry -->|加载 schemas/aius/*.yaml| Types
    Registry -.->|get_rbo_rules → rbo_triggers| Decomposer

    Decomposer -->|读取 AIUType/EXEC_ORDER| Types
    Decomposer -->|__init__ 动态加载 RBO 规则| Registry

    Workflow -->|3. validate_unit| AtomCheck
    AtomCheck -->|Track A: 连通性检查| CodeGraph
    AtomCheck -.->|Track B fallback: 层一致性| DagModel

    Workflow -->|4. estimate_plan| CostEst
    CostEst -->|get_historical_success_rate| Feedback
    Feedback -.->|内存缓存 query O(1)| Feedback

    UnitRunner[unit_runner.py<br/>Execution层] -->|5. 执行成功/失败后 record| Feedback
    UnitRunner -->|_record_aiu_feedback| Feedback
    UnitRunner -->|_get_aiu_feedback_history_level| Feedback
```



---

## 4. 状态流转机制

### 4.1 DagUnit 状态机

```
                    ┌────────────┐
          初始       │  pending   │
                    └─────┬──────┘
                          │ 依赖满足，被 ep_runner 选中
                          ▼
                    ┌────────────┐
                    │in_progress │
                    └─────┬──────┘
              ┌───────────┤
              │ 3-Strike  │  验证通过 + git commit
              │ 全失败     ▼
              │     ┌────────────┐
              │     │    done    │ ← 可断点续跑（保留 commit_hash）
              │     └────────────┘
              │
              ▼
         (当前：输出错误日志
          未来：可扩展为 failed 状态)

    手动跳过 → skipped（不阻断后续依赖节点）
    reset_unit() → pending（支持回退重试）
```

### 4.2 DagUnit 驱动的并发批次执行

`DagState.get_batch_groups()` 将 Unit 按 `order` 分组，同组 Unit 可并行执行。当前 `BatchRunner` 实现为顺序执行（phase 5 预留并行能力）。

```
order=1 → [U1_domain, U2_infra]  ← 可并行（当前顺序执行）
order=2 → [U3_app]               ← 等 order=1 全部完成
order=3 → [U4_api, U5_frontend]  ← 等 order=2 完成
order=4 → [U6_test]              ← 最后
```

### 4.3 AIUStep 的当前角色（半保留策略）

`AIUStep` 现在是**执行提示层**，不是调度状态机：

- **用途**：调用 `build_constrained_context()` 时，向 LLM 传递"你要完成的是步骤 N，逻辑分解为：aiu_1→aiu_2→aiu_3"
- **不做的事**：`unit_runner` 不按 AIUStep 逐步调度、不更新 AIUStep 的状态、不逐步 commit
- `**depends_on` 的语义变化**：v2.1 起始终为 `[]`，`exec_order` 是唯一的顺序表达，避免 LLM 幻觉依赖和 BSP 全同步屏障的过度串行化
- **未来规划**：当需要 Step 级并发调度时，再引入 `status`, `retry_count` 等字段（届时 `depends_on` 重新启用）

---

## 5. 关键设计决策与权衡


| 决策                       | 选择                                                | 理由                                                    |
| ------------------------ | ------------------------------------------------- | ----------------------------------------------------- |
| AIUStep 是否保留状态机字段        | **半保留**（移除状态字段，保留提示字段）                            | 7 个状态字段从未被 `unit_runner` 读写；保留会制造认知负担和伪状态机            |
| AIUStep.depends_on       | **始终 `[]`**，exec_order 唯一排序                       | LLM 声明依赖易引入幻觉；BSP 屏障过度串行化；exec_order 语义已足够            |
| RBO 规则来源                 | **YAML 驱动**（`rbo_triggers` 字段，OCP 设计）             | 新增 RBO 类型无需修改 Python 代码，在 YAML 中添加 `rbo_triggers` 块即可 |
| filelock 依赖策略            | **必选**（`requirements.txt: filelock>=3.12`）        | 移除 `threading.Lock` 降级分支，保证 CI/CD 多进程场景写入安全           |
| get_critical_path_budget | **已删除**                                           | AIUStep.depends_on 始终为 `[]`，关键路径 DP 计算失去意义            |
| A3 内聚性检查                 | **双轨策略**：代码图谱连通性（Track A）→ 层一致性（Track B Fallback） | 图谱更精确反映真实代码耦合；无图时保留原有层一致性检查；两者均为警告不阻断                 |
| history_factor 上限        | **+10% 而非 +50%**                                  | 更多 Token ≠ 更好结果；低成功率应换模型而非堆上下文                        |


---

## 6. 配置项（`docs/memory/_system/config.yaml`）


| 配置键                               | 默认值   | 说明                             |
| --------------------------------- | ----- | ------------------------------ |
| `feedback_decay_window`           | 50    | 每种 AIU 保留的最近执行记录数              |
| `feedback_suggest_min_samples`    | 3     | `suggest()` 所需的最小样本数           |
| `feedback_warn_success_threshold` | 0.5   | 成功率低于此值时发出警告并推荐 capable 模型     |
| `cost_estimator_token_min`        | 1500  | Token 预算下限                     |
| `cost_estimator_token_max`        | 16000 | Token 预算上限                     |
| `fast_model_max_tokens`           | 4000  | ≤ 此值时推荐 fast 模型                |
| `dag_score_threshold_8b`          | 0.75  | 8b 模型的原子化评分阈值                  |
| `dag_score_threshold_16b`         | 0.50  | 16b 模型的原子化评分阈值                 |
| `decomposer_confidence_threshold` | 0.6   | 意图置信度低于此值时触发 AIU 分解            |
| `decomposer_auto_append_test`     | true  | RBO 命中后是否自动追加 TEST_ADD_UNIT 步骤 |


---

## 7. 扩展指南：新增 RBO 规则（OCP 方式）

**无需修改 Python 代码**，只需在 `schemas/aius/` 目录（或 `custom/` 子目录）的 YAML 文件中为目标 AIU 类型添加 `rbo_triggers` 块：

```yaml
# schemas/aius/custom/my_custom_rules.yaml
schema_version: "1.0"
family: X_custom
layer_affinity: [APPLICATION]

aius:
  - id: LOGIC_ADD_BRANCH      # 对应 AIUType Enum 中的值
    rbo_triggers:
      keywords:
        - "策略模式"
        - "strategy pattern"
        - "多路分支"
      description_template: "新增多路分支策略（Strategy Pattern）"
      token_budget: 3500
      model_hint: "fast"
      files_hint:
        - "backend/app/services/"
```

下次 `TaskDecomposer()` 实例化时，`get_registry().get_rbo_rules()` 自动包含新规则，无任何其他操作。

---

## 8. 测试覆盖（TDD 套件）

> 执行命令：`PYTHONPATH=src pytest tests/dag/ -v`  
> 当前结果：**168 tests / 168 passed**，执行时间 < 2 秒  
> 测试文件均使用 `tmp_path` 隔离，无网络依赖，无真实 LLM 调用。

### 8.1 测试文件总览


| 测试文件                                | tests | 覆盖模块                                           | 主要验证点                                                                                   |
| ----------------------------------- | ----- | ---------------------------------------------- | --------------------------------------------------------------------------------------- |
| `test_cost_and_atomicity.py`        | 14    | `atomicity_check.py` + `aiu_cost_estimator.py` | CBO 毒性正反馈阻断（+10% 上限）；A3 新文件悖论修复（7 场景）                                                   |
| `test_aiu_registry_v2.py`           | 13    | `aiu_registry.py`                              | 内置 ≥12 RBO 规则；key 格式与 Decomposer 兼容；OCP YAML 扩展；Decomposer 集成                           |
| `test_feedback_store.py`            | 12    | `aiu_feedback.py`                              | 滑动窗口衰减（边界精确）；FileLock 多线程×100条；FileLock 多进程×50条                                         |
| `test_task_decomposer.py`           | 36    | `task_decomposer.py`                           | RBO 关键词匹配/去重/auto-TEST；LLM 响应解析（8 场景含容错）；Fallback；`_assign_ids_and_order`               |
| `test_aiu_cost_estimator.py`        | 26    | `aiu_cost_estimator.py`                        | 基准代价；层因子；Token 上/下界；模型选择；history_factor 精确公式；文件复杂度排序                                    |
| `test_atomicity_check_full.py`      | 41    | `atomicity_check.py`                           | A1/A2/A4 全路径；`infer_layer` 13 个路径前缀；`compute_atomicity_score` 加权公式；`validate_unit` 完整链路 |
| `test_aiu_registry_ocp_extended.py` | 12    | `aiu_registry.py`                              | custom/ 子目录加载；格式错误静默跳过；缺 id 跳过；非 YAML 忽略；加载后内置类型完整                                      |
| `test_feedback_suggest.py`          | 14    | `aiu_feedback.py`                              | 样本不足默认值；低成功率升级 capable+warning；低估上调/高估下调/正常不变；confidence 线性增长                           |


### 8.2 已消除风险


| 风险                      | 状态       | 对应测试                                                            |
| ----------------------- | -------- | --------------------------------------------------------------- |
| A3 新文件 100% 假阳性（"狼来了"）  | ✅ 已修复+测试 | `test_cost_and_atomicity.py::TestA3NewFileParadox`              |
| CBO 毒性正反馈（低成功率膨胀 token） | ✅ 已测试    | `test_cost_and_atomicity.py::TestCBOAntiToxicFeedback`          |
| FileLock 跨进程竞争          | ✅ 已测试    | `test_feedback_store.py::TestFileLockConcurrency`               |
| RBO 规则硬编码（OCP 违反）       | ✅ 已测试    | `test_aiu_registry_v2.py` + `test_aiu_registry_ocp_extended.py` |
| LLM 响应解析崩溃（格式容错）        | ✅ 已测试    | `test_task_decomposer.py::TestParseLLMResponse`                 |
| suggest() 策略未覆盖         | ✅ 已测试    | `test_feedback_suggest.py`                                      |
| A1/A2/A4 检查器无覆盖         | ✅ 已测试    | `test_atomicity_check_full.py`                                  |


### 8.3 剩余待补（低优先级）


| 场景                               | 优先级 | 说明                                         |
| -------------------------------- | --- | ------------------------------------------ |
| LLM 分解路径 VCR 录制                  | P3  | 需要 API Key 首次录制，平时 replay；当前已用 mock 覆盖核心逻辑 |
| `unit_runner` + FeedbackStore 集成 | P3  | 跨层集成，依赖 unit_runner 的实际实现完成度               |


### 8.4 运行命令参考

```bash
# 全套（推荐日常）
PYTHONPATH=src pytest tests/dag/ -v

# 带覆盖率报告
PYTHONPATH=src pytest tests/dag/ --cov=mms.dag --cov-report=term-missing

# 快速冒烟（仅 P0 关键路径，< 0.5s）
PYTHONPATH=src pytest tests/dag/test_cost_and_atomicity.py tests/dag/test_feedback_store.py -v
```

