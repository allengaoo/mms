"""Schema v5 memory index builder and incremental updater."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .writer import atomic_write_json

try:
    from mms.utils._paths import DOCS_MEMORY as _MEMORY_ROOT
except ImportError:
    _MEMORY_ROOT = Path(__file__).resolve().parent.parent / "docs" / "memory"

_INDEX_FILE = _MEMORY_ROOT / "MEMORY_INDEX.json"
UNIVERSAL_LAYERS = (
    "ADAPTER",
    "APP",
    "DOMAIN",
    "PLATFORM",
    "CC",
    "CC_testing",
    "CC_governance",
    "BIZ",
    "Ops",
)
_OBJECT_TYPE_ALIASES = {
    "pattern": "Pattern",
    "lesson": "Pattern",
    "memorynode": "Pattern",
    "memory_node": "Pattern",
    "arch_constraint": "Pattern",
    "decision": "Decision",
    "archdecision": "Decision",
    "architecturedecision": "Decision",
    "anti_pattern": "AntiPattern",
    "antipattern": "AntiPattern",
    "business_flow": "BusinessFlow",
    "businessflow": "BusinessFlow",
}


def normalize_object_type(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "Pattern"
    key = raw.replace("-", "_").replace(" ", "").lower()
    return _OBJECT_TYPE_ALIASES.get(key, raw)


def empty_index() -> dict:
    return {
        "schema_version": "5.0",
        "tree": [
            {
                "node_id": layer,
                "layer": layer,
                "trigger_keywords": [],
                "nodes": [],
            }
            for layer in UNIVERSAL_LAYERS
        ],
    }


def _load_index(index_file: Path = _INDEX_FILE) -> dict:
    if not index_file.exists():
        return empty_index()
    data = json.loads(index_file.read_text(encoding="utf-8"))
    if str(data.get("schema_version", "")).startswith("5"):
        return data
    return empty_index()


def _find_node(index: dict, layer_id: str, object_type: str) -> Optional[dict]:
    normalized_type = normalize_object_type(object_type)
    for layer_node in index.get("tree", []):
        if layer_node.get("node_id") != layer_id:
            continue
        for type_node in layer_node.get("nodes", []):
            if type_node.get("object_type") == normalized_type:
                return type_node
    return None


def _ensure_node(index: dict, layer_id: str, object_type: str) -> dict:
    if layer_id not in UNIVERSAL_LAYERS:
        layer_id = "CC"
    node = _find_node(index, layer_id, object_type)
    if node is not None:
        return node
    layer_node = next(
        item for item in index["tree"] if item.get("node_id") == layer_id
    )
    normalized_type = normalize_object_type(object_type)
    node = {
        "node_id": f"{layer_id}:{normalized_type}",
        "object_type": normalized_type,
        "trigger_keywords": [],
        "memories": [],
    }
    layer_node.setdefault("nodes", []).append(node)
    return node


def _build_id_map(index: dict) -> Dict[str, Tuple[int, int]]:
    result: Dict[str, Tuple[int, int]] = {}
    for layer_index, layer_node in enumerate(index.get("tree", [])):
        for type_index, type_node in enumerate(layer_node.get("nodes", [])):
            for memory in type_node.get("memories", []):
                result[memory["id"]] = (layer_index, type_index)
    return result


def _remove_from_index(index: dict, memory_id: str) -> bool:
    removed = False
    for layer_node in index.get("tree", []):
        for type_node in layer_node.get("nodes", []):
            before = type_node.get("memories", [])
            after = [item for item in before if item.get("id") != memory_id]
            if len(after) != len(before):
                type_node["memories"] = after
                removed = True
    return removed


def _entry(meta: dict) -> dict:
    layer = str(meta.get("layer") or meta.get("layer_id") or "CC")
    object_type = normalize_object_type(
        str(meta.get("object_type") or meta.get("type") or "Pattern")
    )
    return {
        "id": meta["id"],
        "title": meta.get("title", ""),
        "object_type": object_type,
        "layer": layer,
        "node_id": layer,
        "tier": meta.get("tier", "warm"),
        "access_count": int(meta.get("access_count", 0) or 0),
        "tags": list(meta.get("tags") or []),
        "file": meta["file"],
    }


def _sort_index(index: dict) -> None:
    order = {layer: position for position, layer in enumerate(UNIVERSAL_LAYERS)}
    index["tree"].sort(key=lambda item: order.get(item.get("node_id"), 999))
    for layer_node in index.get("tree", []):
        layer_node["nodes"].sort(key=lambda item: item.get("object_type", ""))
        for type_node in layer_node.get("nodes", []):
            type_node["memories"].sort(key=lambda item: item.get("id", ""))


class IncrementalIndexer:
    def __init__(self, index_file: Optional[Path] = None) -> None:
        self._index_file = Path(index_file or _INDEX_FILE)

    def add_memory(self, meta: dict) -> bool:
        index = _load_index(self._index_file)
        item = _entry(meta)
        _remove_from_index(index, item["id"])
        node = _ensure_node(index, item["layer"], item["object_type"])
        node.setdefault("memories", []).append(item)
        _sort_index(index)
        atomic_write_json(self._index_file, index)
        return True

    def remove_memory(self, memory_id: str) -> bool:
        index = _load_index(self._index_file)
        removed = _remove_from_index(index, memory_id)
        if removed:
            _sort_index(index)
            atomic_write_json(self._index_file, index)
        return removed

    def update_stats(
        self,
        memory_id: str,
        *,
        access_count: Optional[int] = None,
        tier: Optional[str] = None,
    ) -> bool:
        return self.batch_update_stats(
            [
                {
                    "id": memory_id,
                    **(
                        {"access_count": access_count}
                        if access_count is not None
                        else {}
                    ),
                    **({"tier": tier} if tier is not None else {}),
                }
            ]
        ) == 1

    def batch_update_stats(self, updates: List[Dict]) -> int:
        index = _load_index(self._index_file)
        by_id = {item.get("id"): item for item in updates if item.get("id")}
        updated = 0
        for layer_node in index.get("tree", []):
            for type_node in layer_node.get("nodes", []):
                for memory in type_node.get("memories", []):
                    change = by_id.get(memory.get("id"))
                    if change is None:
                        continue
                    if "access_count" in change:
                        memory["access_count"] = change["access_count"]
                    if "tier" in change:
                        memory["tier"] = change["tier"]
                    updated += 1
        if updated:
            _sort_index(index)
            atomic_write_json(self._index_file, index)
        return updated

    def rebuild(self, records: Iterable[Any], memory_root: Path) -> dict:
        index = empty_index()
        root = Path(memory_root).resolve()
        for record in records:
            if record.path is None:
                continue
            try:
                relative_path = str(Path(record.path).resolve().relative_to(root))
            except ValueError:
                continue
            item = _entry(
                {
                    "id": record.id,
                    "title": record.title,
                    "object_type": record.object_type,
                    "layer": record.layer,
                    "tier": record.tier,
                    "access_count": record.access_count,
                    "tags": record.tags,
                    "file": relative_path,
                }
            )
            node = _ensure_node(index, item["layer"], item["object_type"])
            node.setdefault("memories", []).append(item)
        _sort_index(index)
        atomic_write_json(self._index_file, index)
        return index
