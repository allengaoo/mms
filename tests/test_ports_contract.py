from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from mms.adapters import MarkdownRepository
from mms.ports import MemoryQuery, MemoryRecord, MemoryRepository


@pytest.fixture(params=["markdown"])
def repository_factory(
    request,
) -> Callable[[Path], MemoryRepository]:
    # Memoria 已 No-Go；契约矩阵仅保留 markdown。见 test_memory_backend_boundary.py。
    factories = {
        "markdown": lambda root: MarkdownRepository(root / "docs" / "memory"),
    }
    return factories[request.param]


def _memory(memory_id: str, **changes) -> MemoryRecord:
    record = MemoryRecord(
        id=memory_id,
        body=f"# {memory_id}\n\nRepository contract body.",
        title=memory_id,
        object_type="Pattern",
        layer="DOMAIN",
        tier="warm",
        tags=["contract"],
        metadata={"id": memory_id, "custom": {"roundtrip": True}},
    )
    return record.copy(**changes)


def test_repository_contract(
    tmp_path: Path,
    repository_factory: Callable[[Path], MemoryRepository],
) -> None:
    repository = repository_factory(tmp_path)

    first = repository.put(_memory("PAT-CONTRACT-001"))
    assert first.version == 1
    assert repository.get(first.id).metadata["custom"] == {  # type: ignore[union-attr]
        "roundtrip": True
    }

    second = repository.put(first.copy(body=first.body + "\nChanged."))
    assert second.version == 2
    assert repository.list_ids(layer="DOMAIN") == [first.id]
    assert repository.list_ids(tier="hot") == []
    assert repository.list_ids(object_type="Pattern") == [first.id]
    assert repository.query(MemoryQuery(text="contract body"))[0].id == first.id

    assert repository.update_stats(first.id, access_count=3, tier="hot")
    updated = repository.get(first.id)
    assert updated is not None
    assert updated.access_count == 3
    assert updated.tier == "hot"
    assert {record.id for record in repository.load_all()} == {first.id}

    assert repository.delete(first.id, archive=True)
    assert repository.get(first.id) is None
    assert not repository.delete(first.id)
