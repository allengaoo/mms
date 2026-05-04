



基于对 `execution` 层（执行层）源码及 README 文件的深度静态分析，站在企业级工程标准与架构防御（Defensive Architecture）的立场，我发现当前实现虽然在逻辑分层上非常清晰（如双轨执行、沙箱与应用器分离），但**底层代码中埋藏着一个足以导致企业级代码库灾难的毁灭性 Bug**，以及在**大模型协议层（MCP）和测试流转上的严重脆弱性**。

以下是去客套话的批判性工程审查报告、代码级缺陷定位以及对应的 TDD 优化演进蓝图。

---

### 一、 批判性工程缺陷定位 (Critical Flaws Analysis)

#### 1. 毁灭性的沙箱逃逸与主干污染 Bug (`sandbox.py`)
*   **事实审查**：在 `sandbox.py` 中，你定义了 `GitSandbox` 类来提供文件级别的内存快照，README 宣称它“不使用 git stash（避免影响用户未提交的变更）”。但在第 89 行 `commit` 方法中，代码赫然写着：
    ```python
    subprocess.run(["git", "add", "-A"], cwd=str(self.root), ...)
    ```
*   **工程批判**：这是不可饶恕的工程灾难。`git add -A` 会将当前项目根目录（`_ROOT`）下**所有**未追踪（Untracked）和修改过的文件全部添加到暂存区并提交。
    如果开发者正在工作区中调试其他代码（甚至包含临时的密码、API Key 或是测试脏数据），当后端的木兰智能体悄悄完成一个 Unit 并执行 `commit()` 时，开发者的所有临时修改将被强行打包进名为 `EP-XXX U1: ...` 的 Commit 中。这直接破坏了 README 中承诺的“仅快照 unit.files 声明的文件”。
*   **修复指令**：立即废弃 `git add -A`。只能针对 `self.files` 和 `self._new_files` 进行精准 add：
    ```python
    subprocess.run(["git", "add", "--"] + self.files + self._new_files, cwd=str(self.root))
    ```

#### 2. Track B 自治循环（ReAct）的“沉默吞异常”漏洞 (`autonomous_runner.py`)
*   **事实审查**：在 `autonomous_runner.py` 第 183-186 行解析 Tool 调用参数时：
    ```python
    try:
        tool_args = json.loads(tool_args_str)
    except json.JSONDecodeError:
        tool_args = {}
    ```
*   **工程批判**：这是与大模型（LLM）交互时最典型的反模式（Anti-pattern）。如果 GPT-4o 或 Qwen3 输出的工具参数 JSON 格式损坏（如少了个引号），你的系统将异常静默吞没，并强制传一个空字典 `{}` 给底层工具。底层工具会因为缺少必填参数抛出 Python 的 `TypeError`。大模型无法知道是自己的 JSON 写错了，只会看到系统内部报错，从而陷入无意义的幻觉推理（Hallucination Loop）。
*   **修复指令**：必须将 JSON 解析错误**作为 Observation** 直接退回给大模型，强制其修正。
    ```python
    except json.JSONDecodeError as e:
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": f"JSON解析失败，请修复格式: {e}"})
        continue # 直接进入下一轮让 LLM 修正
    ```

#### 3. 语法预验证的“假安全”（False Sense of Security）
*   **事实审查**：在 `file_applier.py` 中，`_validate_python_syntax` 仅使用了 `ast.parse(content)` 来验证代码。
*   **工程批判**：`ast.parse` 只能拦截最低级的缩进和语法符号错误（SyntaxError）。但 LLM 最常犯的错误是**幻觉导入（Hallucinated Imports）**和**未定义变量（Undefined Variables）**。一个包含 `from not_exist import magic` 的文件能完美通过 `ast.parse`，然后写入磁盘，直到漫长的 `pytest` 或 `arch_check` 阶段才暴露。这白白浪费了 3-Strike 循环中宝贵的时间。
*   **修复指令**：在 `file_applier.py` 写入内存前，集成轻量级的 `pyflakes` 或 `ruff` 纯静态 API 调用。它们同样不需要运行环境，耗时 <50ms，但能拦截 90% 的未定义变量和幽灵导入。

#### 4. “内部评审”带来的双盲互斥风险 (`internal_reviewer.py`)
*   **事实审查**：`internal_reviewer.py` 通过让 `qwen3-32b` 审查代码，如果发现违规直接打回。
*   **工程批判**：这是一种“无仲裁者的对抗网络”。LLM-1 (Coder) 根据上下文写了代码，LLM-2 (Reviewer) 根据相同的上下文认为违规。由于没有编译器或真实沙箱报错作为“物理仲裁”，系统容易陷入“互相抬杠”的死循环。
*   **优化建议**：内部评审不应该仅看 Diff，必须配合静态代码扫描。只有当大模型的审查意见与静态扫描工具（如 Pylint 警告）交叉验证一致时，才允许打回重写。建议将此功能继续保持在 Feature Flag `False` 状态，除非引入了严格的语法树校验作为仲裁。

---

### 二、 TDD 驱动的 Execution 层测试实施蓝图

`execution` 层包含大量的 I/O 操作和极其复杂的 LLM 交互流程。为了隔离外部依赖并建立护城河，你需要立即在 `tests/execution/` 中落地以下 TDD 验证计划：

#### 阶段一：锁死物理层的文件操作边界 (Deterministic I/O Testing)
**目标模块**：`sandbox.py`, `file_applier.py`
**测试策略**：在没有 LLM 参与的情况下，用内存字符串和 Pytest 的 `tmp_path` 验证文件应用器的底线。

1.  **测试 1：GitSandbox 污染防御测试**
    *   **操作**：在 `tmp_path` 初始化一个 git 仓库，放入 `A.py` 和 `B.py`。使用 `GitSandbox(["A.py"])`。修改 `A.py` 和 `B.py`。调用 `sandbox.commit()`。
    *   **硬性断言**：运行 `git status`，断言 `B.py` 必须仍然处于 "modified (unstaged)" 状态，绝对不能被 Commit 包含。
2.  **测试 2：FileApplier 的 Scope Guard 拦截测试**
    *   **操作**：手动构造一份恶意的 LLM 输出：
        ```text
        ===BEGIN-CHANGES===
        FILE: /etc/passwd
        ACTION: replace
        CONTENT: hacked
        ===END-FILE===
        ===END-CHANGES===
        ```
    *   **硬性断言**：当 `allowed_files=["src/main.py"]` 时，调用 `parse_and_validate`。必须抛出 `ScopeViolationError`，且磁盘上绝不能出现被覆盖的文件。

#### 阶段二：自治循环（Track B）的边界异常对抗测试
**目标模块**：`autonomous_runner.py`
**测试策略**：通过 `pytest-vcr` 拦截 LLM 的 HTTP 请求，向系统喂入各种变态的（Adversarial）工具调用响应。

1.  **测试 3：JSONDecodeError 的自主修复测试**
    *   **操作**：录制一段 LLM 响应，手动篡改卡带，使 `tool_calls` 中的 `arguments` 为 `{"keyword": "auth",}`（尾部多逗号，非法 JSON）。
    *   **硬性断言**：断言 Runner 捕获该错误，并将包含“JSON 解析失败”的观测结果 `role: tool` 退回给 LLM；同时断言在下一轮（Turn 2）中，系统的 `messages` 数组正确包含了这个退回的报错节点，证明系统具备自我纠错能力。
2.  **测试 4：工具链越权与超时阻断测试**
    *   **操作**：设置 Runner 的 `timeout_s=2`。Mock `BailianProvider` 让其响应 `sleep(3)`。
    *   **硬性断言**：断言循环在第一轮强制终止，返回的 `finish_reason` 必须是 `timeout`，而非抛出不受控的异常导致木兰主进程崩溃。

#### 阶段三：执行引擎（Track A）状态机幂等测试
**目标模块**：`unit_runner.py`
**测试策略**：验证 `3-Strike` 回退机制的确定性流转。

1.  **测试 5：Level 1 Token 扩充回退测试**
    *   **操作**：Mock `_run_arch_check` 始终返回 `(False, "AC-1: Controller 违规")`。
    *   **硬性断言**：
        1. 断言 `UnitRunner` 精确发起了 3 次大模型重试调用。
        2. 断言在重试过程中，传入的 Prompt 中包含了上一次失败的 `error_msg` 上下文。
        3. 断言 3 次失败后，返回的 `RunResult.success` 为 `False`，并且正确调用了 `_record_aiu_feedback` 向 CBO 系统上报失败记录。

---

### 三、 总结与立刻执行的重构令

`execution` 层目前的架构抽象（将文件解析、沙箱隔离、大模型循环分离）设计得很漂亮，但正如前面分析的那样，由于 `git add -A` 这种“图省事”的底层 API 滥用，整个大厦的基础是极其脆弱的。

**请立即在 Cursor 中执行以下重构指令：**

1.  `@src/mms/execution/sandbox.py` 找到 `commit` 方法。将 `subprocess.run(["git", "add", "-A"])` 替换为精确匹配列表 `self.files + self._new_files`。
2.  `@src/mms/execution/autonomous_runner.py` 找到工具参数解析逻辑。捕获 `json.JSONDecodeError` 后，停止向下传递空字典 `{}`，而是将包含错误堆栈的消息追加至 `messages` 列表，强制进入下一个 `Turn`。
3.  创建 `tests/execution/test_sandbox.py`，严格按照上文“测试 1”和“测试 2”的要求，用 TDD 手法保证沙箱再也无法越权修改系统文件。