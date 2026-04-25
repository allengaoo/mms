"""
sandboxed_runner.py — 沙箱代码执行器（Phase 4 新增）

在 GitSandbox 隔离环境中运行 LLM 生成的代码并执行 pytest，
记录 syntax_pass 和 pytest_pass（Pass@1）指标。

设计约束：
  - 不修改主分支任何文件
  - 所有执行在 tmp worktree 中完成，执行后自动清理
  - syntax 检查仅用 ast.parse（Python），不执行代码
  - pytest 执行有超时限制（默认 60s）
  - 非 Python 语言：syntax_pass 仅检查非空，pytest_pass 始终 None

使用方式：
    from mms.execution.sandboxed_runner import SandboxedCodeRunner
    runner = SandboxedCodeRunner()
    result = runner.run(
        code="def add(a, b): return a + b",
        file_path="src/utils.py",
        test_script="def test_add():\n    assert add(1, 2) == 3",
    )
    print(result.syntax_pass, result.pytest_pass)
"""
from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parents[3]  # src/mms/execution/ → project root


@dataclass
class RunResult:
    """单次沙箱执行结果"""
    syntax_pass:    Optional[bool] = None   # 语法无报错
    pytest_pass:    Optional[bool] = None   # pytest 通过（Pass@1）
    syntax_error:   str            = ""
    pytest_output:  str            = ""
    latency_ms:     float          = 0.0

    @property
    def pass_at_1(self) -> bool:
        """Pass@1 = pytest 通过（None 视为未运行）"""
        return self.pytest_pass is True


class SandboxedCodeRunner:
    """
    沙箱代码执行器。

    对每个 LLM 生成的代码片段：
      1. 语法检查（ast.parse，Python only）
      2. 写入临时目录
      3. 运行附带的 pytest 测试脚本（如有）
      4. 返回 RunResult

    注意：此实现为轻量版，不依赖 GitSandbox（避免对 git 的强依赖）。
    未来可升级为完整 GitSandbox worktree 隔离（Phase 4 完整版）。
    """

    def __init__(self, timeout_seconds: int = 60) -> None:
        self._timeout = timeout_seconds

    def check_syntax(self, code: str, file_path: str) -> tuple[bool, str]:
        """
        对 Python 代码执行语法检查。
        非 Python 文件直接返回 (True, "")（无法离线检查）。
        """
        if not file_path.endswith(".py"):
            return True, ""
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"SyntaxError at line {e.lineno}: {e.msg}"

    def run_pytest(
        self,
        code: str,
        file_path: str,
        test_script: Optional[str] = None,
    ) -> tuple[Optional[bool], str]:
        """
        在临时目录中写入代码和测试脚本，运行 pytest。

        Returns:
            (pass: Optional[bool], output: str)
            pass = None 时表示 test_script 为空，未运行测试
        """
        if not test_script:
            return None, "(未提供测试脚本)"

        with tempfile.TemporaryDirectory(prefix="mulan_sandbox_") as tmp:
            tmp_path = Path(tmp)

            # 写入被测代码
            target_file = tmp_path / Path(file_path).name
            target_file.write_text(code, encoding="utf-8")

            # 写入测试脚本
            test_file = tmp_path / "test_generated.py"
            # 确保测试脚本能 import 目标模块
            module_name = Path(file_path).stem
            test_content = f"import sys\nsys.path.insert(0, str(__file__).rsplit('/', 1)[0])\n"
            test_content += f"from {module_name} import *  # noqa\n\n"
            test_content += test_script
            test_file.write_text(test_content, encoding="utf-8")

            # 运行 pytest
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", str(test_file), "-x", "-q", "--tb=short"],
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    cwd=tmp,
                )
                passed = result.returncode == 0
                output = (result.stdout + result.stderr)[:2000]
                return passed, output
            except subprocess.TimeoutExpired:
                return False, f"pytest 超时（>{self._timeout}s）"
            except Exception as e:
                return False, f"pytest 执行异常: {e}"

    def run(
        self,
        code: str,
        file_path: str,
        test_script: Optional[str] = None,
    ) -> RunResult:
        """
        完整沙箱执行：语法检查 → pytest。

        Args:
            code:        LLM 生成的源代码
            file_path:   目标文件路径（用于确定语言和模块名）
            test_script: pytest 测试脚本内容（无 import，直接写测试函数）

        Returns:
            RunResult 包含 syntax_pass, pytest_pass, 输出文本
        """
        import time
        t0 = time.monotonic()

        # 1. 语法检查
        syntax_ok, syntax_err = self.check_syntax(code, file_path)

        # 2. 如语法失败，直接返回（不运行 pytest）
        if not syntax_ok:
            return RunResult(
                syntax_pass=False,
                pytest_pass=False,
                syntax_error=syntax_err,
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        # 3. 运行 pytest
        pytest_pass, pytest_output = self.run_pytest(code, file_path, test_script)

        return RunResult(
            syntax_pass=True,
            pytest_pass=pytest_pass,
            syntax_error="",
            pytest_output=pytest_output,
            latency_ms=(time.monotonic() - t0) * 1000,
        )
