"""Storage-neutral contracts for the MMS memory domain."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, runtime_checkable


@dataclass
class MemoryRecord:
    """Canonical in-process representation of one memory document.

    ``metadata`` retains fields that are not yet promoted to first-class
    attributes.  This is intentional: ontology schemas evolve independently of
    storage adapters, so a read/write round trip must never discard an unknown
    front-matter key.
    """

    id: str
    body: str
    title: str = ""
    object_type: str = ""
    layer: str = ""
    tier: str = "warm"
    tags: List[str] = field(default_factory=list)
    related_to: List[Any] = field(default_factory=list)
    cites_files: List[str] = field(default_factory=list)
    impacts: List[str] = field(default_factory=list)
    about_concepts: List[str] = field(default_factory=list)
    contradicts: List[str] = field(default_factory=list)
    derived_from: List[str] = field(default_factory=list)
    version: int = 1
    access_count: int = 0
    created_at: Any = None
    updated_at: Any = None
    provenance: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    path: Optional[Path] = None

    def copy(self, **changes: Any) -> "MemoryRecord":
        return replace(self, **changes)


@dataclass(frozen=True)
class MemoryQuery:
    text: str = ""
    layer: Optional[str] = None
    tier: Optional[str] = None
    object_type: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    limit: int = 20


@runtime_checkable
class MemoryRepository(Protocol):
    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        ...

    def put(self, record: MemoryRecord) -> MemoryRecord:
        ...

    def delete(self, memory_id: str, *, archive: bool = True) -> bool:
        ...

    def list_ids(
        self,
        *,
        layer: Optional[str] = None,
        tier: Optional[str] = None,
        object_type: Optional[str] = None,
    ) -> List[str]:
        ...

    def query(self, query: MemoryQuery) -> List[MemoryRecord]:
        ...

    def update_stats(
        self,
        memory_id: str,
        *,
        access_count: Optional[int] = None,
        tier: Optional[str] = None,
    ) -> bool:
        ...

    def load_all(self) -> Iterable[MemoryRecord]:
        ...
