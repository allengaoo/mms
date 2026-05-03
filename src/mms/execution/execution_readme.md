# 执行层 (Execution Layer)

## 1. 架构定位

执行层是木兰 (Mulan) 任务工程层 (Layer 1) 的“动作执行器”。它接收来自 DAG 层的 `DagUnit`，并在安全的沙箱环境中驱动大模型完成代码的生成、应用和验证。
执行层实现了“双轨执行引擎”（Track A 串行流水线和 Track B 自治循环），并提供了基于内存快照的轻量级沙箱隔离机制。

## 2. 核心概念

- **UnitRunner (Track A)**: 串行流水线执行器。它严格按照 DAG 的拓扑顺序，逐个执行 Unit。每个 Unit 的执行包含：组装上下文 -> 调用 LLM 生成代码 -> 应用 Diff -> 运行验证 -> 失败重试（3-Strike）。
- **AutonomousRunner (Track B)**: 大模型自治执行器。它不严格遵循 DAG 拆解，而是将大模型置于一个 ReAct 循环中，允许其自主调用工具（Tool-Calling）完成任务。
- **FileApplier**: 负责将 LLM 生成的代码变更（Diff 或全量替换）安全地应用到本地文件系统。
- **GitSandbox**: 轻量级沙箱。在修改文件前，为目标文件建立内存快照。如果代码验证失败，可以快速回滚，避免污染工作区。

## 3. 核心文件与方法签名

### `src/mms/execution/`

#### 1. `unit_runner.py` (Track A 执行器)
Track A 的核心流水线，负责单个 DAG 节点的完整生命周期。

- `class UnitRunner:`
  - `def run(self) -> RunResult`: 执行入口。包含重试循环（3-Strike）。
  - `def _build_context(self) -> str`: 构建 LLM 所需的极度压缩上下文。
  - `def _generate_code(self) -> AiuOutputCarry`: 调用代码生成层（Layer 3）。
  - `def _apply_and_verify(self) -> Tuple[bool, str]`: 应用代码并运行验证（AST 检查、Pytest）。

#### 2. `autonomous_runner.py` (Track B 执行器)
Track B 的自治循环，基于 ReAct 模式。

- `def run_autonomous(ep_id: str, model: str, dry_run: bool, ...) -> AutonomousResult`: 启动自治循环。
- 内部实现了 `MaxTurnsExceededError` 安全边界，防止大模型陷入死循环。

#### 3. `file_applier.py` (文件应用器)
将代码变更安全地写入文件系统。

- `class FileApplier:`
  - `def apply(self, changes: List[FileChange], sandbox: Optional[GitSandbox] = None) -> ApplyResult`: 应用一组文件变更。
  - 支持 AST 级别的 Diff 合并和正则替换。

#### 4. `sandbox.py` (轻量级内存沙箱)
提供基于内存快照的回滚机制，不依赖 `git stash`，避免影响用户其他未提交的代码。

- `class GitSandbox:`
  - `def snapshot(self) -> None`: 为声明的文件建立内存快照。
  - `def rollback(self) -> None`: 恢复文件到快照状态，并删除期间新建的文件。
  - `def commit(self, message: str) -> str`: 验证通过后，将变更真正提交到 Git。

#### 5. `sandboxed_runner.py` (隔离执行器 - Phase 4)
未来规划的完整物理沙箱执行器。当前提供轻量级的语法检查和超时控制。

- `class SandboxedCodeRunner:`
  - `def run(self, code: str, file_path: str, test_script: str) -> RunResult`: 在受限环境中运行代码和测试。

## 4. 3-Strike 回退机制 (Track A)

在 `UnitRunner` 中，如果大模型生成的代码在应用或验证阶段失败（例如：语法错误、测试不通过），系统不会立即报错退出，而是会触发重试机制：
1. **Strike 1**: 收集错误日志（如 Pytest 报错信息）。
2. **Strike 2**: 将错误日志作为额外上下文，要求大模型修复代码。
3. **Strike 3**: 再次尝试。如果连续 3 次失败，则标记该 Unit 为 `failed`，并触发沙箱回滚，Pipeline 暂停。