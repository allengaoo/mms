from pathlib import Path

import pytest

from mms.analysis.ast_skeleton import (
    AstSkeletonBuilder,
    _parse_go,
    _parse_java,
    _parse_typescript,
)
from mms.analysis.parsers.regex_parser import RegexFallbackParser
from mms.analysis.parsers.tree_sitter_parser import TreeSitterParser


@pytest.mark.parametrize(
    ("language", "source", "legacy"),
    [
        ("java", "class Demo { public void run() {} }", _parse_java),
        ("go", "package demo\ntype Demo struct{}\nfunc (d *Demo) Run() {}", _parse_go),
        ("typescript", "export class Demo { run(): void {} }", _parse_typescript),
    ],
)
def test_regex_fallback_remains_field_equivalent(language, source, legacy) -> None:
    assert RegexFallbackParser(language).extract_skeleton(
        source,
        "demo",
    ) == legacy(source, "demo")


@pytest.mark.parametrize("language", ["java", "go", "typescript"])
def test_factory_dispatches_tree_sitter_when_forced(language) -> None:
    from mms.analysis.parsers.factory import get_parser

    assert isinstance(get_parser(language, use_tree_sitter=True), TreeSitterParser)
    assert isinstance(
        get_parser(language, use_tree_sitter=False),
        RegexFallbackParser,
    )


def test_builder_routes_non_python_languages_through_factory(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "Demo.java").write_text(
        "@Service class Demo { public void run() {} }",
        encoding="utf-8",
    )
    builder = AstSkeletonBuilder(
        root=tmp_path,
        scan_dirs=[("src", "java")],
        use_tree_sitter=True,
    )
    result = builder.build()
    assert result["src/Demo.java"]["classes"][0]["annotations"] == ["Service"]
