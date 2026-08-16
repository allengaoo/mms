"""
codemap.py — 代码目录快照生成器

扫描项目关键目录（backend / frontend / scripts），
生成轻量级的目录结构 Markdown（codemap.md），供 LLM 代码生成时参考。

特性:
  - 只展示有意义的目录层级（默认 3 层），不展开 node_modules / __pycache__ 等噪音
  - 可选附加"最近修改"信息（--recent）
  - 输出到 docs/memory/_system/codemap.md（只读自动生成文件，勿手动编辑）

用法:
  python3 scripts/mms/codemap.py                # 生成全量快照
  python3 scripts/mms/codemap.py --depth 2      # 只展示 2 层目录
  python3 scripts/mms/codemap.py --recent 10    # 附加最近 10 个修改文件
  python3 scripts/mms/codemap.py --dry-run      # 只打印，不写文件

注意: 此文件由脚本自动生成。请勿手动编辑 codemap.md。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT = _ROOT / "docs" / "memory" / "_system" / "codemap.md"

# 扫描的顶级目录
_SCAN_DIRS = [
    ("backend/app", "后端应用层"),
    ("frontend/src", "前端源码"),
    ("scripts/mms", "MMS 记忆系统脚本"),
    ("docs/memory/shared", "共享记忆库"),
    ("docs/architecture", "架构文档"),
]

# 忽略的目录名
_IGNORE_DIRS = {
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "htmlcov", "coverage", ".DS_Store",
}

# 忽略的文件扩展名（不在树状图中显示）
_IGNORE_EXTS = {
    ".pyc", ".pyo", ".map", ".lock", ".log",
    ".db", ".sqlite", ".cache",
}


def _should_ignore(name: str) -> bool:
    return name in _IGNORE_DIRS or name.startswith(".")


def _build_tree(
    base: Path,
    current: Path,
    depth: int,
    max_depth: int,
    lines: List[str],
    prefix: str = "",
    is_last: bool = True,
) -> None:
    """递归构建树状目录结构"""
    if depth > max_depth:
        return

    rel = current.relative_to(base)
    connector = "└── " if is_last else "├── "
    name = current.name

    # 显示目录/文件名
    if current.is_dir():
        lines.append(f"{prefix}{connector}{name}/")
    else:
        if current.suffix in _IGNORE_EXTS:
            return
        lines.append(f"{prefix}{connector}{name}")

    if not current.is_dir():
        return

    # 子项排序：目录在前，文件在后
    try:
        children = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
    except PermissionError:
        return

    children = [c for c in children if not _should_ignore(c.name)]
    extension = "    " if is_last else "│   "

    for i, child in enumerate(children):
        _build_tree(
            base=base,
            current=child,
            depth=depth + 1,
            max_depth=max_depth,
            lines=lines,
            prefix=prefix + extension,
            is_last=(i == len(children) - 1),
        )


def generate_codemap(max_depth: int = 3, recent_count: int = 0) -> str:
    """生成 codemap.md 内容"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections: List[str] = []

    sections.append("# Codemap — 项目目录快照")
    sections.append("")
    sections.append(f"> **自动生成** · {now} · 勿手动编辑")
    sections.append("> 使用 `python3 scripts/mms/codemap.py` 刷新")
    sections.append("")
    sections.append("---")
    sections.append("")

    for rel_dir, label in _SCAN_DIRS:
        scan_path = _ROOT / rel_dir
        if not scan_path.exists():
            sections.append(f"## {label} (`{rel_dir}`)")
            sections.append("")
            sections.append("_目录不存在_")
            sections.append("")
            continue

        sections.append(f"## {label} (`{rel_dir}`)")
        sections.append("")
        sections.append("```")
        sections.append(f"{rel_dir}/")

        lines: List[str] = []
        try:
            children = sorted(scan_path.iterdir(), key=lambda p: (p.is_file(), p.name))
            children = [c for c in children if not _should_ignore(c.name)]
            for i, child in enumerate(children):
                _build_tree(
                    base=scan_path,
                    current=child,
                    depth=1,
                    max_depth=max_depth,
                    lines=lines,
                    prefix="",
                    is_last=(i == len(children) - 1),
                )
        except PermissionError:
            lines.append("（权限不足，无法读取）")

        sections.extend(lines)
        sections.append("```")
        sections.append("")

    # 最近修改文件
    if recent_count > 0:
        sections.append("---")
        sections.append("")
        sections.append(f"## 最近修改文件（最近 {recent_count} 个）")
        sections.append("")
        recent = _get_recent_files(recent_count)
        if recent:
            for fpath, mtime in recent:
                sections.append(f"- `{fpath}` — {mtime}")
        else:
            sections.append("_无最近修改文件_")
        sections.append("")

    sections.append("---")
    sections.append("")
    sections.append(
        "_本文件由 `scripts/mms/codemap.py` 自动生成，请勿手动编辑。"
        "刷新命令：`python3 scripts/mms/cli.py codemap`_"
    )
    sections.append("")

    return "\n".join(sections)


def _get_recent_files(n: int) -> List[tuple]:
    """获取项目中最近修改的 n 个文件（排除噪音）"""
    candidates = []
    scan_roots = [_ROOT / d for d, _ in _SCAN_DIRS if (_ROOT / d).exists()]
    for root in scan_roots:
        for path in root.rglob("*"):
            if path.is_file() and not any(_should_ignore(p) for p in path.parts):
                if path.suffix not in _IGNORE_EXTS:
                    try:
                        mtime = path.stat().st_mtime
                        candidates.append((path, mtime))
                    except OSError:
                        pass

    candidates.sort(key=lambda x: x[1], reverse=True)
    result = []
    for path, mtime in candidates[:n]:
        rel = str(path.relative_to(_ROOT))
        dt = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        result.append((rel, dt))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="codemap.py — 代码目录快照生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 scripts/mms/codemap.py               # 生成全量快照（默认 3 层）
  python3 scripts/mms/codemap.py --depth 2     # 只展示 2 层
  python3 scripts/mms/codemap.py --recent 10   # 附加最近 10 个修改文件
  python3 scripts/mms/codemap.py --dry-run     # 只打印不写文件
""",
    )
    parser.add_argument("--depth",   type=int, default=3,  help="目录展开深度（默认 3）")
    parser.add_argument("--recent",  type=int, default=0,  help="附加最近修改文件数量（默认 0）")
    parser.add_argument("--dry-run", action="store_true",   help="只打印，不写文件")
    args = parser.parse_args()

    content = generate_codemap(max_depth=args.depth, recent_count=args.recent)

    if args.dry_run:
        print(content)
        return 0

    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(content, encoding="utf-8")
    print(f"✓ codemap 已生成：{_OUTPUT.relative_to(_ROOT)}")
    print(f"  目录深度: {args.depth} 层 | 字符数: {len(content)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
