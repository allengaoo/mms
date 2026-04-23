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
    """记忆节点，对应一个 .md 文件。"""

    id: str
    path: Path
    tier: str = "warm"
    layer: str = ""
    tags: List[str] = field(default_factory=list)
    related_to: List[Dict] = field(default_factory=list)   # [{id, reason}]
    cites_files: List[str] = field(default_factory=list)   # 引用的代码文件路径
    impacts: List[str] = field(default_factory=list)        # 变更时需检查的记忆 ID
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
        self._file_to_ids: Dict[str, List[str]] = {}  # 文件路径 → 引用它的记忆 ID 列表
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

                node = MemoryNode(
                    id=mem_id,
                    path=md,
                    tier=str(fm.get("tier", "warm")).strip("\"'"),
                    layer=str(fm.get("layer", "")).strip("\"'"),
                    tags=fm.get("tags", []) or [],
                    related_to=related_list,
                    cites_files=[str(f) for f in cites] if cites else [],
                    impacts=[str(i) for i in impacts] if impacts else [],
                    title=title,
                )
                self._nodes[mem_id] = node

                # 建立文件→记忆的反向索引
                for fpath in node.cites_files:
                    norm = fpath.strip()
                    if norm:
                        self._file_to_ids.setdefault(norm, []).append(mem_id)

            except Exception:  # noqa: BLE001
                continue

    # ── 公共 API ──────────────────────────────────────────────────────────────

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
