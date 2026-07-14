from __future__ import annotations

from pathlib import Path

from mms.adapters import MarkdownRepository
from mms.memory.graph_resolver import MemoryGraph
from mms.ports import MemoryQuery, MemoryRecord, MemoryRepository


def _record(memory_id: str = "PAT-TEST-001") -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        object_type="Pattern",
        layer="DOMAIN",
        tier="warm",
        title="Repository pattern",
        body="# Repository pattern\n\nUse a repository boundary.",
        tags=["repository", "domain"],
        metadata={"id": memory_id, "custom_field": {"keep": True}},
    )


def test_markdown_repository_satisfies_protocol(tmp_path: Path) -> None:
    repository = MarkdownRepository(tmp_path / "docs" / "memory")
    assert isinstance(repository, MemoryRepository)


def test_put_get_update_and_archive(tmp_path: Path) -> None:
    memory_root = tmp_path / "docs" / "memory"
    repository = MarkdownRepository(memory_root)

    first = repository.put(_record())
    assert first.version == 1
    assert first.path == memory_root / "shared" / "DOMAIN" / "PAT-TEST-001.md"

    loaded = repository.get(first.id)
    assert loaded is not None
    assert loaded.metadata["custom_field"] == {"keep": True}

    second = repository.put(loaded.copy(body=loaded.body + "\n\nUpdated."))
    assert second.version == 2
    assert repository.get(first.id).body.endswith("Updated.")  # type: ignore[union-attr]

    assert repository.delete(first.id, archive=True)
    assert repository.get(first.id) is None
    assert (
        memory_root / "archive" / "shared" / "DOMAIN" / "PAT-TEST-001.md"
    ).exists()


def test_filters_query_and_stats(tmp_path: Path) -> None:
    repository = MarkdownRepository(tmp_path / "docs" / "memory")
    repository.put(_record("PAT-TEST-001"))
    repository.put(
        _record("DEC-TEST-001").copy(
            object_type="Decision",
            layer="CC",
            tags=["architecture"],
            body="# Architecture choice\n\nKeep adapters behind ports.",
        )
    )

    assert repository.list_ids(layer="DOMAIN") == ["PAT-TEST-001"]
    assert repository.list_ids(object_type="Decision") == ["DEC-TEST-001"]
    assert [
        record.id
        for record in repository.query(MemoryQuery(text="adapters ports"))
    ] == ["DEC-TEST-001"]

    assert repository.update_stats(
        "PAT-TEST-001",
        access_count=4,
        tier="hot",
    )
    updated = repository.get("PAT-TEST-001")
    assert updated is not None
    assert updated.access_count == 4
    assert updated.tier == "hot"
    assert updated.version == 2


def test_rejects_path_traversal_id(tmp_path: Path) -> None:
    repository = MarkdownRepository(tmp_path / "docs" / "memory")
    record = _record("../outside")

    try:
        repository.put(record)
    except ValueError as error:
        assert "unsafe memory id" in str(error)
    else:
        raise AssertionError("path traversal id should be rejected")


def test_real_repository_matches_memory_graph_ids() -> None:
    memory_root = Path(__file__).resolve().parents[1] / "docs" / "memory"
    repository = MarkdownRepository(memory_root)
    graph = MemoryGraph(memory_root=memory_root, repository=repository)
    graph._ensure_loaded()

    assert set(repository.list_ids()) == set(graph._nodes)
