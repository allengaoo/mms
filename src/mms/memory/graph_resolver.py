#!/usr/bin/env python3
"""
graph_resolver.py — MMS-OG v3.0 文本图遍历引擎

基于记忆文件 front-matter 中的 related_to / cites_files / impacts 字段，
在纯文本文件之间做图遍历，无需数据库或向量引擎。

核心功能：
  1. explore(start_id, depth)    — 从一个记忆节点出发，广度优先遍历关联图
  2. find_by_file(file_path)     — 通过代码文件路径反查引用它的所有记忆
  3. find_impacts(memory_id)     — 找到某记忆变更时需要同步检查的所有记忆
  4. build_context(files, mems)  — 给定文件和记忆 ID，通过图扩展完整上下文

用法（内部模块，由 synthesizer.py / arch_resolver.py 调用）：
  from mms.memory.graph_resolver import MemoryGraph
  graph = MemoryGraph()
  related = graph.explore("AD-005", depth=2)
  citing = graph.find_by_file("backend/app/core/response.py")

用法（CLI 调试）：
  python3 scripts/mms/graph_resolver.py explore AD-005
  python3 scripts/mms/graph_resolver.py find-file backend/app/core/response.py
"""

from __future__ import annotations

import re
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_MEMORY_ROOT = _ROOT / "docs" / "memory"

# ── YAML front-matter 解析（轻量，无 PyYAML 依赖） ─────────────────────────

def _parse_frontmatter(text: str) -> dict:
    """
    从记忆文件中提取 YAML front-matter（--- 之间的内容）。
    使用简单的正则解析，避免对 PyYAML 的强依赖。
    只处理记忆文件用到的简单字段类型（标量 + 列表）。
    """
    # 提取 --- 之间的内容
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        # 有些记忆文件在 front-matter 前有 ## 标题（旧格式）
        m = re.match(r"^##\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}

    raw = m.group(1)
    result: dict = {}
    current_key: Optional[str] = None
    current_list: Optional[list] = None

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # 检测缩进（列表项）
        if stripped.startswith("- ") and current_key:
            item = stripped[2:].strip().strip("\"'")
            if current_list is not None:
                # 判断是否是 {id: ..., reason: ...} 格式的对象列表
                if item.startswith("{") or ":" in item:
                    # 尝试简单解析 "id: X, reason: Y" 格式
                    obj = {}
                    for part in item.split(","):
                        part = part.strip().strip("{}")
                        if ":" in part:
                            k, v = part.split(":", 1)
                            obj[k.strip().strip("\"'")] = v.strip().strip("\"'")
                    current_list.append(obj)
                else:
                    current_list.append(item)
            continue

        # 键值对
        if ":" in line and not line.startswith(" "):
            # 保存上一个列表
            if current_key and current_list is not None:
                result[current_key] = current_list
                current_list = None

            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip("\"'")

            if not val:
                # 值为空，后续可能是列表
                current_key = key
                current_list = []
                result[key] = current_list
            else:
                current_key = key
                current_list = None
                # 处理布尔和数字
                if val.lower() == "true":
                    result[key] = True
                elif val.lower() == "false":
                    result[key] = False
                else:
                    try:
                        result[key] = int(val)
                    except ValueError:
                        result[key] = val

    return result


# ── 数据结构 ─────────────────────────────────────────────────────────────────

@dataclass
class MemoryNode:
    """
    记忆节点，对应一个 .md 文件。

    Layer 2 图边字段（v4.0 新增，向后兼容，默认为空列表）：
      about_concepts : DomainConcept ID 列表（about 边，由 _auto_link 填充）
      contradicts    : 矛盾记忆 ID 列表（手动填写）
      derived_from   : 来源记忆 ID 列表（手动填写）
    """

    id: str
    path: Path
    tier: str = "warm"
    layer: str = ""
    tags: List[str] = field(default_factory=list)
    related_to: List[Dict] = field(default_factory=list)    # [{id, reason}]
    cites_files: List[str] = field(default_factory=list)    # cites 边：引用的代码文件路径
    impacts: List[str] = field(default_factory=list)        # impacts 边：变更时需检查的记忆 ID
    about_concepts: List[str] = field(default_factory=list) # about 边：描述的领域概念 ID
    contradicts: List[str] = field(default_factory=list)    # contradicts 边：矛盾记忆 ID
    derived_from: List[str] = field(default_factory=list)   # derived_from 边：来源记忆 ID
    title: str = ""

    @property
    def related_ids(self) -> List[str]:
        """从 related_to 列表中提取纯 ID 列表。"""
        ids = []
        for item in self.related_to:
            if isinstance(item, dict):
                ids.append(item.get("id", ""))
            elif isinstance(item, str):
                ids.append(item)
        return [i for i in ids if i]

    @property
    def summary(self) -> str:
        """用于 CLI 展示的摘要行。"""
        related_str = ", ".join(self.related_ids[:3])
        if len(self.related_ids) > 3:
            related_str += f" (+{len(self.related_ids) - 3})"
        return (
            f"[{self.tier.upper()}] {self.id:<16} {self.title[:40]:<42}"
            f"  → {related_str or '(无关联)'}"
        )


# ── 核心引擎 ─────────────────────────────────────────────────────────────────

class MemoryGraph:
    """
    基于文本文件的记忆图遍历引擎。

    初始化时扫描 docs/memory/shared/ 下所有 .md 文件，
    解析 front-matter 建立内存索引，后续操作均在内存中完成。
    """

    def __init__(self, memory_root: Optional[Path] = None) -> None:
        self._root = memory_root or _MEMORY_ROOT
        self._nodes: Dict[str, MemoryNode] = {}
        self._file_to_ids: Dict[str, List[str]] = {}       # 文件路径 → 记忆 ID（cites 反向索引）
        self._concept_to_ids: Dict[str, List[str]] = {}    # DomainConcept → 记忆 ID（about 反向索引）
        self._in_degree: Dict[str, int] = {}               # 节点 in-degree（被引用次数，v3.0 新增）
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._load_all()
        self._loaded = True

    def _load_all(self) -> None:
        """扫描所有记忆文件，建立索引。"""
        for md in self._root.rglob("*.md"):
            # 跳过系统目录、模板、存档
            parts_set = set(md.parts)
            if "_system" in parts_set or "templates" in parts_set or "archive" in parts_set:
                continue
            if md.name in ("CONTRIBUTING.md", "README.md"):
                continue

            try:
                text = md.read_text(encoding="utf-8", errors="ignore")
                fm = _parse_frontmatter(text)

                mem_id = fm.get("id", md.stem)
                if not mem_id:
                    continue

                # 提取标题
                title = ""
                for line in text.splitlines():
                    if line.startswith("# "):
                        raw = line[2:].strip()
                        # 去掉 "ID · " 前缀
                        title = raw.split("·", 1)[-1].strip() if "·" in raw else raw
                        break

                # 解析 related_to（可能是对象列表或字符串列表）
                raw_related = fm.get("related_to", fm.get("related_memories", []))
                related_list: List[Dict] = []
                for item in (raw_related or []):
                    if isinstance(item, dict):
                        related_list.append(item)
                    elif isinstance(item, str) and item.strip():
                        related_list.append({"id": item.strip(), "reason": ""})

                # 解析 cites_files
                cites = fm.get("cites_files", [])
                if isinstance(cites, str):
                    cites = [cites]

                # 解析 impacts
                impacts = fm.get("impacts", [])
                if isinstance(impacts, str):
                    impacts = [impacts]

                # 解析 v4.0 新增 Layer 2 图边字段（向后兼容：缺失时为空列表）
                about_concepts = fm.get("about_concepts", []) or []
                if isinstance(about_concepts, str):
                    about_concepts = [about_concepts]

                contradicts = fm.get("contradicts", []) or []
                if isinstance(contradicts, str):
                    contradicts = [contradicts]

                derived_from = fm.get("derived_from", []) or []
                if isinstance(derived_from, str):
                    derived_from = [derived_from]

                node = MemoryNode(
                    id=mem_id,
                    path=md,
                    tier=str(fm.get("tier", "warm")).strip("\"'"),
                    layer=str(fm.get("layer", "")).strip("\"'"),
                    tags=fm.get("tags", []) or [],
                    related_to=related_list,
                    cites_files=[str(f) for f in cites] if cites else [],
                    impacts=[str(i) for i in impacts] if impacts else [],
                    about_concepts=[str(c) for c in about_concepts],
                    contradicts=[str(c) for c in contradicts],
                    derived_from=[str(d) for d in derived_from],
                    title=title,
                )
                self._nodes[mem_id] = node

                # 建立文件→记忆的反向索引（cites 边）
                for fpath in node.cites_files:
                    norm = fpath.strip()
                    if norm:
                        self._file_to_ids.setdefault(norm, []).append(mem_id)

                # 建立 DomainConcept→记忆的反向索引（about 边）
                for concept_id in node.about_concepts:
                    concept_id = concept_id.strip()
                    if concept_id:
                        self._concept_to_ids.setdefault(concept_id, []).append(mem_id)

            except Exception:  # noqa: BLE001
                continue

        # ── 计算 in-degree（被其他节点引用的次数）────────────────────────────
        # in-degree 是图结构重要性的核心指标：被越多节点引用，结构重要性越高
        self._in_degree = {node_id: 0 for node_id in self._nodes}
        for node_id, node in self._nodes.items():
            for ref in node.related_to:
                target = ref.get("id", "").strip()
                if target in self._in_degree:
                    self._in_degree[target] += 1
            for impact_id in node.impacts:
                target = impact_id.strip()
                if target in self._in_degree:
                    self._in_degree[target] += 1
            for derived_id in node.derived_from:
                target = derived_id.strip()
                if target in self._in_degree:
                    self._in_degree[target] += 1

    # ── 公共 API ──────────────────────────────────────────────────────────────

    def get_in_degree(self, node_id: str) -> int:
        """返回节点的 in-degree（被引用次数）。图加载后才可调用。"""
        self._ensure_loaded()
        return self._in_degree.get(node_id, 0)

    def get_normalized_importance(self, node_id: str) -> float:
        """
        返回节点的图结构重要性（归一化到 0-1）。
        基于 in-degree，max_in_degree 节点归一化为 1.0。
        用于三维度淘汰评分的 gamma 权重。
        """
        self._ensure_loaded()
        if not self._in_degree:
            return 0.0
        max_degree = max(self._in_degree.values()) if self._in_degree else 1
        if max_degree == 0:
            return 0.0
        return self._in_degree.get(node_id, 0) / max_degree

    def explore(self, start_id: str, depth: int = 2) -> List[MemoryNode]:
        """
        从 start_id 出发，广度优先遍历关联记忆图（via related_to 字段）。

        参数：
            start_id: 起始记忆 ID（如 "AD-005"）
            depth:    遍历深度（默认 2 跳）

        返回：
            按层级顺序排列的 MemoryNode 列表（不含起始节点）
        """
        self._ensure_loaded()

        if start_id not in self._nodes:
            return []

        visited: Set[str] = {start_id}
        queue: deque = deque([(start_id, 0)])
        result: List[MemoryNode] = []

        while queue:
            current_id, current_depth = queue.popleft()
            if current_depth >= depth:
                continue

            node = self._nodes.get(current_id)
            if not node:
                continue

            for related_id in node.related_ids:
                if related_id in visited:
                    continue
                visited.add(related_id)
                related_node = self._nodes.get(related_id)
                if related_node:
                    result.append(related_node)
                    queue.append((related_id, current_depth + 1))

        return result

    def find_by_file(self, file_path: str) -> List[MemoryNode]:
        """
        通过代码文件路径反查所有引用该文件的记忆节点。

        参数：
            file_path: 文件路径（如 "backend/app/core/response.py"）
                       支持模糊匹配（只需包含路径片段即可）

        返回：
            所有 cites_files 中包含该路径（或路径片段）的 MemoryNode 列表
        """
        self._ensure_loaded()

        results: List[MemoryNode] = []
        file_lower = file_path.lower().strip("/")

        # 精确匹配
        if file_path in self._file_to_ids:
            for mem_id in self._file_to_ids[file_path]:
                node = self._nodes.get(mem_id)
                if node:
                    results.append(node)
            if results:
                return results

        # 模糊匹配（包含路径片段）
        for indexed_path, mem_ids in self._file_to_ids.items():
            if file_lower in indexed_path.lower() or indexed_path.lower() in file_lower:
                for mem_id in mem_ids:
                    node = self._nodes.get(mem_id)
                    if node and node not in results:
                        results.append(node)

        return results

    def find_impacts(self, memory_id: str) -> List[MemoryNode]:
        """
        找到某记忆变更时需要同步检查的所有记忆（via impacts 字段）。

        参数：
            memory_id: 发生变更的记忆 ID

        返回：
            需要同步检查的 MemoryNode 列表
        """
        self._ensure_loaded()

        result: List[MemoryNode] = []
        node = self._nodes.get(memory_id)
        if not node:
            return result

        for impact_id in node.impacts:
            impact_node = self._nodes.get(impact_id)
            if impact_node:
                result.append(impact_node)

        return result

    def build_context_for_task(
        self,
        files: List[str],
        seed_memories: List[str],
        depth: int = 1,
        max_nodes: int = 8,
    ) -> str:
        """
        给定代码文件列表和种子记忆 ID，通过图遍历构建完整上下文摘要。

        算法：
          1. 通过 find_by_file 找到每个文件关联的记忆
          2. 合并 seed_memories
          3. 对所有种子做 explore(depth=1) 扩展关联记忆
          4. 按 tier 排序（hot > warm > cold），截取 max_nodes 条
          5. 格式化为可注入 prompt 的 Markdown 块

        参数：
            files:        代码文件路径列表
            seed_memories: 初始种子记忆 ID 列表
            depth:        图遍历深度
            max_nodes:    最多返回多少个记忆节点

        返回：
            格式化的 Markdown 字符串，可直接注入 synthesizer 的 prompt
        """
        self._ensure_loaded()

        # 收集种子集合
        seed_ids: Set[str] = set(seed_memories)

        # 文件 → 关联记忆
        for fp in files:
            for node in self.find_by_file(fp):
                seed_ids.add(node.id)

        if not seed_ids:
            return "（图遍历：无直接关联记忆）"

        # 图扩展
        all_ids: Set[str] = set(seed_ids)
        if depth > 0:
            for sid in list(seed_ids):
                for node in self.explore(sid, depth=depth):
                    all_ids.add(node.id)

        # 排序：hot > warm > cold，相同 tier 按 access_count 降序
        tier_order = {"hot": 0, "warm": 1, "cold": 2, "archive": 3}
        nodes = [self._nodes[i] for i in all_ids if i in self._nodes]
        nodes.sort(key=lambda n: (tier_order.get(n.tier, 9), n.id))

        # 截取
        nodes = nodes[:max_nodes]

        if not nodes:
            return "（图遍历：无关联记忆节点）"

        # 格式化
        lines = ["### 图遍历关联记忆（来自 cites_files + related_to 关系链）\n"]
        for node in nodes:
            tier_emoji = "🔥" if node.tier == "hot" else "🌡️" if node.tier == "warm" else "❄️"
            lines.append(f"- {tier_emoji} **{node.id}** ({node.layer}) — {node.title}")
            if node.related_ids:
                lines.append(f"  → 关联: {', '.join(node.related_ids[:4])}")
        return "\n".join(lines)

    # ── Phase 2：语义有向图遍历新方法（保持向后兼容，不删旧方法）──────────────

    def typed_explore(
        self,
        start_id: str,
        path_intent: str = "concept_lookup",
        depth: Optional[int] = None,
    ) -> List[MemoryNode]:
        """
        按 traversal_paths.yaml 配置的路径，沿指定 LinkType 边有向遍历。

        比 explore() 更精准：只走配置中指定类型的边，不混合无关边。

        参数：
            start_id    : 起始记忆 ID
            path_intent : 遍历路径 ID（"concept_lookup"|"code_change_impact"|"knowledge_expand"）
            depth       : 覆盖 YAML 中的 max_depth（可选）

        返回：
            按遍历层级排列的 MemoryNode 列表（不含起始节点）
        """
        self._ensure_loaded()

        from mms.memory.link_registry import get_registry  # 延迟导入
        registry = get_registry()
        path_def = registry.traversal_path_def(path_intent)

        if path_def is None:
            return self.explore(start_id, depth=depth or 2)

        max_depth = depth if depth is not None else path_def.max_depth
        edge_types = path_def.edge_types
        include_inverse = path_def.include_inverse

        if start_id not in self._nodes:
            return []

        visited: Set[str] = {start_id}
        queue: deque = deque([(start_id, 0)])
        result: List[MemoryNode] = []

        while queue:
            current_id, current_depth = queue.popleft()
            if current_depth >= max_depth:
                continue

            node = self._nodes.get(current_id)
            if not node:
                continue

            neighbor_ids: List[str] = []

            for edge_type in edge_types:
                if edge_type in ("related_to", "related"):
                    neighbor_ids.extend(node.related_ids)
                elif edge_type == "cites":
                    # cites 边正向（文件路径，不是记忆 ID，跳过）
                    pass
                elif edge_type == "impacts":
                    neighbor_ids.extend(node.impacts)
                elif edge_type == "about":
                    # about 正向：概念 ID，不是记忆 ID，跳过正向遍历
                    if include_inverse:
                        # 反向：找所有 about_concepts 包含本节点概念的记忆
                        for concept_id in node.about_concepts:
                            neighbor_ids.extend(self._concept_to_ids.get(concept_id, []))
                elif edge_type == "derived_from":
                    neighbor_ids.extend(node.derived_from)
                elif edge_type == "contradicts":
                    neighbor_ids.extend(node.contradicts)

            for nid in neighbor_ids:
                if nid and nid not in visited and nid != current_id:
                    visited.add(nid)
                    neighbor_node = self._nodes.get(nid)
                    if neighbor_node:
                        result.append(neighbor_node)
                        queue.append((nid, current_depth + 1))

        return result

    def find_by_concept(self, keywords: List[str]) -> List[MemoryNode]:
        """
        零 LLM 的概念级语义检索：

        算法：
          1. 从 _system/routing/layers.yaml 的 keywords 字段做规则匹配
          2. 通过 _concept_to_ids 反向索引，O(1) 定位所有相关 MemoryNode
          3. 同时在 node.tags 和 node.about_concepts 中做关键词匹配补充

        参数：
            keywords: 关键词列表（如 ["gRPC", "服务层"]）

        返回：
            匹配的 MemoryNode 列表（按 tier 排序）
        """
        self._ensure_loaded()

        matched_ids: Set[str] = set()
        kw_lower = [k.lower() for k in keywords]

        # Step 1: 通过 about_concepts 反向索引快速匹配
        for concept_id, node_ids in self._concept_to_ids.items():
            for kw in kw_lower:
                if kw in concept_id.lower():
                    matched_ids.update(node_ids)
                    break

        # Step 2: 在每个节点的 tags 中做关键词匹配
        for node in self._nodes.values():
            if node.id in matched_ids:
                continue
            node_tags_lower = [t.lower() for t in node.tags]
            if any(kw in tag for kw in kw_lower for tag in node_tags_lower):
                matched_ids.add(node.id)

        # Step 3: 在 layers.yaml keywords 中匹配，找到相关 DomainConcept 名
        layer_concepts = self._get_layer_concepts(kw_lower)
        for concept_id in layer_concepts:
            matched_ids.update(self._concept_to_ids.get(concept_id, []))

        result = [self._nodes[nid] for nid in matched_ids if nid in self._nodes]
        tier_order = {"hot": 0, "warm": 1, "cold": 2, "archive": 3}
        result.sort(key=lambda n: (tier_order.get(n.tier, 9), n.id))
        return result

    def _get_layer_concepts(self, kw_lower: List[str]) -> List[str]:
        """从 layers.yaml 中找到关键词命中的层 ID，作为 DomainConcept 标识符。"""
        try:
            import yaml  # type: ignore[import]
            routing_dir = _ROOT / "docs" / "memory" / "_system" / "routing"
            layers_file = routing_dir / "layers.yaml"
            if not layers_file.exists():
                return []
            data = yaml.safe_load(layers_file.read_text(encoding="utf-8")) or {}
            layers = data.get("layers", {})
            matched_concepts = []
            for layer_id, layer_data in layers.items():
                if not isinstance(layer_data, dict):
                    continue
                layer_keywords = [k.lower() for k in (layer_data.get("keywords") or [])]
                if any(kw in layer_kw or layer_kw in kw for kw in kw_lower for layer_kw in layer_keywords):
                    matched_concepts.append(layer_id.lower())
            return matched_concepts
        except Exception:  # noqa: BLE001
            return []

    def hybrid_search(
        self,
        keywords: List[str],
        use_graph: bool = True,
        fallback_to_keyword: bool = True,
        graph_confidence_threshold: Optional[int] = None,
    ) -> List[MemoryNode]:
        """
        混合检索（图 + 关键词降级）：

        算法：
          1. 先执行 find_by_concept（图路径）
          2. 若结果数 >= 阈值，直接返回
          3. 否则补充关键词全文检索，取并集排序

        参数：
            keywords                  : 检索关键词列表
            use_graph                 : 是否启用图检索（默认 True）
            fallback_to_keyword       : 图结果不足时是否 fallback（默认 True）
            graph_confidence_threshold: 图结果最小数量阈值（默认从 config 读取，否则 3）

        返回：
            混合检索结果（每个节点有 is_graph_result 属性标注来源）
        """
        self._ensure_loaded()

        threshold = graph_confidence_threshold
        if threshold is None:
            try:
                from mms.utils.mms_config import MmsConfig
                threshold = getattr(MmsConfig(), "graph_confidence_threshold", 3)
            except Exception:  # noqa: BLE001
                threshold = 3

        graph_results: List[MemoryNode] = []
        if use_graph:
            graph_results = self.find_by_concept(keywords)

        if len(graph_results) >= threshold:
            return graph_results

        if not fallback_to_keyword:
            return graph_results

        # Fallback：关键词全文检索
        keyword_results = self._keyword_fallback(keywords)

        # 合并去重（图结果优先）
        seen: Set[str] = {n.id for n in graph_results}
        combined = list(graph_results)
        for node in keyword_results:
            if node.id not in seen:
                seen.add(node.id)
                combined.append(node)

        return combined

    def _keyword_fallback(self, keywords: List[str]) -> List[MemoryNode]:
        """
        简单的关键词全文检索（通过节点标题和标签匹配）。
        作为图检索的补充手段。
        """
        kw_lower = [k.lower() for k in keywords]
        results: List[MemoryNode] = []

        for node in self._nodes.values():
            title_lower = node.title.lower()
            tags_lower = [t.lower() for t in node.tags]
            if any(kw in title_lower for kw in kw_lower) or \
               any(kw in tag for kw in kw_lower for tag in tags_lower):
                results.append(node)

        tier_order = {"hot": 0, "warm": 1, "cold": 2, "archive": 3}
        results.sort(key=lambda n: (tier_order.get(n.tier, 9), n.id))
        return results

    def get(self, memory_id: str) -> Optional[MemoryNode]:
        """获取单个记忆节点。"""
        self._ensure_loaded()
        return self._nodes.get(memory_id)

    def all_hot(self) -> List[MemoryNode]:
        """返回所有 hot tier 记忆节点（按 ID 排序）。"""
        self._ensure_loaded()
        return sorted(
            [n for n in self._nodes.values() if n.tier == "hot"],
            key=lambda n: n.id,
        )

    def stats(self) -> Dict[str, int]:
        """返回图统计信息。"""
        self._ensure_loaded()
        tier_counts: Dict[str, int] = {}
        edge_count = 0
        file_ref_count = 0

        for node in self._nodes.values():
            tier_counts[node.tier] = tier_counts.get(node.tier, 0) + 1
            edge_count += len(node.related_ids)
            file_ref_count += len(node.cites_files)

        return {
            "total_nodes": len(self._nodes),
            "total_edges": edge_count,
            "total_file_refs": file_ref_count,
            **{f"tier_{k}": v for k, v in tier_counts.items()},
        }

    def get_candidates_for_contradiction_check(
        self,
        new_layer_affinity: List[str],
        max_candidates: int = 20,
    ) -> List[MemoryNode]:
        """
        返回矛盾检测的候选节点集合（爆炸半径控制）。

        策略：
          1. 仅检查与新节点具有相同 layer_affinity 的现有节点
          2. 仅检查 tier 为 hot 或 warm 的节点（archive 节点已降级，无需检查）
          3. 最多返回 max_candidates 个节点（按 in-degree 倒序，优先检查重要节点）

        Args:
            new_layer_affinity: 新节点的层级亲和性列表（如 ["DOMAIN", "ADAPTER"]）
            max_candidates: 最大候选节点数（默认 20）

        Returns:
            候选 MemoryNode 列表（可能为空）
        """
        self._ensure_loaded()
        affinity_set = set(new_layer_affinity)
        candidates = []

        for node in self._nodes.values():
            if node.tier not in ("hot", "warm"):
                continue
            # 通过 about_concepts 判断层级亲和性（简化：检查 layer 字段）
            node_layer = getattr(node, "layer", "")
            if not node_layer or node_layer in affinity_set:
                candidates.append(node)

        # 按 in-degree 倒序排序（重要节点优先检查）
        candidates.sort(key=lambda n: self._in_degree.get(n.id, 0), reverse=True)
        return candidates[:max_candidates]

    def add_contradicts_edge(
        self,
        new_node_id: str,
        conflicting_node_id: str,
        memory_root: Optional[Path] = None,
    ) -> bool:
        """
        在两个节点之间建立 contradicts 边。

        操作：
          1. 更新内存中的 MemoryNode 对象
          2. 在磁盘的 Markdown 文件 front-matter 中更新 contradicts 字段

        Args:
            new_node_id: 新节点 ID
            conflicting_node_id: 与之矛盾的旧节点 ID
            memory_root: 记忆根目录（默认使用初始化时的 _root）

        Returns:
            是否成功（文件未找到时返回 False）
        """
        self._ensure_loaded()
        memory_root = memory_root or self._root

        success = True
        for node_id, target_id in [
            (new_node_id, conflicting_node_id),
            (conflicting_node_id, new_node_id),
        ]:
            node = self._nodes.get(node_id)
            if not node:
                continue

            # 更新内存对象
            if target_id not in node.contradicts:
                node.contradicts.append(target_id)

            # 更新磁盘文件
            file_updated = self._update_frontmatter_field(
                node_id,
                "contradicts",
                node.contradicts,
                memory_root,
            )
            if not file_updated:
                success = False

        return success

    def archive_node(
        self,
        node_id: str,
        reason: str = "",
        memory_root: Optional[Path] = None,
    ) -> bool:
        """
        将节点 tier 降级为 archive，切断其所有入边（使其在 hybrid_search 中被永久忽略）。

        操作：
          1. 将 tier 改为 archive
          2. 在磁盘文件中更新 tier 字段并记录 archive_reason
          3. 更新 in-degree 计数（降级节点不再贡献入度）

        Args:
            node_id: 要降级的节点 ID
            reason: 降级原因（如 "矛盾检测：与 MEM-L-012 的 gRPC vs REST 约束冲突"）
            memory_root: 记忆根目录

        Returns:
            是否成功
        """
        self._ensure_loaded()
        memory_root = memory_root or self._root

        node = self._nodes.get(node_id)
        if not node:
            return False

        original_tier = node.tier
        node.tier = "archive"

        # 更新磁盘文件：tier 字段
        ok1 = self._update_frontmatter_field(node_id, "tier", "archive", memory_root)
        # 更新磁盘文件：archive_reason 字段
        ok2 = self._update_frontmatter_field(node_id, "archive_reason", reason, memory_root)

        if ok1:
            # 更新 in-degree：降级节点的出边不再贡献入度
            for related_id in node.related_ids:
                if related_id in self._in_degree:
                    self._in_degree[related_id] = max(0, self._in_degree[related_id] - 1)

        return ok1

    def _update_frontmatter_field(
        self,
        node_id: str,
        field_name: str,
        field_value,
        memory_root: Path,
    ) -> bool:
        """
        在磁盘 Markdown 文件的 front-matter 中更新指定字段。

        Returns:
            是否成功找到并更新了文件
        """
        import re as _re
        import yaml as _yaml

        # 找到文件路径
        for md in memory_root.rglob("*.md"):
            try:
                text = md.read_text(encoding="utf-8", errors="ignore")
                fm_match = _re.match(r"^---\s*\n(.*?)\n---\s*\n", text, _re.DOTALL)
                if not fm_match:
                    continue
                fm = _yaml.safe_load(fm_match.group(1)) or {}
                if str(fm.get("id", "")) != str(node_id):
                    continue

                # 找到目标文件，更新 front-matter
                fm[field_name] = field_value
                new_fm_str = _yaml.dump(
                    fm,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                ).rstrip()
                body = text[fm_match.end():]
                new_text = f"---\n{new_fm_str}\n---\n{body}"
                md.write_text(new_text, encoding="utf-8")
                return True
            except Exception:  # noqa: BLE001
                continue
        return False


# ── CLI 入口（调试用）─────────────────────────────────────────────────────────

def _cli_explore(args: List[str]) -> None:
    if not args:
        print("用法: graph_resolver.py explore <MEM-ID> [depth]")
        return

    mem_id = args[0]
    depth = int(args[1]) if len(args) > 1 else 2

    graph = MemoryGraph()
    start = graph.get(mem_id)
    if not start:
        print(f"❌ 未找到记忆节点：{mem_id}")
        print(f"   可用节点数：{len(graph._nodes)}（先调用 _ensure_loaded）")
        graph._ensure_loaded()
        print(f"   加载后节点数：{len(graph._nodes)}")
        return

    print(f"\n📍 起始节点：{start.summary}")
    print(f"   cites_files: {start.cites_files or '(未配置)'}")
    print(f"   impacts: {start.impacts or '(未配置)'}\n")

    related = graph.explore(mem_id, depth=depth)
    if not related:
        print("  （无关联节点）")
    else:
        print(f"关联节点（深度={depth}，共 {len(related)} 个）：")
        for node in related:
            print(f"  {node.summary}")

    print(f"\n📊 图统计：{graph.stats()}")


def _cli_find_file(args: List[str]) -> None:
    if not args:
        print("用法: graph_resolver.py find-file <file_path>")
        return

    file_path = " ".join(args)
    graph = MemoryGraph()
    nodes = graph.find_by_file(file_path)

    if not nodes:
        print(f"  未找到引用 '{file_path}' 的记忆节点")
    else:
        print(f"\n📁 引用 '{file_path}' 的记忆节点（共 {len(nodes)} 个）：")
        for node in nodes:
            print(f"  {node.summary}")


def _cli_stats(_args: List[str]) -> None:
    graph = MemoryGraph()
    stats = graph.stats()
    print("\n📊 MMS 图谱统计：")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    hot_nodes = graph.all_hot()
    v3_count = sum(1 for n in hot_nodes if n.related_to or n.cites_files)
    print(f"\n🔥 Hot 节点升级进度：{v3_count}/{len(hot_nodes)} 个已包含 v3 图关系字段")
    if v3_count < len(hot_nodes):
        missing = [n.id for n in hot_nodes if not n.related_to and not n.cites_files]
        print(f"   待升级：{', '.join(missing)}")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        sys.exit(0)

    cmd = argv[0]
    rest = argv[1:]

    if cmd == "explore":
        _cli_explore(rest)
    elif cmd == "find-file":
        _cli_find_file(rest)
    elif cmd == "stats":
        _cli_stats(rest)
    else:
        print(f"未知命令: {cmd}")
        print("支持的命令: explore / find-file / stats")
        sys.exit(1)
