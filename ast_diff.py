"""
ast_diff.py — AST 契约变更检测器（EP-130）

比对两个 ast_index.json 快照，输出结构性变更（契约层变更）。

核心思想：
  AST Diff ≠ 代码 Diff（git diff 已有）
  AST Diff = 接口契约 Diff（类签名/方法签名/字段定义是否改变）

只关注以下变更（契约层）：
  - 新增 Class
  - 删除 Class（STALE）
  - 新增 Method/Function
  - 删除 Method/Function
  - Method 签名变更（签名不同但名称相同）
  - fingerprint 变化（表示该文件的骨架整体改变）

不关注：
  - 方法体变化（不影响契约）
  - 注释/文档变化（不影响契约）
  - 测试文件变化

用于：
  1. postcheck 阶段检测代码变更是否影响 Ontology 绑定
  2. ontology_syncer 决定是否需要修补 YAML

EP-130 | 2026-04-18
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
try:
    from _paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_AST_INDEX_PATH = _ROOT / "docs" / "memory" / "_system" / "ast_index.json"


# ── 变更类型 ─────────────────────────────────────────────────────────────────

class ChangeKind(str, Enum):
    ADDED_CLASS     = "added_class"
    REMOVED_CLASS   = "removed_class"
    ADDED_METHOD    = "added_method"
    REMOVED_METHOD  = "removed_method"
    MODIFIED_METHOD = "modified_method"  # 签名变化
    ADDED_FILE      = "added_file"
    REMOVED_FILE    = "removed_file"
    FINGERPRINT_CHANGED = "fingerprint_changed"

    @property
    def is_breaking(self) -> bool:
        """是否是破坏性变更（需要人工确认）。"""
        return self in (
            ChangeKind.REMOVED_CLASS,
            ChangeKind.REMOVED_METHOD,
            ChangeKind.MODIFIED_METHOD,
        )

    @property
    def is_additive(self) -> bool:
        """是否是增量变更（可自动处理）。"""
        return self in (
            ChangeKind.ADDED_CLASS,
            ChangeKind.ADDED_METHOD,
        )


@dataclass
class ContractChange:
    """单条契约变更记录。"""
    kind: ChangeKind
    file_path: str
    class_name: Optional[str] = None
    method_name: Optional[str] = None
    before_signature: Optional[str] = None
    after_signature: Optional[str] = None
    fingerprint_before: Optional[str] = None
    fingerprint_after: Optional[str] = None

    @property
    def description(self) -> str:
        """人类可读的变更描述。"""
        if self.kind == ChangeKind.ADDED_CLASS:
            return f"新增类: {self.class_name} in {self.file_path}"
        elif self.kind == ChangeKind.REMOVED_CLASS:
            return f"删除类: {self.class_name} in {self.file_path} ⚠️ 需人工确认"
        elif self.kind == ChangeKind.ADDED_METHOD:
            return f"新增方法: {self.class_name}.{self.method_name} in {self.file_path}"
        elif self.kind == ChangeKind.REMOVED_METHOD:
            return f"删除方法: {self.class_name}.{self.method_name} in {self.file_path} ⚠️ 需人工确认"
        elif self.kind == ChangeKind.MODIFIED_METHOD:
            return (
                f"签名变更: {self.class_name}.{self.method_name} in {self.file_path}\n"
                f"  before: {self.before_signature}\n"
                f"  after:  {self.after_signature}"
            )
        elif self.kind == ChangeKind.ADDED_FILE:
            return f"新增文件: {self.file_path}"
        elif self.kind == ChangeKind.REMOVED_FILE:
            return f"删除文件: {self.file_path} ⚠️ 需人工确认"
        elif self.kind == ChangeKind.FINGERPRINT_CHANGED:
            return f"骨架变化: {self.file_path} ({self.fingerprint_before} → {self.fingerprint_after})"
        return f"{self.kind}: {self.file_path}"


@dataclass
class AstDiffResult:
    """AST Diff 完整结果。"""
    changes: List[ContractChange] = field(default_factory=list)
    files_compared: int = 0
    has_breaking_changes: bool = False
    has_additive_changes: bool = False

    def breaking_changes(self) -> List[ContractChange]:
        return [c for c in self.changes if c.kind.is_breaking]

    def additive_changes(self) -> List[ContractChange]:
        return [c for c in self.changes if c.kind.is_additive]

    def changes_for_file(self, file_path: str) -> List[ContractChange]:
        return [c for c in self.changes if c.file_path == file_path]

    def summary(self) -> str:
        if not self.changes:
            return f"无契约变更（比对 {self.files_compared} 个文件）"
        lines = [f"契约变更摘要（{self.files_compared} 个文件）:"]
        for c in self.changes:
            prefix = "⚠️ " if c.kind.is_breaking else "✅ "
            lines.append(f"  {prefix}{c.description}")
        return "\n".join(lines)


# ── 核心 Diff 逻辑 ───────────────────────────────────────────────────────────

def _index_methods(skeleton: dict) -> Dict[str, Dict[str, str]]:
    """
    从文件骨架中提取 {class_name: {method_name: signature}} 映射。
    顶层函数用 "__top__" 作为 class_name。
    """
    result: Dict[str, Dict[str, str]] = {}

    for cls in skeleton.get("classes", []):
        cname = cls.get("name", "")
        if not cname:
            continue
        methods = {}
        for m in cls.get("methods", []):
            mname = m.get("name", "")
            sig = m.get("signature", "")
            if mname:
                methods[mname] = sig
        result[cname] = methods

    top_funcs = {}
    for fn in skeleton.get("top_level_functions", []):
        fname = fn.get("name", "")
        sig = fn.get("signature", "")
        if fname:
            top_funcs[fname] = sig
    if top_funcs:
        result["__top__"] = top_funcs

    return result


def diff_ast(
    before: Dict[str, dict],
    after: Dict[str, dict],
    scope_files: Optional[List[str]] = None,
) -> AstDiffResult:
    """
    比对两个 ast_index.json 快照，返回 AstDiffResult。

    Args:
        before: 变更前的 ast_index（dict）
        after:  变更后的 ast_index（dict）
        scope_files: 只比对这些文件（None 表示全量比对）
    """
    result = AstDiffResult()

    # 确定比对范围
    all_files = set(before.keys()) | set(after.keys())
    if scope_files:
        all_files = all_files & set(scope_files)

    result.files_compared = len(all_files)

    for file_path in sorted(all_files):
        before_skel = before.get(file_path)
        after_skel = after.get(file_path)

        if before_skel is None and after_skel is not None:
            result.changes.append(ContractChange(
                kind=ChangeKind.ADDED_FILE,
                file_path=file_path,
            ))
            continue

        if before_skel is not None and after_skel is None:
            result.changes.append(ContractChange(
                kind=ChangeKind.REMOVED_FILE,
                file_path=file_path,
            ))
            continue

        # 两者都存在，比对 fingerprint
        fp_before = before_skel.get("fingerprint", "")
        fp_after = after_skel.get("fingerprint", "")
        if fp_before and fp_after and fp_before == fp_after:
            continue  # 骨架未变，跳过

        # fingerprint 变了，做细粒度比对
        before_methods = _index_methods(before_skel)
        after_methods = _index_methods(after_skel)

        all_classes = set(before_methods.keys()) | set(after_methods.keys())

        for class_name in sorted(all_classes):
            display_class = None if class_name == "__top__" else class_name

            before_cls = before_methods.get(class_name)
            after_cls = after_methods.get(class_name)

            if before_cls is None and after_cls is not None:
                if class_name != "__top__":
                    result.changes.append(ContractChange(
                        kind=ChangeKind.ADDED_CLASS,
                        file_path=file_path,
                        class_name=class_name,
                    ))
                continue

            if before_cls is not None and after_cls is None:
                if class_name != "__top__":
                    result.changes.append(ContractChange(
                        kind=ChangeKind.REMOVED_CLASS,
                        file_path=file_path,
                        class_name=class_name,
                    ))
                continue

            # 比对方法
            all_methods = set(before_cls.keys()) | set(after_cls.keys())
            for method_name in sorted(all_methods):
                before_sig = before_cls.get(method_name)
                after_sig = after_cls.get(method_name)

                if before_sig is None and after_sig is not None:
                    result.changes.append(ContractChange(
                        kind=ChangeKind.ADDED_METHOD,
                        file_path=file_path,
                        class_name=display_class,
                        method_name=method_name,
                        after_signature=after_sig,
                    ))
                elif before_sig is not None and after_sig is None:
                    result.changes.append(ContractChange(
                        kind=ChangeKind.REMOVED_METHOD,
                        file_path=file_path,
                        class_name=display_class,
                        method_name=method_name,
                        before_signature=before_sig,
                    ))
                elif before_sig != after_sig:
                    result.changes.append(ContractChange(
                        kind=ChangeKind.MODIFIED_METHOD,
                        file_path=file_path,
                        class_name=display_class,
                        method_name=method_name,
                        before_signature=before_sig,
                        after_signature=after_sig,
                    ))

        # 如果有变更但没有细粒度记录，添加 fingerprint_changed
        if fp_before and fp_after and fp_before != fp_after:
            file_changes = result.changes_for_file(file_path)
            if not file_changes:
                result.changes.append(ContractChange(
                    kind=ChangeKind.FINGERPRINT_CHANGED,
                    file_path=file_path,
                    fingerprint_before=fp_before,
                    fingerprint_after=fp_after,
                ))

    result.has_breaking_changes = any(c.kind.is_breaking for c in result.changes)
    result.has_additive_changes = any(c.kind.is_additive for c in result.changes)
    return result


def diff_ast_files(
    before_path: Path,
    after_path: Path,
    scope_files: Optional[List[str]] = None,
) -> AstDiffResult:
    """从文件路径加载并比对。"""
    def _load(p: Path) -> Dict[str, dict]:
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    return diff_ast(_load(before_path), _load(after_path), scope_files)


def load_ast_index(path: Path = _AST_INDEX_PATH) -> Dict[str, dict]:
    """加载 ast_index.json。"""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
