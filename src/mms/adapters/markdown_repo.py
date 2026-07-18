"""Markdown implementation of the storage-neutral memory repository."""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, Dict, Iterable, List, Optional, Tuple

from mms.core.writer import atomic_write
from mms.core.sanitize import sanitize_or_raise
from mms.core.indexer import IncrementalIndexer
from mms.ports.projection import FrontMatterProjection
from mms.ports.repository import MemoryQuery, MemoryRecord

_SKIP_DIRS = {"_system", "templates", "archive", "_archived", "seed_packs", "private"}
_SKIP_FILES = {"CONTRIBUTING.md", "README.md"}
_UNIVERSAL_LAYERS = {
    "ADAPTER",
    "APP",
    "DOMAIN",
    "PLATFORM",
    "CC",
    "CC_testing",
    "CC_governance",
    "BIZ",
    "Ops",
}
_LEGACY_LAYER_MAP = {
    "L1": "PLATFORM",
    "L2": "ADAPTER",
    "L3": "DOMAIN",
    "L4": "APP",
    "L5": "ADAPTER",
}


class MarkdownRepository:
    _cache_lock: ClassVar[threading.RLock] = threading.RLock()
    _shared_cache: ClassVar[
        Dict[Path, Tuple[Dict[Path, Tuple[int, int]], Dict[Path, MemoryRecord]]]
    ] = {}

    def __init__(
        self,
        memory_root: Path,
        *,
        projection: Optional[FrontMatterProjection] = None,
        indexer: Optional[IncrementalIndexer] = None,
    ) -> None:
        self.memory_root = Path(memory_root).resolve()
        self.shared_root = self.memory_root / "shared"
        self.projection = projection or FrontMatterProjection()
        self._records: Optional[Dict[str, MemoryRecord]] = None
        self._index_file = self.memory_root / "MEMORY_INDEX.json"
        self._indexer = indexer or IncrementalIndexer(self._index_file)

    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        self._ensure_loaded()
        return self._records.get(memory_id) if self._records is not None else None

    def put(self, record: MemoryRecord) -> MemoryRecord:
        self._validate_id(record.id)
        existing = self.get(record.id)
        now = datetime.now(timezone.utc).isoformat()
        # Explicit path wins (allows relocating seed templates → shared/)
        if record.path is not None:
            target = self._target_path(record)
            version = max(record.version, (existing.version + 1) if existing else 1)
            created_at = record.created_at or (existing.created_at if existing else now)
        elif existing is not None:
            target = existing.path
            version = existing.version + 1
            created_at = record.created_at or existing.created_at
        else:
            target = self._target_path(record)
            version = max(record.version, 1)
            created_at = record.created_at or now
        if target is None:
            raise ValueError(f"cannot resolve target path for memory {record.id}")

        stored = record.copy(
            version=version,
            created_at=created_at,
            updated_at=now,
            path=target,
        )
        stored = self._sanitize_record(stored, target)
        self._ensure_index()
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, self.projection.render(stored))
        if self._records is not None:
            self._records[stored.id] = stored
        self._indexer.add_memory(self._index_meta(stored))
        self._publish_shared_cache()
        return stored

    def import_raw(self, content: str, target: Path) -> MemoryRecord:
        """Write a memory document as-is (preserve front-matter formatting) and index it.

        Used by v3.1 seed install so seed templates keep inline ``tags: [...]``
        compatible with ``validate.py``'s simple front-matter parser.
        """
        target = Path(target)
        if not target.is_absolute():
            target = (self.memory_root / target).resolve()
        try:
            target.relative_to(self.memory_root)
        except ValueError as exc:
            raise ValueError(f"import target outside memory root: {target}") from exc

        record = self.projection.parse(content, path=target)
        self._validate_id(record.id)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_index()
        atomic_write(target, content)
        stored = record.copy(path=target)
        if self._records is not None:
            self._records[stored.id] = stored
        self._indexer.add_memory(self._index_meta(stored))
        self._publish_shared_cache()
        return stored

    def delete(self, memory_id: str, *, archive: bool = True) -> bool:
        record = self.get(memory_id)
        if record is None or record.path is None:
            return False
        self._ensure_index()
        if not archive:
            record.path.unlink()
            if self._records is not None:
                self._records.pop(memory_id, None)
            self._indexer.remove_memory(memory_id)
            self._publish_shared_cache()
            return True

        try:
            relative = record.path.relative_to(self.memory_root)
        except ValueError:
            relative = Path(record.path.name)
        target = self.memory_root / "archive" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
            target = target.with_name(f"{target.stem}.{timestamp}{target.suffix}")
        os.replace(record.path, target)
        if self._records is not None:
            self._records.pop(memory_id, None)
        self._indexer.remove_memory(memory_id)
        self._publish_shared_cache()
        return True

    def list_ids(
        self,
        *,
        layer: Optional[str] = None,
        tier: Optional[str] = None,
        object_type: Optional[str] = None,
    ) -> List[str]:
        return [
            record.id
            for record in self.load_all()
            if self._matches_filters(
                record,
                layer=layer,
                tier=tier,
                object_type=object_type,
            )
        ]

    def query(self, query: MemoryQuery) -> List[MemoryRecord]:
        terms = [term for term in query.text.lower().split() if term]
        ranked = []
        for record in self.load_all():
            if not self._matches_filters(
                record,
                layer=query.layer,
                tier=query.tier,
                object_type=query.object_type,
            ):
                continue
            if query.tags and not set(query.tags).issubset(set(record.tags)):
                continue
            haystack = " ".join(
                [record.id, record.title, record.body, " ".join(record.tags)]
            ).lower()
            if terms and not all(term in haystack for term in terms):
                continue
            score = sum(haystack.count(term) for term in terms)
            ranked.append((score, record.id, record))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in ranked[: max(query.limit, 0)]]

    def update_stats(
        self,
        memory_id: str,
        *,
        access_count: Optional[int] = None,
        tier: Optional[str] = None,
    ) -> bool:
        record = self.get(memory_id)
        if record is None:
            return False
        changes = {}
        if access_count is not None:
            changes["access_count"] = access_count
        if tier is not None:
            changes["tier"] = tier
        if not changes:
            return True
        self.put(record.copy(**changes))
        return True

    def load_all(self) -> Iterable[MemoryRecord]:
        self._ensure_loaded()
        return list(self._records.values()) if self._records is not None else []

    def _ensure_loaded(self) -> None:
        if self._records is not None:
            return
        paths = list(self._iter_memory_files())
        signatures = self._signatures(paths)
        with self._cache_lock:
            previous_signatures, previous_by_path = self._shared_cache.get(
                self.memory_root,
                ({}, {}),
            )
            by_path: Dict[Path, MemoryRecord] = {}
            for path in paths:
                if (
                    previous_signatures.get(path) == signatures.get(path)
                    and path in previous_by_path
                ):
                    by_path[path] = previous_by_path[path]
                    continue
                try:
                    by_path[path] = self._read(path)
                except (OSError, ValueError):
                    continue
            self._shared_cache[self.memory_root] = (signatures, by_path)
        self._records = {record.id: record for record in by_path.values()}

    @staticmethod
    def _signatures(paths: Iterable[Path]) -> Dict[Path, Tuple[int, int]]:
        signatures = {}
        for path in paths:
            try:
                stat = path.stat()
                signatures[path] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue
        return signatures

    def _publish_shared_cache(self) -> None:
        if self._records is None:
            return
        by_path = {
            record.path: record
            for record in self._records.values()
            if record.path is not None and record.path.exists()
        }
        with self._cache_lock:
            self._shared_cache[self.memory_root] = (
                self._signatures(by_path),
                by_path,
            )

    def _read(self, path: Path) -> MemoryRecord:
        return self.projection.parse(
            path.read_text(encoding="utf-8", errors="ignore"),
            path=path,
        )

    def _ensure_index(self) -> None:
        if self._index_file.exists():
            return
        active_records = [
            record
            for record in self.load_all()
            if record.path is not None and self.shared_root in record.path.parents
        ]
        self._indexer.rebuild(active_records, self.memory_root)

    def _index_meta(self, record: MemoryRecord) -> dict:
        if record.path is None:
            raise ValueError(f"memory {record.id} has no storage path")
        return {
            "id": record.id,
            "title": record.title,
            "object_type": record.object_type,
            "layer": record.layer,
            "tier": record.tier,
            "access_count": record.access_count,
            "tags": record.tags,
            "file": str(record.path.relative_to(self.memory_root)),
        }

    def _sanitize_record(self, record: MemoryRecord, target: Path) -> MemoryRecord:
        if os.environ.get("MMS_SANITIZE_DISABLE") == "1":
            return record
        front_matter, body = self.projection.from_record(record)

        def sanitize_value(value, *, key: str = ""):
            if isinstance(value, str):
                if key == "id":
                    return value
                return sanitize_or_raise(value, path_hint=str(target))
            if isinstance(value, list):
                return [sanitize_value(item) for item in value]
            if isinstance(value, dict):
                return {
                    item_key: sanitize_value(item_value, key=str(item_key))
                    for item_key, item_value in value.items()
                }
            return value

        sanitized_front_matter = sanitize_value(front_matter)
        sanitized_body = sanitize_or_raise(body, path_hint=str(target))
        return self.projection.to_record(
            sanitized_front_matter,
            sanitized_body,
            path=target,
        )

    def _iter_memory_files(self) -> Iterable[Path]:
        if not self.memory_root.exists():
            return []
        # Match skip dirs against paths *relative to memory_root* only.
        # Never use absolute path.parts — on macOS /private/var/... would
        # falsely match the "private" skip entry.
        results: List[Path] = []
        for path in sorted(self.memory_root.rglob("*.md")):
            try:
                rel_parts = set(path.relative_to(self.memory_root).parts)
            except ValueError:
                continue
            if _SKIP_DIRS & rel_parts:
                continue
            if path.name in _SKIP_FILES:
                continue
            results.append(path)
        return results

    def _target_path(self, record: MemoryRecord) -> Path:
        if record.path is not None:
            candidate = Path(record.path)
            if not candidate.is_absolute():
                candidate = self.memory_root / candidate
            candidate = candidate.resolve()
            try:
                candidate.relative_to(self.memory_root)
                return candidate
            except ValueError:
                pass
        layer = self._normalize_layer(record.layer)
        return self.shared_root / layer / f"{record.id}.md"

    @staticmethod
    def _validate_id(memory_id: str) -> None:
        if not memory_id or memory_id in {".", ".."}:
            raise ValueError("memory id must not be empty")
        if "/" in memory_id or "\\" in memory_id or Path(memory_id).name != memory_id:
            raise ValueError(f"unsafe memory id: {memory_id!r}")

    @staticmethod
    def _normalize_layer(layer: str) -> str:
        value = layer.strip()
        if value in _UNIVERSAL_LAYERS:
            return value
        upper = value.upper()
        if upper in _UNIVERSAL_LAYERS:
            return upper
        for prefix, universal in _LEGACY_LAYER_MAP.items():
            if upper.startswith(prefix):
                return universal
        return "CC"

    @staticmethod
    def _matches_filters(
        record: MemoryRecord,
        *,
        layer: Optional[str],
        tier: Optional[str],
        object_type: Optional[str],
    ) -> bool:
        return (
            (layer is None or record.layer == layer)
            and (tier is None or record.tier == tier)
            and (object_type is None or record.object_type == object_type)
        )
