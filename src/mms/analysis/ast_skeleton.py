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
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_OUTPUT = _ROOT / "docs" / "memory" / "_system" / "ast_index.json"

# ── 可配置常量 ────────────────────────────────────────────────────────────────

try:
    sys.path.insert(0, str(_HERE))
    from mms.utils.mms_config import cfg as _cfg  # type: ignore[import]
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
_JAVA_EXTS = {".java"}
_GO_EXTS = {".go"}


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


# ── Java 正则骨架提取器 ───────────────────────────────────────────────────────

def _parse_java(source: str, rel_path: str) -> FileSkeleton:
    """
    Java 正则骨架提取器（不依赖 JDK/javalang）。

    提取内容：
      - 顶层 public class / interface / enum 声明（含 extends/implements）
      - 方法签名：访问修饰符 + 返回类型 + 方法名 + 参数类型列表
      - import 语句中的顶层类型名

    局限性：正则不处理嵌套类和泛型复杂情况，适合骨架对比而非完整 AST。
    """
    skeleton = FileSkeleton(path=rel_path, lang="java")

    # imports
    for m in re.finditer(r'^import\s+(?:static\s+)?[\w.]+\.(\w+)\s*;', source, re.MULTILINE):
        skeleton.imports.append(m.group(1))
    skeleton.imports = sorted(set(skeleton.imports))

    # class / interface / enum declarations
    class_pat = re.compile(
        r'(?:public\s+)?(?:abstract\s+)?(?:final\s+)?'
        r'(class|interface|enum)\s+(\w+)'
        r'(?:\s+extends\s+([\w<>, ]+?))?'
        r'(?:\s+implements\s+([\w<>, ]+?))?'
        r'\s*\{',
        re.MULTILINE,
    )
    for m in class_pat.finditer(source):
        kind, name = m.group(1), m.group(2)
        bases = []
        if m.group(3):
            bases.extend(b.strip().split('<')[0] for b in m.group(3).split(','))
        if m.group(4):
            bases.extend(b.strip().split('<')[0] for b in m.group(4).split(','))
        cls_skel = ClassSkeleton(name=name, bases=[b for b in bases if b])

        # methods within approximate class body
        # Use a simple heuristic: collect methods until next class-level brace
        cls_start = m.end()
        # Find methods: access modifier(s) + return type + name + params
        method_pat = re.compile(
            r'(?:(?:public|protected|private|static|final|abstract|synchronized|native|default)\s+){0,4}'
            r'(?!class|interface|enum)'
            r'([\w<>\[\]]+(?:\s*\[\])*)\s+'   # return type
            r'(\w+)\s*'                        # method name
            r'\(([^)]*)\)',                    # params
            re.MULTILINE,
        )
        for mm in method_pat.finditer(source[cls_start:cls_start + 8000]):
            ret_type = mm.group(1).strip()
            meth_name = mm.group(2)
            params_raw = mm.group(3).strip()
            # Extract only types from params (strip param names)
            param_types = []
            for part in params_raw.split(','):
                part = part.strip()
                if not part:
                    continue
                tokens = part.split()
                # Last token is name, second-to-last (or earlier) is type
                type_part = tokens[-2] if len(tokens) >= 2 else tokens[0] if tokens else '_'
                param_types.append(type_part.rstrip('[]'))
            sig = f"({', '.join(param_types)}) -> {ret_type}"
            cls_skel.methods.append(MethodSkeleton(name=meth_name, signature=sig))

        skeleton.classes.append(cls_skel)

    return skeleton


# ── Go 正则骨架提取器 ─────────────────────────────────────────────────────────

def _parse_go(source: str, rel_path: str) -> FileSkeleton:
    """
    Go 正则骨架提取器（不依赖 go/ast）。

    提取内容：
      - struct / interface 类型声明
      - func 声明（含 receiver，即方法）
      - import 的包名

    局限性：正则不处理泛型（Go 1.18+）的复杂情况，适合骨架对比。
    """
    skeleton = FileSkeleton(path=rel_path, lang="go")

    # package imports
    for m in re.finditer(r'^\s+"(?:[\w./]+/)?([\w]+)"', source, re.MULTILINE):
        skeleton.imports.append(m.group(1))
    skeleton.imports = sorted(set(skeleton.imports))

    # struct / interface declarations
    type_pat = re.compile(
        r'^type\s+(\w+)\s+(struct|interface)\s*\{',
        re.MULTILINE,
    )
    structs: Dict[str, ClassSkeleton] = {}
    for m in type_pat.finditer(source):
        name, kind = m.group(1), m.group(2)
        bases = [kind]  # 用 "struct" 或 "interface" 作为 base 标记
        structs[name] = ClassSkeleton(name=name, bases=bases)

    # func declarations (包含 receiver 的方法 + 顶层函数)
    # Pattern: func (recv RecvType) MethodName(params) RetType
    # or:      func FuncName(params) RetType
    func_pat = re.compile(
        r'^func\s+'
        r'(?:\(\s*\w+\s+\*?(\w+)\s*\)\s*)?'  # optional receiver: (r *RecvType)
        r'(\w+)\s*'                             # func/method name
        r'\(([^)]*)\)'                          # params
        r'(?:\s*(?:\([^)]*\)|[\w\[\]*]+))?',   # optional return type
        re.MULTILINE,
    )
    for m in func_pat.finditer(source):
        receiver = m.group(1)  # may be None
        name = m.group(2)
        params_raw = m.group(3).strip()

        # Extract type-only signature
        param_types = []
        for part in params_raw.split(','):
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            # Go params: "name type" or "type" only
            type_part = tokens[-1] if tokens else '_'
            type_part = type_part.lstrip('*[]')
            if type_part:
                param_types.append(type_part)

        sig = f"({', '.join(param_types)})"

        if receiver and receiver in structs:
            structs[receiver].methods.append(MethodSkeleton(name=name, signature=sig))
        elif receiver:
            # receiver type not yet seen (possibly defined elsewhere)
            if receiver not in structs:
                structs[receiver] = ClassSkeleton(name=receiver, bases=["struct"])
            structs[receiver].methods.append(MethodSkeleton(name=name, signature=sig))
        else:
            skeleton.top_level_functions.append(MethodSkeleton(name=name, signature=sig))

    skeleton.classes = list(structs.values())
    return skeleton


# ── 指纹计算 ────────────────────────────────────────────────────────────────

def _semantic_sig(node: "ast.FunctionDef | ast.AsyncFunctionDef") -> str:
    """
    语义签名：仅保留参数类型注解和返回类型，剥离参数名和默认值。

    目的：避免因重命名参数或修改默认值（语义不变）导致的"虚假漂移"。
    格式：(Type1, Type2, *Type3, **Type4) -> RetType
    """
    args = node.args
    type_parts = []

    for arg in args.args:
        ann = _unparse_annotation(arg.annotation)
        type_parts.append(ann if ann else "_")

    if args.vararg:
        ann = _unparse_annotation(args.vararg.annotation)
        type_parts.append(f"*{ann}" if ann else "*_")

    if args.kwarg:
        ann = _unparse_annotation(args.kwarg.annotation)
        type_parts.append(f"**{ann}" if ann else "**_")

    ret = _unparse_annotation(node.returns)
    ret_str = f" -> {ret}" if ret else ""
    return f"({', '.join(type_parts)}){ret_str}"


def _strip_param_names(sig: str) -> str:
    """
    从签名字符串中剥离参数名，只保留类型注解。

    输入:  (self, name: str, value: int = 0, *args: Any, **kw: dict) -> None
    输出:  (_, str, int, *Any, **dict) -> None

    这样当开发者重命名参数（name→n）或修改默认值时，哈希不变，
    避免 Black/Ruff 格式化或无意义改动触发"虚假漂移"。
    """
    import re as _re
    # 分离参数体和返回值
    m = _re.match(r'^\((.*)\)(.*)', sig, _re.DOTALL)
    if not m:
        return sig
    params_str, ret_str = m.group(1), m.group(2)
    if not params_str.strip():
        return f"(){ret_str}"

    result_params = []
    for param in params_str.split(','):
        param = param.strip()
        if not param:
            continue
        # *args / **kwargs 前缀
        prefix = ''
        if param.startswith('**'):
            prefix = '**'
            param = param[2:]
        elif param.startswith('*'):
            prefix = '*'
            param = param[1:]

        # 去掉默认值 (= ...) 部分
        param = _re.sub(r'\s*=.*$', '', param).strip()
        # 提取类型注解：name: Type → Type
        if ':' in param:
            type_part = param.split(':', 1)[1].strip()
        else:
            type_part = '_'  # 无类型注解用 _ 占位
        result_params.append(prefix + type_part)

    return f"({', '.join(result_params)}){ret_str}"


def _compute_fingerprint(skeleton: FileSkeleton) -> str:
    """
    基于语义骨架计算 SHA-256 指纹（用于 ast_diff 变更检测）。

    语义哈希策略（防"虚假漂移"）：
      - 只对类名、方法名、参数类型注解和返回类型取哈希
      - 通过 _strip_param_names() 剥离参数名和默认值
      - 参数重命名、加注释、Black/Ruff 格式化均不影响哈希
    """
    parts = []
    for cls in sorted(skeleton.classes, key=lambda c: c.name):
        parts.append(f"class:{cls.name}({','.join(cls.bases)})")
        for m in sorted(cls.methods, key=lambda x: x.name):
            sem_sig = _strip_param_names(m.signature)
            parts.append(f"  method:{m.name}{sem_sig}")
    for fn in sorted(skeleton.top_level_functions, key=lambda x: x.name):
        sem_sig = _strip_param_names(fn.signature)
        parts.append(f"func:{fn.name}{sem_sig}")
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
                if entry.suffix in (_PYTHON_EXTS | _TS_EXTS | _JAVA_EXTS | _GO_EXTS):
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
        elif suffix in _JAVA_EXTS:
            return _parse_java(source, rel)
        elif suffix in _GO_EXTS:
            return _parse_go(source, rel)
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
