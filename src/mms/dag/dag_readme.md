# DAG 层 (Directed Acyclic Graph)

> **最后更新**：2026-05-04（反映 P0 修复与 AIUStep 半保留策略重构）

## 1. 架构定位

DAG 层是木兰 (Mulan) 任务工程层 (Layer 1) 的核心数据结构与任务拆解模块。它负责将高层级的执行计划 (EP) 转化为机器可读的、带有依赖关系的原子任务图 (DAG)，并为执行层提供代价估算和执行反馈统计。

**设计哲学**：类比数据库优化器的 CBO/RBO 双轨策略。
- RBO（Rule-Based Optimizer）：关键词匹配 12 种高频 AIU 类型，零延迟，100% 确定性，覆盖约 70% 常见任务。
- LLM 兜底：RBO miss 时调用 LLM 分解，保留 LLM 显式声明的稀疏依赖，构建真实 DAG 拓扑（而非 BSP 同步屏障）。

**与 Execution 层的边界**：DAG 层只负责"拆解计划"（WHAT to do & in what order），不负责"执行"（HOW to run）。`DagUnit` 是 Execution 层调度的最小粒度单元；`AIUStep` 是比 `DagUnit` 更细的"执行提示（Hint）"，向 LLM 传递逻辑分解意图，不参与实际调度。

---

## 2. 核心文件结构与主要函数

### 2.1 状态与模型定义 (`dag_model.py`)

定义了 DAG 的核心数据结构和状态流转逻辑，是整个执行过程的状态机持久化载体。

#### `class DagUnit`
代表 DAG 图中的单个执行节点（Execution 层调度的最小原子单元）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `str` | 节点 ID，如 `"U1"`, `"U2"` |
| `title` | `str` | 一句话描述 |
| `layer` | `str` | 所属架构层（如 `"L4_application"`） |
| `files` | `List[str]` | 涉及文件路径列表 |
| `depends_on` | `List[str]` | 前置 Unit ID 列表（DAG 边） |
| `order` | `int` | 执行批次（同 order 可并行） |
| `status` | `str` | `pending / in_progress / done / skipped` |
| `model_hint` | `str` | 建议执行模型（`8b / 16b / capable`） |
| `atomicity_score` | `float` | 原子化评分（0.0–1.0） |
| `aiu_steps` | `List[dict]` | AIUStep 的序列化列表（执行提示层，非调度状态） |
| `aiu_feedback_log` | `List[dict]` | Feedback 回退记录（历史溯源用） |

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

**持久化**：
- `save() -> Path`：写入 `docs/memory/_system/dag/{EP}.json`。
- `DagState.load(ep_id) / DagState.exists(ep_id)`：从磁盘加载/检测存在。

#### `make_dag_state(ep_id, units_data, orchestrator_model) -> DagState`
工厂函数，将 dict 列表转化为强类型 `DagState`，自动推导 `order`（从 `LAYER_ORDER` 映射）。

---

### 2.2 任务拆解引擎 (`task_decomposer.py`)

将自然语言任务描述拆解为有序的 AIUStep 序列（AIUPlan），供 `DagUnit.aiu_steps` 存储。

#### `class TaskDecomposer`

**入口方法**：
```
decompose(task, dag_unit_id, layer, operation, confidence, files_hint) -> AIUPlan
```
- Phase 1：RBO 规则匹配（`_rbo_decompose`）→ 命中则直接返回，零 LLM 调用。
- Phase 2：LLM 兜底（`_llm_decompose`）→ RBO miss 时调用。
- Fallback：返回单步骤 Plan（等同于不分解）。

**关键静态方法**：
```
_assign_ids_and_order(steps, preserve_llm_deps=False) -> List[AIUStep]
```
- **RBO 路径**（`preserve_llm_deps=False`）：BSP 同步屏障策略——高 order 步骤依赖所有低 order 步骤。适合 RBO 生成的已知串行链。
- **LLM 路径**（`preserve_llm_deps=True`）：保留 LLM 显式声明的稀疏依赖关系。按 `exec_order` 重排后做旧 ID → 新 ID 映射，只对没有显式 `depends_on` 的步骤回落至 BSP 屏障。这打破了原来的全局 BSP 同步屏障，构建真实的稀疏 DAG 拓扑。

**RBO 规则库** (`RBO_RULES`)：12 条硬编码规则，覆盖 `SCHEMA_ADD_FIELD`、`ROUTE_ADD_ENDPOINT`、`MUTATION_ADD_INSERT` 等高频 AIU 类型。每条规则含关键词列表、文件路径 hint、token budget 和 model hint。

**静态辅助函数**：
```
should_decompose(task, confidence) -> bool    # 判断是否需要触发分解
_rbo_decompose(task, files_hint) -> (steps, confidence)
_llm_decompose(task, layer, operation, confidence) -> (steps, confidence)
_parse_llm_response(raw) -> (steps, confidence)  # 解析 LLM JSON 输出，分配临时顺序 ID
_match_files(dag_files, hint_prefixes) -> List[str]
```

**模块级函数**：
```
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

| 字段 | 类型 | 说明 |
|------|------|------|
| `aiu_id` | `str` | 步骤 ID，如 `"aiu_1"` |
| `aiu_type` | `str` | AIUType 字符串值 |
| `description` | `str` | 自然语言描述 |
| `layer` | `str` | 所属架构层 |
| `target_files` | `List[str]` | 涉及文件（DagUnit.files 的子集） |
| `depends_on` | `List[str]` | 前置 AIU step ID 列表（数据流依赖） |
| `exec_order` | `int` | 执行顺序 |
| `token_budget` | `int` | Token 预算 |
| `model_hint` | `str` | 推荐执行模型 |

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

全局 AIU 类型注册表，提供 Schema-Driven 的类型元数据查询能力（v2.0，OCP 重构）。

**三层加载优先级**（低到高）：
1. `AIUType` Enum 内置（43 种，兜底层）
2. `schemas/aiu_types_extended.yaml`（轻量扩展，向后兼容）
3. `schemas/aius/*.yaml` 合约文件（含 `input_schema` + `validation_rules`，最高优先级）

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
registry.all_types()                     # -> List[str]，所有已注册类型
registry.types_with_contracts()          # -> List[str]，已定义 input_schema 的类型
registry.types_without_contracts()       # -> List[str]，待完善合约的类型
```

**便捷函数**：`get_registry() -> AIURegistry`（模块级单例，懒加载）

---

### 2.5 原子性验证器 (`atomicity_check.py`)

验证一个 `DagUnit` 是否满足小模型（8B/16B）可执行的 4 条原子化标准。阈值来源于 `docs/memory/_system/config.yaml`。

**4 条原子化标准**：

| 标准 | 说明 | 权重 | 违反行为 |
|------|------|------|----------|
| A1 文件数量 | `≤ max_files_per_unit`（默认 2） | 0.3 | 硬性阻断 |
| A2 Token 估算 | `≤` 模型对应阈值（8b: 4000, 16b: 8000） | 0.3 | 硬性阻断 |
| A3 层一致性 | 所有文件属于同一架构层 | 0.1 | **仅警告**，不阻断 |
| A4 可验证性 | 有 pytest 路径 OR arch_check 覆盖 | 0.3 | 硬性阻断 |

> A3 为软性标准：现代垂直切片架构（CQRS 等）中，跨层修改是正常的业务需求，强制阻断会人为割裂内聚的业务逻辑。

**主要函数**：
```python
validate_unit(files, model, test_files, max_files, token_thresholds, verbose)
    -> (is_atomic: bool, score: float, results: List[CheckResult])

check_a1_file_count(files, max_files) -> CheckResult
check_a2_token_budget(files, model, thresholds) -> CheckResult
check_a3_layer_consistency(files) -> CheckResult   # is_warning=True，不阻断
check_a4_verifiability(files, test_files) -> CheckResult
compute_atomicity_score(results) -> float          # 加权综合分 0.0-1.0
infer_layer(file_path) -> str                      # 从路径推断架构层
estimate_tokens(file_paths) -> int                 # 粗略 token 估算
```

**CLI 用法**：
```bash
python3 atomicity_check.py --files f1.py f2.py --model 8b
python3 atomicity_check.py --unit U3 --ep EP-117 --model 16b
```

---

### 2.6 代价估算器 (`aiu_cost_estimator.py`)

为 AIUPlan 中的每个 AIUStep 估算执行代价（Token 预算、推荐模型、文件优先级），类比 CBO。

**代价模型（4 维）**：

| 维度 | 说明 |
|------|------|
| 基准代价 | `AIU_BASE_COST[aiu_type]`，每种 AIU 类型的经验基准 Token 数 |
| 文件复杂度 | `estimate_token_for_file()` 估算目标文件的 Token 成本（含 ratio=0.3 摘要系数） |
| 层传播系数 | `LAYER_PROPAGATION_COST`，如 L3_domain 修改代价系数 1.3 |
| 历史调整 | `history_factor = min(1.0 + (1.0 - success_rate) * 0.1, 1.1)`，**上限 +10%**（已修复毒性正反馈） |

> **v2.0 修复**：原公式 `1.0 + (1-rate) * 0.5` 会在低成功率时分配过多 Token，导致 LLM 上下文过长、注意力分散，进而导致成功率进一步下降（毒性正反馈）。新公式将增幅上限从 +50% 收窄至 +10%，低成功率情况改由 `suggest()` 切换 capable 模型解决。

**主要类与函数**：
```python
class AIUCostEstimator:
    estimate_step(step, all_unit_files) -> AIUStep  # 原地更新 token_budget 和 model_hint
    estimate_plan(steps, all_unit_files) -> List[AIUStep]  # 批量估算并按复杂度排序文件
    get_total_budget(steps) -> int           # 串行上界
    get_critical_path_budget(steps) -> int  # 关键路径代价（DP 计算最长依赖链）

# 辅助函数
estimate_file_complexity(file_path) -> Dict  # 行数、函数数、import 数、复杂度分
estimate_token_for_file(file_path, ratio) -> int
get_historical_success_rate(aiu_type) -> float  # 委托 AIUFeedbackStore 查询（O(1)，v2.0 修复）
```

---

### 2.7 执行反馈系统 (`aiu_feedback.py`)

收集 AIU 执行结果并建立统计闭环，为代价估算器提供真实数据。v2.0 完全重写。

**v2.0 改进**：
1. **跨平台安全**：移除 `fcntl`（仅 Unix），改用 `threading.Lock`（单进程）+ 可选 `filelock`（跨进程，`pip install filelock`）
2. **内存态缓存**：`Dict[str, deque(maxlen=N)]` 按 AIU 类型缓存最近 N 条记录，`query()` 不再触发磁盘 I/O
3. **滑动窗口衰减**：每种 AIU 类型默认保留最近 50 条（`feedback_decay_window`），自动淘汰旧版本积累的幽灵记忆
4. **统一 Feedback 入口**：新增 `record_unit_feedback()` 和 `get_max_feedback_level()`，替代 `unit_runner` 中的直接文件读写

#### `class AIUStats`

从滑动窗口记录中计算的统计对象（按需计算，不积累全局状态）：

| 属性 | 说明 |
|------|------|
| `total_runs` | 窗口内总执行次数 |
| `success_rate` | 成功率（无数据时默认 0.8） |
| `avg_attempts` | 平均重试次数 |
| `avg_actual_tokens` | 平均实际 Token 消耗 |
| `token_estimation_error` | Token 预估偏差率（>0 表示低估） |
| `avg_latency_ms` | 平均执行延迟 |

#### `class AIUFeedbackStore`

```python
store.record(ep_id, unit_id, aiu_id, aiu_type, success,
             attempts, actual_tokens, estimated_tokens, latency_ms,
             feedback_level, error_pattern)
    # 同步更新内存缓存 + 追加写磁盘（WAL）

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
ep_runner.py (ep_runner.py 调用 DAG 层)
    │
    ├─ dag_model.make_dag_state(units_data) ──→ DagState（持久化到 JSON）
    │
    └─ task_decomposer.decompose(task, dag_unit_id, ...)
           │
           ├─ RBO: _rbo_decompose() ──→ AIUPlan（零 LLM，毫秒级）
           │       └─ _assign_ids_and_order(steps, preserve_llm_deps=False)  # BSP 保守策略
           │
           ├─ LLM: _llm_decompose() ──→ AIUPlan（LLM 生成稀疏 DAG）
           │       └─ _assign_ids_and_order(steps, preserve_llm_deps=True)   # 保留 LLM 声明依赖
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
    end

    Workflow[ep_runner.py<br/>Workflow层] -->|1. make_dag_state| DagModel
    Workflow -->|2. decompose| Decomposer
    Decomposer -->|读取 AIUType/EXEC_ORDER| Types
    Decomposer -->|查询合规规则| Registry
    Registry -.->|加载 YAML 合约| Types
    Decomposer -->|_rbo_decompose / _llm_decompose| Types
    Decomposer -->|_assign_ids_and_order| Types

    Workflow -->|3. validate_unit| AtomCheck
    AtomCheck -.->|配置阈值| DagModel

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
- **未来规划**：当 BSP 同步屏障彻底修复后，再引入 Step 级并发调度（届时补充 `status`, `retry_count` 等字段）

---

## 5. 关键设计决策与权衡

| 决策 | 选择 | 理由 |
|------|------|------|
| AIUStep 是否保留状态机字段 | **半保留**（移除状态字段，保留提示字段） | 7 个状态字段从未被 `unit_runner` 读写；保留会制造认知负担和伪状态机 |
| BSP vs 稀疏 DAG | **RBO=BSP，LLM=稀疏** | RBO 生成已知串行链，BSP 合理；LLM 应声明数据流依赖以避免过度同步 |
| aiu_feedback 写锁 | **threading.Lock + 可选 filelock** | 移除 `fcntl`（仅 Unix），向 Windows 兼容 |
| history_factor 上限 | **+10% 而非 +50%** | 更多 Token ≠ 更好结果；低成功率应换模型而非堆上下文 |
| A3 层一致性检查 | **警告而非阻断** | 垂直切片架构要求跨层修改，硬阻断违背现代开发实践 |

---

## 6. 配置项（`docs/memory/_system/config.yaml`）

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| `feedback_decay_window` | 50 | 每种 AIU 保留的最近执行记录数 |
| `feedback_suggest_min_samples` | 3 | `suggest()` 所需的最小样本数 |
| `feedback_warn_success_threshold` | 0.5 | 成功率低于此值时发出警告并推荐 capable 模型 |
| `cost_estimator_token_min` | 1500 | Token 预算下限 |
| `cost_estimator_token_max` | 16000 | Token 预算上限 |
| `fast_model_max_tokens` | 4000 | ≤ 此值时推荐 fast 模型 |
| `dag_score_threshold_8b` | 0.75 | 8b 模型的原子化评分阈值 |
| `dag_score_threshold_16b` | 0.50 | 16b 模型的原子化评分阈值 |
| `decomposer_confidence_threshold` | 0.6 | 意图置信度低于此值时触发 AIU 分解 |
| `decomposer_auto_append_test` | true | RBO 命中后是否自动追加 TEST_ADD_UNIT 步骤 |
