"""
test_ast_diff.py — AST 契约变更检测测试（EP-130）
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from ast_diff import (
    diff_ast, ChangeKind, ContractChange, AstDiffResult,
)


def _make_index(file_path: str, classes: list, fingerprint: str = "") -> dict:
    """构建简单的 ast_index 条目。"""
    return {
        file_path: {
            "lang": "python",
            "classes": classes,
            "top_level_functions": [],
            "imports": [],
            "fingerprint": fingerprint or f"sha256:{hash(str(classes)):016x}",
        }
    }


class TestBasicDiff:
    def test_no_changes_when_identical(self):
        index = _make_index(
            "service.py",
            [{"name": "Foo", "bases": [], "methods": [{"name": "bar", "signature": "(self) -> None", "decorators": [], "is_async": False, "docstring": ""}], "docstring": ""}],
            fingerprint="sha256:abc123",
        )
        result = diff_ast(index, index)
        assert result.changes == []
        assert result.has_breaking_changes is False

    def test_detects_added_method(self):
        base_class = [{"name": "Foo", "bases": [], "methods": [
            {"name": "old_method", "signature": "(self)", "decorators": [], "is_async": False, "docstring": ""},
        ], "docstring": ""}]
        new_class = [{"name": "Foo", "bases": [], "methods": [
            {"name": "old_method", "signature": "(self)", "decorators": [], "is_async": False, "docstring": ""},
            {"name": "new_method", "signature": "(self, x: int)", "decorators": [], "is_async": False, "docstring": ""},
        ], "docstring": ""}]
        
        before = _make_index("service.py", base_class, "sha256:fp_before")
        after = _make_index("service.py", new_class, "sha256:fp_after")
        
        result = diff_ast(before, after)
        assert any(c.kind == ChangeKind.ADDED_METHOD for c in result.changes)
        added = [c for c in result.changes if c.kind == ChangeKind.ADDED_METHOD]
        assert added[0].method_name == "new_method"
        assert result.has_additive_changes is True

    def test_detects_removed_method(self):
        before_class = [{"name": "Foo", "bases": [], "methods": [
            {"name": "method_a", "signature": "(self)", "decorators": [], "is_async": False, "docstring": ""},
            {"name": "method_b", "signature": "(self)", "decorators": [], "is_async": False, "docstring": ""},
        ], "docstring": ""}]
        after_class = [{"name": "Foo", "bases": [], "methods": [
            {"name": "method_a", "signature": "(self)", "decorators": [], "is_async": False, "docstring": ""},
        ], "docstring": ""}]
        
        before = _make_index("service.py", before_class, "sha256:fp_before")
        after = _make_index("service.py", after_class, "sha256:fp_after")
        
        result = diff_ast(before, after)
        removed = [c for c in result.changes if c.kind == ChangeKind.REMOVED_METHOD]
        assert len(removed) == 1
        assert removed[0].method_name == "method_b"
        assert result.has_breaking_changes is True

    def test_detects_signature_change(self):
        before_class = [{"name": "Foo", "bases": [], "methods": [
            {"name": "create", "signature": "(self, ctx: SecurityContext) -> None", "decorators": [], "is_async": False, "docstring": ""},
        ], "docstring": ""}]
        after_class = [{"name": "Foo", "bases": [], "methods": [
            {"name": "create", "signature": "(self, ctx: SecurityContext, extra: str) -> None", "decorators": [], "is_async": False, "docstring": ""},
        ], "docstring": ""}]
        
        before = _make_index("service.py", before_class, "sha256:fp_before")
        after = _make_index("service.py", after_class, "sha256:fp_after")
        
        result = diff_ast(before, after)
        modified = [c for c in result.changes if c.kind == ChangeKind.MODIFIED_METHOD]
        assert len(modified) == 1
        assert modified[0].method_name == "create"
        assert result.has_breaking_changes is True

    def test_detects_added_file(self):
        after = _make_index("new_service.py", [{"name": "NewService", "bases": [], "methods": [], "docstring": ""}], "sha256:fp")
        result = diff_ast({}, after)
        assert any(c.kind == ChangeKind.ADDED_FILE for c in result.changes)

    def test_detects_removed_file(self):
        before = _make_index("old_service.py", [{"name": "OldService", "bases": [], "methods": [], "docstring": ""}], "sha256:fp")
        result = diff_ast(before, {})
        assert any(c.kind == ChangeKind.REMOVED_FILE for c in result.changes)


class TestScopeFiles:
    def test_scope_limits_comparison(self):
        before = {}
        before.update(_make_index("service_a.py", [], "sha256:a1"))
        before.update(_make_index("service_b.py", [{"name": "B", "bases": [], "methods": [], "docstring": ""}], "sha256:b1"))
        
        after = {}
        after.update(_make_index("service_a.py", [{"name": "A", "bases": [], "methods": [], "docstring": ""}], "sha256:a2"))  # 变了
        after.update(_make_index("service_b.py", [{"name": "B_changed", "bases": [], "methods": [], "docstring": ""}], "sha256:b2"))  # 也变了
        
        # 只比对 service_a.py
        result = diff_ast(before, after, scope_files=["service_a.py"])
        assert all(c.file_path == "service_a.py" for c in result.changes)

    def test_empty_scope_files_compares_all(self):
        before = {}
        before.update(_make_index("service_a.py", [], "sha256:a1"))
        after = {}
        after.update(_make_index("service_a.py", [{"name": "A", "bases": [], "methods": [], "docstring": ""}], "sha256:a2"))
        
        result = diff_ast(before, after, scope_files=None)
        assert len(result.changes) > 0


class TestContractChange:
    def test_description_formats(self):
        c1 = ContractChange(kind=ChangeKind.ADDED_METHOD, file_path="f.py", class_name="Foo", method_name="bar")
        assert "新增方法" in c1.description
        assert "bar" in c1.description

        c2 = ContractChange(kind=ChangeKind.REMOVED_CLASS, file_path="f.py", class_name="Foo")
        assert "删除类" in c2.description
        assert "⚠️" in c2.description

    def test_is_breaking_flags(self):
        assert ChangeKind.REMOVED_CLASS.is_breaking is True
        assert ChangeKind.REMOVED_METHOD.is_breaking is True
        assert ChangeKind.MODIFIED_METHOD.is_breaking is True
        assert ChangeKind.ADDED_CLASS.is_breaking is False
        assert ChangeKind.ADDED_METHOD.is_breaking is False

    def test_is_additive_flags(self):
        assert ChangeKind.ADDED_CLASS.is_additive is True
        assert ChangeKind.ADDED_METHOD.is_additive is True
        assert ChangeKind.REMOVED_CLASS.is_additive is False
