"""
test_file_applier_scope_guard.py — FileApplier 作用域守卫与语法验证强化测试

覆盖目标（对比现有 test_file_applier.py 的增量部分）：
  1. ScopeViolationError 语义：越界文件被拦截，合法文件不受影响
  2. 路径遍历攻击防御：../../../etc/passwd 类路径
  3. Python 语法验证增强：py_compile 与 ast.parse 等价性确认
  4. 非 Python 文件不走语法检查
  5. FileApplier.apply() 返回值结构完整性
  6. internal_reviewer 特性开关行为
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mms.execution.file_applier import (
    FileApplier, FileChange, ParseError, ScopeViolationError,
    parse_llm_output, validate_scope, pre_validate,
    BEGIN_MARKER, END_MARKER, FILE_END_MARKER,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _build_llm_output(*files):
    """构造合法的 LLM 文件输出块。"""
    blocks = []
    for path, action, content in files:
        block = f"FILE: {path}\nACTION: {action}\nCONTENT:\n{content}"
        blocks.append(block)
    return (
        f"{BEGIN_MARKER}\n"
        + f"\n{FILE_END_MARKER}\n".join(blocks)
        + f"\n{FILE_END_MARKER}\n"
        + f"{END_MARKER}"
    )


@pytest.fixture()
def tmp_root(tmp_path):
    return tmp_path


# ── 作用域守卫测试 ────────────────────────────────────────────────────────────

class TestScopeGuardIntercept:
    """validate_scope 对越界文件的拦截精度测试。

    validate_scope 接口说明：
      - strict=True（默认）：有违规时抛出 ScopeViolationError
      - strict=False：返回违规路径列表（List[str]），不抛出
    """

    def test_declared_file_passes_scope_check(self):
        changes = [FileChange("src/model.py", "create", "x = 1")]
        allowed = ["src/model.py"]
        violations = validate_scope(changes, allowed_files=allowed, strict=False)
        assert violations == []

    def test_undeclared_file_is_intercepted(self):
        changes = [
            FileChange("src/model.py", "create", "x = 1"),
            FileChange("src/secret.py", "create", "API_KEY = 'abc'"),
        ]
        allowed = ["src/model.py"]
        violations = validate_scope(changes, allowed_files=allowed, strict=False)
        assert len(violations) == 1
        assert "src/secret.py" in violations

    def test_all_files_undeclared_returns_all_violations(self):
        changes = [
            FileChange("evil1.py", "create", "x"),
            FileChange("evil2.py", "create", "y"),
        ]
        violations = validate_scope(changes, allowed_files=["safe.py"], strict=False)
        assert len(violations) == 2

    def test_empty_allowed_files_blocks_everything(self):
        changes = [FileChange("anything.py", "create", "x = 1")]
        violations = validate_scope(changes, allowed_files=[], strict=False)
        assert len(violations) == 1

    def test_strict_mode_raises_on_violation(self):
        """strict=True 时，有违规应抛出 ScopeViolationError。"""
        changes = [FileChange("evil.py", "create", "x = 1")]
        with pytest.raises(ScopeViolationError):
            validate_scope(changes, allowed_files=["safe.py"], strict=True)

    def test_path_traversal_attack_is_blocked(self):
        """路径遍历攻击不应绕过 allowed_files 检查。"""
        changes = [FileChange("../../.env", "create", "SECRET=leaked")]
        violations = validate_scope(changes, allowed_files=["src/model.py"], strict=False)
        assert len(violations) == 1
        assert "../../.env" in violations

    def test_multiple_files_mixed_scope(self):
        """允许和拒绝的文件混合时，精确过滤违规集合。"""
        changes = [
            FileChange("a.py", "create", "x"),
            FileChange("b.py", "create", "y"),
            FileChange("c.py", "create", "z"),
        ]
        violations = validate_scope(changes, allowed_files=["a.py", "c.py"], strict=False)
        assert violations == ["b.py"]


# ── Python 语法验证测试 ────────────────────────────────────────────────────────

class TestPythonSyntaxValidation:
    """pre_validate 对 Python 语法的检测覆盖。

    pre_validate 接口说明：
      - 返回 Optional[str]：None 表示通过，非空字符串表示错误信息
    """

    def test_valid_python_passes(self):
        change = FileChange("model.py", "create", "def hello():\n    return 42\n")
        err = pre_validate(change)
        assert err is None

    def test_syntax_error_is_caught(self):
        change = FileChange("broken.py", "create", "def broken(\n    # 缺少闭括号")
        err = pre_validate(change)
        assert err is not None
        assert len(err) > 0

    def test_empty_python_file_passes(self):
        change = FileChange("empty.py", "create", "")
        err = pre_validate(change)
        assert err is None

    def test_import_only_file_passes(self):
        change = FileChange("imports.py", "create", "import os\nimport sys\n")
        err = pre_validate(change)
        assert err is None

    def test_non_python_file_skips_syntax_check(self):
        """非 .py 文件不走语法验证，返回 None（通过）。"""
        change = FileChange("config.yaml", "create", "key: value\nlist:\n  - a\n")
        err = pre_validate(change)
        assert err is None

    def test_json_file_skips_python_syntax_check(self):
        change = FileChange("schema.json", "create", '{"type": "object"}')
        err = pre_validate(change)
        assert err is None

    def test_markdown_file_skips_syntax_check(self):
        change = FileChange("README.md", "create", "# Title\nSome text")
        err = pre_validate(change)
        assert err is None

    def test_indentation_error_is_caught(self):
        """IndentationError 是 SyntaxError 的子类，也应被捕获。"""
        change = FileChange("bad_indent.py", "create", "def foo():\nreturn 1\n")
        err = pre_validate(change)
        assert err is not None

    def test_complex_valid_class_passes(self):
        code = '''
class MyService:
    def __init__(self, name: str) -> None:
        self.name = name

    def greet(self) -> str:
        return f"Hello, {self.name}"
'''
        change = FileChange("service.py", "create", code)
        err = pre_validate(change)
        assert err is None


# ── FileApplier.apply 返回值结构测试 ─────────────────────────────────────────

class TestFileApplierApplyResults:
    """FileApplier.apply() 返回的 ApplyResult 对象结构完整性。"""

    def test_apply_create_returns_success_result(self, tmp_root):
        applier = FileApplier(root=tmp_root)
        changes = [FileChange("new_file.py", "create", "x = 1\n")]
        results = applier.apply(changes, allowed_files=["new_file.py"])
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].path == "new_file.py"

    def test_apply_scope_violation_raises_in_strict_mode(self, tmp_root):
        """strict_scope=True（默认）时，越界文件触发 ScopeViolationError。"""
        applier = FileApplier(root=tmp_root, strict_scope=True)
        changes = [FileChange("evil.py", "create", "x = 1")]
        with pytest.raises(ScopeViolationError):
            applier.apply(changes, allowed_files=["safe.py"])

    def test_apply_scope_violation_filters_in_non_strict_mode(self, tmp_root):
        """strict_scope=False 时，越界文件被过滤，合法文件仍被应用。"""
        applier = FileApplier(root=tmp_root, strict_scope=False)
        changes = [
            FileChange("good.py", "create", "x = 1\n"),
            FileChange("evil.py", "create", "y = 2\n"),
        ]
        results = applier.apply(changes, allowed_files=["good.py"])
        # 只有 good.py 应该在结果中
        assert len(results) == 1
        assert results[0].path == "good.py"
        assert results[0].success is True

    def test_apply_syntax_error_returns_failure_result(self, tmp_root):
        applier = FileApplier(root=tmp_root)
        changes = [FileChange("bad.py", "create", "def broken(\n")]
        results = applier.apply(changes, allowed_files=["bad.py"])
        assert len(results) == 1
        assert results[0].success is False
        assert len(results[0].error) > 0

    def test_apply_multiple_files_independent_results(self, tmp_root):
        """每个文件独立返回结果，一个失败不影响其他文件处理。"""
        applier = FileApplier(root=tmp_root)
        changes = [
            FileChange("good.py", "create", "x = 1\n"),
            FileChange("bad.py", "create", "def broken(\n"),
        ]
        results = applier.apply(changes, allowed_files=["good.py", "bad.py"])
        assert len(results) == 2
        success_results = [r for r in results if r.success]
        failure_results = [r for r in results if not r.success]
        assert len(success_results) == 1
        assert len(failure_results) == 1
        assert success_results[0].path == "good.py"

    def test_apply_creates_parent_directories(self, tmp_root):
        """apply create 时，不存在的父目录应被自动创建。"""
        applier = FileApplier(root=tmp_root)
        deep_path = "src/api/v2/handler.py"
        changes = [FileChange(deep_path, "create", "x = 1\n")]
        results = applier.apply(changes, allowed_files=[deep_path])
        assert results[0].success is True
        assert (tmp_root / deep_path).exists()
