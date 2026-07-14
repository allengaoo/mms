from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mms.ports import FrontMatterProjection, NullVersionStore

ROOT = Path(__file__).resolve().parents[1]


def _split(document: str):
    assert document.startswith("---\n")
    _, raw, body = document.split("---", 2)
    return yaml.safe_load(raw) or {}, body.lstrip("\n")


def test_frontmatter_projection_preserves_all_existing_fields() -> None:
    projection = FrontMatterProjection()
    paths = [
        path
        for path in (ROOT / "docs" / "memory").rglob("*.md")
        if not {"_system", "templates", "archive", "_archived"} & set(path.parts)
    ]
    checked = 0
    for path in paths:
        document = path.read_text(encoding="utf-8", errors="ignore")
        try:
            original_front_matter, original_body = _split(document)
            record = projection.parse(document, path=path)
        except (AssertionError, ValueError, yaml.YAMLError):
            continue
        rendered = projection.render(record)
        projected_front_matter, projected_body = _split(rendered)
        assert projected_front_matter == original_front_matter, path
        assert projected_body == original_body, path
        checked += 1
    assert checked >= 20


def test_projection_retains_unknown_ontology_fields() -> None:
    document = """---
id: PAT-X-001
object_type: Pattern
layer: DOMAIN
custom_schema_field:
  nested: [one, two]
---
# A pattern

Body.
"""
    projection = FrontMatterProjection()
    record = projection.parse(document)
    front_matter, body = projection.from_record(record)

    assert front_matter["custom_schema_field"] == {"nested": ["one", "two"]}
    assert body.startswith("# A pattern")


def test_null_version_store_is_explicitly_unsupported() -> None:
    store = NullVersionStore()
    with pytest.raises(NotImplementedError, match="does not implement"):
        store.snapshot("before-change")
