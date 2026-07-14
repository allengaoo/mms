from __future__ import annotations

from pathlib import Path

from mms.adapters import MarkdownRepository
from mms.memory.graph_resolver import MemoryGraph
from mms.ports import FrontMatterProjection, MemoryRecord


class CountingProjection(FrontMatterProjection):
    def __init__(self) -> None:
        self.parse_count = 0

    def parse(self, document: str, *, path=None):
        self.parse_count += 1
        return super().parse(document, path=path)


def _record(memory_id: str) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        body=f"# {memory_id}\n\nBody.",
        title=memory_id,
        object_type="Pattern",
        layer="DOMAIN",
        metadata={"id": memory_id, "layer": "DOMAIN", "object_type": "Pattern"},
    )


def test_second_graph_reuses_parsed_records_and_invalidates_one_file(
    tmp_path: Path,
) -> None:
    memory_root = tmp_path / "docs" / "memory"
    writer = MarkdownRepository(memory_root)
    writer.put(_record("PAT-CACHE-001"))
    writer.put(_record("PAT-CACHE-002"))
    MarkdownRepository._shared_cache.pop(memory_root.resolve(), None)

    projection = CountingProjection()
    first_repository = MarkdownRepository(memory_root, projection=projection)
    first = MemoryGraph(memory_root=memory_root, repository=first_repository)
    first._ensure_loaded()
    assert projection.parse_count == 2

    second_repository = MarkdownRepository(memory_root, projection=projection)
    second = MemoryGraph(memory_root=memory_root, repository=second_repository)
    second._ensure_loaded()
    assert projection.parse_count == 2
    assert set(second._nodes) == {"PAT-CACHE-001", "PAT-CACHE-002"}

    changed_path = memory_root / "shared" / "DOMAIN" / "PAT-CACHE-001.md"
    changed_path.write_text(
        changed_path.read_text(encoding="utf-8") + "\nChanged externally.\n",
        encoding="utf-8",
    )
    third_repository = MarkdownRepository(memory_root, projection=projection)
    third = MemoryGraph(memory_root=memory_root, repository=third_repository)
    third._ensure_loaded()
    assert projection.parse_count == 3
    assert "Changed externally." in third_repository.get("PAT-CACHE-001").body
