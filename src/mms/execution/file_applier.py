#!/usr/bin/env python3
"""
file_applier.py — LLM 输出解析与文件安全应用器

职责：
  1. 解析 LLM 输出的结构化变更块（===BEGIN-CHANGES=== 协议）
  2. Scope Guard：拒绝 unit.files 范围外的写入
  3. 语法预验证：.py 文件写入前用 ast.parse() 检查
  4. 安全写入：配合 GitSandbox 完成文件应用

LLM 输出协议：
    ===BEGIN-CHANGES===
    FILE: path/to/file.py
    ACTION: create
    CONTENT:
    ... 完整文件内容 ...
    ===END-FILE===
    ===END-CHANGES===

    支持的 ACTION：
      create  — 新建文件（目标路径已存在时拒绝，除非 force=True）
      replace — 完整替换文件内容（目标路径不存在时自动创建）
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]

_G = "\033[92m"
_Y = "\033[93m"
_R = "\033[91m"
_C = "\033[96m"
_B = "\033[1m"
_D = "\033[2m"
_X = "\033[0m"

# ── LLM 输出协议标记 ─────────────────────────────────────────────────────────

BEGIN_MARKER = "===BEGIN-CHANGES==="
END_MARKER = "===END-CHANGES==="
FILE_END_MARKER = "===END-FILE==="
ALLOWED_ACTIONS = frozenset({"create", "replace"})


# ── 数据结构 ─────────────────────────────────────────────────────────────────

@dataclass
class FileChange:
    """单个文件变更描述"""
    path: str          # 相对于项目根目录的路径
    action: str        # "create" | "replace"
    content: str       # 文件完整内容

    @property
    def abs_path(self) -> Path:
        return _ROOT / self.path

    @property
    def language(self) -> str:
        """根据文件后缀推断语言"""
        suffix = Path(self.path).suffix.lower()
        return {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".md": "markdown",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
        }.get(suffix, "unknown")


@dataclass
class ApplyResult:
    """单个文件应用结果"""
    path: str
    action: str
    success: bool
    error: Optional[str] = None


class ParseError(Exception):
    """LLM 输出解析失败"""


class ScopeViolationError(Exception):
    """Scope Guard 拦截：写入范围外的文件"""


class PreValidationError(Exception):
    """语法预验证失败"""


# ── 解析器 ───────────────────────────────────────────────────────────────────

def parse_llm_output(raw: str) -> List[FileChange]:
    """
    解析 LLM 输出的结构化变更块。

    Args:
        raw: LLM 原始输出文本

    Returns:
        List[FileChange]，可能为空（LLM 未输出任何变更）

    Raises:
        ParseError: 结构解析失败
    """
    # 找到 BEGIN/END 标记
    begin_idx = raw.find(BEGIN_MARKER)
    end_idx = raw.find(END_MARKER)

    if begin_idx == -1 and end_idx == -1:
        # 允许 LLM 直接输出不含标记的单文件内容（降级模式）
        return []

    if begin_idx == -1 or end_idx == -1:
        raise ParseError(
            f"变更块标记不完整：{'BEGIN' if begin_idx == -1 else 'END'} 标记缺失\n"
            f"期望格式：{BEGIN_MARKER} ... {END_MARKER}"
        )

    body = raw[begin_idx + len(BEGIN_MARKER):end_idx]
    changes: List[FileChange] = []

    # 按 ===END-FILE=== 分割文件块
    file_blocks = body.split(FILE_END_MARKER)

    for block in file_blocks:
        block = block.strip()
        if not block:
            continue

        change = _parse_file_block(block)
        if change:
            changes.append(change)

    return changes


def _parse_file_block(block: str) -> Optional[FileChange]:
    """解析单个文件块，提取 FILE/ACTION/CONTENT"""
    lines = block.splitlines()
    if not lines:
        return None

    file_path: Optional[str] = None
    action: Optional[str] = None
    content_start_idx = -1

    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if line_stripped.startswith("FILE:"):
            file_path = line_stripped[5:].strip()
        elif line_stripped.startswith("ACTION:"):
            action = line_stripped[7:].strip().lower()
        elif line_stripped == "CONTENT:" or line_stripped.startswith("CONTENT:"):
            content_start_idx = i + 1
            break

    if not file_path:
        return None

    if not action:
        action = "create"  # 默认 action

    if action not in ALLOWED_ACTIONS:
        raise ParseError(
            f"不支持的 ACTION：'{action}'（文件：{file_path}）\n"
            f"允许的 ACTION：{', '.join(sorted(ALLOWED_ACTIONS))}"
        )

    # 提取 CONTENT
    if content_start_idx >= 0:
        content_lines = lines[content_start_idx:]
        # 去除 markdown 代码块标记（```python ... ```）
        content = _strip_markdown_fences("\n".join(content_lines))
    else:
        # 无 CONTENT: 标记，则 FILE:/ACTION: 之后的所有内容为 content
        content = "\n".join(
            l for l in lines
            if not l.strip().startswith("FILE:") and not l.strip().startswith("ACTION:")
        )
        content = _strip_markdown_fences(content)

    return FileChange(path=file_path, action=action, content=content.strip())


def _strip_markdown_fences(text: str) -> str:
    """去除 LLM 可能包裹的 markdown 代码块标记"""
    text = text.strip()
    # 匹配 ```python\n...\n``` 或 ```\n...\n```
    fence_match = re.match(r"^```[\w]*\n(.*)\n```$", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1)
    return text


# ── Scope Guard ───────────────────────────────────────────────────────────────

def validate_scope(
    changes: List[FileChange],
    allowed_files: List[str],
    strict: bool = True,
) -> List[str]:
    """
    Scope Guard：检查变更是否超出 unit.files 声明的范围。

    Args:
        changes: 待应用的变更列表
        allowed_files: unit.files 声明的允许路径列表
        strict: True=违规时抛出异常；False=返回违规列表（仅警告）

    Returns:
        违规文件列表（strict=False 时有意义）

    Raises:
        ScopeViolationError: 违规文件被发现且 strict=True
    """
    allowed_set = set(allowed_files)
    violations = [c.path for c in changes if c.path not in allowed_set]

    if violations and strict:
        raise ScopeViolationError(
            f"Scope Guard 拦截：LLM 尝试写入 unit.files 范围外的文件\n"
            f"  违规路径：{violations}\n"
            f"  允许路径：{list(allowed_set)}\n"
            f"  修复方案：在 EP DAG 的 unit.files 中添加该路径，或让 LLM 重新生成"
        )

    return violations


# ── 语法预验证 ────────────────────────────────────────────────────────────────

def pre_validate(change: FileChange) -> Optional[str]:
    """
    写入前语法预验证。

    Returns:
        错误信息字符串，None 表示通过
    """
    if change.language == "python":
        return _validate_python_syntax(change.content, change.path)

    if change.language in ("typescript", "javascript"):
        # TS/JS 无法静态 parse，仅做基本非空检查
        if not change.content.strip():
            return f"文件内容为空：{change.path}"
        return None

    if change.language == "yaml":
        return _validate_yaml_syntax(change.content, change.path)

    if change.language == "json":
        return _validate_json_syntax(change.content, change.path)

    return None


def _validate_python_syntax(content: str, path: str) -> Optional[str]:
    """用 ast.parse() 检查 Python 语法"""
    try:
        ast.parse(content)
        return None
    except SyntaxError as e:
        return (
            f"Python 语法错误（{path}）：{e.msg}\n"
            f"  行 {e.lineno}：{e.text.strip() if e.text else '（无）'}"
        )


def _validate_yaml_syntax(content: str, path: str) -> Optional[str]:
    """尝试用 yaml.safe_load() 检查 YAML 语法"""
    try:
        import yaml  # type: ignore[import]
        yaml.safe_load(content)
        return None
    except ImportError:
        return None  # yaml 不可用，跳过验证
    except Exception as e:
        return f"YAML 语法错误（{path}）：{e}"


def _validate_json_syntax(content: str, path: str) -> Optional[str]:
    """用 json.loads() 检查 JSON 语法"""
    import json
    try:
        json.loads(content)
        return None
    except json.JSONDecodeError as e:
        return f"JSON 语法错误（{path}）：{e}"


# ── 文件应用器 ────────────────────────────────────────────────────────────────

class FileApplier:
    """
    将解析后的 FileChange 列表安全写入文件系统。

    配合 GitSandbox 使用：
        sandbox.snapshot()
        results = applier.apply(changes, sandbox)
        if all(r.success for r in results):
            sandbox.commit("...")
        else:
            sandbox.rollback()
    """

    def __init__(self, root: Path = _ROOT, strict_scope: bool = True):
        self.root = root
        self.strict_scope = strict_scope

    def apply(
        self,
        changes: List[FileChange],
        allowed_files: List[str],
        sandbox=None,  # Optional[GitSandbox]
        force: bool = False,
    ) -> List[ApplyResult]:
        """
        应用所有文件变更。

        Args:
            changes: 解析后的变更列表
            allowed_files: 允许写入的路径列表（unit.files）
            sandbox: GitSandbox 实例（用于标记新文件）
            force: True=允许 create 时覆盖已有文件

        Returns:
            List[ApplyResult] — 每个文件的应用结果
        """
        # Step 1: Scope Guard
        violations = validate_scope(changes, allowed_files, strict=self.strict_scope)
        if violations:
            # strict=False 时只打印警告，不阻断
            for v in violations:
                print(f"  {_Y}⚠️  Scope Guard 警告：{v} 不在 unit.files 范围内（已跳过）{_X}")
            changes = [c for c in changes if c.path not in violations]

        results: List[ApplyResult] = []

        for change in changes:
            result = self._apply_one(change, force=force, sandbox=sandbox)
            results.append(result)
            if result.success:
                print(f"  {_G}✅{_X} {change.action.upper()}: {change.path}")
            else:
                print(f"  {_R}❌{_X} {change.path}：{result.error}")

        return results

    def _apply_one(
        self,
        change: FileChange,
        force: bool = False,
        sandbox=None,
    ) -> ApplyResult:
        """应用单个文件变更"""
        abs_path = self.root / change.path

        # Step 2: 语法预验证
        syntax_err = pre_validate(change)
        if syntax_err:
            return ApplyResult(
                path=change.path,
                action=change.action,
                success=False,
                error=f"语法预验证失败：{syntax_err}",
            )

        # Step 3: action 检查
        if change.action == "create" and abs_path.exists() and not force:
            return ApplyResult(
                path=change.path,
                action=change.action,
                success=False,
                error=(
                    f"文件已存在（action=create 不允许覆盖）：{change.path}\n"
                    f"  若要覆盖，使用 action=replace 或传入 force=True"
                ),
            )

        # Step 4: 写入
        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(change.content, encoding="utf-8")

            # 标记新文件（原本不存在）
            if sandbox is not None and self._snapshot_was_none(change.path, sandbox):
                sandbox.mark_new_file(change.path)

            return ApplyResult(path=change.path, action=change.action, success=True)

        except OSError as e:
            return ApplyResult(
                path=change.path,
                action=change.action,
                success=False,
                error=f"文件写入失败：{e}",
            )

    @staticmethod
    def _snapshot_was_none(path: str, sandbox) -> bool:
        """检查该路径在沙箱快照中是否原本不存在"""
        return sandbox._snapshot.get(path) is None


# ── 便利函数 ──────────────────────────────────────────────────────────────────

def parse_and_validate(
    raw: str,
    allowed_files: List[str],
    strict_scope: bool = True,
) -> Tuple[List[FileChange], List[str]]:
    """
    一步完成解析 + Scope Guard（不写文件）。

    Returns:
        (valid_changes, error_messages)
    """
    errors: List[str] = []

    try:
        changes = parse_llm_output(raw)
    except ParseError as e:
        return [], [str(e)]

    if not changes:
        return [], ["LLM 未输出任何文件变更（未找到 ===BEGIN-CHANGES=== 块）"]

    # Scope Guard（非 strict，收集违规信息）
    violations = validate_scope(changes, allowed_files, strict=False)
    if violations:
        errors.append(
            f"Scope Guard：{len(violations)} 个文件超出 unit.files 范围（已过滤）：{violations}"
        )
        changes = [c for c in changes if c.path not in violations]

    # 语法预验证
    for change in changes:
        err = pre_validate(change)
        if err:
            errors.append(err)

    return changes, errors
