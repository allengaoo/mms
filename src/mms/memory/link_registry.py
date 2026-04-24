#!/usr/bin/env python3
"""
link_registry.py — MMS Layer 2 LinkType 注册表（YAML 驱动）

将 docs/memory/ontology/links/*.yaml 中定义的 LinkType 加载为内存对象，
供 graph_resolver.py 的 typed_explore() 和 hybrid_search() 使用。

设计原则：
  - 新增 LinkType：在 ontology/links/ 新建一个 YAML 文件，无需修改本类
  - 新增遍历路径：在 ontology/_config/traversal_paths.yaml 新增一个 entry，无需修改本类
  - 仅在首次访问时懒加载，避免 import 时磁盘 I/O

使用示例：
  from mms.memory.link_registry import LinkTypeRegistry
  registry = LinkTypeRegistry()
  link = registry.get("link_cites")        # LinkTypeDef | None
  edges = registry.traversal_path("concept_lookup")  # ["about", "related_to"]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent.parent

_LINKS_DIR = _ROOT / "docs" / "memory" / "ontology" / "links"
_CONFIG_DIR = _ROOT / "docs" / "memory" / "ontology" / "_config"
_TRAVERSAL_FILE = _CONFIG_DIR / "traversal_paths.yaml"


# ── YAML 解析（优先使用 PyYAML，回退到轻量正则解析）─────────────────────────

def _load_yaml(text: str) -> dict:
    """
    加载 YAML 文本为 dict。
    优先使用 PyYAML（已在 requirements 中），回退到轻量解析。
    """
    try:
        import yaml  # type: ignore[import]
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return _parse_yaml_fallback(text)


def _parse_yaml_fallback(text: str) -> dict:
    """
    轻量 YAML 回退解析器（仅处理标量键值对，不支持嵌套对象）。
    仅在 PyYAML 不可用时使用。
    """
    result: dict = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped in ("---", "..."):
            continue
        if ":" in stripped and not stripped.startswith("-"):
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip().strip("\"'")
            if val and not result.get(key):
                result[key] = val
    return result


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class LinkTypeDef:
    """
    LinkType 定义，对应 docs/memory/ontology/links/*.yaml 中的一个条目。

    字段含义：
      id            : 唯一标识，如 "link_cites"
      label         : 人类可读标签
      source_type   : 起点节点类型（如 "MemoryNode"）
      target_type   : 终点节点类型（如 "CodeFile", "DomainConcept", "MemoryNode"）
      cardinality   : 基数关系（"1:1" | "1:N" | "M:N" | "N:M"）
      inverse       : 反向边名称（可选）
      storage_field : front-matter 字段名（如 "cites_files"）
      auto_populate : 是否自动建边
      symmetric     : 是否对称关系（如 contradicts）
    """
    id: str
    label: str = ""
    source_type: str = "MemoryNode"
    target_type: str = "MemoryNode"
    cardinality: str = "M:N"
    inverse: Optional[str] = None
    storage_field: Optional[str] = None   # front-matter 中的字段名
    auto_populate: bool = False
    symmetric: bool = False
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "LinkTypeDef":
        storage = data.get("storage", {}) or {}
        return cls(
            id=data.get("id", ""),
            label=data.get("label", ""),
            source_type=data.get("source_type", "MemoryNode"),
            target_type=data.get("target_type", "MemoryNode"),
            cardinality=data.get("cardinality", "M:N"),
            inverse=data.get("inverse"),
            storage_field=storage.get("field_name") if isinstance(storage, dict) else None,
            auto_populate=bool((data.get("auto_population") or {}) and
                               (data.get("auto_population") or {}).get("trigger")),
            symmetric=bool(data.get("symmetric", False)),
            raw=data,
        )


@dataclass
class TraversalPathDef:
    """
    遍历路径定义，来自 ontology/_config/traversal_paths.yaml。

    edge_types      : 要走的 LinkType 字段名列表（顺序有意义）
    max_depth       : 最大遍历深度
    include_inverse : 是否同时走反向边
    min_results     : 结果少于此数时触发 hybrid_search fallback
    """
    path_id: str
    label: str = ""
    edge_types: List[str] = field(default_factory=list)
    max_depth: int = 2
    include_inverse: bool = False
    min_results: int = 3


# ── 注册表 ────────────────────────────────────────────────────────────────────

class LinkTypeRegistry:
    """
    YAML 驱动的 LinkType 注册表。

    懒加载（首次 get/all/traversal_path 调用时扫描磁盘）。
    新增 LinkType：在 docs/memory/ontology/links/ 新建 YAML 文件即可，
    无需修改本类代码。
    """

    def __init__(
        self,
        links_dir: Optional[Path] = None,
        traversal_file: Optional[Path] = None,
    ) -> None:
        self._links_dir = links_dir or _LINKS_DIR
        self._traversal_file = traversal_file or _TRAVERSAL_FILE
        self._links: Dict[str, LinkTypeDef] = {}
        self._paths: Dict[str, TraversalPathDef] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._load()
        self._loaded = True

    def _load(self) -> None:
        """扫描 links/ 目录和 traversal_paths.yaml，建立内存注册表。"""
        # 1. 加载 LinkType 定义
        if self._links_dir.exists():
            for yaml_file in sorted(self._links_dir.glob("*.yaml")):
                try:
                    text = yaml_file.read_text(encoding="utf-8")
                    data = _load_yaml(text)
                    if data.get("id"):
                        link_def = LinkTypeDef.from_dict(data)
                        self._links[link_def.id] = link_def
                        # 同时以 storage_field 名注册（方便 front-matter 字段名直接查询）
                        if link_def.storage_field:
                            self._links.setdefault(link_def.storage_field, link_def)
                except Exception:  # noqa: BLE001
                    continue

        # 2. 加载遍历路径配置
        if self._traversal_file.exists():
            try:
                text = self._traversal_file.read_text(encoding="utf-8")
                self._load_traversal_paths(text)
            except Exception:  # noqa: BLE001
                pass

    def _load_traversal_paths(self, text: str) -> None:
        """
        解析 traversal_paths.yaml，提取 paths: 下的所有路径定义。
        使用 _load_yaml 解析（优先 PyYAML），结果稳定可靠。
        """
        data = _load_yaml(text)
        paths_dict = data.get("paths", {}) or {}
        for path_id, path_data in paths_dict.items():
            if isinstance(path_data, dict):
                self._paths[path_id] = self._make_traversal_path(path_id, path_data)

    def _make_traversal_path(self, path_id: str, data: dict) -> TraversalPathDef:
        return TraversalPathDef(
            path_id=path_id,
            label=data.get("label", ""),
            edge_types=data.get("edge_types", []),
            max_depth=int(data.get("max_depth", 2)),
            include_inverse=bool(data.get("include_inverse", False)),
            min_results=int(data.get("min_results", 3)),
        )

    # ── 公共 API ──────────────────────────────────────────────────────────────

    def get(self, link_id: str) -> Optional[LinkTypeDef]:
        """
        按 id 或 storage_field 名查询 LinkType 定义。
        未知 link_id 返回 None（不抛异常）。
        """
        self._ensure_loaded()
        return self._links.get(link_id)

    def all(self) -> List[LinkTypeDef]:
        """返回所有已注册的 LinkType 定义列表（去重）。"""
        self._ensure_loaded()
        seen: set = set()
        result = []
        for link in self._links.values():
            if link.id not in seen:
                seen.add(link.id)
                result.append(link)
        return result

    def traversal_path(self, intent: str) -> List[str]:
        """
        按 intent 查询遍历路径的边类型序列。

        参数：
            intent: 路径 ID（如 "concept_lookup"、"code_change_impact"）

        返回：
            edge_types 列表（如 ["about", "related_to"]）；
            未知 intent 返回空列表（不抛异常）。
        """
        self._ensure_loaded()
        path = self._paths.get(intent)
        return path.edge_types if path else []

    def traversal_path_def(self, intent: str) -> Optional[TraversalPathDef]:
        """返回完整的 TraversalPathDef，包括 max_depth、include_inverse 等配置。"""
        self._ensure_loaded()
        return self._paths.get(intent)

    def all_path_ids(self) -> List[str]:
        """返回所有已注册的遍历路径 ID。"""
        self._ensure_loaded()
        return list(self._paths.keys())


# ── 模块级单例（可被各模块共享）────────────────────────────────────────────────

_default_registry: Optional[LinkTypeRegistry] = None


def get_registry() -> LinkTypeRegistry:
    """获取模块级默认 LinkTypeRegistry 实例（懒创建单例）。"""
    global _default_registry
    if _default_registry is None:
        _default_registry = LinkTypeRegistry()
    return _default_registry
