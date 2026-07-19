"""Tree-sitter 可选依赖的降级与语言覆盖。"""
from __future__ import annotations

import pytest

from mms.analysis.parsers.factory import get_parser
from mms.analysis.parsers.protocol import ASTParserProtocol
from mms.analysis.parsers.regex_parser import RegexFallbackParser


def _require_tree_sitter() -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_java")
    pytest.importorskip("tree_sitter_go")
    pytest.importorskip("tree_sitter_typescript")


def test_factory_falls_back_when_tree_sitter_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """强制启用 Tree-sitter 时，初始化/探测失败必须降级到 Regex。"""
    _require_tree_sitter()
    import mms.analysis.parsers.tree_sitter_parser as tsp

    class Boom:
        def __init__(self, lang: str) -> None:
            raise RuntimeError("simulated tree-sitter failure")

    monkeypatch.setattr(tsp, "TreeSitterParser", Boom)
    parser = get_parser("java", use_tree_sitter=True)
    assert isinstance(parser, RegexFallbackParser)
    sk = parser.extract_skeleton("class Demo {}", "Demo.java")
    assert [c.name for c in sk.classes] == ["Demo"]


@pytest.mark.parametrize("language", ["java", "go", "typescript", "tsx"])
def test_tsx_and_core_languages_dispatch_when_available(language: str) -> None:
    _require_tree_sitter()
    from mms.analysis.parsers.tree_sitter_parser import TreeSitterParser

    parser = get_parser(language, use_tree_sitter=True)
    assert isinstance(parser, TreeSitterParser)
    assert isinstance(parser, ASTParserProtocol)


def test_unsupported_language_still_raises() -> None:
    with pytest.raises(ValueError, match="仅支持"):
        get_parser("rust", use_tree_sitter=False)
