"""
factory.py — AST 解析器工厂

根据配置决定返回 TreeSitterParser 还是 RegexFallbackParser。
调用方只调用 get_parser(lang)，无需关心底层实现。

降级策略：
  1. use_tree_sitter=False (默认) → 直接返回 RegexFallbackParser
  2. use_tree_sitter=True 但 tree-sitter 未安装 → 打印警告并降级到 RegexFallbackParser
  3. use_tree_sitter=True 且 lang 不在 tree_sitter_languages 列表中 → RegexFallbackParser
  4. use_tree_sitter=True 且已安装且 lang 在列表中 → TreeSitterParser
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mms.analysis.parsers.protocol import ASTParserProtocol

logger = logging.getLogger(__name__)


def get_parser(lang: str, use_tree_sitter: bool | None = None) -> "ASTParserProtocol":
    """
    获取指定语言的 AST 解析器。

    Args:
        lang:            目标语言，如 "java"、"go"
        use_tree_sitter: 是否强制使用 Tree-sitter。
                         None（默认）：从 cfg 读取配置；
                         True/False：显式覆盖配置（用于测试）

    Returns:
        满足 ASTParserProtocol 的解析器实例
    """
    from mms.analysis.parsers.regex_parser import RegexFallbackParser

    if lang not in ("java", "go"):
        raise ValueError(
            f"get_parser() 仅支持 java/go（Python 使用 ast 标准库，无需此工厂）。"
            f"收到: {lang!r}"
        )

    # 决定是否尝试 Tree-sitter
    if use_tree_sitter is None:
        try:
            from mms.utils.mms_config import cfg
            use_ts = cfg.analysis_use_tree_sitter
            ts_langs = cfg.analysis_tree_sitter_languages
        except Exception:
            use_ts = False
            ts_langs = []
    else:
        use_ts = use_tree_sitter
        ts_langs = ["java", "go"]

    if not use_ts or lang not in ts_langs:
        return RegexFallbackParser(lang)

    # 尝试加载 Tree-sitter
    try:
        from mms.analysis.parsers.tree_sitter_parser import TreeSitterParser
        parser = TreeSitterParser(lang)
        # 做一次最小测试，确认 tree-sitter 库已正确安装
        parser.extract_skeleton("", f"_probe.{lang}")
        return parser
    except (ImportError, Exception) as e:
        logger.warning(
            "[Mulan] Tree-sitter 加载失败，自动降级为正则解析器。原因: %s\n"
            "  提示：运行 pip install 'mulan[tree_sitter]' 安装 Tree-sitter 依赖。",
            e,
        )
        return RegexFallbackParser(lang)
