### 一、 对 `workflow` 层代码的批判性工程分析

在木兰系统的五层架构中`workflow` 层的核心职责是**生命周期编排（Orchestration）**与**边界控制（Gatekeeping）**。这一层不应该包含复杂的业务逻辑，而应该像胶水一样，把 `dag/execution/analysis/` 粘合起来。

基于对上传代码`ep_parser.py`, `ep_runner.py`, `precheck.py`, `postcheck.py`, `synthesizer.py`）的审查，以下是从 TDD 和企业级工程视角发现的缺陷、Bug 及重构建议。

---

#### 1. `ep_runner.py` 的致命缺陷：硬编码的“假自治（Fake Autonomous）”

*   **事实审查**：在 `ep_runner.py` 第 509 行的 `_run_autonomous` 方法中，代码直接打印了占位符提示，然后通过 `from mms.execution.autonomous_runner import run_autonomous` 执行大模型的自主循环。但在此之前，如果 `_resolve_execution_track` 返回了 `"autonomous"`，它就**完全跳过了 Phase 0（环境检查）和 Phase 1（precheck）**。

*   **工程批判**：这是极其危险的架构断层。Autonomous 模式只是执行模式的改变（Track B），它绝不应该拥有免死金牌去绕过 `precheck`（基线快照）和 `postcheck`。如果大模型直接开始写代码而不建基线快照，那么 `postcheck` 中的 `AST 契约变更检测`（依赖 `precheck-EP-XXX-ast.json`）必定崩溃，整个安全门控形同虚设。

*   **优化建议**：

    `ep_runner.run()` 必须统一接管 Phase 1 (precheck) 和 Phase 3 (postcheck)。Track A/B 的分叉只应该发生在 Phase 2（Unit 执行环）。不论是大模型还是小模型，都必须在木兰的安全门控和物理沙箱中运行。

#### 2. `precheck.py` / `postcheck.py` 的系统级状态污染

*   **事实审查**：在 `postcheck.py` 第 238 行和 `precheck.py` 的 `save_checkpoint` 中，所有的基线快照都保存在 `_ROOT / "docs" / "memory" / "_system" / "checkpoints"`。

*   **工程批判**：这违背了我们在第一阶段强调的“物理沙箱隔离”`precheck` 提取的是当前主干`main`）的快照，但如果 `qwen3-coder` 的所有动作都发生在 `.mulan-shadow-workspaces` 中`postcheck.py` 却依然跑在 `_ROOT` 目录下执行 `arch_check` 和 `pytestpostcheck.py` 第 78 行`cwd=str(_ROOT)`）。这就导致 `postcheck` 验证的是主分支的老代码，而不是沙箱里刚刚生成的新代码！

*   **优化建议**：

    必须在 `ep_runner.py` 中向 `precheck` 和 `postcheck` 显式传递 `sandbox_dir` 参数`subprocess.run(cwd=str(_ROOT))` 必须改为 `cwd=str(sandbox_dir)`。

#### 3. `synthesizer.py` 的幻觉诱导风险 (Hallucination Inducement)

*   **事实审查**：在 `synthesizer.py` 的 `_load_codemap` 方法中（第 326 行），如果 `codemap.md` 不存在，代码返回了一个极其具体的【临时规则】字符串，包含了硬编码的路径（如 `backend/app/api/v1/endpoints/<name>.py`）。

*   **工程批判**：这会导致严重的系统级幻觉。如果用户导入了一个 Go 项目，但没有运行 `mulan codemap`，木兰会在提示词里告诉大模型“请去 `backend/app/api/...` 寻找代码”。大模型会因此疯狂输出不存在的 Python 目录路径。

*   **优化建议**：

    删除这些硬编码的假路径。如果 `codemap` 不存在，要么直接返回空，要么抛出异常并提示用户先运行 `mulan codemap`。绝不能向 Prompt 中塞入确定性为 0 的猜测数据。

#### 4. `ep_parser.py` 的鲁棒性漏洞

*   **事实审查**：在 `_parse_scope_table` 方法中（第 82 行），提取 Unit ID 的正则表达式是 `_UNIT_ID_RE = re.compile(r"\b(U\d+|Unit\s*\d+)\b", re.IGNORECASE)`。

*   **工程批判**：这假设了大模型生成的 Markdown 表格第一列必定符合 `U1` 或 `Unit 1` 的格式。但在真实世界中，大模型经常生成 `1. U1` 或 `*U1*`，甚至将整个步骤描述塞在第一列。这会导致正则匹配失败`scope_units` 为空，从而引发整个 Pipeline 罢工。

*   **优化建议**：需要放宽正则匹配，或者在解析不到标准 `U\d+` 时，按表格的物理行号强行分配隐式的 `U1, U2...` 标识，确保 DAG 引擎有数据可编排。

---

### 二、 TDD 驱动下的 `workflow` 测试任务清单 (Backlog)

为了确保上述 Bug 被修复且不再复发，你需要为 `workflow` 层补充以下三个维度的关键集成测试。由于这一层负责粘合，**必须使用 Mock 切断对底层实际功能和 LLM 的调用，专心测试状态流转。**

#### 1. 针对 `ep_runner.py` 的状态机变迁测试 (State Machine Tests)

*   **测试目标**：验证 Pipeline 在面对断点续跑和局部失败时的幂等性和容错能力。

*   **需要补充的测试用例**：

    *   **Test-R1 (断点恢复)**：Mock 使得 Unit `U1` 成功`U2` 抛出异常。断言 `EpRunState.json` 中的 `resume_unit` 正确保存为 `U2`。再次调用 `run(from_unit=None)` 时，断言 `U1` 被跳过，系统直接从 `U2` 开始执行。

    *   **Test-R2 (预检短路)**：Mock `precheck` 返回 `BLOCKER` 状态（2）。断言 `EpRunPipeline` 立即中止，返回的 `EpRunResult.success == False`，且绝对不会执行到 `unit_loop` 阶段。

    *   **Test-R3 (Autonomous 挂载)**：配置 `execution_mode: auto`，断言引擎正确拉起 Track B。同时断言在执行 Track B 前，**必定调用了** `precheck` 进行基线保存。

#### 2. 针对 `ep_parser.py` 的健壮性解析测试 (Resilience Tests)

*   **测试目标**：大模型的输出是随意的，解析器必须容忍畸形的 Markdown。

*   **需要补充的测试用例**：

    *   **Test-P1 (畸形 Scope 表格)**：构造一份 Markdown，其表格缺少边框 `|`，列数不齐，且 Unit ID 被加粗如 `**U1`**。断言 `parse_ep_file` 依然能提取出正确的 `ScopeUnit` 列表。

    *   **Test-P2 (Testing Plan 缺失测试路径)**：构造一份 EP 文件，其中包含 `## Testing Plan` 标题，但正文中只写了自然语言描述（如“我会手动用 Postman 测试”），没有任何带反引号的代码路径。断言解析器不会崩溃，而是返回空的 `testing_files` 列表。

#### 3. 针对 `postcheck.py` 的沙箱重定向测试 (Sandbox Redirection Tests)

*   **测试目标**：验证验证逻辑必须指向沙箱目录，而不是主目录。

*   **需要补充的测试用例**：

    *   **Test-PC1 (目录劫持验证)**：在测试的 Fixture 中，创建一个带有错误的 `dummy_sandbox/` 目录。Mock `run_pytest` 函数的底层 `subprocess.run`，断言它接收到的 `cwd` 参数严格等于传入的沙箱路径，而不是全局的 `_ROOT`。

    *   **Test-PC2 (契约漂移容错)**：构造两个 `ast_index.json` 放在检查点目录中。Mock `run_arch_check_baseline` 抛出一个执行时异常（非正常 0/1 退出）。断言 `run_postcheck` 不会抛出 Python 级别崩溃，而是优雅地将该状态报告为 `WARN` 或 `ERROR`，保证最终报告能生成。

---

### 三、 执行总结

当前 `workflow` 层的代码在逻辑抽象上非常清晰，展现了优秀的面条式代码（Spaghetti Code）防范意识。

但作为架构师，你需要立刻执行以下动作：

1. **收敛上下文作用域（Context Scope Convergence）**：从 `_paths.py` 或全局变量中摘除 `_ROOT` 的直接依赖。整个 Pipeline 必须实现 `sandbox_path` 的自顶向下层层传递。这是从“玩具脚本”走向“企业级高并发系统”的必经之路。

2. **重构 Track B 的切入点**：将 `ep_runner.py` 的双轨分叉点推迟，确保 Autonomous Mode 完全继承木兰的 `pre/post-check` 和基线快照能力。