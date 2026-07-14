from pathlib import Path

import pytest

from mms.analysis.ast_skeleton import build_ast_index

FIXTURES = [
    "spring-boot-demo",
    "go-gin-demo",
    "typescript-nestjs-demo",
]


@pytest.mark.parametrize("fixture", FIXTURES)
def test_fingerprints_are_parser_independent(fixture: str) -> None:
    root = Path(__file__).resolve().parent / "fixtures" / fixture
    regex_index = build_ast_index(
        root,
        dry_run=True,
        use_tree_sitter=False,
    )
    tree_sitter_index = build_ast_index(
        root,
        dry_run=True,
        use_tree_sitter=True,
    )

    assert set(regex_index) == set(tree_sitter_index)
    assert {
        path: item["fingerprint"] for path, item in regex_index.items()
    } == {
        path: item["fingerprint"] for path, item in tree_sitter_index.items()
    }
