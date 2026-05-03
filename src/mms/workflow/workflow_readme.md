# 任务工程层 (Task Engineering Layer)

## 1. 架构定位
任务工程层位于木兰 (Mulan) AIOS 架构的 **Layer 1**。它是整个 AI 编码工具链的大脑和中枢神经，负责将自然语言描述的、模糊的业务需求，转化为机器可执行的、确定性的原子操作序列，并最终驱动底层大模型完成代码变更。

本层**不直接**与大模型交互生成代码，也**不直接**解析代码 AST。它通过调用 **Layer 2 (知识本体层)** 获取架构上下文，调用 **Layer 3 (代码生成层)** 执行具体的编码任务，并依赖 **Layer 4 (安全验证层)** 进行质量门控。

## 2. 核心概念

*   **EP (Execution Plan, 执行计划)**：
    *   任务的最高层级抽象。一个 EP 对应一个完整的用户需求（如“新增批量导出 API”）。
    *   EP 以 Markdown 格式存储在 `docs/memory/private/EP-NNN/` 中，包含任务描述、架构约束、验收标准等。
*   **DAG (Directed Acyclic Graph, 有向无环图)**：
    *   EP 被分解后的数据结构。将复杂的 EP 拆解为具有依赖关系的多个子任务节点。
*   **AIU (Atomic Intent Unit, 原子意图单元)**：
    *   DAG 中的最小执行节点。它是高度结构化的、不可再分的编码动作（如 `SCHEMA_ADD_FIELD`, `ENDPOINT_ADD`）。
    *   木兰预定义了 9 族 43 种 AIU 类型，每种类型都有严格的输入输出 Schema 和验证规则。

## 3. 双轨执行引擎 (Capability Router)

为了兼顾执行效率与大模型能力的差异，任务工程层设计了“双轨执行”架构，由 `ep_runner.py` 中的 Capability Router 动态路由：

*   **Track A: UnitRunner 串行流水线 (Pipeline Mode)**
    *   **适用场景**：能力较弱但速度快、成本低的小模型（如 `qwen3-coder-plus`）。
    *   **机制**：高度确定性的流水线。`task_decomposer` 将 EP 拆解为严格的 DAG，`unit_runner` 按照拓扑排序逐个执行 AIU。每个 AIU 执行前组装极度压缩的上下文，执行后进行严格的独立验证（3-Strike 回退机制）。
    *   **特点**：低智商模型的高可靠性保障。
*   **Track B: Autonomous ReAct 循环 (Autonomous Mode)**
    *   **适用场景**：具备强大推理和 Tool-Calling 能力的顶级大模型（如 `claude-opus-4`, `qwen3-32b`）。
    *   **机制**：大模型自治。系统仅提供顶层 EP 描述和一组标准化工具（`ToolRegistry`），大模型在沙盒中自主决定调用哪些工具（如查本体、看 AST、跑测试），直到任务完成 (`tool_finish`)。
    *   **特点**：高智商模型的高自由度探索，受限于 `max_turns` 和 `token_budget` 安全边界。

## 4. 目录与模块映射

任务工程层横跨三个核心目录：

### `src/mms/workflow/` (生命周期编排)
*   `synthesizer.py`: 意图合成器。将用户的一句话需求，结合模板，扩充为结构化的 EP Markdown 文件。
*   `ep_parser.py`: EP 解析器。将 EP Markdown 文件解析为内存中的 `DagState` 对象。
*   `ep_runner.py`: **核心引擎**。全自动 Pipeline 编排，包含 Capability Router，负责触发 precheck、路由到 Track A/B、以及触发 postcheck。
*   `precheck.py`: 前置基线检查。在生成代码前，快照当前 AST，并进行初步的架构合规性检查。
*   `postcheck.py`: 后置质量门。在代码生成后，运行全局测试 (`pytest`)、架构约束 (`arch_check`) 和 DB 迁移门控 (`migration_gate`)。

### `src/mms/dag/` (任务分解与模型)
*   `aiu_types.py` / `aiu_registry.py`: AIU 类型体系的定义与动态注册表。
*   `dag_model.py`: `DagUnit` 和 `DagState` 的数据模型定义。
*   `task_decomposer.py`: 核心分解器。调用 LLM 将 EP 描述拆解为符合依赖关系的 AIU 序列 (DAG)。
*   `aiu_cost_estimator.py`: CBO (Cost-Based Optimizer) 代价估算，预测 AIU 执行的 token 消耗。
*   `aiu_feedback.py`: 3 级回退机制（扩预算 → 插前置 → 拆分），处理 AIU 执行失败的情况。
*   `atomicity_check.py`: 评估切分出的 Unit 是否足够“原子化”。

### `src/mms/execution/` (底层执行引擎)
*   `unit_runner.py`: Track A 的执行器。负责单个 Unit 的上下文组装、LLM 调用、Diff 应用和验证回滚。
*   `autonomous_runner.py`: Track B 的执行器。实现 ReAct 循环。
*   `unit_generate.py`: 驱动 `task_decomposer` 生成 DAG。
*   `unit_context.py`: 为 Track A 组装单 Unit 的极度压缩上下文。
*   `file_applier.py`: 解析 LLM 输出的 `BEGIN/END-CHANGES` 块，并安全地应用到本地文件。
*   `sandbox.py` / `sandboxed_runner.py`: 基于 Git 的工作区隔离与自动回滚机制。
*   `internal_reviewer.py`: 双角色内部评审机制（Feature Flag 控制）。

## 5. 自动化执行理念
本层设计遵循**“确定性约束下的全自动执行”**原则。
从 `mulan ep run` 启动开始，系统将自动完成前置检查、路由、分解、生成、验证、后置检查的全流程，期间**不需要任何人工交互确认**。人工干预仅发生在任务结束后的代码 Review 阶段。
