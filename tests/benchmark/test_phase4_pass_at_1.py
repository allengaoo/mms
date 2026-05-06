"""
test_phase4_pass_at_1.py — Pass@1 闭环评测单元测试

覆盖：
  1. SandboxedCodeRunner：语法检查（正确/错误）
  2. SandboxedCodeRunner：pytest 执行（通过/失败/超时）
  3. TaskResult 新字段：source / syntax_pass / pytest_pass
  4. dual_rail 降级（LLM 不可用时返回 mock）
"""
from __future__ import annotations

import pytest
from mms.execution.sandboxed_runner import SandboxedCodeRunner, RunResult
from benchmark.v2.schema import TaskResult, TaskStatus
from benchmark.v2.layer2_memory.metrics.injection_lift import (
    InjectionLiftCase,
    mock_injection_lift_result,
)


# ── SandboxedCodeRunner 语法检查 ──────────────────────────────────────────────

class TestSyntaxCheck:
    def _runner(self) -> SandboxedCodeRunner:
        return SandboxedCodeRunner()

    def test_valid_python_passes(self):
        runner = self._runner()
        ok, err = runner.check_syntax("def add(a, b):\n    return a + b\n", "math_utils.py")
        assert ok is True
        assert err == ""

    def test_invalid_python_fails(self):
        runner = self._runner()
        ok, err = runner.check_syntax("def add(a, b)\n    return a + b\n", "bad.py")
        assert ok is False
        assert "SyntaxError" in err

    def test_non_python_always_passes(self):
        runner = self._runner()
        ok, err = runner.check_syntax("class Foo { void bar() {} }", "Foo.java")
        assert ok is True
        assert err == ""

    def test_empty_code_passes_syntax(self):
        runner = self._runner()
        ok, err = runner.check_syntax("", "empty.py")
        assert ok is True


# ── SandboxedCodeRunner pytest 执行 ──────────────────────────────────────────

class TestPytestExecution:
    def _runner(self) -> SandboxedCodeRunner:
        return SandboxedCodeRunner(timeout_seconds=30)

    def test_passing_test(self):
        runner = self._runner()
        code = "def add(a, b):\n    return a + b\n"
        test = "def test_add():\n    assert add(1, 2) == 3\n    assert add(-1, 1) == 0\n"
        result = runner.run(code=code, file_path="math_utils.py", test_script=test)
        assert result.syntax_pass is True
        assert result.pytest_pass is True
        assert result.pass_at_1 is True

    def test_failing_test(self):
        runner = self._runner()
        code = "def add(a, b):\n    return a - b  # bug!\n"
        test = "def test_add():\n    assert add(1, 2) == 3\n"
        result = runner.run(code=code, file_path="math_utils.py", test_script=test)
        assert result.syntax_pass is True
        assert result.pytest_pass is False
        assert result.pass_at_1 is False

    def test_no_test_script(self):
        runner = self._runner()
        code = "def foo():\n    pass\n"
        result = runner.run(code=code, file_path="foo.py", test_script=None)
        assert result.syntax_pass is True
        assert result.pytest_pass is None  # 未运行测试
        assert result.pass_at_1 is False   # None → False

    def test_syntax_error_skips_pytest(self):
        runner = self._runner()
        code = "def broken(\n    pass\n"
        test = "def test_it():\n    assert True\n"
        result = runner.run(code=code, file_path="broken.py", test_script=test)
        assert result.syntax_pass is False
        assert result.pytest_pass is False
        assert "SyntaxError" in result.syntax_error


# ── TaskResult 新字段测试 ─────────────────────────────────────────────────────

class TestTaskResultNewFields:
    def test_source_default(self):
        result = TaskResult(task_id="T-001", status=TaskStatus.PASSED)
        assert result.source == "human"

    def test_source_synthetic(self):
        result = TaskResult(task_id="T-002", status=TaskStatus.PASSED, source="synthetic")
        assert result.source == "synthetic"

    def test_syntax_pass_default_none(self):
        result = TaskResult(task_id="T-003", status=TaskStatus.PASSED)
        assert result.syntax_pass is None

    def test_pytest_pass_tracking(self):
        result = TaskResult(
            task_id="T-004",
            status=TaskStatus.PASSED,
            syntax_pass=True,
            pytest_pass=True,
        )
        assert result.syntax_pass is True
        assert result.pytest_pass is True


# ── injection_lift mock 降级测试 ─────────────────────────────────────────────

class TestInjectionLiftDegradation:
    def test_mock_result_when_no_llm(self):
        case = InjectionLiftCase(
            case_id="D2-001",
            description="测试 mock 降级",
            domain="generic_python",
            task_description="生成一个 fibonacci 函数",
            required_imports=["def fibonacci"],
        )
        result = mock_injection_lift_result(case)
        assert result.skipped is True
        assert result.case_id == "D2-001"
        assert "不可用" in result.skip_reason
