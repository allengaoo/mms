"""
ast_skeleton.py — AST 骨架化器（EP-130）

将项目代码库压缩为纯结构性骨架，剥离所有业务逻辑实现，
只保留 Class 定义、方法签名、类型提示和 docstring 首行。

设计参考：aider repo-map 的骨架提取层（不含 PageRank，PageRank 在 repo_map.py）

离线约束：
  - Python 文件：使用 ast 标准库（精确 AST，零依赖）
  - TypeScript 文件：使用正则骨架提取（粗粒度，零依赖）
  - 禁止 import tree_sitter / pygments / libcst 等需 C 编译的库

输出格式：docs/memory/_system/ast_index.json
  {
    "backend/app/services/control/ontology_service.py": {
      "lang": "python",
      "classes": [
        {
          "name": "OntologyService",
          "bases": ["BaseService"],
          "methods": [
            {
              "name": "create_object_type",
              "signature": "(self, ctx: SecurityContext, payload: CreateRequest) -> ObjectTypeResponse",
              "docstring": "创建新对象类型定义",
              "decorators": ["require_permission"]
            }
          ]
        }
      ],
      "top_level_functions": [],
      "imports": ["SecurityContext", "AuditService"],
      "fingerprint": "sha256:abc123ef"  ← 用于 ast_diff 变更检测
    }
  }

EP-130 | 2026-04-18
"""

from __future__ import annotations

import ast
import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
try:
    from _paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_OUTPUT = _ROOT / "docs" / "memory" / "_system" / "ast_index.json"

# ── 可配置常量 ────────────────────────────────────────────────────────────────

try:
    sys.path.insert(0, str(_HERE))
    from mms_config import cfg as _cfg  # type: ignore[import]
    _MAX_METHODS_PER_CLASS: int = int(getattr(_cfg, "ast_max_methods_per_class", 20))
    _MAX_FILES: int = int(getattr(_cfg, "ast_max_files", 2000))
    _DOCSTRING_MAX_LEN: int = int(getattr(_cfg, "ast_docstring_max_len", 100))
except (ImportError, AttributeError):
    _MAX_METHODS_PER_CLASS = 20
    _MAX_FILES = 2000
    _DOCSTRING_MAX_LEN = 100

# 扫描的目录配置
_SCAN_DIRS = [
    ("backend/app/services", "python"),
    ("backend/app/api/v1", "python"),
    ("backend/app/workers", "python"),
    ("backend/app/infrastructure", "python"),
    ("backend/app/core", "python"),
    ("backend/app/models", "python"),
    ("frontend/src/stores", "typescript"),
    ("frontend/src/services", "typescript"),
    ("scripts/mms", "python"),
]

_IGNORE_DIRS = {
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    "dist", "build", ".mypy_cache", ".pytest_cache",
    "migrations", "alembic", "htmlcov",
}

_PYTHON_EXTS = {".py"}
_TS_EXTS = {".ts", ".tsx"}


# ── 数据结构 ─────────────────────────────────────────────────────────────────

@dataclass
class MethodSkeleton:
    name: str
    signature: str
    docstring: str = ""
    decorators: List[str] = field(default_factory=list)
    is_async: bool = False


@dataclass
class ClassSkeleton:
    name: str
    bases: List[str] = field(default_factory=list)
    methods: List[MethodSkeleton] = field(default_factory=list)
    docstring: str = ""


@dataclass
class FileSkeleton:
    path: str           # 相对于项目根的路径
    lang: str           # "python" | "typescript"
    classes: List[ClassSkeleton] = field(default_factory=list)
    top_level_functions: List[MethodSkeleton] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)  # 关键导入（类名/接口名）
    fingerprint: str = ""  # SHA-256 of sorted(classes + functions signatures)


# ── Python 解析（ast 标准库）─────────────────────────────────────────────────

def _extract_docstring(node: ast.AST) -> str:
    """从 AST 节点提取 docstring 首行。"""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return ""
    body = node.body
    if not body:
        return ""
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        val = first.value.value
        if isinstance(val, str):
            first_line = val.strip().split("\n")[0].strip()
            return first_line[:_DOCSTRING_MAX_LEN]
    return ""


def _unparse_annotation(node: Optional[ast.expr]) -> str:
    """将类型注解 AST 节点还原为字符串（兼容 Python 3.9+）。"""
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return "..."


def _extract_method_sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """提取函数签名字符串，不含 def/async def 前缀。"""
    args = node.args
    params = []

    # positional args
    defaults_offset = len(args.args) - len(args.defaults)
    for i, arg in enumerate(args.args):
        annotation = _unparse_annotation(arg.annotation)
        param = arg.arg
        if annotation:
            param = f"{param}: {annotation}"
        default_idx = i - defaults_offset
        if default_idx >= 0:
            try:
                default_str = ast.unparse(args.defaults[default_idx])
                param = f"{param} = {default_str}"
            except Exception:
                param = f"{param} = ..."
        params.append(param)

    # *args
    if args.vararg:
        annotation = _unparse_annotation(args.vararg.annotation)
        s = f"*{args.vararg.arg}"
        if annotation:
            s = f"*{args.vararg.arg}: {annotation}"
        params.append(s)

    # **kwargs
    if args.kwarg:
        annotation = _unparse_annotation(args.kwarg.annotation)
        s = f"**{args.kwarg.arg}"
        if annotation:
            s = f"**{args.kwarg.arg}: {annotation}"
        params.append(s)

    ret = _unparse_annotation(node.returns)
    ret_str = f" -> {ret}" if ret else ""
    return f"({', '.join(params)}){ret_str}"


def _extract_decorator_names(decorators: list) -> List[str]:
    """提取装饰器名称列表。"""
    names = []
    for d in decorators:
        try:
            names.append(ast.unparse(d).split("(")[0].strip())
        except Exception:
            pass
    return names


def _parse_python(source: str, rel_path: str) -> FileSkeleton:
    """解析 Python 文件，返回 FileSkeleton。"""
    skeleton = FileSkeleton(path=rel_path, lang="python")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return skeleton

    # 收集顶层 import 中的类名/接口名（过滤掉模块名）
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.names:
            for alias in node.names:
                name = alias.asname or alias.name
                # 只收集大写开头的名称（类、接口、TypeAlias）
                if name and name[0].isupper():
                    skeleton.imports.append(name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[-1]
                if name and name[0].isupper():
                    skeleton.imports.append(name)

    # 去重
    skeleton.imports = sorted(set(skeleton.imports))

    # 遍历顶层节点
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_skel = ClassSkeleton(
                name=node.name,
                bases=[_unparse_annotation(b) for b in node.bases],
                docstring=_extract_docstring(node),
            )
            # 提取方法
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # 跳过私有方法（双下划线除外），减少噪音
                    if item.name.startswith("_") and not item.name.startswith("__"):
                        continue
                    method = MethodSkeleton(
                        name=item.name,
                        signature=_extract_method_sig(item),
                        docstring=_extract_docstring(item),
                        decorators=_extract_decorator_names(item.decorator_list),
                        is_async=isinstance(item, ast.AsyncFunctionDef),
                    )
                    class_skel.methods.append(method)
                    if len(class_skel.methods) >= _MAX_METHODS_PER_CLASS:
                        break
            skeleton.classes.append(class_skel)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # 跳过私有函数
            if node.name.startswith("_"):
                continue
            func = MethodSkeleton(
                name=node.name,
                signature=_extract_method_sig(node),
                docstring=_extract_docstring(node),
                decorators=_extract_decorator_names(node.decorator_list),
                is_async=isinstance(node, ast.AsyncFunctionDef),
            )
            skeleton.top_level_functions.append(func)

    return skeleton


# ── TypeScript 解析（正则，粗粒度）──────────────────────────────────────────

# 匹配 export class Foo extends Bar
_RE_TS_CLASS = re.compile(
    r"export\s+(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+([\w<>, ]+))?(?:\s+implements\s+([\w<>, ]+))?",
    re.MULTILINE,
)
# 匹配方法签名（包含可见性修饰符）
_RE_TS_METHOD = re.compile(
    r"(?:(?:public|private|protected|async|static|readonly)\s+)*(\w+)\s*\([^)]*\)\s*(?::\s*[\w<>\[\]| ]+)?(?:\s*\{|;)",
    re.MULTILINE,
)
# 匹配 export function / export const fn = () =>
_RE_TS_FUNC = re.compile(
    r"export\s+(?:async\s+)?(?:function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s+)?\()",
    re.MULTILINE,
)
# 匹配顶层 import { Foo, Bar } from 'xxx'
_RE_TS_IMPORT = re.compile(
    r"import\s+(?:type\s+)?\{([^}]+)\}\s+from",
    re.MULTILINE,
)


def _parse_typescript(source: str, rel_path: str) -> FileSkeleton:
    """解析 TypeScript/TSX 文件，返回粗粒度 FileSkeleton。"""
    skeleton = FileSkeleton(path=rel_path, lang="typescript")

    # 导入（只取大写开头的名称）
    for m in _RE_TS_IMPORT.finditer(source):
        names = [n.strip().split(" as ")[-1].strip() for n in m.group(1).split(",")]
        skeleton.imports.extend(n for n in names if n and n[0].isupper())
    skeleton.imports = sorted(set(skeleton.imports))

    # 类
    for m in _RE_TS_CLASS.finditer(source):
        class_name = m.group(1)
        bases = []
        if m.group(2):
            bases.extend(b.strip() for b in m.group(2).split(","))
        if m.group(3):
            bases.extend(b.strip() for b in m.group(3).split(","))
        class_skel = ClassSkeleton(name=class_name, bases=bases)

        # 提取该 class 块内的方法（简单定位：从 class { 到下一个顶层 }）
        start = m.end()
        # 找到 class 块开始
        block_start = source.find("{", start)
        if block_start == -1:
            skeleton.classes.append(class_skel)
            continue
        # 找对应的 } 结尾（简单括号计数）
        depth = 0
        block_end = block_start
        for i, ch in enumerate(source[block_start:], block_start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    block_end = i
                    break
        class_body = source[block_start:block_end]
        count = 0
        for mm in _RE_TS_METHOD.finditer(class_body):
            name = mm.group(1)
            if not name or name in {"if", "for", "while", "switch", "return"}:
                continue
            if name.startswith("_"):
                continue
            class_skel.methods.append(MethodSkeleton(name=name, signature="(...)"))
            count += 1
            if count >= _MAX_METHODS_PER_CLASS:
                break
        skeleton.classes.append(class_skel)

    # 顶层 export 函数
    for m in _RE_TS_FUNC.finditer(source):
        name = m.group(1) or m.group(2)
        if name:
            skeleton.top_level_functions.append(
                MethodSkeleton(name=name, signature="(...)")
            )

    return skeleton


# ── 指纹计算 ────────────────────────────────────────────────────────────────

def _compute_fingerprint(skeleton: FileSkeleton) -> str:
    """基于骨架结构计算 SHA-256 指纹（用于 ast_diff 变更检测）。"""
    parts = []
    for cls in sorted(skeleton.classes, key=lambda c: c.name):
        parts.append(f"class:{cls.name}({','.join(cls.bases)})")
        for m in sorted(cls.methods, key=lambda x: x.name):
            parts.append(f"  method:{m.name}{m.signature}")
    for fn in sorted(skeleton.top_level_functions, key=lambda x: x.name):
        parts.append(f"func:{fn.name}{fn.signature}")
    content = "\n".join(parts)
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()[:16]


# ── 主扫描器 ────────────────────────────────────────────────────────────────

class AstSkeletonBuilder:
    """项目 AST 骨架全量扫描器。"""

    def __init__(self, root: Path = _ROOT, scan_dirs=None):
        self.root = root
        self.scan_dirs = scan_dirs or _SCAN_DIRS

    def build(self) -> Dict[str, dict]:
        """扫描项目，返回 {rel_path: FileSkeleton dict} 字典。"""
        index: Dict[str, dict] = {}
        count = 0
        for dir_path, lang_hint in self.scan_dirs:
            abs_dir = self.root / dir_path
            if not abs_dir.exists():
                continue
            for file_path in self._iter_files(abs_dir):
                if count >= _MAX_FILES:
                    break
                rel = str(file_path.relative_to(self.root))
                skeleton = self._parse_file(file_path, rel, lang_hint)
                if skeleton and (skeleton.classes or skeleton.top_level_functions):
                    skeleton.fingerprint = _compute_fingerprint(skeleton)
                    index[rel] = asdict(skeleton)
                    count += 1
        return index

    def _iter_files(self, directory: Path):
        """递归遍历目录，yield 符合条件的文件。"""
        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            return
        for entry in entries:
            if entry.name in _IGNORE_DIRS or entry.name.startswith("."):
                continue
            if entry.is_dir():
                yield from self._iter_files(entry)
            elif entry.is_file():
                if entry.suffix in _PYTHON_EXTS or entry.suffix in _TS_EXTS:
                    yield entry

    def _parse_file(self, path: Path, rel: str, lang_hint: str) -> Optional[FileSkeleton]:
        """解析单个文件。"""
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
        if not source.strip():
            return None

        suffix = path.suffix
        if suffix in _PYTHON_EXTS:
            return _parse_python(source, rel)
        elif suffix in _TS_EXTS:
            return _parse_typescript(source, rel)
        return None


def build_ast_index(
    root: Path = _ROOT,
    output: Path = _OUTPUT,
    dry_run: bool = False,
) -> Dict[str, dict]:
    """构建并保存 AST 索引。"""
    builder = AstSkeletonBuilder(root=root)
    index = builder.build()

    if not dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return index


# ── CLI ─────────────────────────────────────────────────────────────────────

def _main():
    parser = argparse.ArgumentParser(description="MMS AST 骨架化器")
    parser.add_argument("--dry-run", action="store_true", help="只打印摘要，不写文件")
    parser.add_argument("--output", type=str, default=str(_OUTPUT), help="输出路径")
    parser.add_argument("--root", type=str, default=str(_ROOT), help="项目根目录")
    args = parser.parse_args()

    root = Path(args.root)
    output = Path(args.output)

    print(f"[ast_skeleton] 扫描项目: {root}")
    index = build_ast_index(root=root, output=output, dry_run=args.dry_run)

    # 摘要统计
    total_files = len(index)
    total_classes = sum(len(v.get("classes", [])) for v in index.values())
    total_methods = sum(
        len(c.get("methods", []))
        for v in index.values()
        for c in v.get("classes", [])
    )
    total_funcs = sum(len(v.get("top_level_functions", [])) for v in index.values())

    print("[ast_skeleton] 扫描完成:")
    print(f"  文件数: {total_files}")
    print(f"  类数:   {total_classes}")
    print(f"  方法数: {total_methods}")
    print(f"  函数数: {total_funcs}")

    if not args.dry_run:
        print(f"[ast_skeleton] 输出: {output}")
    else:
        print("[ast_skeleton] dry-run 模式，未写入文件")


if __name__ == "__main__":
    _main()
