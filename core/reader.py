"""
带 TTL 缓存的记忆文件读取器

缓存策略：
  - MEMORY_INDEX.json：TTL=300s（5分钟），进程内 dict 缓存
  - 热记忆文件内容：TTL=600s（10分钟），最多 20 条
  - 缓存 key = 文件路径字符串

设计目标：
  - 支持 >2000 条记忆时，检索响应 <1ms（缓存命中时）
  - 进程内缓存，跨请求复用，无序列化开销
  - 无第三方依赖（不用 cachetools）
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from _paths import DOCS_MEMORY as _MEMORY_ROOT  # type: ignore[import]
except ImportError:
    _MEMORY_ROOT = Path(__file__).resolve().parent.parent / "docs" / "memory"

_INDEX_FILE = _MEMORY_ROOT / "MEMORY_INDEX.json"

# 缓存条目：(数据, 过期时间戳)
_CacheEntry = Tuple[Any, float]


class _TTLCache:
    """简单 TTL 缓存（进程内，非线程安全，MMS 场景单线程足够）"""

    def __init__(self, ttl: float, max_size: int = 100) -> None:
        self._ttl = ttl
        self._max_size = max_size
        self._store: Dict[str, _CacheEntry] = {}
        self._access_order: List[str] = []   # 用于 LRU 淘汰

    def get(self, key: str) -> Tuple[bool, Any]:
        """返回 (hit, value)"""
        if key not in self._store:
            return False, None
        value, expire_ts = self._store[key]
        if time.monotonic() > expire_ts:
            del self._store[key]
            if key in self._access_order:
                self._access_order.remove(key)
            return False, None
        self._access_order.append(key)
        return True, value

    def set(self, key: str, value: Any) -> None:
        if len(self._store) >= self._max_size and key not in self._store:
            self._evict_lru()
        self._store[key] = (value, time.monotonic() + self._ttl)
        self._access_order.append(key)

    def _evict_lru(self) -> None:
        while self._access_order:
            oldest = self._access_order.pop(0)
            if oldest in self._store:
                del self._store[oldest]
                return

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
        self._access_order.clear()


class MemoryReader:
    """
    记忆文件读取器，提供 TTL 缓存加速。

    Example:
        reader = MemoryReader()
        index = reader.read_index()           # 首次从磁盘读取，后续缓存命中
        content = reader.read_memory_file("shared/L2_infrastructure/D9_database/MEM-DB-002.md")
        reader.invalidate_index()             # 索引更新后使缓存失效
    """

    def __init__(
        self,
        index_ttl: float = 300.0,
        file_ttl: float = 600.0,
        max_cached_files: int = 20,
        memory_root: Optional[Path] = None,
    ) -> None:
        self._root = memory_root or _MEMORY_ROOT
        self._index_cache = _TTLCache(ttl=index_ttl, max_size=1)
        self._file_cache = _TTLCache(ttl=file_ttl, max_size=max_cached_files)

    def read_index(self) -> dict:
        """
        读取 MEMORY_INDEX.json，TTL 内返回缓存。

        Returns:
            解析后的 index dict

        Raises:
            FileNotFoundError: 索引文件不存在
        """
        index_path = str(self._root / "MEMORY_INDEX.json")
        hit, cached = self._index_cache.get(index_path)
        if hit:
            return cached

        data = json.loads((self._root / "MEMORY_INDEX.json").read_text(encoding="utf-8"))
        self._index_cache.set(index_path, data)
        return data

    def read_memory_file(self, relative_path: str) -> Optional[str]:
        """
        读取记忆文件内容，TTL 内返回缓存。

        Args:
            relative_path: 相对于 docs/memory/ 的路径
                           例："shared/L2_infrastructure/D9_database/MEM-DB-002.md"

        Returns:
            文件内容字符串，文件不存在时返回 None
        """
        hit, cached = self._file_cache.get(relative_path)
        if hit:
            return cached

        full_path = self._root / relative_path
        if not full_path.exists():
            return None

        content = full_path.read_text(encoding="utf-8")
        self._file_cache.set(relative_path, content)
        return content

    def invalidate_index(self) -> None:
        """索引被更新后，手动使缓存失效"""
        self._index_cache.clear()

    def invalidate_file(self, relative_path: str) -> None:
        """特定记忆文件被更新后，使其缓存失效"""
        self._file_cache.invalidate(relative_path)

    def search_by_keywords(self, keywords: List[str], top_k: int = 3) -> List[dict]:
        """
        基于关键词在索引树中推理式检索（无向量，纯文本匹配）。

        匹配策略：
          1. 遍历 MEMORY_INDEX.json 的 tree 节点
          2. 计算每个 node 的 trigger_keywords 与查询词的交集数量
          3. 按匹配分数排序，返回 top_k 个记忆条目

        Args:
            keywords: 查询关键词列表（如 ["kafka", "replication", "k8s"]）
            top_k:    返回的记忆条目数上限

        Returns:
            记忆条目列表，每条包含 {id, title, tier, file, score}
        """
        index = self.read_index()
        scored: List[Tuple[int, dict]] = []
        kw_set = {k.lower() for k in keywords}

        for layer_node in index.get("tree", []):
            layer_kws = {k.lower() for k in layer_node.get("trigger_keywords", [])}
            layer_score = len(kw_set & layer_kws)

            for dim_node in layer_node.get("nodes", []):
                dim_kws = {k.lower() for k in dim_node.get("trigger_keywords", [])}
                dim_score = layer_score + len(kw_set & dim_kws)

                for mem in dim_node.get("memories", []):
                    mem_tags = {t.lower() for t in mem.get("tags", [])}
                    score = dim_score + len(kw_set & mem_tags)
                    if score > 0:
                        scored.append((score, {**mem, "score": score}))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:top_k]]
