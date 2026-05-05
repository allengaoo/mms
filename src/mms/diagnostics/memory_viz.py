#!/usr/bin/env python3
"""
memory_viz.py — 记忆图谱数据收集器

从 docs/memory/ 下的 Markdown 记忆文件中提取结构化数据，
为可视化渲染提供标准化的图节点 + 边 + AST 指针数据。

核心输出：
  - nodes: List[NodeData]    — 图节点（每个记忆文件对应一个节点）
  - edges: List[EdgeData]    — 图边（related_to / cites_files / impacts 关系）
  - ast_mappings: List[AstMapping] — 记忆节点 ↔ 代码文件的映射关系
  - stats: dict              — 统计摘要（节点数、层分布、tier 分布等）
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
    _ROOT = _HERE.parent.parent.parent  # src/mms/diagnostics → project root

_MEMORY_ROOT = _ROOT / "docs" / "memory"


# ── 数据模型 ─────────────────────────────────────────────────────────────────

@dataclass
class NodeData:
    """一个记忆节点的核心属性，直接映射到 vis-network 图节点。"""
    id: str
    label: str           # 显示标签（id 或截断后的 class_name）
    layer: str
    tier: str            # hot / warm / cold / archive
    node_type: str       # decision / pattern / constraint / ...
    tags: List[str]
    file_path: str       # 相对于项目根目录的记忆文件路径
    title: str           # 鼠标悬浮提示（详细信息）
    ast_file: str = ""   # 关联的源码文件路径（来自 ast_pointer.file_path）
    ast_class: str = ""  # 关联的类名（来自 ast_pointer.class_name）
    ast_drift: bool = False
    layer_confidence: float = 0.0
    about_concepts: List[str] = field(default_factory=list)


@dataclass
class EdgeData:
    """图中的有向边，表示两个记忆节点之间的关联类型。"""
    source: str
    target: str
    relation: str        # related_to / cites / impacts / derived_from
    label: str           # 显示在边上的简短标签


@dataclass
class AstMapping:
    """代码文件 ↔ 记忆节点的映射关系，用于 Tab 3 展示。"""
    source_file: str     # 相对路径（代码文件）
    class_name: str
    memory_id: str
    layer: str
    tier: str
    drift: bool
    confidence: float


@dataclass
class VizData:
    """收集器的完整输出，传递给 html_renderer。"""
    nodes: List[NodeData]
    edges: List[EdgeData]
    ast_mappings: List[AstMapping]
    stats: Dict
    project_name: str
    memory_root: str


# ── YAML front-matter 轻量解析 ─────────────────────────────────────────────

def _parse_frontmatter(text: str) -> dict:
    """从 Markdown 文件提取 YAML front-matter，返回 dict。
    
    处理记忆文件中用到的字段类型：
    - 标量（str / int / float / bool）
    - 行内列表 [a, b, c]
    - 多行列表（- item）
    - 嵌套对象（子键以 2 空格缩进）
    """
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}

    raw = m.group(1)
    result: dict = {}
    # 当前正在填充的顶层 key
    current_key: Optional[str] = None
    # 当前模式："scalar" / "list" / "obj"
    current_mode: Optional[str] = None
    current_list: Optional[list] = None
    current_obj: Optional[dict] = None
    current_obj_key: Optional[str] = None
    # 子对象内部的子列表
    sub_list: Optional[list] = None

    def _flush():
        nonlocal current_list, current_obj, current_mode, sub_list, current_obj_key
        if current_key is None:
            return
        if current_mode == "list" and current_list is not None:
            result[current_key] = current_list
        elif current_mode == "obj" and current_obj is not None:
            if sub_list is not None and current_obj_key:
                current_obj[current_obj_key] = sub_list
            result[current_key] = current_obj
        current_list = None
        current_obj = None
        current_obj_key = None
        sub_list = None
        current_mode = None

    for line in raw.splitlines():
        # ── 子列表项（4 空格 + "- "，子对象内部）─────────────────────────────
        if line.startswith("    - ") and current_mode == "obj":
            item = line[6:].strip().strip('"').strip("'")
            if sub_list is not None:
                sub_list.append(item)
            continue

        # ── 顶层列表项（"- "）───────────────────────────────────────────────
        if line.startswith("- ") and current_mode == "list":
            item = line[2:].strip().strip('"').strip("'")
            if current_list is not None:
                current_list.append(item)
            continue

        # ── 嵌套对象字段（2 空格缩进，非 "  - " 形式）──────────────────────
        if line.startswith("  ") and not line.startswith("    ") and current_mode == "obj":
            stripped = line.strip()
            if stripped.startswith("- "):
                # 顶层 key 对应的列表项（罕见格式兼容）
                item = stripped[2:].strip().strip('"').strip("'")
                if current_list is not None:
                    current_list.append(item)
                continue
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                k = k.strip()
                v = v.strip()
                # 保存上一个子列表
                if sub_list is not None and current_obj_key:
                    current_obj[current_obj_key] = sub_list  # type: ignore[index]
                    sub_list = None
                current_obj_key = k
                if v == "" or v is None:
                    sub_list = []
                elif v == "[]":
                    current_obj[k] = []  # type: ignore[index]
                    current_obj_key = None
                else:
                    current_obj[k] = _cast_value(v)  # type: ignore[index]
                    current_obj_key = None
            continue

        # ── 顶层列表项（2 空格 + "- "）─────────────────────────────────────
        if line.startswith("  - ") and current_mode == "list":
            item = line[4:].strip().strip('"').strip("'")
            if current_list is not None:
                current_list.append(item)
            continue

        # ── 顶层 key: value ─────────────────────────────────────────────────
        if ":" in line and not line.startswith(" "):
            _flush()

            k, _, v = line.partition(":")
            current_key = k.strip()
            v = v.strip()

            # 去掉行尾注释（"# ..."）——仅对标量有效
            if v and "#" in v and not v.startswith("[") and not v.startswith('"'):
                v = v.split("#")[0].strip()

            if v == "" or v is None:
                # 空值：等待下一行确定是 list 还是 obj
                current_mode = None
            elif v == "[]":
                result[current_key] = []
            elif v.startswith("["):
                inner = v.strip("[]")
                result[current_key] = [
                    i.strip().strip('"').strip("'")
                    for i in inner.split(",")
                    if i.strip()
                ]
            elif v == "{}":
                result[current_key] = {}
            else:
                result[current_key] = _cast_value(v)
            continue

        # ── 判断空值 key 后续是 list 还是 obj ─────────────────────────────
        if current_key and current_mode is None:
            stripped = line.strip()
            if stripped == "":
                continue
            if stripped.startswith("- ") or line.startswith("  - "):
                current_mode = "list"
                current_list = []
                item = stripped[2:].strip().strip('"').strip("'")
                current_list.append(item)
            elif ":" in stripped and not stripped.startswith("- "):
                current_mode = "obj"
                current_obj = {}
                # 解析第一个子字段
                kk, _, vv = stripped.partition(":")
                kk = kk.strip()
                vv = vv.strip().strip('"').strip("'")
                current_obj_key = kk
                if vv == "" or vv is None:
                    sub_list = []
                elif vv == "[]":
                    current_obj[kk] = []
                    current_obj_key = None
                else:
                    current_obj[kk] = _cast_value(vv)
                    current_obj_key = None
            continue

    _flush()
    return result


def _cast_value(v: str):
    """将字符串转换为合适的 Python 类型。"""
    v = v.strip()
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v.strip('"').strip("'")


def _extract_title(text: str) -> str:
    """从 Markdown 正文提取第一行 # 标题。"""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


# ── 主收集器 ─────────────────────────────────────────────────────────────────

class MemoryVizCollector:
    """
    遍历 docs/memory/ 目录，收集记忆图谱数据用于可视化。

    用法：
        collector = MemoryVizCollector(memory_root=Path("docs/memory"))
        data = collector.collect(project_name="my-project")
    """

    # tier → vis-network 节点颜色
    _TIER_COLORS = {
        "hot":     "#ef4444",  # 红
        "warm":    "#f97316",  # 橙
        "cold":    "#3b82f6",  # 蓝
        "archive": "#9ca3af",  # 灰
    }

    # layer → 简短标签
    _LAYER_LABELS = {
        "L1_platform":    "L1",
        "L2_infrastructure": "L2",
        "L3_domain":      "L3",
        "L4_application": "L4",
        "L5_interface":   "L5",
        "CC":             "CC",
        "BIZ":            "BIZ",
        "PLATFORM":       "PLAT",
    }

    def __init__(self, memory_root: Optional[Path] = None, project_root: Optional[Path] = None):
        self.memory_root = Path(memory_root) if memory_root else _MEMORY_ROOT
        self.project_root = Path(project_root) if project_root else _ROOT

    def collect(self, project_name: str = "project") -> VizData:
        """扫描所有记忆文件并返回 VizData。"""
        nodes: List[NodeData] = []
        edges: List[EdgeData] = []
        ast_mappings: List[AstMapping] = []

        node_ids: set = set()

        # 遍历所有记忆 Markdown 文件（排除 _system 目录）
        for md_file in sorted(self.memory_root.rglob("*.md")):
            if "_system" in md_file.parts:
                continue

            try:
                text = md_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            fm = _parse_frontmatter(text)
            if not fm or "id" not in fm:
                continue

            node_id = str(fm.get("id", ""))
            if not node_id or node_id in node_ids:
                continue
            node_ids.add(node_id)

            layer = str(fm.get("layer", "CC"))
            tier = str(fm.get("tier", "warm"))
            node_type = str(fm.get("type", "pattern"))
            tags = fm.get("tags", []) if isinstance(fm.get("tags"), list) else []
            about_concepts = fm.get("about_concepts", []) if isinstance(fm.get("about_concepts"), list) else []

            # AST 指针
            ast_ptr = fm.get("ast_pointer") or {}
            if not isinstance(ast_ptr, dict):
                ast_ptr = {}
            ast_file = str(ast_ptr.get("file_path", ""))
            ast_class = str(ast_ptr.get("class_name", ""))
            ast_drift = bool(ast_ptr.get("drift", False))

            # 置信度
            provenance = fm.get("provenance") or {}
            if not isinstance(provenance, dict):
                provenance = {}
            confidence = float(provenance.get("layer_confidence", 0.0))

            # 标题
            md_title = _extract_title(text)
            label_text = ast_class or node_id
            if len(label_text) > 20:
                label_text = label_text[:18] + "…"

            # 相对路径（用于链接显示）
            try:
                rel_path = str(md_file.relative_to(self.project_root))
            except ValueError:
                rel_path = str(md_file)

            layer_short = self._LAYER_LABELS.get(layer, layer)
            tooltip = (
                f"ID: {node_id}\n"
                f"Layer: {layer} ({layer_short})\n"
                f"Tier: {tier}\n"
                f"Type: {node_type}\n"
                f"Confidence: {confidence:.0%}\n"
                + (f"AST: {ast_class} @ {ast_file}\n" if ast_file else "")
                + (f"Drift: ⚠️ YES\n" if ast_drift else "")
                + (f"Title: {md_title[:60]}" if md_title else "")
            )

            nodes.append(NodeData(
                id=node_id,
                label=label_text,
                layer=layer,
                tier=tier,
                node_type=node_type,
                tags=tags,
                file_path=rel_path,
                title=tooltip,
                ast_file=ast_file,
                ast_class=ast_class,
                ast_drift=ast_drift,
                layer_confidence=confidence,
                about_concepts=about_concepts,
            ))

            # 收集 AST 映射
            if ast_file:
                ast_mappings.append(AstMapping(
                    source_file=ast_file,
                    class_name=ast_class,
                    memory_id=node_id,
                    layer=layer,
                    tier=tier,
                    drift=ast_drift,
                    confidence=confidence,
                ))

            # ── 收集显式边关系（Bug 修复：related_to 元素可能是 dict {id, reason} 或 str）
            def _extract_id(item) -> str:
                """兼容 str 和 {id: X, reason: Y} 两种 related_to 格式。"""
                if isinstance(item, dict):
                    return str(item.get("id", "")).strip()
                if isinstance(item, str):
                    # 修复：防止 _parse_frontmatter 将 "- id: X" 解析成字符串 "id: X"
                    raw = item.strip()
                    if raw.startswith("id:"):
                        return raw[3:].strip()
                    return raw
                return ""

            for rel in (fm.get("related_to") or []):
                rel_id = _extract_id(rel)
                if rel_id:
                    edges.append(EdgeData(
                        source=node_id, target=rel_id,
                        relation="related_to", label="related",
                    ))

            for imp in (fm.get("impacts") or []):
                imp_id = _extract_id(imp)
                if imp_id:
                    edges.append(EdgeData(
                        source=node_id, target=imp_id,
                        relation="impacts", label="impacts",
                    ))

            for der in (fm.get("derived_from") or []):
                der_id = _extract_id(der)
                if der_id:
                    edges.append(EdgeData(
                        source=node_id, target=der_id,
                        relation="derived_from", label="derived",
                    ))

        # 过滤掉指向不存在节点的边（避免 vis-network 报错）
        edges = [e for e in edges if e.target in node_ids and e.source in node_ids]

        # ── 推断隐式边：共享同一代码文件（ast_file）的节点之间加 cites_same_file 边
        # 这些边展示哪些记忆节点"共同描述了同一个代码文件"，有助于理解记忆覆盖的粒度
        # 注意：file_path 是记忆 .md 文件路径，ast_file 才是源代码文件路径
        ast_file_to_nodes: Dict[str, list] = {}
        for nd in nodes:
            if nd.ast_file:
                ast_file_to_nodes.setdefault(nd.ast_file, []).append(nd.id)
        seen_pairs: set = set()
        for code_file, nids in ast_file_to_nodes.items():
            if len(nids) < 2:
                continue
            fname = Path(code_file).name
            for i in range(len(nids)):
                for j in range(i + 1, len(nids)):
                    pair = tuple(sorted([nids[i], nids[j]]))
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        edges.append(EdgeData(
                            source=nids[i], target=nids[j],
                            relation="cites_same_file",
                            label=fname,
                        ))

        stats = self._build_stats(nodes, edges, ast_mappings)

        return VizData(
            nodes=nodes,
            edges=edges,
            ast_mappings=ast_mappings,
            stats=stats,
            project_name=project_name,
            memory_root=str(self.memory_root),
        )

    def _build_stats(
        self,
        nodes: List[NodeData],
        edges: List[EdgeData],
        ast_mappings: List[AstMapping],
    ) -> Dict:
        from collections import Counter

        layer_counts = Counter(n.layer for n in nodes)
        tier_counts = Counter(n.tier for n in nodes)
        type_counts = Counter(n.node_type for n in nodes)
        drift_count = sum(1 for m in ast_mappings if m.drift)
        has_ast = sum(1 for n in nodes if n.ast_file)

        return {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "total_ast_mappings": len(ast_mappings),
            "drift_count": drift_count,
            "has_ast_count": has_ast,
            "layer_distribution": dict(layer_counts),
            "tier_distribution": dict(tier_counts),
            "type_distribution": dict(type_counts),
        }
