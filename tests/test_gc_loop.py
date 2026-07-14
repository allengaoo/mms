from __future__ import annotations

import json
from pathlib import Path

from mms.adapters import MarkdownRepository
from mms.memory.entropy_scan import run_gc
from mms.memory.injector import MemoryInjector
from mms.memory import private as private_memory
from mms.ports import MemoryRecord


def _memory(memory_id: str, tier: str, drift: bool) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        title="Domain aggregate lifecycle",
        body="# Domain aggregate lifecycle\n\n## HOW\nKeep lifecycle deterministic.",
        object_type="Pattern",
        layer="APP",
        tier=tier,
        access_count=0,
        tags=["domain", "aggregate"],
        metadata={
            "id": memory_id,
            "object_type": "Pattern",
            "layer": "APP",
            "tier": tier,
            "access_count": 0,
            "last_accessed": "2020-01-01",
            "drift_suspected": drift,
        },
    )


def _index_ids(index_path: Path):
    index = json.loads(index_path.read_text(encoding="utf-8"))
    return {
        memory["id"]
        for layer in index["tree"]
        for type_node in layer.get("nodes", [])
        for memory in type_node.get("memories", [])
    }


def test_gc_updates_files_and_index_through_repository(tmp_path: Path) -> None:
    memory_root = tmp_path / "docs" / "memory"
    repository = MarkdownRepository(memory_root)
    repository.put(_memory("PAT-GC-HOT", "hot", False))
    repository.put(_memory("PAT-GC-COLD", "cold", True))

    stats = run_gc(
        memory_root,
        current_ep="EP-200",
        repository=repository,
    )

    assert stats["downgraded"] == 1
    assert stats["archived"] == 1
    assert repository.get("PAT-GC-HOT").tier == "warm"  # type: ignore[union-attr]
    assert repository.get("PAT-GC-COLD") is None
    assert _index_ids(memory_root / "MEMORY_INDEX.json") == {"PAT-GC-HOT"}


def test_private_promote_is_immediately_retrievable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    memory_root = tmp_path / "docs" / "memory"
    private_root = memory_root / "private"
    monkeypatch.setattr(private_memory, "_MMS_ROOT", tmp_path)
    monkeypatch.setattr(private_memory, "_PRIVATE_DIR", private_root)
    monkeypatch.setattr(private_memory, "_SHARED_DIR", memory_root / "shared")
    repository = MarkdownRepository(memory_root)

    private_memory.init_ep("EP-200")
    note = private_memory.add_note(
        "EP-200",
        "Domain aggregate repository",
        "Use repository boundaries.",
    )
    relative_note = str(note.relative_to(private_root / "EP-200"))
    private_memory.promote_note(
        "EP-200",
        relative_note,
        "DOMAIN",
        "PAT-PROMOTE-001",
        repository=repository,
    )

    result = MemoryInjector(
        project_root=tmp_path,
        repository=repository,
    ).inject("domain aggregate repository")
    assert "PAT-PROMOTE-001" in [memory.memory_id for memory in result.memories]
