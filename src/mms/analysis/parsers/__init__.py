"""
mms.analysis.parsers — 多语言 AST 解析器适配层

对外只暴露 get_parser()，调用方无需关心底层使用正则还是 Tree-sitter。

使用方式：
    from mms.analysis.parsers import get_parser
    parser = get_parser("java")
    skeleton = parser.extract_skeleton(source, "src/Foo.java")
"""
from mms.analysis.parsers.factory import get_parser

__all__ = ["get_parser"]
