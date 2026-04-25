"""
tree_sitter_parser.py — Tree-sitter AST 解析器（Sidecar 实现）

仅在 config.yaml 中 analysis.use_tree_sitter: true 且已安装
  pip install "mulan[tree_sitter]"
时才会被激活。未安装时抛出清晰的 ImportError，factory.py 负责降级。

设计约束：
  - Python 路径始终使用 ast 标准库，不走 Tree-sitter
  - 仅处理 Java 和 Go（正则解析的主要盲区语言）
  - 懒加载：模块 import 时不加载 tree-sitter，只在 extract_skeleton() 首次调用时初始化
  - 线程安全：_init_parser() 通过 functools.lru_cache 保证单例
"""
from __future__ import annotations

import functools
from typing import Any, List

from mms.analysis.ast_skeleton import (
    ClassSkeleton,
    FileSkeleton,
    MethodSkeleton,
)


def _require_tree_sitter() -> Any:
    """导入 tree_sitter，不可用时给出明确安装提示。"""
    try:
        import tree_sitter  # noqa: F401
        return tree_sitter
    except ImportError:
        raise ImportError(
            "Tree-sitter 未安装。请运行：pip install \"mulan[tree_sitter]\"\n"
            "或在 config.yaml 中设置 analysis.use_tree_sitter: false 禁用此功能。"
        )


@functools.lru_cache(maxsize=4)
def _get_java_parser() -> Any:
    """懒加载并缓存 Java Tree-sitter 解析器实例。"""
    _require_tree_sitter()
    try:
        import tree_sitter_java  # type: ignore[import]
        from tree_sitter import Language, Parser
        lang = Language(tree_sitter_java.language())
        parser = Parser(lang)
        return parser, lang
    except Exception as e:
        raise ImportError(f"tree-sitter-java 初始化失败: {e}") from e


@functools.lru_cache(maxsize=4)
def _get_go_parser() -> Any:
    """懒加载并缓存 Go Tree-sitter 解析器实例。"""
    _require_tree_sitter()
    try:
        import tree_sitter_go  # type: ignore[import]
        from tree_sitter import Language, Parser
        lang = Language(tree_sitter_go.language())
        parser = Parser(lang)
        return parser, lang
    except Exception as e:
        raise ImportError(f"tree-sitter-go 初始化失败: {e}") from e


# ── Java SCM 查询（S-Expression 风格） ──────────────────────────────────────

_JAVA_CLASS_QUERY = """
[
  (class_declaration name: (identifier) @class.name)
  (interface_declaration name: (identifier) @class.name)
  (enum_declaration name: (identifier) @class.name)
  (record_declaration name: (identifier) @class.name)
  (annotation_type_declaration name: (identifier) @class.name)
]
"""

_JAVA_METHOD_QUERY = """
[
  (method_declaration name: (identifier) @method.name)
  (constructor_declaration name: (identifier) @method.name)
]
"""

# ── Go SCM 查询 ──────────────────────────────────────────────────────────────

_GO_TYPE_QUERY = """
[
  (type_spec name: (type_identifier) @type.name)
]
"""

_GO_FUNC_QUERY = """
[
  (function_declaration name: (identifier) @func.name)
  (method_declaration name: (field_identifier) @method.name
                      receiver: (parameter_list
                        (parameter_declaration
                          type: [(pointer_type (type_identifier) @recv.type)
                                 (type_identifier) @recv.type
                                 (generic_type (type_identifier) @recv.type)])))
]
"""


def _run_query(ts_module: Any, lang: Any, query_str: str, node: Any) -> List[Any]:
    """运行 Tree-sitter 查询，返回 (node, capture_name) 列表。"""
    try:
        query = lang.query(query_str)
        return query.captures(node)
    except Exception:
        return []


class TreeSitterParser:
    """
    Tree-sitter AST 解析器（Sidecar 实现）。

    提供比正则解析更精准的结构提取，特别是对复杂泛型、注解、嵌套类的处理。
    降级策略由 factory.py 负责：tree-sitter 不可用时自动回退到 RegexFallbackParser。
    """

    def __init__(self, lang: str) -> None:
        if lang not in ("java", "go"):
            raise ValueError(f"TreeSitterParser 仅支持 java/go，收到: {lang!r}")
        self._lang = lang

    def extract_skeleton(self, source: str, rel_path: str) -> FileSkeleton:
        if self._lang == "java":
            return self._parse_java(source, rel_path)
        return self._parse_go(source, rel_path)

    def _parse_java(self, source: str, rel_path: str) -> FileSkeleton:
        parser, lang = _get_java_parser()
        tree = parser.parse(source.encode())
        skeleton = FileSkeleton(path=rel_path, lang="java")

        # 提取类/接口/enum/record
        class_captures = _run_query(None, lang, _JAVA_CLASS_QUERY, tree.root_node)
        class_names = [node.text.decode() for node, _ in class_captures if hasattr(node, "text")]

        # 提取方法（不区分归属，全部放在第一个类下，作为骨架对比用途）
        method_captures = _run_query(None, lang, _JAVA_METHOD_QUERY, tree.root_node)
        methods = [
            MethodSkeleton(name=node.text.decode(), signature="()")
            for node, _ in method_captures
            if hasattr(node, "text")
        ]

        # 构建简单类骨架（骨架对比场景不需要精确归属）
        for cname in class_names:
            cls = ClassSkeleton(name=cname, bases=[])
            skeleton.classes.append(cls)
        if skeleton.classes and methods:
            skeleton.classes[0].methods = methods

        return skeleton

    def _parse_go(self, source: str, rel_path: str) -> FileSkeleton:
        parser, lang = _get_go_parser()
        tree = parser.parse(source.encode())
        skeleton = FileSkeleton(path=rel_path, lang="go")

        # 提取 struct/interface 类型
        type_captures = _run_query(None, lang, _GO_TYPE_QUERY, tree.root_node)
        structs: dict[str, ClassSkeleton] = {}
        for node, cap_name in type_captures:
            if cap_name == "type.name" and hasattr(node, "text"):
                name = node.text.decode()
                structs[name] = ClassSkeleton(name=name, bases=["struct"])

        # 提取函数和方法（含 receiver 归属）
        func_captures = _run_query(None, lang, _GO_FUNC_QUERY, tree.root_node)
        recv_map: dict[str, str] = {}  # func_node_id -> recv_type
        func_names: list[tuple[str, str | None]] = []

        i = 0
        while i < len(func_captures):
            node, cap_name = func_captures[i]
            if cap_name in ("func.name", "method.name") and hasattr(node, "text"):
                func_name = node.text.decode()
                recv_type = None
                # 下一个 capture 可能是 recv.type
                if i + 1 < len(func_captures):
                    next_node, next_cap = func_captures[i + 1]
                    if next_cap == "recv.type" and hasattr(next_node, "text"):
                        recv_type = next_node.text.decode()
                        i += 1
                func_names.append((func_name, recv_type))
            i += 1

        for fname, recv in func_names:
            m = MethodSkeleton(name=fname, signature="()")
            if recv:
                if recv not in structs:
                    structs[recv] = ClassSkeleton(name=recv, bases=["struct"])
                structs[recv].methods.append(m)
            else:
                skeleton.top_level_functions.append(m)

        skeleton.classes = list(structs.values())
        return skeleton
