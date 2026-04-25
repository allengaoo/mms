"""
protocol.py — ASTParserProtocol 接口定义

所有解析器实现（RegexFallbackParser、TreeSitterParser）必须满足此协议。
调用方只依赖此协议，不依赖具体实现，从而实现可插拔替换。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from mms.analysis.ast_skeleton import FileSkeleton


@runtime_checkable
class ASTParserProtocol(Protocol):
    """
    多语言 AST 解析器协议。

    实现类必须提供 extract_skeleton()，将源码转换为 FileSkeleton 对象。
    FileSkeleton 包含：类列表、顶层函数列表、import 列表等结构信息。
    """

    def extract_skeleton(self, source: str, rel_path: str) -> "FileSkeleton":
        """
        从源码提取骨架结构。

        Args:
            source:   源文件完整文本内容
            rel_path: 相对路径（用于 FileSkeleton.path 字段，影响 cache key）

        Returns:
            FileSkeleton 对象，包含 classes、top_level_functions、imports 等字段
        """
        ...
