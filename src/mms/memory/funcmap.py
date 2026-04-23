"""
funcmap.py — 函数签名索引生成器（Code Structure Dimension）

扫描项目后端 Python 和前端 TypeScript 的关键函数/类/方法，
提取签名（含参数、返回类型）和 docstring/注释，
生成轻量 Markdown 索引（funcmap.md），供 LLM 了解可复用代码结构。

特性:
  - 后端：扫描 Service / API / Worker / Infrastructure 层
  - 前端：扫描 Store / Services / Components（只取 export 函数）
  - 只提取有 docstring 或 JSDoc 注释的函数（噪音过滤）
  - 输出到 docs/memory/_system/funcmap.md（只读自动生成，勿手动编辑）

用法:
  python3 scripts/mms/funcmap.py                  # 生成全量索引
  python3 scripts/mms/funcmap.py --backend-only   # 只扫描后端
  python3 scripts/mms/funcmap.py --frontend-only  # 只扫描前端
  python3 scripts/mms/funcmap.py --dry-run        # 只打印，不写文件
"""

from __future__ import annotations

import ast
import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, NamedTuple, Optional

_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT = _ROOT / "docs" / "memory" / "_system" / "mms.memory.funcmap.md"

_BACKEND_DIRS = [
    ("backend/app/services", "后端 Service 层"),
    ("backend/app/api/v1", "后端 API 路由"),
    ("backend/app/workers", "后端 Worker"),
    ("backend/app/infrastructure", "基础设施适配器"),
]

_FRONTEND_DIRS = [
    ("frontend/src/stores", "前端 Zustand Store"),
    ("frontend/src/services", "前端 API Service"),
]

_IGNORE_DIRS = {"__pycache__", ".mypy_cache", "node_modules", ".venv"}
_MAX_FUNCTIONS_PER_FILE = 10  # 防止单文件过多函数占用大量 token


class FuncEntry(NamedTuple):
    file: str
    name: str
    signature: str
    docstring: str
    line: int


# ── Python 函数提取 ──────────────────────────────────────────────────────────

def _extract_python_functions(path: Path) -> List[FuncEntry]:
    """
    使用 AST 解析 Python 文件，提取有 docstring 的公开函数/方法。
    私有函数（_xxx）和没有 docstring 的函数跳过。
    """
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except SyntaxError:
        return []

    entries: List[FuncEntry] = []
    rel = str(path.relative_to(_ROOT))

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        docstring = ast.get_docstring(node)
        if not docstring:
            continue

        # 构建签名
        args = node.args
        params = []
        for arg in args.args:
            annotation = ""
            # arg.annotation may be None if untyped
            if hasattr(arg, "annotation") and arg.annotation:
                try:
                    annotation = f": {ast.unparse(arg.annotation)}"
                except (AttributeError, TypeError):
                    annotation = ""
            arg_name = arg.arg if hasattr(arg, "arg") else getattr(arg, "name", "?")
            params.append(f"{arg_name}{annotation}")

        return_ann = ""
        if node.returns:
            try:
                return_ann = f" -> {ast.unparse(node.returns)}"
            except AttributeError:
                return_ann = ""

        is_async = isinstance(node, ast.AsyncFunctionDef)
        prefix = "async def" if is_async else "def"
        sig = f"{prefix} {node.name}({', '.join(params)}){return_ann}"

        # 取 docstring 第一行
        doc_first_line = docstring.strip().split("\n")[0][:120]

        entries.append(FuncEntry(
            file=rel,
            name=node.name,
            signature=sig,
            docstring=doc_first_line,
            line=node.lineno,
        ))

        if len(entries) >= _MAX_FUNCTIONS_PER_FILE:
            break

    return entries


# ── TypeScript 函数提取（正则，不做完整 TS 解析） ─────────────────────────────

_TS_EXPORT_FUNC = re.compile(
    r"^export\s+(?:async\s+)?(?:function|const)\s+(\w+)\s*"
    r"(?:<[^>]*>)?\s*[\(=]",
    re.MULTILINE,
)

_JSDOC = re.compile(
    r"/\*\*\s*(.*?)\s*\*/\s*\nexport",
    re.DOTALL,
)


def _extract_ts_functions(path: Path) -> List[FuncEntry]:
    """提取 TypeScript 文件中的 export 函数（有 JSDoc 注释的）"""
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    entries: List[FuncEntry] = []
    rel = str(path.relative_to(_ROOT))

    # 找所有有 JSDoc 的 export 函数
    for m_doc in _JSDOC.finditer(source):
        pos = m_doc.end() - len("export")
        remaining = source[pos:]
        m_func = _TS_EXPORT_FUNC.match(remaining)
        if m_func:
            func_name = m_func.group(1)
            doc_text = m_doc.group(1).strip()
            # 清理 JSDoc 格式，取第一行有效内容
            doc_lines = [
                ln.strip().lstrip("* ").strip()
                for ln in doc_text.split("\n")
                if ln.strip() and ln.strip() not in ("/**", "*/", "*")
            ]
            doc_first = doc_lines[0][:120] if doc_lines else ""
            line_no = source[:m_doc.start()].count("\n") + 1

            entries.append(FuncEntry(
                file=rel,
                name=func_name,
                signature=f"export function {func_name}()",
                docstring=doc_first,
                line=line_no,
            ))

        if len(entries) >= _MAX_FUNCTIONS_PER_FILE:
            break

    return entries


# ── 生成 Markdown ─────────────────────────────────────────────────────────────

def generate_funcmap(
    backend_only: bool = False,
    frontend_only: bool = False,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections: List[str] = []

    sections.append("# Funcmap — 函数签名索引")
    sections.append("")
    sections.append(f"> **自动生成** · {now} · 勿手动编辑")
    sections.append("> 仅包含有 docstring/JSDoc 注释的公开函数")
    sections.append("> 使用 `python3 scripts/mms/funcmap.py` 刷新")
    sections.append("")
    sections.append("---")
    sections.append("")

    if not frontend_only:
        sections.append("## 后端函数索引")
        sections.append("")
        for rel_dir, label in _BACKEND_DIRS:
            scan_path = _ROOT / rel_dir
            if not scan_path.exists():
                continue
            dir_entries: List[FuncEntry] = []
            for py in sorted(scan_path.rglob("*.py")):
                if any(p in _IGNORE_DIRS for p in py.parts):
                    continue
                dir_entries.extend(_extract_python_functions(py))

            if not dir_entries:
                continue

            sections.append(f"### {label} (`{rel_dir}`)")
            sections.append("")
            sections.append("| 函数 | 文件 | 行号 | 说明 |")
            sections.append("|:--|:--|:--|:--|")
            for entry in dir_entries[:50]:  # 每个目录最多显示 50 条
                fname = Path(entry.file).name
                sig_short = entry.signature[:80].replace("|", "\\|")
                doc_short = entry.docstring[:60].replace("|", "\\|") if entry.docstring else ""
                sections.append(f"| `{sig_short}` | `{fname}:{entry.line}` | {entry.line} | {doc_short} |")
            sections.append("")

    if not backend_only:
        sections.append("## 前端函数索引")
        sections.append("")
        for rel_dir, label in _FRONTEND_DIRS:
            scan_path = _ROOT / rel_dir
            if not scan_path.exists():
                continue
            dir_entries_ts: List[FuncEntry] = []
            for ts in sorted(scan_path.rglob("*.ts")) + sorted(scan_path.rglob("*.tsx")):
                if any(p in _IGNORE_DIRS for p in ts.parts):
                    continue
                dir_entries_ts.extend(_extract_ts_functions(ts))

            if not dir_entries_ts:
                continue

            sections.append(f"### {label} (`{rel_dir}`)")
            sections.append("")
            sections.append("| 函数 | 文件 | 说明 |")
            sections.append("|:--|:--|:--|")
            for entry in dir_entries_ts[:30]:
                fname = Path(entry.file).name
                doc_short = entry.docstring[:60].replace("|", "\\|") if entry.docstring else ""
                sections.append(f"| `{entry.name}` | `{fname}:{entry.line}` | {doc_short} |")
            sections.append("")

    sections.append("---")
    sections.append("")
    sections.append(
        "_本文件由 `scripts/mms/funcmap.py` 自动生成。"
        "刷新命令：`python3 scripts/mms/cli.py funcmap`_"
    )
    sections.append("")

    return "\n".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="mms.memory.funcmap.py — 函数签名索引生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 scripts/mms/funcmap.py                  # 生成全量索引
  python3 scripts/mms/funcmap.py --backend-only   # 只扫描后端
  python3 scripts/mms/funcmap.py --dry-run        # 只打印不写文件
""",
    )
    parser.add_argument("--backend-only",  action="store_true", help="只扫描后端 Python")
    parser.add_argument("--frontend-only", action="store_true", help="只扫描前端 TS/TSX")
    parser.add_argument("--dry-run",       action="store_true", help="只打印，不写文件")
    args = parser.parse_args()

    content = generate_funcmap(
        backend_only=args.backend_only,
        frontend_only=args.frontend_only,
    )

    if args.dry_run:
        print(content[:3000])  # 只打印前 3000 字
        print("\n... (truncated for dry-run)")
        return 0

    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(content, encoding="utf-8")
    print(f"✓ funcmap 已生成：{_OUTPUT.relative_to(_ROOT)}")
    print(f"  字符数: {len(content)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
