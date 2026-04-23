"""
test_file_applier.py — FileApplier 单元测试

覆盖：
  - parse_llm_output: 正常 / 多文件 / 无标记 / 不完整标记
  - validate_scope: strict/非 strict 模式
  - pre_validate: Python 语法 / YAML / JSON
  - FileApplier.apply: 成功写入 / scope 违规过滤 / 已存在文件 create 拒绝
  - parse_and_validate 组合函数
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from file_applier import (
    parse_llm_output, parse_and_validate,
    validate_scope, pre_validate,
    FileApplier, FileChange, ParseError, ScopeViolationError,
    BEGIN_MARKER, END_MARKER, FILE_END_MARKER,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_llm_output(*files):
    """
    构造合法的 LLM 输出。
    files: (path, action, content) 元组列表
    """
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


# ── parse_llm_output ──────────────────────────────────────────────────────────

class TestParseLlmOutput:

    def test_single_file_create(self):
        raw = _build_llm_output(
            ("backend/app/foo.py", "create", "# hello\nprint('world')\n")
        )
        changes = parse_llm_output(raw)
        assert len(changes) == 1
        assert changes[0].path == "backend/app/foo.py"
        assert changes[0].action == "create"
        assert "print" in changes[0].content

    def test_multiple_files(self):
        raw = _build_llm_output(
            ("a.py", "create", "x = 1"),
            ("b.py", "replace", "y = 2"),
        )
        changes = parse_llm_output(raw)
        assert len(changes) == 2
        paths = {c.path for c in changes}
        assert paths == {"a.py", "b.py"}

    def test_no_markers_returns_empty(self):
        changes = parse_llm_output("这是一段没有任何标记的普通文本")
        assert changes == []

    def test_missing_end_marker_raises(self):
        raw = f"{BEGIN_MARKER}\nFILE: x.py\nACTION: create\nCONTENT:\nx=1\n{FILE_END_MARKER}\n"
        with pytest.raises(ParseError, match="END.*标记缺失"):
            parse_llm_output(raw)

    def test_missing_begin_marker_raises(self):
        raw = f"FILE: x.py\nACTION: create\nCONTENT:\nx=1\n{FILE_END_MARKER}\n{END_MARKER}"
        with pytest.raises(ParseError, match="BEGIN.*标记缺失"):
            parse_llm_output(raw)

    def test_invalid_action_raises(self):
        raw = _build_llm_output(("x.py", "delete", "content"))
        with pytest.raises(ParseError, match="不支持的 ACTION"):
            parse_llm_output(raw)

    def test_strip_markdown_fences(self):
        """CONTENT 包裹 ``` 代码块时应自动去除"""
        raw = _build_llm_output(
            ("x.py", "create", "```python\nx = 1\n```")
        )
        changes = parse_llm_output(raw)
        assert "```" not in changes[0].content
        assert "x = 1" in changes[0].content

    def test_default_action_is_create(self):
        """无 ACTION 行时默认 create"""
        raw = (
            f"{BEGIN_MARKER}\n"
            f"FILE: foo.py\n"
            f"CONTENT:\nx=1\n"
            f"{FILE_END_MARKER}\n"
            f"{END_MARKER}"
        )
        changes = parse_llm_output(raw)
        assert len(changes) == 1
        assert changes[0].action == "create"


# ── validate_scope ────────────────────────────────────────────────────────────

class TestValidateScope:

    def _changes(self, *paths):
        return [FileChange(path=p, action="create", content="x") for p in paths]

    def test_all_in_scope(self):
        changes = self._changes("a.py", "b.py")
        violations = validate_scope(changes, ["a.py", "b.py"])
        assert violations == []

    def test_strict_violation_raises(self):
        changes = self._changes("a.py", "c.py")
        with pytest.raises(ScopeViolationError):
            validate_scope(changes, ["a.py"], strict=True)

    def test_non_strict_returns_violations(self):
        changes = self._changes("a.py", "c.py")
        violations = validate_scope(changes, ["a.py"], strict=False)
        assert violations == ["c.py"]

    def test_empty_allowed_blocks_all(self):
        changes = self._changes("x.py")
        violations = validate_scope(changes, [], strict=False)
        assert "x.py" in violations


# ── pre_validate ──────────────────────────────────────────────────────────────

class TestPreValidate:

    def test_valid_python(self):
        change = FileChange("x.py", "create", "x = 1\nprint(x)\n")
        assert pre_validate(change) is None

    def test_invalid_python(self):
        change = FileChange("x.py", "create", "def foo(\n")
        err = pre_validate(change)
        assert err is not None
        assert "Python 语法错误" in err

    def test_valid_json(self):
        change = FileChange("x.json", "create", '{"key": "value"}')
        assert pre_validate(change) is None

    def test_invalid_json(self):
        change = FileChange("x.json", "create", "{key: value}")
        err = pre_validate(change)
        assert err is not None
        assert "JSON 语法错误" in err

    def test_unknown_extension_passes(self):
        change = FileChange("x.tmpl", "create", "{{variable}}")
        assert pre_validate(change) is None

    def test_empty_ts_fails(self):
        change = FileChange("x.ts", "create", "   ")
        err = pre_validate(change)
        assert err is not None

    def test_nonempty_ts_passes(self):
        change = FileChange("x.ts", "create", "export const x = 1;")
        assert pre_validate(change) is None


# ── FileApplier.apply ─────────────────────────────────────────────────────────

class TestFileApplier:

    def test_apply_creates_file(self, tmp_path):
        applier = FileApplier(root=tmp_path)
        changes = [FileChange("new.py", "create", "x = 1\n")]
        results = applier.apply(changes, allowed_files=["new.py"])
        assert all(r.success for r in results)
        assert (tmp_path / "new.py").read_text() == "x = 1\n"

    def test_apply_replace_updates_file(self, tmp_path):
        f = tmp_path / "existing.py"
        f.write_text("old\n", encoding="utf-8")
        applier = FileApplier(root=tmp_path)
        changes = [FileChange("existing.py", "replace", "new\n")]
        results = applier.apply(changes, allowed_files=["existing.py"])
        assert results[0].success
        assert f.read_text() == "new\n"

    def test_apply_create_fails_if_exists(self, tmp_path):
        f = tmp_path / "existing.py"
        f.write_text("old\n", encoding="utf-8")
        applier = FileApplier(root=tmp_path)
        changes = [FileChange("existing.py", "create", "new\n")]
        results = applier.apply(changes, allowed_files=["existing.py"])
        assert not results[0].success
        assert "action=create 不允许覆盖" in results[0].error

    def test_apply_force_allows_create_overwrite(self, tmp_path):
        f = tmp_path / "existing.py"
        f.write_text("old\n", encoding="utf-8")
        applier = FileApplier(root=tmp_path)
        changes = [FileChange("existing.py", "create", "new\n")]
        results = applier.apply(changes, allowed_files=["existing.py"], force=True)
        assert results[0].success

    def test_apply_scope_violation_filtered_in_non_strict(self, tmp_path):
        """非 strict 模式：超范围文件被过滤，不应用"""
        applier = FileApplier(root=tmp_path, strict_scope=False)
        changes = [
            FileChange("allowed.py", "create", "x = 1\n"),
            FileChange("not_allowed.py", "create", "y = 2\n"),
        ]
        results = applier.apply(changes, allowed_files=["allowed.py"])
        # 只有 allowed.py 被应用
        assert len(results) == 1
        assert results[0].path == "allowed.py"
        assert not (tmp_path / "not_allowed.py").exists()

    def test_apply_creates_parent_dirs(self, tmp_path):
        applier = FileApplier(root=tmp_path)
        path = "a/b/c/new.py"
        changes = [FileChange(path, "create", "x = 1\n")]
        results = applier.apply(changes, allowed_files=[path])
        assert results[0].success
        assert (tmp_path / path).exists()

    def test_apply_syntax_error_fails(self, tmp_path):
        applier = FileApplier(root=tmp_path)
        changes = [FileChange("bad.py", "create", "def broken(\n")]
        results = applier.apply(changes, allowed_files=["bad.py"])
        assert not results[0].success
        assert "语法预验证失败" in results[0].error


# ── parse_and_validate ────────────────────────────────────────────────────────

class TestParseAndValidate:

    def test_valid_output(self):
        raw = _build_llm_output(("a.py", "create", "x = 1\n"))
        changes, errors = parse_and_validate(raw, allowed_files=["a.py"])
        assert len(changes) == 1
        assert errors == []

    def test_no_markers_returns_error(self):
        changes, errors = parse_and_validate("plain text", allowed_files=["a.py"])
        assert changes == []
        assert len(errors) == 1

    def test_scope_violation_reported(self):
        raw = _build_llm_output(
            ("a.py", "create", "x = 1"),
            ("evil.py", "create", "y = 2"),
        )
        changes, errors = parse_and_validate(raw, allowed_files=["a.py"])
        assert len(changes) == 1
        assert any("Scope Guard" in e for e in errors)

    def test_syntax_error_reported(self):
        raw = _build_llm_output(("bad.py", "create", "def oops(\n"))
        changes, errors = parse_and_validate(raw, allowed_files=["bad.py"])
        assert any("语法" in e for e in errors)
