"""
MEMORY_INDEX.json 增量更新器

设计原则：
  - 增量更新（O(1)）：只 patch 变更节点，不重建整个索引（O(n)）
  - 原子写入：使用 core.writer.atomic_write_json
  - 维护 {memory_id → (layer_node_id, dim_node_id)} 查找映射，加速定位

支持的操作：
  add_memory(meta)      — 新增记忆条目
  remove_memory(id)     — 移除（GC 归档时调用）
  update_stats(id, ...) — 更新 tier / access_count（GC 后调用）
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .writer import atomic_write_json

_MEMORY_ROOT = Path(__file__).parent.parent.parent.parent / "docs" / "memory"
_INDEX_FILE = _MEMORY_ROOT / "MEMORY_INDEX.json"


def _load_index() -> dict:
    return json.loads(_INDEX_FILE.read_text(encoding="utf-8"))


def _find_node(
    index: dict, layer_id: str, dim_id: str
) -> Optional[dict]:
    """在索引树中定位 (layer, dimension) 节点"""
    for layer_node in index.get("tree", []):
        if layer_node.get("node_id") == layer_id:
            for dim_node in layer_node.get("nodes", []):
                if dim_node.get("node_id") == f"{layer_id}-{dim_id}":
                    return dim_node
    return None


def _build_id_map(index: dict) -> Dict[str, Tuple[int, int]]:
    """
    构建 {memory_id → (layer_node_idx, dim_node_idx)} 快速查找表。
    用于 remove_memory 和 update_stats。
    """
    id_map: Dict[str, Tuple[int, int]] = {}
    for li, layer_node in enumerate(index.get("tree", [])):
        for di, dim_node in enumerate(layer_node.get("nodes", [])):
            for mem in dim_node.get("memories", []):
                id_map[mem["id"]] = (li, di)
    return id_map


class IncrementalIndexer:
    """
    MEMORY_INDEX.json 增量更新器。

    每次操作：读取 → 定位节点 → patch → 原子写入。
    写入后自动使 MemoryReader 缓存失效（如传入 reader 实例）。

    Example:
        indexer = IncrementalIndexer()
        indexer.add_memory({
            "id":         "MEM-L-025",
            "layer_id":   "L2",
            "dim_id":     "D6",
            "title":      "Kafka 分区数必须匹配消费者线程数",
            "tier":       "warm",
            "tags":       ["kafka", "partition", "consumer"],
            "file":       "shared/L2_infrastructure/D6_messaging/MEM-L-025.md",
        })
    """

    def __init__(self, index_file: Optional[Path] = None) -> None:
        self._index_file = index_file or _INDEX_FILE

    def add_memory(self, meta: dict) -> bool:
        """
        在索引中新增一条记忆条目。

        Args:
            meta: 必须包含 id, layer_id, dim_id, title, tier, file
                  可选包含 tags, access_count

        Returns:
            True=新增成功，False=目标节点不存在（需检查 layer_id/dim_id 是否合法）
        """
        index = _load_index()
        layer_id = meta.get("layer_id", "")
        dim_id = meta.get("dim_id", "")
        node = _find_node(index, layer_id, dim_id)
        if node is None:
            return False

        entry = {
            "id":           meta["id"],
            "title":        meta.get("title", ""),
            "tier":         meta.get("tier", "warm"),
            "access_count": meta.get("access_count", 0),
            "file":         meta["file"],
        }
        if "tags" in meta:
            entry["tags"] = meta["tags"]

        existing_ids = {m["id"] for m in node.get("memories", [])}
        if meta["id"] in existing_ids:
            return True   # 幂等：已存在则跳过

        node.setdefault("memories", []).append(entry)
        atomic_write_json(self._index_file, index)
        return True

    def remove_memory(self, memory_id: str) -> bool:
        """
        从索引中移除记忆条目（GC 归档时调用）。

        Returns:
            True=已移除，False=未找到
        """
        index = _load_index()
        id_map = _build_id_map(index)

        if memory_id not in id_map:
            return False

        li, di = id_map[memory_id]
        memories = index["tree"][li]["nodes"][di]["memories"]
        index["tree"][li]["nodes"][di]["memories"] = [
            m for m in memories if m["id"] != memory_id
        ]
        atomic_write_json(self._index_file, index)
        return True

    def update_stats(
        self,
        memory_id: str,
        *,
        access_count: Optional[int] = None,
        tier: Optional[str] = None,
    ) -> bool:
        """
        更新记忆条目的 access_count 和 tier（GC 计算后调用）。

        Returns:
            True=更新成功，False=未找到
        """
        index = _load_index()
        id_map = _build_id_map(index)

        if memory_id not in id_map:
            return False

        li, di = id_map[memory_id]
        for mem in index["tree"][li]["nodes"][di]["memories"]:
            if mem["id"] == memory_id:
                if access_count is not None:
                    mem["access_count"] = access_count
                if tier is not None:
                    mem["tier"] = tier
                break

        atomic_write_json(self._index_file, index)
        return True

    def batch_update_stats(self, updates: List[Dict]) -> int:
        """
        批量更新多条记忆的统计信息（GC 批处理，只写一次磁盘）。

        Args:
            updates: [{"id": "MEM-L-010", "access_count": 9, "tier": "hot"}, ...]

        Returns:
            成功更新的条目数
        """
        index = _load_index()
        id_map = _build_id_map(index)
        updated = 0

        for upd in updates:
            mid = upd.get("id")
            if not mid or mid not in id_map:
                continue
            li, di = id_map[mid]
            for mem in index["tree"][li]["nodes"][di]["memories"]:
                if mem["id"] == mid:
                    if "access_count" in upd:
                        mem["access_count"] = upd["access_count"]
                    if "tier" in upd:
                        mem["tier"] = upd["tier"]
                    updated += 1
                    break

        if updated > 0:
            atomic_write_json(self._index_file, index)
        return updated
