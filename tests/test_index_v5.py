from __future__ import annotations

import json
from pathlib import Path

from mms.adapters import MarkdownRepository
from mms.memory.injector import MemoryInjector
from mms.ports import MemoryRecord


def _record(memory_id: str, *, layer: str = "DOMAIN") -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        title="Domain aggregate repository",
        body="# Domain aggregate repository\n\n## HOW\nUse a repository.\n",
        object_type="Pattern",
        layer=layer,
        tier="warm",
        tags=["domain", "aggregate"],
        metadata={
            "id": memory_id,
            "object_type": "Pattern",
            "layer": layer,
            "tier": "warm",
            "tags": ["domain", "aggregate"],
        },
    )


def _entries(index: dict):
    return [
        memory
        for layer in index["tree"]
        for type_node in layer.get("nodes", [])
        for memory in type_node.get("memories", [])
    ]


def test_repository_write_hook_creates_and_updates_v5_index(
    tmp_path: Path,
) -> None:
    memory_root = tmp_path / "docs" / "memory"
    repository = MarkdownRepository(memory_root)

    repository.put(_record("PAT-INDEX-001"))
    index_path = memory_root / "MEMORY_INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["schema_version"] == "5.0"
    assert _entries(index)[0]["layer"] == "DOMAIN"
    assert _entries(index)[0]["object_type"] == "Pattern"

    existing = repository.get("PAT-INDEX-001")
    assert existing is not None
    repository.put(existing.copy(layer="APP"))
    entries = _entries(json.loads(index_path.read_text(encoding="utf-8")))
    assert len(entries) == 1
    assert entries[0]["layer"] == "APP"

    repository.delete("PAT-INDEX-001")
    assert _entries(json.loads(index_path.read_text(encoding="utf-8"))) == []


def test_injector_reads_single_v5_index(tmp_path: Path) -> None:
    memory_root = tmp_path / "docs" / "memory"
    repository = MarkdownRepository(memory_root)
    repository.put(_record("PAT-INDEX-001"))

    injector = MemoryInjector(project_root=tmp_path, repository=repository)
    result = injector.inject("domain aggregate repository", top_k=3)

    assert [memory.memory_id for memory in result.memories] == ["PAT-INDEX-001"]
    assert result.detected_layers == ["DOMAIN"]


def test_index_bytes_are_stable_after_equivalent_rebuild(
    tmp_path: Path,
) -> None:
    memory_root = tmp_path / "docs" / "memory"
    repository = MarkdownRepository(memory_root)
    repository.put(_record("PAT-INDEX-002"))
    before = (memory_root / "MEMORY_INDEX.json").read_bytes()

    repository._indexer.rebuild(
        repository.load_all(),
        memory_root,
    )
    after = (memory_root / "MEMORY_INDEX.json").read_bytes()
    assert after == before
