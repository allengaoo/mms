基于对木兰系统 Layer 1 `dag` 层最新代码集及 `dag_readme.md` 的深度静态分析，你已经成功将上次审查中提到的“OCP 破坏”、“毒性正反馈”和“跨进程崩溃”等致命缺陷彻底修复。引入 `filelock` 和 `rbo_triggers` YAML 驱动是非常成熟的工业级实践。

然而，站在企业级架构和图计算理论的客观立场，当前代码在修复旧问题的同时，**矫枉过正地引发了“架构退化”，并潜伏了一个隐蔽的“新文件悖论”**。

以下是去客套话的批判性工程审查、优化建议以及为 DAG 层量身定制的 TDD 落地计划。

---

### 一、 批判性工程分析与缺陷定位

#### 1. 架构退化：从“有向无环图（DAG）”退化为“批处理队列（Batch Queue）”

- **事实审查**：在 `dag_readme.md` 和 `aiu_types.py` 中，你明确声明 `depends_on` 始终为 `[]`，完全依靠 `exec_order` 进行排序。在 `task_decomposer.py` 第 386 行，代码被硬性修改为 `step.depends_on =[]`。
- **工程批判**：这是典型的**矫枉过正（Overcorrection）**。之前的问题在于“基于 Order 的强制 BSP 屏障（所有步骤互相等待）”，而不是“边（Edges）”本身有错。你删除了 `depends_on`，意味着木兰在这一层彻底丧失了构建“稀疏依赖树”的能力。
  - 如果大模型明确知道：“新建 User 表（A）”与“新建 Product 表（B）”毫无关联，但“更新 User API（C）”依赖 A，“更新 Product API（D）”依赖 B。
  - 在真正的 DAG 中，C 可以和 B 并行，D 可以和 A 并行。而在你的退化版本中，C 和 D 必须死等 A 和 B 所在批次（Order）全部执行完。这就失去了大模型“自主声明资源依赖”的智能优势，让系统倒退回了硬编码的线性批处理时代。

#### 2. 新文件悖论（The New File Paradox）：A3 连通性检查的逻辑盲区

- **事实审查**：在 `atomicity_check.py` 中，你引入了先进的 Track A（代码图谱连通性检查）。代码读取 `code_graph.json`，如果文件不连通则发出警告。
- **工程批判**：大模型执行 EP 的核心目的是**“写新代码”**。如果 `DagUnit` 中声明了一个即将创建的新文件（如 `backend/app/domain/new_entity.py`），这个文件在当前项目的 `code_graph.json` 快照中是**绝对不存在的**。
此时，`_are_files_connected` 算法会将这个新文件直接判定为“孤立节点（Isolated）”，从而无差别地触发 A3 警告。这会导致开发者或系统频繁收到虚假的架构割裂告警（False Positives），最终产生“狼来了”效应，彻底忽视 A3 检查。

#### 3. CBO 与反馈存储的物理强耦合（Tight Coupling in CBO）

- **事实审查**：在 `aiu_cost_estimator.py` 第 127 行，`get_historical_success_rate` 直接硬导入了 `from mms.dag.aiu_feedback import get_feedback_store`。
- **工程批判**：这违背了依赖倒置原则（DIP）。代价估算器（CBO）是一个纯粹的数学计算模型，它不应该直接感知底层磁盘和文件锁（`aiu_feedback`）。这种强耦合导致你无法在测试中轻松 Mock 历史成功率，也阻碍了未来将统计信息替换为 Redis 或云端服务的可能。

---

### 二、 优化建议与落地指南

#### 1. 恢复“稀疏 DAG”能力，保留大模型的心智

- **实施建议**：
在 `task_decomposer.py` 中，区分 RBO 和 LLM 的依赖处理：
  - **对于 RBO**：由于规则是预设的，可以继续将 `depends_on` 置空，依赖 `exec_order`。
  - **对于 LLM 兜底分解**：恢复解析大模型返回的 `depends_on` 字段，并在校验其无环（Acyclic）后予以保留。
  - 让 `DagUnit.is_executable()` 真正发挥图计算的作用，只要前置 `depends_on` 节点完成，该节点即可被 `BatchRunner` 选中执行，打破僵化的 Order 屏障。

#### 2. 修复“新文件悖论”：引入虚拟节点连通（Virtual Node Linking）

- **实施建议**：
修改 `atomicity_check.py` 中的 A3 连通性算法。
  - 在检测 `files` 列表时，区分“图谱中已有的旧文件”和“图谱中没有的新文件”。
  - 如果是一个新文件，**降级判定其目录路径**。如果新文件与旧文件同处于一个高内聚的目录（如都在 `backend/app/domain/` 下），则**隐式假设**它们连通。只有当旧文件在图中不连通，或新文件的目录也与其他文件毫无关联时，才抛出孤立警告。

#### 3. 依赖注入解耦 CBO

- **实施建议**：
在 `aiu_cost_estimator.py` 的 `AIUCostEstimator` 初始化方法中，注入一个接口 `success_rate_provider: Callable[[str], float] = None`。如果不传，再 fallback 到读取 `get_feedback_store`。这将使得阶段性的纯函数 TDD 成为可能。

---

### 三、 DAG 层 TDD 测试实施蓝图 (Cursor 专用)

与 `workflow` 层的宏观组装不同，`dag` 层是高密度的算法与数据结构集合。以下是针对 `dag` 层的 **TDD 四阶段测试计划**。请将此计划拖入 Cursor，作为开发规范严格执行。

#### 阶段一：纯粹的数学与算法底座验证 (Deterministic Unit Tests)

**目标文件**：`tests/dag/test_cost_and_atomicity.py`
**工程目标**：不触发任何 LLM、不读写真实的 JSONL，用纯内存数据锁死估算与验证逻辑。

- **测试 1：CBO 毒性正反馈阻断验证**
  - **Mock**：传入 `success_rate_provider = lambda x: 0.1`（模拟成功率极低：10%）。
  - **执行**：调用 `AIUCostEstimator.estimate_step()`。
  - **硬性断言**：返回的 `token_budget` **不得超过**基础代价加上文件代价的 1.1 倍（证明 `history_factor` 上限 +10% 严格生效），并且 `model_hint` 必须被切换为 `capable`。
- **测试 2：A3 新文件连通性免责验证 (The New File Paradox Fix)**
  - **Mock**：在内存构造 `code_graph`：`A.py` 连通 `B.py`。
  - **执行**：测试 `check_a3_layer_consistency`，输入文件列表为 `[A.py, B.py, new_file.py]`。
  - **硬性断言**：结果必须返回 `passed=True, is_warning=False`，证明系统正确处理了未被索引的新文件，避免了误报。

#### 阶段二：OCP 注册表与 YAML 引擎验证 (Schema-Driven Tests)

**目标文件**：`tests/dag/test_aiu_registry_v2.py`
**工程目标**：验证 `aiu_registry.py` 是否能正确合并多层级配置，且不破坏现有 Enum 系统。

- **测试 3：动态 RBO 提取能力**
  - **Mock**：使用 `pytest` 的 `tmp_path` 创建一个伪造的 `schemas/aius/custom_rule.yaml`，包含一个自定义的 `K8S_ADD_SIDECAR` AIU 和 `rbo_triggers`。
  - **执行**：实例化 `AIURegistry` 并调用 `get_rbo_rules()`。
  - **硬性断言**：返回的 List 中必须包含 `K8S_ADD_SIDECAR` 对应的规则字典，且 `token_budget` 和 `keywords` 映射完全正确，证明 OCP 设计闭环。

#### 阶段三：并发 I/O 与衰减状态机验证 (Concurrency & Decay Tests)

**目标文件**：`tests/dag/test_feedback_store.py`
**工程目标**：这是对 `filelock` 跨进程安全和滑动窗口衰减算法的最严苛验证。

- **测试 4：滑动窗口 (Decay Window) 淘汰验证**
  - **执行**：将配置的 `_DECAY_WINDOW` mock 为 `5`。向 `AIUFeedbackStore` 的同一个 AIU 类型连续写入 `10` 条 `success=False` 记录，紧接着写入 `5` 条 `success=True` 记录。
  - **硬性断言**：调用 `store.query()`。断言该 AIU 的 `success_rate` 必须为 **1.0 (100%)**。这证明系统完美执行了基于窗口的“幽灵记忆淘汰”，没有被前 10 次的失败记录拖累。
- **测试 5：多线程/进程争用防碎裂测试**
  - **执行**：在测试用例中启动 5 个 Thread（或 Process），并发向同一个 `feedback_stats.jsonl` 调用 `record()` 各 100 次。
  - **硬性断言**：测试结束后，读取该 jsonl 文件，行数必须严格等于 500 行，且每一行都能被合法的 `json.loads()` 解析。这证明 `filelock` 的原子写入护城河坚不可摧。

#### 阶段四：LLM 编排与回退的 VCR 录制测试 (Probabilistic Tests)

**目标文件**：`tests/dag/test_task_decomposer_vcr.py`
**工程目标**：在不消耗真实 Token 的情况下，验证 LLM 兜底拆解（Phase 2）的能力。

- **测试 6：稀疏 DAG 依赖声明解析 (Sparse DAG Test)**
  - **执行**：使用 `pytest-vcr` 录制一次复杂的任务（如：“新建 User 表，并为其编写对应的查询接口”），提示词引导大模型输出包含 `depends_on` 的 JSON。
  - **硬性断言**：断网重放测试。解析出的 `AIUPlan` 中，路由接口步骤（Order 4）的 `depends_on` 列表中，必须精确包含 Schema 步骤（Order 1）的 `aiu_id`，而没有被系统强行置为空列表 `